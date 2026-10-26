"""Worker CLI for OCR review sessions (`python -m core.ocr_review_job ...`).

Two modes, mirroring the Qt `gui/ocr_worker.py`:

- `ocr`        extract the bitmap subtitle track into OCR events plus one PNG
               per event, then mark the session `ready`;
- `writeback`  rebuild the SRT from the (possibly corrected) events and write
               it as a sidecar next to the video.

The subprocess keeps PIL, tesseract and ffmpeg out of the web process. The
write-back is always a **sidecar**: the browser review never rewrites the
media file, matching what the headless pipeline does today.

Exit status is 0 when the session reached `ready`/`saved`, 1 otherwise; the
reason is recorded in `session.json` (`error`) and in `worker.log`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from web.ocr_review import (STATUS_FAILED, STATUS_READY, STATUS_SAVED,
                           atomic_write_json, read_json)

BITMAP_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub"}
VOBSUB_CODECS = {"dvd_subtitle", "dvdsub"}


def _log(message: str) -> None:
    print(message, flush=True)


def pick_bitmap_kind(video: str) -> str:
    """Return 'pgs' or 'vobsub' for the track to OCR.

    Prefers an Italian bitmap track, then the first bitmap track found. Uses
    `core.subtitle_extractor` so the detection rules stay in one place.
    """
    from core.subtitle_extractor import SubtitleExtractor

    streams = SubtitleExtractor(video).detect_subtitles() or []
    bitmap = [stream for stream in streams
              if (stream.get("codec") or "").lower() in BITMAP_CODECS]
    if not bitmap:
        raise RuntimeError("no PGS/VOBSUB bitmap subtitle track found")
    italian = [stream for stream in bitmap if stream.get("lang") == "it"]
    chosen = (italian or bitmap)[0]
    codec = (chosen.get("codec") or "").lower()
    _log(f"bitmap track {chosen.get('index')} codec={codec} lang={chosen.get('lang')}")
    return "vobsub" if codec in VOBSUB_CODECS else "pgs"


def make_ocr(video: str, kind: str):
    from core.ocr_auto import make_bitmap_ocr
    from utils.config import get_config

    return make_bitmap_ocr(video, get_config(), kind, log_callback=_log)


def run_ocr(session_dir: Path, video: str) -> int:
    from core.pgs_types import WRITEBACK_SIDECAR

    meta = read_json(session_dir / "session.json", {}) or {}
    try:
        kind = pick_bitmap_kind(video)
        ocr = make_ocr(video, kind)
        if hasattr(ocr, "writeback_override"):
            ocr.writeback_override = WRITEBACK_SIDECAR
        _log(f"OCR {kind} on {Path(video).name}")
        events, language = ocr.ocr_to_events()

        records: List[Dict[str, Any]] = []
        images = session_dir / "images"
        images.mkdir(parents=True, exist_ok=True)
        for event in events:
            image_name = ""
            if getattr(event, "image", None) is not None:
                image_name = f"{event.index}.png"
                event.image.convert("RGBA").save(images / image_name, format="PNG")
            records.append({
                "index": event.index,
                "start_ms": event.start_ms,
                "end_ms": event.end_ms,
                "text": event.text,
                "confidence": round(float(event.confidence or 0.0), 2),
                "flags": sorted(event.flags or ()),
                "verified": bool(event.verified),
                "image": image_name,
            })
        flagged = sum(1 for record in records if record["flags"] and not record["verified"])
        atomic_write_json(session_dir / "events.json", records)

        meta.update({
            "status": STATUS_READY,
            "error": "",
            "kind": kind,
            "language": language or meta.get("language") or "",
            "event_count": len(records),
            "flagged_count": flagged,
        })
        atomic_write_json(session_dir / "session.json", meta)
        _log(f"{len(records)} events ({flagged} flagged), language {meta['language']}")
        return 0
    except Exception as exc:  # noqa: BLE001 - the reason goes into the session
        meta.update({"status": STATUS_FAILED, "error": str(exc)})
        atomic_write_json(session_dir / "session.json", meta)
        _log(f"OCR failed: {exc}")
        return 1


def build_events(records: List[Dict[str, Any]]):
    from core.pgs_types import OcrEvent

    events = []
    for record in records:
        events.append(OcrEvent(
            index=int(record.get("index") or 0),
            start_ms=int(record.get("start_ms") or 0),
            end_ms=int(record.get("end_ms") or 0),
            text=record.get("text") or "",
            confidence=float(record.get("confidence") or 0.0),
            flags=set(record.get("flags") or ()),
            verified=bool(record.get("verified")),
        ))
    return events


def run_writeback(session_dir: Path, video: str) -> int:
    from core.pgs_types import WRITEBACK_SIDECAR, events_to_srt

    meta = read_json(session_dir / "session.json", {}) or {}
    try:
        records = read_json(session_dir / "events.json", []) or []
        if not records:
            raise RuntimeError("no OCR events to write")
        srt_text = events_to_srt(build_events(records))
        (session_dir / "draft.srt").write_text(srt_text, encoding="utf-8")

        kind: Optional[str] = meta.get("kind") or pick_bitmap_kind(video)
        ocr = make_ocr(video, kind)
        if hasattr(ocr, "writeback_override"):
            ocr.writeback_override = WRITEBACK_SIDECAR
        language = meta.get("language") or "ita"
        ok = ocr.writeback(srt_text, language)
        if not ok:
            raise RuntimeError("write-back returned false")

        srt_path = str(Path(video).with_name(f"{Path(video).stem}.{language}.srt"))
        meta.update({"status": STATUS_SAVED, "error": "", "srt_path": srt_path})
        atomic_write_json(session_dir / "session.json", meta)
        _log(f"SRT written: {srt_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        meta.update({"status": STATUS_FAILED, "error": str(exc)})
        atomic_write_json(session_dir / "session.json", meta)
        _log(f"write-back failed: {exc}")
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="OCR review worker")
    parser.add_argument("mode", choices=("ocr", "writeback"))
    parser.add_argument("--session", required=True)
    parser.add_argument("--video", required=True)
    args = parser.parse_args(argv)

    session_dir = Path(args.session)
    if not (session_dir / "session.json").is_file():
        print(f"not a session directory: {session_dir}", file=sys.stderr)
        return 1
    if args.mode == "ocr":
        return run_ocr(session_dir, args.video)
    return run_writeback(session_dir, args.video)


if __name__ == "__main__":
    sys.exit(main())
