# -*- coding: utf-8 -*-
"""Sanitized export of benchmark results (no personal paths in git)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.export import export, sanitize_text  # noqa: E402
from bench.runner import REPO  # noqa: E402


def test_sanitize_replaces_repo_and_home():
    assert sanitize_text(f"{REPO}/samples/x.srt") == "samples/x.srt"
    assert sanitize_text("/home/alice/projects/x") == "~/projects/x"
    assert sanitize_text("/Users/alice/x") == "~/x"
    assert sanitize_text("plain text") == "plain text"


def test_export_writes_sanitized_results(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    payload = {
        "environment": {"gpu_summary": "Test GPU", "backend": "rocm",
                        "distro": "Linux", "kernel": "x", "cpu": "cpu",
                        "arch": "x86_64", "timestamp": "now", "git_commit": "abc"},
        "runs": [{
            "suite": "translation", "engine": "nllb", "run": 0,
            "time_s": 1.0, "peak_vram_mib": 100, "device": "gpu",
            "metrics": {"wer": {"rate": 0.1}, "cer": {"rate": 0.1},
                        "chrf": 0.9, "similarity": 0.9},
            "output": "/home/alice/results/run0.srt",
            "error": "failed at /home/alice/work",
        }],
    }
    (run_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "manifest.txt").write_text("data=/home/alice/samples\n", encoding="utf-8")

    out = tmp_path / "out"
    export(run_dir, out, "translation")

    text = "\n".join(path.read_text(encoding="utf-8") for path in out.glob("*"))
    assert "/home/" not in text
    assert "alice" not in text
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert results["runs"][0]["output"] == "run0.srt"
    assert "Test GPU" in (out / "summary.md").read_text(encoding="utf-8")
    assert (out / "SOURCE.txt").exists()
