# -*- coding: utf-8 -*-
"""WebUI (server-rendered) tests: pages, forms, login, static assets."""
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
    def run(self, video, target_language, files_processed, log_path,
            on_line=None, on_event=None, cancel_event=None):
        if on_line:
            on_line("line one")
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


def _make(tmp_path, token=None):
    config = FakeConfig({"allowed_media_roots": [str(tmp_path)]})
    manager = JobManager(runner=FakeRunner(), keep_alive=True, log_dir=tmp_path / "logs")
    return create_app(manager, token=token, config=config), manager


def test_index_renders(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Transcriber Pro" in response.text
        assert "Add to queue" in response.text
        assert "Queue" in response.text


def test_static_assets_and_security_headers(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        css = client.get("/static/app.css")
        assert css.status_code == 200
        assert "Content-Security-Policy" in css.headers
        assert "nosniff" in css.headers.get("X-Content-Type-Options", "")
        assert client.get("/static/vendor/htmx.min.js").status_code == 200
        assert client.get("/static/vendor/alpine.min.js").status_code == 200


def test_add_job_from_form(tmp_path, media):
    app, manager = _make(tmp_path)
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={"path": str(media)})
        assert response.status_code == 200
        assert media.name in response.text or "Queued" in response.text
        assert _wait(lambda: manager.snapshot()[0]["status"] == "done")


def test_invalid_path_shows_error(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={"path": str(tmp_path / "missing.mp4")})
        assert response.status_code == 200
        assert "not found" in response.text.lower()


def test_login_flow_with_token(tmp_path):
    app, _ = _make(tmp_path, token="s3cret")
    with TestClient(app) as client:
        redirect = client.get("/", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"].startswith("/login")

        login = client.get("/login")
        assert login.status_code == 200
        assert "Sign in" in login.text

        wrong = client.post("/login", data={"token": "wrong", "next": "/"})
        assert wrong.status_code == 200
        assert "Invalid token" in wrong.text

        good = client.post("/login", data={"token": "s3cret", "next": "/"},
                           follow_redirects=False)
        assert good.status_code == 303
        assert client.cookies.get("tp_session") == "s3cret"

        index = client.get("/")
        assert index.status_code == 200
        assert "s3cret" not in index.text

        logout = client.post("/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert client.get("/", follow_redirects=False).status_code == 303


def test_open_redirect_is_rejected(tmp_path):
    app, _ = _make(tmp_path, token="s3cret")
    with TestClient(app) as client:
        response = client.post("/login", data={"token": "s3cret", "next": "//evil.example"},
                               follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
