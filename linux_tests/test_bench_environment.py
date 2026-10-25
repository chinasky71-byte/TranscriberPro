# -*- coding: utf-8 -*-
"""Hardware/environment reporting tests (no GPU required)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import environment  # noqa: E402
from bench.runner import detect_device  # noqa: E402


def test_detect_device_from_log_and_vram():
    assert detect_device("AdaptiveBatchManager started: device=CPU") == "cpu"
    assert detect_device("Model large-v3 loaded on CPU") == "cpu"
    assert detect_device("AdaptiveBatchManager started: device=GPU") == "gpu"
    assert detect_device("Model loaded on CUDA") == "gpu"
    assert detect_device("GGUF Vulkan offload enabled") == "gpu"
    assert detect_device("", 9000) == "gpu"
    assert detect_device("", 500) == "cpu"
    assert detect_device("", None) == "unknown"


def test_cpu_only_detection():
    assert environment.is_cpu_only({"backend": "cpu"})
    assert environment.is_cpu_only({"backend": "cpu (GPU detected but not usable by torch)"})
    assert not environment.is_cpu_only({"backend": "rocm"})
    assert not environment.is_cpu_only({"backend": "cuda"})


def test_header_states_hardware_and_backend():
    env = {
        "gpu_summary": "Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB",
        "backend": "rocm",
        "torch": "2.10.0+rocm7.0",
        "hip": "7.0.51831",
        "rocm_smi": "ROCM-SMI version: 4.0.0",
        "distro": "Ubuntu 26.04.1 LTS",
        "kernel": "7.0.0-38-generic",
        "cpu": "AMD Ryzen 5 9600X",
        "arch": "x86_64",
        "timestamp": "2026-10-25T12:00:00+02:00",
        "git_commit": "abc1234",
    }
    text = environment.header(env)
    assert "**Hardware:** Radeon RX 9060 XT" in text
    assert "**Backend:** rocm" in text
    assert "HIP 7.0.51831" in text
    assert "CPU-only" not in text


def test_header_warns_on_cpu_runs():
    env = {"gpu_summary": "no discrete GPU detected", "backend": "cpu",
           "distro": "Linux", "kernel": "x", "cpu": "x", "arch": "x86_64",
           "timestamp": "now", "git_commit": "abc"}
    text = environment.header(env)
    assert "CPU-only run" in text
    assert "not representative" in text
