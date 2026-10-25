"""Benchmark CLI.

Examples:
    python -m bench.run --suite asr --engines faster-whisper,qwen3 --repeat 3
    python -m bench.run --suite translation --engines nllb,llm --repeat 3
    python -m bench.run --suite all

Results go to ~/.transcriberpro/bench/<timestamp>/ (outside the repository).
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

from bench.runner import (
    DEFAULT_DATA, DEFAULT_OUT, REPO,
    run_asr, run_translation, summary, write_report,
)

DEFAULT_ASR_ENGINES = "faster-whisper,qwen3"
DEFAULT_TRANSLATION_ENGINES = "nllb,llm"


def _engines(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcriber Pro benchmark harness")
    parser.add_argument("--suite", choices=["asr", "translation", "all"], default="asr")
    parser.add_argument("--engines", default="", help="comma separated; defaults depend on the suite")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    if not args.data.is_dir():
        print(f"data directory not found: {args.data}", file=sys.stderr)
        return 2

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out or (DEFAULT_OUT / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"results: {out_dir}")

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        commit = ""
    (out_dir / "manifest.txt").write_text(
        f"commit={commit}\ndata={args.data}\nsuite={args.suite}\nrepeat={args.repeat}\n",
        encoding="utf-8",
    )

    records = []
    suites = ["asr", "translation"] if args.suite == "all" else [args.suite]
    for suite in suites:
        engines = _engines(args.engines) or _engines(
            DEFAULT_ASR_ENGINES if suite == "asr" else DEFAULT_TRANSLATION_ENGINES)
        runner = run_asr if suite == "asr" else run_translation
        for engine in engines:
            records.extend(runner(engine, args.data, out_dir, args.repeat, args.timeout))

    write_report(records, out_dir)
    rows = summary(records)
    for row in rows:
        print(f"{row['suite']:<12} {row['engine']:<16} "
              f"runs={row['runs']} failed={row['failed']} "
              f"time={row.get('time_s_median', 0):.1f}s "
              f"wer={row.get('wer', float('nan')):.3f} "
              f"chrf={row.get('chrf', float('nan')):.3f} "
              f"vram={row.get('peak_vram_mib')}")

    failed = sum(row["failed"] for row in rows)
    total = sum(row["runs"] for row in rows)
    print(f"done: {total - failed}/{total} runs ok")
    return 0 if failed < total else 1


if __name__ == "__main__":
    sys.exit(main())
