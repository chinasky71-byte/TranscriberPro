#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score a generated SRT against a reference SRT (or an embedded subtitle track).

The comparison has to survive two realities:

- the two files segment the text differently (a human subtitle splits sentences
  where the ASR does not), so text is compared inside **time windows** (10 s by
  default): every cue is assigned to the window of its midpoint and the windows
  are concatenated in order before scoring;
- a human subtitle is not a verbatim transcript: it drops fillers, condenses and
  rephrases. Absolute WER against subtitles is therefore optimistic-biased for
  the machine and pessimistic for the human, so this tool is meant to **rank**
  configurations that share the same handicap, and it reports chrF (more tolerant
  of wording) plus coverage and silence insertions next to WER.

Usage:

    python bench/subtitle_eval.py --make-clip SRC.mkv --at 600 --duration 600 --out clip.mkv
    python bench/subtitle_eval.py --extract-reference SRC.mkv --stream 22 --out ref.srt
    python bench/subtitle_eval.py --reference ref.srt --hypothesis out.srt --json score.json

Metrics come from :mod:`bench.metrics` and :mod:`bench.text`, so they are the
same ones the rest of the benchmark suite uses.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.metrics import cer, chrf, wer  # noqa: E402
from bench.text import normalize, parse_srt_entries, tokens  # noqa: E402

TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
DEFAULT_WINDOW_S = 10.0
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>|\{\\[^}]*\}")     # <i>, <font ...>, {\an8}


def _seconds(stamp: str) -> float:
    match = TIME_RE.search(stamp)
    if not match:
        raise ValueError(f"bad timestamp: {stamp}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def strip_tags(text: str) -> str:
    """Remove SRT/ASS formatting: `<i>`, `<font ...>`, `{\\an8}` and friends."""
    return TAG_RE.sub(" ", text)


def clean(text: str) -> str:
    """Formatting removed, then the shared benchmark normalisation."""
    return normalize(strip_tags(text))


WATERMARK_RE = re.compile(r"ai generated subtitles", re.IGNORECASE)
ITALIC_RE = re.compile(r"^\s*<i>(.*)</i>\s*$", re.IGNORECASE)


def is_italic_only(text: str) -> bool:
    """True when every line of the cue is wrapped in <i>…</i> (songs, off-screen, radio)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and all(ITALIC_RE.match(line) for line in lines)


def cues(path: Path, drop_watermark: bool = True) -> List[Dict[str, Any]]:
    """SRT -> [{start, end, text, italic}], in seconds.

    The watermark this pipeline writes at the top of every file is dropped: it is
    our own artifact, not transcription, and it would count as a huge error.
    """
    result = []
    for entry in parse_srt_entries(path):
        text = entry["text"]
        if drop_watermark and WATERMARK_RE.search(text):
            continue
        result.append({"start": _seconds(entry["start"]), "end": _seconds(entry["end"]),
                       "text": text, "italic": is_italic_only(text)})
    return result


def bucket_text(items: Iterable[Dict[str, Any]], window_s: float = DEFAULT_WINDOW_S) -> Dict[int, str]:
    """Cue texts grouped by the window that contains each cue's midpoint."""
    buckets: Dict[int, List[str]] = {}
    for item in items:
        middle = (item["start"] + item["end"]) / 2.0
        index = int(middle // window_s)
        buckets.setdefault(index, []).append(item["text"])
    return {index: " ".join(texts) for index, texts in sorted(buckets.items())}


def _joined(buckets: Dict[int, str]) -> str:
    return " ".join(buckets[index] for index in sorted(buckets))


def timing_offsets(reference: List[Dict[str, Any]], hypothesis: List[Dict[str, Any]]) -> Dict[str, float]:
    """Median and p90 of |start offset| for the cues that overlap in time."""
    offsets: List[float] = []
    for ref in reference:
        best, best_overlap = None, 0.0
        for hyp in hypothesis:
            overlap = min(ref["end"], hyp["end"]) - max(ref["start"], hyp["start"])
            if overlap > best_overlap:
                best, best_overlap = hyp, overlap
        if best is None:                       # nessuna sovrapposizione: il piu' vicino entro 5 s
            nearest = min(hypothesis, key=lambda hyp: abs(hyp["start"] - ref["start"]), default=None)
            if nearest is not None and abs(nearest["start"] - ref["start"]) <= 5.0:
                best = nearest
        if best is not None:
            offsets.append(abs(best["start"] - ref["start"]))
    if not offsets:
        return {"count": 0, "median_s": 0.0, "p90_s": 0.0}
    offsets.sort()
    middle = len(offsets) // 2
    median = offsets[middle] if len(offsets) % 2 else (offsets[middle - 1] + offsets[middle]) / 2.0
    p90 = offsets[min(len(offsets) - 1, int(len(offsets) * 0.9))]
    return {"count": len(offsets), "median_s": round(median, 2), "p90_s": round(p90, 2)}


def evaluate(reference: List[Dict[str, Any]], hypothesis: List[Dict[str, Any]],
             window_s: float = DEFAULT_WINDOW_S,
             exclude_italic_reference: bool = True) -> Dict[str, Any]:
    """Compare two cue lists inside time windows and return the metrics.

    `exclude_italic_reference` drops reference cues that are entirely italic
    (songs, off-screen voices): the pipeline does not transcribe singing, so
    keeping them measures something else. The amount excluded is reported.
    """
    italic = [cue for cue in reference if cue.get("italic")]
    italic_windows = {int(((cue["start"] + cue["end"]) / 2.0) // window_s) for cue in italic}
    if exclude_italic_reference and italic:
        reference = [cue for cue in reference if not cue.get("italic")]
    ref_buckets = bucket_text(reference, window_s)
    hyp_buckets = bucket_text(hypothesis, window_s)
    ref_windows = {index: clean(text) for index, text in ref_buckets.items()}
    hyp_windows = {index: clean(text) for index, text in hyp_buckets.items()}
    if exclude_italic_reference:
        # Le finestre con soli corsivi (canzoni, voci fuori campo) escono dal
        # confronto **da entrambi i lati**: chi le trascrive non guadagna, chi le
        # salta non viene penalizzato.
        hyp_windows = {index: text for index, text in hyp_windows.items()
                       if index not in italic_windows}
    ref_windows = {index: text for index, text in ref_windows.items() if text}
    hyp_windows = {index: text for index, text in hyp_windows.items() if text}

    shared = sorted(set(ref_windows) & set(hyp_windows))
    only_ref = sorted(set(ref_windows) - set(hyp_windows))
    only_hyp = sorted(set(hyp_windows) - set(ref_windows))

    ref_text = " ".join(ref_windows[index] for index in sorted(ref_windows))
    hyp_shared = " ".join(hyp_windows[index] for index in shared)
    ref_shared = " ".join(ref_windows[index] for index in shared)
    silence_words = sum(len(tokens(hyp_windows[index])) for index in only_hyp)
    missing_words = sum(len(tokens(ref_windows[index])) for index in only_ref)

    global_wer = wer(tokens(ref_text), tokens(hyp_shared))
    return {
        "window_s": window_s,
        "excluded_italic": {
            "cues": len(italic) if exclude_italic_reference else 0,
            "words": len(tokens(_joined(bucket_text(italic, window_s)))) if exclude_italic_reference else 0,
            "windows": len(italic_windows) if exclude_italic_reference else 0,
        },
        "reference": {
            "cues": len(reference),
            "words": len(tokens(ref_text)),
            "windows": len(ref_windows),
        },
        "hypothesis": {
            "cues": len(hypothesis),
            "words": len(tokens(_joined(hyp_buckets))),
            "windows": len(hyp_windows),
        },
        "coverage": {
            "matched_windows": len(shared),
            "coverage_pct": round(100.0 * len(shared) / len(ref_windows), 1) if ref_windows else 0.0,
            "missing_windows": len(only_ref),
            "missing_words": missing_words,
        },
        "silence": {
            "extra_windows": len(only_hyp),
            "extra_words": silence_words,
        },
        "wer": {**global_wer, "rate_pct": round(100.0 * global_wer["rate"], 2)},
        "cer": {"rate_pct": round(100.0 * cer(ref_text.replace(" ", ""), hyp_shared.replace(" ", ""))["rate"], 2)},
        "chrf": round(100.0 * chrf(ref_text, hyp_shared), 2),
        "wer_matched_only": round(100.0 * wer(tokens(ref_shared), tokens(hyp_shared))["rate"], 2),
        "timing": timing_offsets(reference, hypothesis),
        "per_window": {
            str(index): round(100.0 * wer(tokens(ref_windows[index]), tokens(hyp_windows.get(index, "")))["rate"], 1)
            for index in sorted(ref_windows)
        },
    }


def extract_track(video: Path, stream: int, out: Path, ffmpeg: str = "ffmpeg") -> Path:
    """Extract one subtitle stream (by absolute index) to `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(video),
                             "-map", f"0:{stream}", str(out)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:300]}")
    return out


def cut_clip(video: Path, start_s: float, duration_s: float, out: Path,
             ffmpeg: str = "ffmpeg") -> Path:
    """Cut a clip without re-encoding, keeping the subtitle tracks aligned."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", str(start_s), "-i", str(video),
                             "-t", str(duration_s), "-c", "copy", "-map", "0", str(out)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:300]}")
    return out


def summarise(result: Dict[str, Any], label: str = "") -> str:
    head = f"{label}: " if label else ""
    return (f"{head}WER {result['wer']['rate_pct']}% (matched {result['wer_matched_only']}%) · "
            f"CER {result['cer']['rate_pct']}% · chrF {result['chrf']} · "
            f"coverage {result['coverage']['coverage_pct']}% · "
            f"parole extra {result['silence']['extra_words']} · "
            f"sfasamento mediano {result['timing']['median_s']}s")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score a generated SRT against a reference")
    parser.add_argument("--reference", help="reference SRT")
    parser.add_argument("--hypothesis", help="generated SRT")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_S, help="window size in seconds")
    parser.add_argument("--json", default="", help="write the full result here")
    parser.add_argument("--extract-reference", metavar="VIDEO", help="extract a subtitle stream from a video")
    parser.add_argument("--stream", type=int, default=0, help="absolute stream index for --extract-reference")
    parser.add_argument("--make-clip", metavar="VIDEO", help="cut a clip from a video")
    parser.add_argument("--at", type=float, default=0.0, help="clip start in seconds")
    parser.add_argument("--duration", type=float, default=600.0, help="clip duration in seconds")
    parser.add_argument("--out", default="", help="output path for --extract-reference / --make-clip")
    args = parser.parse_args(argv)

    if args.make_clip:
        if not args.out:
            parser.error("--make-clip needs --out")
        clip = cut_clip(Path(args.make_clip), args.at, args.duration, Path(args.out))
        print(f"clip: {clip} ({clip.stat().st_size // (1024 * 1024)} MB)")
        return 0
    if args.extract_reference:
        if not args.out:
            parser.error("--extract-reference needs --out and --stream")
        ref = extract_track(Path(args.extract_reference), args.stream, Path(args.out))
        print(f"reference: {ref} ({len(cues(ref))} cues)")
        return 0
    if not args.reference or not args.hypothesis:
        parser.error("need --reference and --hypothesis")
    result = evaluate(cues(Path(args.reference)), cues(Path(args.hypothesis)), args.window)
    print(summarise(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"json: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
