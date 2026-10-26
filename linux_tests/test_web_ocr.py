# -*- coding: utf-8 -*-
"""OCR review: session store, API and pages, with a fake OCR runner.

No tesseract, no ffmpeg, no GPU: the runner is replaced by a function that
writes the same files `core/ocr_review_job.py` writes (events.json, one PNG per event,
session status). The real worker is exercised only through the frozen contract
(`build_events` -> `events_to_srt`).
"""
import io
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from web.app import create_app  # noqa: E402
from core.ocr_review_job import build_events  # noqa: E402
from web.ocr_review import OcrReviewService, atomic_write_json, read_json  # noqa: E402


class FakeConfig:
    CONFIG_DIR = Path("/tmp/tp-config-ocr")

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, save=True):
        self.values[key] = value


class FakeRunner:
    def run(self, video, target_language, files_processed, log_path,
            on_line=None, on_event=None, cancel_event=None):
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


EVENTS = [
    {"index": 1, "start_ms": 1000, "end_ms": 3000, "text": "Prima riga OCR",
     "confidence": 91.5, "flags": [], "verified": False, "image": "1.png"},
    {"index": 2, "start_ms": 3000, "end_ms": 5000, "text": "Seconda riga 0CR",
     "confidence": 42.0, "flags": ["low_conf"], "verified": False, "image": "2.png"},
]


def fake_runner(session_dir: Path, video: str, mode: str) -> None:
    """Synchronous stand-in for `core/ocr_review_job.py`."""
    meta = read_json(session_dir / "session.json", {}) or {}
    images = session_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    if mode == "ocr":
        (images / "1.png").write_bytes(_png_bytes())
        (images / "2.png").write_bytes(_png_bytes())
        atomic_write_json(session_dir / "events.json", [dict(event) for event in EVENTS])
        meta.update({"status": "ready", "kind": "pgs", "language": "ita",
                     "event_count": 2, "flagged_count": 1})
    else:
        (session_dir / "draft.srt").write_text("FAKE SRT\n", encoding="utf-8")
        meta.update({"status": "saved",
                     "srt_path": str(Path(video).with_name(Path(video).stem + ".ita.srt"))})
    atomic_write_json(session_dir / "session.json", meta)


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "bitmap.mkv"
    path.write_bytes(b"not a real video")
    return path


def _app(tmp_path, token=None):
    config = FakeConfig({"allowed_media_roots": [str(tmp_path)]})
    manager = JobManager(runner=FakeRunner(), keep_alive=True, log_dir=tmp_path / "logs")
    service = OcrReviewService(tmp_path / "ocr", runner=fake_runner)
    return create_app(manager, token=token, config=config, ocr_service=service), service


def test_ocr_session_lifecycle(tmp_path, media):
    app, service = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/ocr/sessions", json={"path": str(media)})
        assert created.status_code == 201
        session = created.json()
        assert session["status"] == "ready"

        detail = client.get(f"/api/ocr/sessions/{session['id']}").json()
        assert detail["session"]["kind"] == "pgs"
        assert [event["index"] for event in detail["events"]] == [1, 2]

        image = client.get(f"/api/ocr/sessions/{session['id']}/images/1")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        updated = client.put(f"/api/ocr/sessions/{session['id']}/events/2",
                             json={"text": "Seconda riga OCR", "verified": True})
        assert updated.status_code == 200
        assert updated.json()["text"] == "Seconda riga OCR"
        assert client.get(f"/api/ocr/sessions/{session['id']}").json()[
            "session"]["flagged_count"] == 0

        saved = client.post(f"/api/ocr/sessions/{session['id']}/srt")
        assert saved.status_code == 200
        assert saved.json()["status"] == "saved"
        assert saved.json()["srt_path"].endswith(".ita.srt")

        assert client.delete(f"/api/ocr/sessions/{session['id']}").status_code == 200
        assert client.get(f"/api/ocr/sessions/{session['id']}").status_code == 404
        assert client.get("/api/ocr/sessions").json() == []


def test_ocr_rejects_bad_input(tmp_path, media):
    app, _ = _app(tmp_path)
    outside = tmp_path.parent / "outside.mkv"
    outside.write_bytes(b"x")
    with TestClient(app) as client:
        assert client.post("/api/ocr/sessions", json={"path": str(outside)}).status_code == 403
        assert client.post("/api/ocr/sessions",
                           json={"path": str(tmp_path / "missing.mkv")}).status_code == 404
        assert client.post("/api/ocr/sessions", json={"path": "relative.mkv"}).status_code == 400
        assert client.post("/api/ocr/sessions",
                           json={"path": str(media), "language": "italian"}).status_code == 400
        assert client.get("/api/ocr/sessions/deadbeef0000").status_code == 404
        assert client.put("/api/ocr/sessions/deadbeef0000/events/1",
                          json={"text": "x"}).status_code == 404


def test_event_update_is_bounded(tmp_path, media):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        session = client.post("/api/ocr/sessions", json={"path": str(media)}).json()
        too_long = client.put(f"/api/ocr/sessions/{session['id']}/events/1",
                              json={"text": "x" * 3000})
        assert too_long.status_code == 400
        assert client.put(f"/api/ocr/sessions/{session['id']}/events/99",
                          json={"text": "x"}).status_code == 404


def test_ocr_pages(tmp_path, media):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = client.get("/ocr")
        assert page.status_code == 200
        assert "No OCR sessions yet" in page.text

        started = client.post("/ocr", data={"path": str(media)}, follow_redirects=False)
        assert started.status_code == 303
        location = started.headers["location"]
        assert location.startswith("/ocr/")

        session_page = client.get(location)
        assert session_page.status_code == 200
        assert "Prima riga OCR" in session_page.text
        assert "/images/1" in session_page.text
        assert "flagged (1)" in session_page.text

        flagged = client.get(location + "?flagged=1")
        assert "Seconda riga 0CR" in flagged.text
        assert "Prima riga OCR" not in flagged.text

        saved = client.post(f"{location}/events/1",
                            data={"text": "Riga corretta", "verified": "true"},
                            follow_redirects=False)
        assert saved.status_code == 303

        written = client.post(f"{location}/srt", follow_redirects=False)
        assert written.status_code == 303

        listing = client.get("/ocr")
        assert "bitmap.mkv" in listing.text
        assert "saved" in listing.text

        removed = client.post(f"{location}/delete", follow_redirects=False)
        assert removed.status_code == 303
        assert client.get("/ocr").text.count("bitmap.mkv") == 0


def test_ocr_pages_require_login(tmp_path):
    app, _ = _app(tmp_path, token="s3cret")
    with TestClient(app) as client:
        for path in ("/ocr", "/ocr/deadbeef0000"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"].startswith("/login")
        assert client.get("/api/ocr/sessions").status_code == 401


def test_worker_rebuilds_the_srt_from_corrected_events(tmp_path):
    from core.pgs_types import events_to_srt

    records = [
        {"index": 1, "start_ms": 1000, "end_ms": 3000, "text": "Testo corretto",
         "confidence": 90.0, "flags": [], "verified": True},
        {"index": 2, "start_ms": 3000, "end_ms": 5000, "text": "Seconda riga",
         "confidence": 40.0, "flags": ["low_conf"], "verified": False},
    ]
    srt = events_to_srt(build_events(records))
    assert "Testo corretto" in srt
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert srt.count("-->") == 2


def test_session_files_stay_outside_the_project(tmp_path, media):
    app, service = _app(tmp_path)
    with TestClient(app) as client:
        session = client.post("/api/ocr/sessions", json={"path": str(media)}).json()
        session_dir = service.root / session["id"]
        assert str(session_dir).startswith(str(tmp_path))
        assert (session_dir / "session.json").is_file()
        assert (session_dir / "events.json").is_file()
        # the session id is validated, so a traversal attempt cannot escape
        assert client.get("/api/ocr/sessions/..%2F..%2Fetc").status_code == 404


def test_slow_runner_keeps_the_page_polling(tmp_path, media):
    """While the worker runs the status is `running` and the page polls itself."""
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        session = client.post("/api/ocr/sessions", json={"path": str(media)}).json()
        service = app.state.ocr
        service.set_status(session["id"], "running")
        time.sleep(0.01)
        page = client.get(f"/ocr/{session['id']}")
        assert "refreshes by itself" in page.text
        partial = client.get(f"/ui/ocr/{session['id']}")
        assert partial.status_code == 200
        assert "refreshes by itself" in partial.text
