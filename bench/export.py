"""Export a benchmark run into the repository, sanitized.

The raw runs live under ``~/.transcriberpro/bench/`` and may contain absolute
home paths in logs and result files. This command keeps the useful artefacts
(environment, summary, results) inside the repo after replacing personal paths
with neutral placeholders. Logs and media are never copied.

Usage:
    python -m bench.export --run ~/.transcriberpro/bench/<stamp> \
        --suite translation --out docs/benchmarks/<name>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import fields
from pathlib import Path

from bench.runner import REPO, RunResult, write_report

HOME_RE = re.compile(r"/(?:home|Users)/[^/\s\"']+")


def sanitize_text(text: str) -> str:
    """Remove absolute home paths and the repository path from a string."""
    text = text.replace(str(REPO), "<repo>")
    text = HOME_RE.sub("~", text)
    return text.replace("<repo>/samples", "samples")


def export(run_dir: Path, out_dir: Path, suite: str | None = None) -> Path:
    source = run_dir / "results.json"
    if not source.exists():
        raise SystemExit(f"missing results.json in {run_dir}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    environment = payload.get("environment") or {}
    runs = [run for run in payload.get("runs", []) if not suite or run.get("suite") == suite]
    if not runs:
        raise SystemExit(f"no runs for suite={suite!r} in {run_dir}")

    records = []
    for run in runs:
        values = {field.name: run.get(field.name) for field in fields(RunResult)}
        record = RunResult(**values)
        record.output = Path(record.output).name if record.output else ""
        record.error = sanitize_text(record.error) if record.error else ""
        records.append(record)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_report(records, out_dir, environment)

    source_manifest = run_dir / "manifest.txt"
    if source_manifest.exists():
        manifest = source_manifest.read_text(encoding="utf-8")
        (out_dir / "manifest.txt").write_text(sanitize_text(manifest), encoding="utf-8")

    for name in ("summary.md", "summary.csv", "results.json", "environment.json", "manifest.txt"):
        path = out_dir / name
        if path.exists():
            path.write_text(sanitize_text(path.read_text(encoding="utf-8")), encoding="utf-8")

    (out_dir / "SOURCE.txt").write_text(
        f"source_run={run_dir.name}\nsuite={suite or 'all'}\n", encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export sanitized benchmark results")
    parser.add_argument("--run", type=Path, required=True, help="source run directory")
    parser.add_argument("--suite", choices=["asr", "translation"], default=None)
    parser.add_argument("--out", type=Path, required=True, help="destination inside the repository")
    args = parser.parse_args(argv)

    out = args.out.resolve()
    if not out.is_relative_to(REPO.resolve()):
        print(f"refusing to write outside the repository: {out}", file=sys.stderr)
        return 2
    if not (args.run / "results.json").exists():
        print(f"missing results.json in {args.run}", file=sys.stderr)
        return 2

    export(args.run, out, args.suite)
    print(f"exported to {out}")
    for name in ("summary.md", "results.json", "environment.json", "manifest.txt", "SOURCE.txt"):
        path = out / name
        if path.exists():
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
