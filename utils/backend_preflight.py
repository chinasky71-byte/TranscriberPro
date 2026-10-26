# -*- coding: utf-8 -*-
"""Runtime check: is the GPU backend the venv was installed for still there?

The installer writes `venv/.tp-backend` (ADR-007) after verifying the backend.
This module reads that stamp, asks the *actual* libraries what they see, and
answers one question for the queue: can this job use the GPU?

The probe runs in a subprocess: the web server must not import torch (several
seconds and hundreds of MB) just to answer it, and a crash in the probe cannot
take the server down. The result is cached, so a queue of ten files costs one
probe.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

STAMP_NAME = ".tp-backend"
PROBE_TIMEOUT_S = 180
CACHE_TTL_S = 300.0

PROBE_CODE = """
import json
report = {"torch": "", "runtime": "", "cuda_available": False, "devices": 0,
          "ctranslate2": "", "ct2_devices": 0, "error": ""}
try:
    import torch
    report["torch"] = torch.__version__
    report["runtime"] = torch.version.hip or torch.version.cuda or ""
    report["cuda_available"] = bool(torch.cuda.is_available())
    report["devices"] = torch.cuda.device_count() if report["cuda_available"] else 0
except Exception as exc:
    report["error"] = "torch: %s" % exc
try:
    import ctranslate2
    report["ctranslate2"] = ctranslate2.__version__
    report["ct2_devices"] = ctranslate2.get_cuda_device_count()
except Exception as exc:
    report["error"] = (report["error"] + " | " if report["error"] else "") + "ctranslate2: %s" % exc
print(json.dumps(report))
"""

_cache: Dict[str, Any] = {"at": 0.0, "report": None}


def stamp_path() -> Path:
    """`<venv>/.tp-backend`, the file `install.sh` writes."""
    return Path(sys.prefix) / STAMP_NAME


def read_stamp(path: Optional[Path] = None) -> Dict[str, str]:
    """Parse the stamp; an absent or unreadable file is an empty dict."""
    target = Path(path) if path else stamp_path()
    stamp: Dict[str, str] = {}
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip():
                stamp[key.strip()] = value.strip()
    except OSError:
        return {}
    return stamp


def _probe() -> Dict[str, Any]:
    result: Dict[str, Any] = {"torch": "", "runtime": "", "cuda_available": False, "devices": 0,
                              "ctranslate2": "", "ct2_devices": 0, "error": ""}
    try:
        done = subprocess.run([sys.executable, "-c", PROBE_CODE], capture_output=True,
                              text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = f"probe: {exc}"
        return result
    for line in reversed((done.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result.update(json.loads(line))
            except ValueError:
                pass
            break
    if not result.get("torch") and not result.get("error"):
        result["error"] = (done.stderr or "probe senza output").strip()[-400:]
    return result


def report(force: bool = False) -> Dict[str, Any]:
    """Stamp + runtime facts, cached for `CACHE_TTL_S` seconds."""
    now = time.monotonic()
    if not force and _cache["report"] is not None and now - _cache["at"] < CACHE_TTL_S:
        return _cache["report"]
    stamp = read_stamp()
    runtime = _probe()
    backend = stamp.get("backend", "")
    problems = []
    if not stamp:
        problems.append("il venv non ha il timbro .tp-backend: installazione non verificata "
                        "(rilancia ./install.sh)")
    elif backend in ("rocm", "cuda"):
        expected = "hip" if backend == "rocm" else "cuda"
        if backend == "rocm" and not runtime.get("runtime"):
            problems.append("il timbro dice rocm ma torch non ha runtime HIP (ruota CPU o CUDA)")
        if backend == "cuda" and not runtime.get("runtime"):
            problems.append("il timbro dice cuda ma torch non ha runtime CUDA")
        if not runtime.get("cuda_available"):
            problems.append("torch non vede la GPU (cuda.is_available() = False)")
        elif runtime.get("devices", 0) < 1:
            problems.append("nessun device GPU visibile a torch")
        if runtime.get("ctranslate2") and runtime.get("ct2_devices", 0) < 1:
            problems.append("ctranslate2 non vede la GPU: Whisper girerebbe su CPU")
        del expected
    if runtime.get("error") and not problems:
        problems.append(runtime["error"])
    current = {
        "backend": backend,
        "stamp": stamp,
        "runtime": runtime,
        "stamp_path": str(stamp_path()),
        "ok": not problems,
        "problems": problems,
    }
    _cache["report"] = current
    _cache["at"] = now
    return current


def check_for_job(config: Any, overrides: Optional[Dict[str, Any]] = None,
                  force: bool = False) -> Tuple[bool, str]:
    """May this job use the GPU? Returns (ok, message).

    `allow_cpu` in the job overrides skips the check on purpose: the job will be
    slow, but the user asked for it.
    """
    overrides = overrides or {}
    if overrides.get("allow_cpu"):
        return True, ""
    if not bool(config.get("use_gpu", True)):
        return True, ""
    current = report(force=force)
    if current["ok"]:
        return True, ""
    remedy = ("Rilancia ./install.sh (backend automatico) oppure spunta "
              "'Allow CPU' sul job per elaborare comunque, molto piu' lentamente.")
    return False, "GPU non disponibile: " + "; ".join(current["problems"]) + ". " + remedy


def banner() -> str:
    """One-line status for the WebUI and the startup log."""
    current = report()
    runtime = current["runtime"]
    if current["ok"]:
        return (f"{current['backend'] or 'cpu'}: torch {runtime.get('torch', '?')} "
                f"({runtime.get('runtime') or 'nessun runtime GPU'}), "
                f"device {runtime.get('devices', 0)}, ctranslate2 {runtime.get('ctranslate2') or '?'}")
    return "GPU non disponibile — " + "; ".join(current["problems"])
