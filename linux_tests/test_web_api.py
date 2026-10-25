# -*- coding: utf-8 -*-
"""Web API tests with a fake runner (no subprocess, no GPU)."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from web.app import create_app  # noqa: E402


class FakeConfig:
    CONFIG_DIR = Path("/tmp/tp-config")

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, save=True):
        self.values[key] = value


class FakeRunner:
    def __init__(self, block=False):
        self.block = block

    def run(self, video, target_language, files_processed, log_path,
            on_line=None, on_event=None, cancel_event=None):
        if on_event:
            on_event("phase", {"name": "asr"})
            on_event("bar", {"phase": "asr", "pct": 50})
        if on_line:
            on_line("4. Audio transcription...")
        if self.block:
            deadline = time.time() + 5
            while not cancel_event.is_set() and time.time() < deadline:
                time.sleep(0.01)
        if cancel_event is not None and cancel_event.is_set():
            return {"ok": False, "cancelled": True, "error": "cancelled", "output": None}
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


def _wait(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "movie.mp4"
    path.write_text("x", encoding="utf-8")
    return path


def _app(tmp_path, runner=None, token=None, values=None):
    config = FakeConfig({"allowed_media_roots": [str(tmp_path)], **(values or {})})
    manager = JobManager(runner=runner or FakeRunner(), keep_alive=True,
                         log_dir=tmp_path / "logs")
    return create_app(manager, token=token, config=config), manager


def test_health_and_status(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        status = client.get("/api/status").json()
        assert status["line"] == "development"
        assert "queue" in status and "backend" in status


def test_add_job_runs_and_appears_in_history(tmp_path, media):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/jobs", json={"path": str(media)})
        assert response.status_code == 201
        job = response.json()
        assert _wait(lambda: client.get(f"/api/jobs/{job['id']}").json()["status"] == "done")
        assert client.get("/api/history").json()[0]["id"] == job["id"]
        logs = client.get(f"/api/jobs/{job['id']}/logs").json()["lines"]
        assert any("Audio transcription" in line for line in logs)


def test_rejects_outside_missing_and_relative_paths(tmp_path, media):
    app, _ = _app(tmp_path)
    outside = tmp_path.parent / "outside.mp4"
    outside.write_text("x", encoding="utf-8")
    with TestClient(app) as client:
        assert client.post("/api/jobs", json={"path": str(outside)}).status_code == 403
        assert client.post("/api/jobs", json={"path": str(tmp_path / "nope.mp4")}).status_code == 404
        assert client.post("/api/jobs", json={"path": "relative.mp4"}).status_code == 400


def test_token_is_required_when_configured(tmp_path):
    app, _ = _app(tmp_path, token="s3cret")
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/jobs", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/api/jobs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert client.get("/api/jobs?token=s3cret").status_code == 200


def test_cancel_running_job(tmp_path, media):
    app, _ = _app(tmp_path, runner=FakeRunner(block=True))
    with TestClient(app) as client:
        job = client.post("/api/jobs", json={"path": str(media)}).json()
        assert _wait(lambda: client.get(f"/api/jobs/{job['id']}").json()["status"] == "running")
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
        assert _wait(lambda: client.get(f"/api/jobs/{job['id']}").json()["status"] == "cancelled")


def test_config_read_masks_secrets_and_write_whitelist(tmp_path):
    app, _ = _app(tmp_path, values={"huggingface_token": "topsecret",
                                    "transcription_engine_mode": "auto"})
    with TestClient(app) as client:
        body = client.get("/api/config")
        assert body.status_code == 200
        assert body.json()["huggingface_token"] == {"is_set": True}
        assert "topsecret" not in body.text
        assert client.put("/api/config", json={"values": {"transcription_engine_mode": "qwen3"}}).status_code == 200
        assert client.get("/api/config").json()["transcription_engine_mode"] == "qwen3"
        assert client.put("/api/config", json={"values": {"nope": 1}}).status_code == 400
