#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B harness for the ASR settings, measured on one fixed clip.

Runs the real pipeline (`core.pipeline_cli`) once per variant, each with its own
`TP_DATA_DIR` so the working configuration is never touched, and reads the phase
timings from the structured events (`@@TPEV@@`, `utils/events.py`).

Why it exists: the knobs that look obvious (bigger batch, longer chunks) are not
obviously wins, and in the 2026-10 measurement they were not — see
`docs/benchmarks/2026-10-26-asr-knobs.md`.

    python bench/asr_ab.py --video /path/clip.mkv \
        --variants bench/asr_ab_variants.json --work-dir /var/tmp/tp-ab

Variant file (JSON, list of objects):

    [{"tag": "baseline", "profile": "maximum"},
     {"tag": "batch8", "profile": "balanced"},
     {"tag": "chunk45", "profile": "maximum",
      "config": {"asr_chunk_target_duration": 45, "asr_chunk_min_duration": 20,
                 "asr_chunk_max_duration": 60}}]

`transcription_profile_locked` is set to false for every run: with the default
(true) `Config.get_transcription_profile()` ignores the profile and returns
`maximum`, which silently makes the A/B meaningless.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
EVENT_PREFIX = "@@TPEV@@ "

BASE_CONFIG: Dict[str, Any] = {
    "transcription_engine_mode": "qwen3",
    "target_language": "ita",
    "use_gpu": True,
    "punctuation_restore_mode": "off",       # keeps the CPU punctuation model out of the timings
    "asr_chunk_target_duration": 20,
    "asr_chunk_min_duration": 10,
    "asr_chunk_max_duration": 25,
    "transcription_profile_locked": False,   # otherwise the profile is forced to 'maximum'
}


def build_config(variant: Dict[str, Any]) -> Dict[str, Any]:
    """Config for one variant: the base plus its profile and overrides."""
    config = dict(BASE_CONFIG)
    if variant.get("profile"):
        config["transcription_profile"] = variant["profile"]
    config.update(variant.get("config") or {})
    if variant.get("target_language"):
        config["target_language"] = variant["target_language"]
    return config


def parse_events(lines: Iterable[str], started: float) -> Dict[str, Any]:
    """Extract phase transitions and the batch line from the pipeline output."""
    phases: List[Dict[str, Any]] = []
    batch_line = ""
    total_line = ""
    for line in lines:
        if line.startswith(EVENT_PREFIX):
            try:
                event = json.loads(line[len(EVENT_PREFIX):])
            except ValueError:
                continue
            if event.get("k") == "phase":
                phases.append({"at": time.time(), "phase": str(event.get("name") or "")})
        elif "Transcribing" in line and "batch=" in line:
            batch_line = line.strip()
        elif "Total time:" in line:
            total_line = line.strip()
    return {"phases": phases, "batch_line": batch_line, "total_line": total_line,
            "started": started}


def phase_timeline(phases: List[Dict[str, Any]], finished: float) -> List[Dict[str, Any]]:
    """Seconds spent in each phase (the last one ends when the process does)."""
    timeline: List[Dict[str, Any]] = []
    for index, item in enumerate(phases):
        end = phases[index + 1]["at"] if index + 1 < len(phases) else finished
        timeline.append({"phase": item["phase"], "seconds": round(end - item["at"], 1)})
    return timeline


def run_variant(video: Path, variant: Dict[str, Any], work_dir: Path,
                python: Optional[str] = None, tmpdir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the pipeline once for `variant` and return its timings."""
    tag = str(variant.get("tag") or "run")
    data_dir = work_dir / f"cfg-{tag}"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True)
    (data_dir / "config.json").write_text(json.dumps(build_config(variant)), encoding="utf-8")
    work_tmp = Path(tmpdir or work_dir / "tmp") / tag
    shutil.rmtree(work_tmp, ignore_errors=True)
    work_tmp.mkdir(parents=True)
    for stale in list(video.parent.glob(f"{video.stem}.*.srt")) + list(work_dir.glob(f"{video.stem}.*.srt")):
        stale.unlink()
    args = {"video_path": str(video),
            "target_language": build_config(variant).get("target_language", "ita"),
            "files_processed": 0, "result_path": str(work_dir / f"result-{tag}.json")}
    args_path = data_dir / "args.json"
    args_path.write_text(json.dumps(args), encoding="utf-8")
    env = dict(os.environ)
    env.update({"TP_DATA_DIR": str(data_dir),
                "TP_MODELS_DIR": env.get("TP_MODELS_DIR", str(ROOT / "models")),
                "TMPDIR": str(work_tmp), "TP_EVENTS": "1",
                "TQDM_DISABLE": "1", "PYTHONIOENCODING": "utf-8"})
    started = time.time()
    process = subprocess.Popen([python or sys.executable, "-m", "core.pipeline_cli", str(args_path)],
                               cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    log_lines = []                                   # log completo: serve a verificare la config usata
    parsed = parse_events(_tee(process.stdout or [], log_lines), started)
    process.wait()
    finished = time.time()
    # la pipeline scrive l'SRT accanto al video: si cerca li', poi in work_dir
    (work_dir / f"log-{tag}.txt").write_text("".join(log_lines), encoding="utf-8")
    produced = next(iter(video.parent.glob(f"{video.stem}.*.srt")), None) \
        or next(iter(work_dir.glob(f"{video.stem}.*.srt")), None)
    kept = work_dir / f"out-{tag}.srt"
    if produced:
        produced.replace(kept)
    return {
        "tag": tag,
        "profile": build_config(variant).get("transcription_profile", ""),
        "returncode_process": process.returncode,
        "wall_seconds": round(finished - started, 1),
        "phases": phase_timeline(parsed["phases"], finished),
        "batch_line": parsed["batch_line"],
        "total_line": parsed["total_line"],
        "srt": str(kept) if kept.exists() else "",
    }


def _tee(lines: Iterable[str], sink: List[str]) -> Iterable[str]:
    """Passa le righe a valle e le accumula, per scrivere il log del run."""
    for line in lines:
        sink.append(line)
        yield line


def summarise(results: List[Dict[str, Any]]) -> str:
    lines = [f"{'variant':14} {'wall':>8} {'demucs':>8} {'asr':>8}  batch"]
    for result in results:
        per = {item["phase"]: item["seconds"] for item in result["phases"]}
        batch = result.get("batch_line", "")
        batch = batch.split("(batch=")[-1].rstrip(")...") if "(batch=" in batch else "?"
        lines.append(f"{result['tag']:14} {result['wall_seconds']:8.1f} "
                     f"{per.get('demucs', 0):8.1f} {per.get('asr', 0):8.1f}  {batch}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A/B the ASR settings on a fixed clip")
    parser.add_argument("--video", required=True, help="video clip used for every run")
    parser.add_argument("--variants", required=True, help="JSON list of variants")
    parser.add_argument("--work-dir", default="/var/tmp/tp-asr-ab",
                        help="where configs, temp folders and results go (never inside the repo)")
    parser.add_argument("--tmpdir", default="", help="TMPDIR for the runs (default: <work-dir>/tmp)")
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        print(f"clip not found: {video}", file=sys.stderr)
        return 2
    work_dir = Path(args.work_dir).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []
    for variant in variants:
        print(f"== {variant.get('tag')}: {variant}", flush=True)
        result = run_variant(video, variant, work_dir,
                             tmpdir=Path(args.tmpdir) if args.tmpdir else None)
        print(summarise(results + [result]).splitlines()[-1], flush=True)
        results.append(result)
        (work_dir / "asr-ab-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n" + summarise(results), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
