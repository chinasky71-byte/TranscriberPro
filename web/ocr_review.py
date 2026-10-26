"""OCR review sessions for the WebUI.

The data contract is frozen in `core/pgs_types.py` (`OcrEvent`,
`events_to_srt`): the Qt dialog and this module consume the same schema, so a
correction made in the browser means the same thing as one made in the desktop
dialog.

An OCR run happens in a **subprocess** (`core/ocr_review_job.py`), like the Qt worker:
PIL, tesseract and the extraction cost never enter the web process, and a
crash in the OCR engine cannot take the API down.

Layout under `TP_DATA_DIR/ocr/<session_id>/`:

```
session.json     metadata and status (atomic writes)
events.json      list of OCR events, `image` is the file name in images/
images/<i>.png   the bitmap shown next to the text
worker.log       stdout/stderr of the OCR subprocess
draft.srt        the SRT produced by the last write-back
```

The session directory holds media-derived text and images, therefore it lives
outside the project tree (privacy rule in `AGENTS.md`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = "core.ocr_review_job"

STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_SAVING = "saving"
STATUS_SAVED = "saved"
STATUS_FAILED = "failed"

_SESSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_TEXT_CHARS = 2000


class OcrSessionError(ValueError):
    """Bad request on a session (unknown id, invalid index, wrong state)."""


class OcrSessionNotFound(OcrSessionError):
    """The session does not exist."""


def atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


Runner = Callable[[Path, str, str], None]


def default_runner(session_dir: Path, video: str, mode: str) -> None:
    """Start `python -m core.ocr_review_job <mode> ...` without waiting for it."""
    log_path = session_dir / "worker.log"
    with open(log_path, "ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", MODULE, mode, "--session", str(session_dir),
             "--video", video],
            cwd=str(PROJECT_ROOT), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )


class OcrReviewService:
    """Filesystem-backed store plus the two OCR operations (extract, write back)."""

    def __init__(self, root: Path, runner: Optional[Runner] = None):
        self.root = Path(root)
        self.runner = runner or default_runner
        self.root.mkdir(parents=True, exist_ok=True)

    # ── paths ────────────────────────────────────────────────────────────
    def _dir(self, session_id: str) -> Path:
        if not _SESSION_ID_RE.match(session_id or ""):
            raise OcrSessionNotFound("unknown session")
        path = self.root / session_id
        if not path.is_dir():
            raise OcrSessionNotFound("unknown session")
        return path

    @staticmethod
    def _meta(session_dir: Path) -> Dict[str, Any]:
        return read_json(session_dir / "session.json", {}) or {}

    # ── operations ───────────────────────────────────────────────────────
    def create(self, video: str, language: str = "") -> Dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        session_dir = self.root / session_id
        (session_dir / "images").mkdir(parents=True, exist_ok=True)
        meta = {
            "id": session_id,
            "video": str(video),
            "name": Path(video).name,
            "language": language,
            "kind": "",
            "status": STATUS_RUNNING,
            "error": "",
            "created_at": time.time(),
            "updated_at": time.time(),
            "event_count": 0,
            "flagged_count": 0,
            "srt_path": "",
        }
        atomic_write_json(session_dir / "session.json", meta)
        self.runner(session_dir, str(video), "ocr")
        return self._meta(session_dir)

    def list(self) -> List[Dict[str, Any]]:
        sessions = []
        for session_dir in sorted(self.root.iterdir()):
            if not session_dir.is_dir() or not _SESSION_ID_RE.match(session_dir.name):
                continue
            meta = self._meta(session_dir)
            if meta:
                sessions.append(meta)
        sessions.sort(key=lambda meta: meta.get("created_at") or 0.0, reverse=True)
        return sessions

    def get(self, session_id: str) -> Dict[str, Any]:
        return self._meta(self._dir(session_id))

    def events(self, session_id: str) -> List[Dict[str, Any]]:
        return read_json(self._dir(session_id) / "events.json", []) or []

    def image_path(self, session_id: str, index: int) -> Path:
        return self._image(self._dir(session_id), index)

    @staticmethod
    def _image(session_dir: Path, index: int) -> Path:
        if index < 1:
            raise OcrSessionError("event index must be >= 1")
        path = session_dir / "images" / f"{index}.png"
        if not path.is_file():
            raise OcrSessionNotFound("no bitmap for this event")
        return path

    def update_event(self, session_id: str, index: int, text: str,
                     verified: bool) -> Dict[str, Any]:
        session_dir = self._dir(session_id)
        meta = self._meta(session_dir)
        if meta.get("status") not in (STATUS_READY, STATUS_SAVED):
            raise OcrSessionError("the session is not ready for review")
        events = read_json(session_dir / "events.json", []) or []
        target = next((event for event in events if event.get("index") == index), None)
        if target is None:
            raise OcrSessionNotFound("unknown event")
        if len(text or "") > MAX_TEXT_CHARS:
            raise OcrSessionError(f"text is longer than {MAX_TEXT_CHARS} characters")
        target["text"] = text or ""
        target["verified"] = bool(verified)
        atomic_write_json(session_dir / "events.json", events)
        meta["flagged_count"] = sum(1 for event in events
                                    if event.get("flags") and not event.get("verified"))
        meta["updated_at"] = time.time()
        atomic_write_json(session_dir / "session.json", meta)
        return target

    def writeback(self, session_id: str) -> Dict[str, Any]:
        session_dir = self._dir(session_id)
        meta = self._meta(session_dir)
        if meta.get("status") not in (STATUS_READY, STATUS_SAVED):
            raise OcrSessionError("the session is not ready for write-back")
        meta["status"] = STATUS_SAVING
        meta["error"] = ""
        meta["updated_at"] = time.time()
        atomic_write_json(session_dir / "session.json", meta)
        self.runner(session_dir, meta.get("video", ""), "writeback")
        return self._meta(session_dir)

    def delete(self, session_id: str) -> None:
        session_dir = self._dir(session_id)
        for child in sorted(session_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        session_dir.rmdir()

    # ── helpers used by the worker and by tests ──────────────────────────
    def set_status(self, session_id: str, status: str, error: str = "",
                   **extra: Any) -> Dict[str, Any]:
        session_dir = self._dir(session_id)
        meta = self._meta(session_dir)
        meta.update({"status": status, "error": error, "updated_at": time.time(), **extra})
        atomic_write_json(session_dir / "session.json", meta)
        return meta


def session_dir_for(root: Path, session_id: str) -> Path:
    """Path of a session directory, validated (used by the worker CLI)."""
    if not _SESSION_ID_RE.match(session_id or ""):
        raise OcrSessionNotFound("unknown session")
    return Path(root) / session_id


def env_root(config: Any) -> Path:
    base = getattr(config, "CONFIG_DIR", None) or os.environ.get("TP_DATA_DIR", "")
    return Path(base).expanduser() / "ocr" if base else Path.home() / ".transcriberpro" / "ocr"
