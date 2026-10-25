"""Hardware and environment fingerprint for benchmark results.

Every result directory gets an ``environment.json`` and a human-readable block
at the top of ``summary.md``, so a number is never separated from the machine
that produced it.

No personal data is collected: no hostname, username or absolute home path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:
        return ""


def _distro() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return platform.platform()


def _cpu() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def _ram_gib() -> Optional[float]:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except Exception:
        return None


def _torch_info() -> dict[str, Any]:
    info: dict[str, Any] = {"torch": None, "hip": None, "cuda": None, "device_count": None}
    try:
        import torch
        info["torch"] = torch.__version__
        info["hip"] = getattr(torch.version, "hip", None)
        info["cuda"] = bool(torch.cuda.is_available())
        info["device_count"] = torch.cuda.device_count() if info["cuda"] else 0
    except Exception:
        pass
    return info


def _gpus() -> list[dict]:
    raw = _run([sys.executable, "utils/gpu_detect.py", "--json"])
    try:
        return json.loads(raw).get("gpus", [])
    except Exception:
        return []


def _gpu_summary(gpus: list[dict]) -> str:
    parts = []
    for gpu in gpus:
        name = gpu.get("name") or "unknown GPU"
        extra = ", ".join(str(x) for x in (gpu.get("gfx"), gpu.get("amd_family")) if x)
        vram = gpu.get("vram_mib")
        piece = f"{name}" + (f" ({extra})" if extra else "")
        if vram:
            piece += f", {int(vram)} MiB"
        parts.append(piece)
    return "; ".join(parts) or "no discrete GPU detected"


def _backend(torch_info: dict, gpus: list[dict]) -> str:
    if torch_info.get("hip"):
        return "rocm"
    if torch_info.get("cuda"):
        return "cuda"
    # A GPU may exist but be unusable by torch: report the detection source.
    if gpus:
        return "cpu (GPU detected but not usable by torch)"
    return "cpu"


def _rocm_version() -> str:
    out = _run(["rocm-smi", "--version"])
    for line in out.splitlines():
        if "ROCM-SMI" in line.upper():
            return line.strip()
    return ""


def _amdgpu_version() -> str:
    for path in ("/sys/module/amdgpu/version",):
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def collect(label: str = "") -> dict[str, Any]:
    torch_info = _torch_info()
    gpus = _gpus()
    env: dict[str, Any] = {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": label,
        "git_commit": _run(["git", "rev-parse", "--short", "HEAD"]),
        "distro": _distro(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "cpu": _cpu(),
        "ram_gib": _ram_gib(),
        "python": platform.python_version(),
        "gpus": gpus,
        "gpu_summary": _gpu_summary(gpus),
        "torch": torch_info["torch"],
        "hip": torch_info["hip"],
        "cuda_available": torch_info["cuda"],
        "device_count": torch_info["device_count"],
        "backend": _backend(torch_info, gpus),
        "rocm_smi": _rocm_version(),
        "amdgpu_version": _amdgpu_version(),
    }
    return env


def is_cpu_only(env: dict[str, Any]) -> bool:
    return str(env.get("backend", "")).startswith("cpu")


def header(env: dict[str, Any]) -> str:
    """Markdown block placed at the top of summary.md."""
    torch_bits = []
    if env.get("torch"):
        torch_bits.append(f"torch {env['torch']}")
    if env.get("hip"):
        torch_bits.append(f"HIP {env['hip']}")
    if env.get("rocm_smi"):
        torch_bits.append(env["rocm_smi"])
    lines = [
        "# Benchmark results",
        "",
        f"- **Hardware:** {env.get('gpu_summary', 'unknown')}",
        f"- **Backend:** {env.get('backend', 'unknown')}"
        + (f" ({', '.join(torch_bits)})" if torch_bits else ""),
        f"- **OS:** {env.get('distro', '')} / kernel {env.get('kernel', '')}",
        f"- **CPU:** {env.get('cpu', '')} ({env.get('arch', '')})",
        f"- **Date:** {env.get('timestamp', '')}",
        f"- **Commit:** {env.get('git_commit', '')}",
    ]
    if env.get("label"):
        lines.append(f"- **Label:** {env['label']}")
    if is_cpu_only(env):
        lines += ["", "> **CPU-only run:** timings and VRAM are not representative "
                      "of GPU performance."]
    return "\n".join(lines) + "\n"
