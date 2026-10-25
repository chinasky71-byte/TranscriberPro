"""Benchmark runners.

Two suites:

* ``asr`` — runs the real headless pipeline (``core.queue_runner``) with a
  forced engine and English target, then scores the produced SRT against the
  reference transcription.
* ``translation`` — translates a source SRT built from the reference English
  lines with one engine, then scores the output against the reference
  translation. Timings are synthetic; only the text matters.

Results are written outside the repository (default
``~/.transcriberpro/bench/<timestamp>/``), as required by the privacy rule.
"""
from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from bench import metrics
from bench.text import (Line, compact, normalize, parse_reference,
                        split_sentences, srt_blocks, srt_from_lines, tokens)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "samples"
DEFAULT_OUT = Path.home() / ".transcriberpro" / "bench"
CONFIG_FILE = Path.home() / ".transcriberpro" / "config.json"

ASR_VIDEO = "prova_amd_test.mp4"
ASR_REFERENCE = "correct_transcription_en.txt"
TRANSLATION_SOURCE = "correct_transcription_en.txt"
TRANSLATION_REFERENCE = "correct_translation_it.txt"


@dataclass
class RunResult:
    suite: str
    engine: str
    run: int
    time_s: float
    peak_vram_mib: Optional[int]
    metrics: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: str = ""
    device: str = ""


def detect_device(text: str, peak_mib: Optional[int] = None) -> str:
    """Infer whether a run actually used the GPU, from its log and VRAM peak."""
    low = (text or "").lower()
    if "device=cpu" in low or "loaded on cpu" in low or "caricato su cpu" in low:
        return "cpu"
    if "device=gpu" in low or "loaded on cuda" in low or "caricato su cuda" in low:
        return "gpu"
    if "gguf" in low and ("vulkan" in low or "offload" in low):
        return "gpu"
    if peak_mib is not None:
        if peak_mib >= 1500:
            return "gpu"
        if peak_mib <= 800:
            return "cpu"
    return "unknown"


class VramSampler:
    """Poll ``rocm-smi`` on device 0 and keep the peak used memory."""

    def __init__(self, interval_s: float = 0.5):
        self.interval_s = interval_s
        self.peak_mib: Optional[int] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _read(self) -> Optional[int]:
        try:
            out = subprocess.run(
                ["rocm-smi", "-d", "0", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            return None
        for line in out.splitlines():
            if "Used Memory" in line:
                try:
                    value = int(line.rsplit(":", 1)[1].strip())
                    return value // (1024 * 1024)
                except ValueError:
                    return None
        return None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            value = self._read()
            if value is not None and (self.peak_mib is None or value > self.peak_mib):
                self.peak_mib = value

    def __enter__(self) -> "VramSampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


@contextmanager
def temporary_config(updates: dict[str, Any]):
    """Apply config keys for the duration of a run, then restore the file byte for byte."""
    original = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else None
    data = json.loads(original) if original else {}
    data.update(updates)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        yield
    finally:
        if original is None:
            CONFIG_FILE.unlink(missing_ok=True)
        else:
            CONFIG_FILE.write_text(original, encoding="utf-8")


def _run(cmd: list[str], timeout_s: int, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(REPO), capture_output=True, text=True,
        timeout=timeout_s, env=env,
    )


def _score_transcription(reference_text: str, hypothesis_text: str) -> dict:
    ref_tokens, hyp_tokens = tokens(reference_text), tokens(hypothesis_text)
    return {
        "wer": metrics.wer(ref_tokens, hyp_tokens),
        "cer": metrics.cer(compact(reference_text), compact(hypothesis_text)),
        "chrf": metrics.chrf(normalize(reference_text), normalize(hypothesis_text)),
        "similarity": metrics.similarity(ref_tokens, hyp_tokens),
        "words_ref": len(ref_tokens),
        "words_hyp": len(hyp_tokens),
    }


def _score_translation(source_blocks: list[str], output_blocks: list[str], reference_text: str) -> dict:
    output_text = " ".join(output_blocks)
    source_text = " ".join(source_blocks)
    flagged = metrics.untranslated_blocks(source_blocks, output_blocks)
    return {
        "wer": metrics.wer(tokens(reference_text), tokens(output_text)),
        "cer": metrics.cer(compact(reference_text), compact(output_text)),
        "chrf": metrics.chrf(normalize(reference_text), normalize(output_text)),
        "similarity": metrics.similarity(tokens(reference_text), tokens(output_text)),
        "untranslated_blocks": len(flagged),
        "blocks": len(output_blocks),
        "blocks_source": len(source_blocks),
        "untranslated_ratio": (len(flagged) / len(output_blocks)) if output_blocks else 1.0,
        "words_ref": len(tokens(reference_text)),
        "words_hyp": len(tokens(output_text)),
        "source_words": len(tokens(source_text)),
    }


def _write_output(run_dir: Path, name: str, content: str) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def run_asr(engine: str, data_dir: Path, out_dir: Path, repeat: int,
            timeout_s: int, log=print) -> list[RunResult]:
    video = data_dir / ASR_VIDEO
    reference = " ".join(line.text for line in parse_reference(data_dir / ASR_REFERENCE))
    results: list[RunResult] = []

    for index in range(repeat):
        started = time.perf_counter()
        error = ""
        hypothesis = ""
        peak = None
        with tempfile.TemporaryDirectory(prefix="tp_bench_asr_") as tmp:
            tmp_path = Path(tmp)
            with VramSampler() as sampler:
                try:
                    with temporary_config({
                        "transcription_engine_mode": engine,
                        "target_language": "eng",
                        "dialogue_style_enabled": False,
                        "enable_diarization": False,
                        "model_cache_cleanup_enabled": False,
                    }):
                        proc = _run(
                            [sys.executable, "-m", "core.queue_runner", str(video),
                             "--status", str(tmp_path / "status.json"),
                             "--log-dir", str(tmp_path / "logs")],
                            timeout_s=timeout_s,
                        )
                finally:
                    peak = sampler.peak_mib
                elapsed = time.perf_counter() - started
                logs = sorted((tmp_path / "logs").glob("*.log"))
                log_text = ""
                if logs:
                    log_text = logs[-1].read_text(encoding="utf-8", errors="replace")
                    _write_output(out_dir / "asr" / engine, f"run{index}.log", log_text)
                if proc.returncode != 0:
                    tail = logs[-1].read_text(encoding="utf-8", errors="replace")[-2000:] if logs else proc.stderr[-2000:]
                    error = f"exit {proc.returncode}: {tail}"
                else:
                    produced = video.with_suffix(".en.srt")
                    if not produced.exists():
                        error = "pipeline succeeded but produced no .en.srt"
                    else:
                        blocks = srt_blocks(produced)
                        hypothesis = " ".join(blocks)
                        srt_text = produced.read_text(encoding="utf-8-sig")
                        produced.unlink(missing_ok=True)

        record = RunResult(suite="asr", engine=engine, run=index, time_s=elapsed,
                           peak_vram_mib=peak, error=error,
                           device=detect_device(log_text, peak))
        if hypothesis:
            record.metrics = _score_transcription(reference, hypothesis)
            record.output = str(_write_output(out_dir / "asr" / engine, f"run{index}.srt", srt_text))
        results.append(record)
        log(f"[asr:{engine}] run {index + 1}/{repeat}: "
            f"{'OK' if not error else 'FAIL'} in {elapsed:.1f}s"
            + (f", peak {peak} MiB" if peak else ""))
    return results


def run_translation(engine: str, data_dir: Path, out_dir: Path, repeat: int,
                    timeout_s: int, log=print) -> list[RunResult]:
    source_lines = parse_reference(data_dir / TRANSLATION_SOURCE)
    reference_text = " ".join(line.text for line in parse_reference(data_dir / TRANSLATION_REFERENCE))
    sentences = []
    for line in source_lines:
        sentences.extend(Line(line.speaker, part) for part in split_sentences(line.text))
    source_blocks = [line.text for line in sentences]
    source_srt = srt_from_lines(sentences)
    results: list[RunResult] = []

    for index in range(repeat):
        started = time.perf_counter()
        error = ""
        output_blocks: list[str] = []
        peak = None
        with tempfile.TemporaryDirectory(prefix="tp_bench_tr_") as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.srt"
            out_path = tmp_path / "translated.srt"
            src_path.write_text(source_srt, encoding="utf-8")
            with VramSampler() as sampler:
                try:
                    proc = _run(
                        [sys.executable, "-m", "bench._translate", engine,
                         str(src_path), str(out_path)],
                        timeout_s=timeout_s,
                    )
                finally:
                    peak = sampler.peak_mib
            elapsed = time.perf_counter() - started
            log_text = (proc.stdout or "") + (proc.stderr or "")
            _write_output(out_dir / "translation" / engine, f"run{index}.log", log_text)
            if proc.returncode != 0 or not out_path.exists():
                error = f"exit {proc.returncode}: {proc.stderr[-2000:]}"
            else:
                output_blocks = srt_blocks(out_path)
                _write_output(out_dir / "translation" / engine, f"run{index}.srt",
                              out_path.read_text(encoding="utf-8-sig"))

        record = RunResult(suite="translation", engine=engine, run=index,
                           time_s=elapsed, peak_vram_mib=peak, error=error,
                           device=detect_device((proc.stdout or "") + (proc.stderr or ""), peak))
        if output_blocks:
            record.metrics = _score_translation(source_blocks, output_blocks, reference_text)
        results.append(record)
        log(f"[translation:{engine}] run {index + 1}/{repeat}: "
            f"{'OK' if not error else 'FAIL'} in {elapsed:.1f}s"
            + (f", peak {peak} MiB" if peak else ""))
    return results


def summary(records: list[RunResult], environment: Optional[dict] = None) -> list[dict]:
    grouped: dict[tuple[str, str], list[RunResult]] = {}
    for record in records:
        grouped.setdefault((record.suite, record.engine), []).append(record)

    rows = []
    for (suite, engine), items in sorted(grouped.items()):
        ok = [item for item in items if not item.error]
        row: dict[str, Any] = {
            "suite": suite,
            "engine": engine,
            "runs": len(items),
            "failed": len(items) - len(ok),
            "device": ",".join(sorted({item.device for item in items if item.device})) or "unknown",
        }
        if environment:
            row["backend"] = environment.get("backend", "")
            row["hardware"] = environment.get("gpu_summary", "")
        if ok:
            row["time_s_median"] = statistics.median(item.time_s for item in ok)
            peaks = [item.peak_vram_mib for item in ok if item.peak_vram_mib is not None]
            row["peak_vram_mib"] = max(peaks) if peaks else None
            for key in ("wer", "cer", "chrf", "similarity"):
                values = [item.metrics[key] for item in ok if key in item.metrics]
                if values:
                    if key in ("wer", "cer"):
                        row[key] = statistics.median(v["rate"] for v in values)
                    else:
                        row[key] = statistics.median(values)
            if all("untranslated_ratio" in item.metrics for item in ok):
                row["untranslated_ratio"] = statistics.median(
                    item.metrics["untranslated_ratio"] for item in ok)
        rows.append(row)
    return rows


def write_report(records: list[RunResult], out_dir: Path,
                 environment: Optional[dict] = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = summary(records, environment)
    payload: dict[str, Any] = {"environment": environment,
                              "runs": [record.__dict__ for record in records],
                              "summary": rows}
    (out_dir / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if environment:
        (out_dir / "environment.json").write_text(
            json.dumps(environment, indent=2, ensure_ascii=False), encoding="utf-8")
    headers = ["suite", "engine", "runs", "failed", "device", "backend", "hardware",
               "time_s_median", "peak_vram_mib", "wer", "cer", "chrf", "similarity",
               "untranslated_ratio"]
    lines = []
    if environment:
        from bench.environment import header
        lines.append(header(environment))
    lines += ["| " + " | ".join(headers) + " |",
              "|" + "---|" * len(headers)]
    for row in rows:
        cells = []
        for header_name in headers:
            value = row.get(header_name)
            if isinstance(value, float):
                cells.append(f"{value:.4f}")
            else:
                cells.append("" if value is None else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    csv_headers = headers
    csv_lines = [",".join(csv_headers)]
    for row in rows:
        csv_lines.append(",".join("" if row.get(h) is None else str(row.get(h)) for h in csv_headers))
    (out_dir / "summary.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
