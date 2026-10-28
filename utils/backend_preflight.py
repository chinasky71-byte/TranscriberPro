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
from typing import Any, Callable, Dict, Optional, Tuple

STAMP_NAME = ".tp-backend"
PROBE_TIMEOUT_S = 180
CACHE_TTL_S = 300.0

PROBE_CODE = """
import json
report = {"torch": "", "runtime": "", "cuda_available": False, "devices": 0,
          "error": ""}
try:
    import torch
    report["torch"] = torch.__version__
    report["runtime"] = torch.version.hip or torch.version.cuda or ""
    report["cuda_available"] = bool(torch.cuda.is_available())
    report["devices"] = torch.cuda.device_count() if report["cuda_available"] else 0
except Exception as exc:
    report["error"] = "torch: %s" % exc
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
                              "error": ""}
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
                f"device {runtime.get('devices', 0)}")
    return "GPU non disponibile — " + "; ".join(current["problems"])


# ---------------------------------------------------------------------------
# Traduzione: il motore GGUF c'e' e puo' girare?
# ---------------------------------------------------------------------------
# ADR-009 ha lasciato un solo motore di traduzione: TranslateGemma-12B in GGUF su
# llama.cpp. Non esiste piu' un ripiego, quindi tre difetti che prima finivano in
# una traduzione fatta da un altro modello — pesi mancanti, llama.cpp senza
# supporto GPU, VRAM insufficiente — adesso sono errori del job. Meglio scoprirli
# in due secondi all'inizio che dopo venti minuti di trascrizione.
#
# Gli stessi fatti servono in due processi: il job (che puo' importare llama_cpp
# direttamente: e' il processo che lo usera') e il server WebUI (che non deve:
# `test_il_genitore_non_importa_mai_llama_cpp`). Per questo la sonda e'
# parametrizzabile e quella predefinita lavora in-process.
TRANSLATION_PROBE_CODE = """
import json
facts = {"llama": "", "gpu_offload": False, "free_gib": 0.0, "error": ""}
try:
    import llama_cpp
    facts["llama"] = getattr(llama_cpp, "__version__", "?")
    try:
        llama_cpp.llama_backend_init()      # il registro dei backend e' vuoto prima di questa chiamata
    except Exception:
        pass
    facts["gpu_offload"] = bool(llama_cpp.llama_supports_gpu_offload())
except Exception as exc:
    facts["error"] = "llama_cpp: %s" % exc
try:
    import torch
    if torch.cuda.is_available():
        free, _total = torch.cuda.mem_get_info()
        facts["free_gib"] = free / 1024 ** 3
except Exception:
    pass
print(json.dumps(facts))
"""

_translation_cache: Dict[str, Any] = {"at": 0.0, "facts": None}


def translation_facts(force: bool = False) -> Dict[str, Any]:
    """llama.cpp utilizzabile sulla GPU? VRAM libera adesso. Sonda in-process, cache `CACHE_TTL_S`."""
    now = time.monotonic()
    if not force and _translation_cache["facts"] is not None and now - _translation_cache["at"] < CACHE_TTL_S:
        return _translation_cache["facts"]
    facts: Dict[str, Any] = {"llama": "", "gpu_offload": False, "free_gib": 0.0, "error": ""}
    try:
        import llama_cpp
        facts["llama"] = getattr(llama_cpp, "__version__", "?")
        try:
            llama_cpp.llama_backend_init()
        except Exception:
            pass
        facts["gpu_offload"] = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception as exc:
        facts["error"] = f"llama_cpp: {exc}"
    try:
        import torch
        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            facts["free_gib"] = free / 1024 ** 3
    except Exception:
        pass
    _translation_cache["facts"] = facts
    _translation_cache["at"] = now
    return facts


def translation_facts_subprocess(force: bool = False) -> Dict[str, Any]:
    """Come `translation_facts`, ma in un processo separato (per il server WebUI).

    Se il probe non risponde si restituisce un errore, non un verdetto positivo:
    meglio dire "non lo so" che far partire un job che fallira'.
    """
    now = time.monotonic()
    if not force and _translation_cache["facts"] is not None and now - _translation_cache["at"] < CACHE_TTL_S:
        return _translation_cache["facts"]
    facts: Dict[str, Any] = {"llama": "", "gpu_offload": False, "free_gib": 0.0, "error": ""}
    try:
        done = subprocess.run([sys.executable, "-c", TRANSLATION_PROBE_CODE],
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        facts["error"] = f"probe: {exc}"
        _translation_cache.update(facts=facts, at=now)
        return facts
    for line in reversed((done.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                facts.update(json.loads(line))
            except ValueError:
                pass
            break
    if not facts.get("llama") and not facts.get("error"):
        facts["error"] = (done.stderr or "probe senza output").strip()[-400:]
    _translation_cache.update(facts=facts, at=now)
    return facts


def _translation_config(config: Any) -> Tuple[Any, Optional[str], int]:
    """(quantizzazione, cartella GGUF o None, sequenze parallele) dalla config."""
    from utils.gguf_quant import DEFAULT_N_PARALLEL
    quant = config.get("llm_translator_gguf_quant", None)
    directory = (str(config.get("llm_translator_gguf_dir") or "").strip()
                 or str(config.get("llm_translator_model_path") or "").strip() or None)
    try:
        n_parallel = max(1, int(config.get("llm_translator_gguf_parallel") or DEFAULT_N_PARALLEL))
    except (TypeError, ValueError):
        n_parallel = DEFAULT_N_PARALLEL
    return quant, directory, n_parallel


def check_translation_ready(config: Any, allow_cpu: bool = False,
                            check_fit: bool = False,
                            free_gib: Optional[float] = None,
                            probe: Optional[Callable[..., Dict[str, Any]]] = None) -> Tuple[bool, str]:
    """Il passo di traduzione puo' girare? (ok, messaggio con il rimedio).

    Controlla, nell'ordine in cui falliscono: la quantizzazione in config, il
    file GGUF, llama.cpp con supporto GPU. Con `check_fit` controlla anche che
    la VRAM libera basti ai pesi: va fatto appena prima di caricare (STEP 6),
    non all'accodamento, dove il job precedente sta ancora occupando la scheda.
    `free_gib` la fornisce chi la legge gia' (il job); altrimenti vale quella
    della sonda.

    `allow_cpu` (eccezione del singolo job) accetta un llama.cpp senza offload
    GPU: sara' lentissimo, ma e' una scelta dichiarata dall'utente.
    """
    from core.llm_subtitle_translator import gguf_engine
    from utils.gguf_quant import gguf_need_gib, normalize_quant
    from utils.translations import tr

    raw_quant, directory, n_parallel = _translation_config(config)
    try:
        quant = normalize_quant(raw_quant)
    except ValueError as exc:
        return False, tr("pf_translation_not_ready").format(
            reason=str(exc), remedy=tr("pf_remedy_translation"))

    try:
        _path, quant = gguf_engine.resolve_gguf_path(directory, quant)
    except (RuntimeError, ValueError) as exc:
        return False, tr("pf_translation_not_ready").format(
            reason=str(exc), remedy=tr("pf_remedy_translation"))

    facts = (probe or translation_facts)(force=check_fit)
    if facts.get("error"):
        return False, tr("pf_translation_not_ready").format(
            reason=facts["error"], remedy=tr("pf_remedy_translation"))
    if not facts.get("gpu_offload") and not allow_cpu:
        return False, tr("pf_translation_not_ready").format(
            reason=tr("pf_reason_llama_no_gpu"), remedy=tr("pf_remedy_translation"))

    if check_fit and facts.get("gpu_offload"):
        free = free_gib if free_gib is not None else float(facts.get("free_gib") or 0.0)
        need = gguf_need_gib(quant, n_parallel)
        if free < need:
            return False, tr("pf_translation_not_ready").format(
                reason=tr("pf_reason_vram_too_low").format(
                    free_gb=free, need_gb=need, quant=quant),
                remedy=tr("pf_remedy_vram"))
    return True, ""
