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


SETTINGS_VALUES = {
    "allowed_media_roots": [],
    "use_gpu": True,
    "language": "auto",
    "model_cache_cleanup_enabled": True,
    "transcription_engine_mode": "auto",
    "whisper_model": "large-v3",
    "punctuation_restore_mode": "auto",
    "enable_diarization": False,
    "dialogue_style_enabled": True,
    "gender_correction_enabled": False,
    "translation_model": "nllb",
    "llm_translator_model": "translategemma-12b",
    "llm_translator_gguf_enabled": True,
    "translation_max_untranslated_pct": 80.0,
    "target_language": "ita",
    "opensubtitles_upload_enabled": True,
    "mux_subtitle_into_video": False,
    "replace_mislabeled_italian_track": True,
    "huggingface_token": "stored-secret",
}

SETTINGS_FORM = {
    "language": "it",
    "transcription_engine_mode": "qwen3",
    "whisper_model": "large-v3",
    "punctuation_restore_mode": "auto",
    "translation_model": "nllb",
    "llm_translator_model": "translategemma-12b",
    "translation_max_untranslated_pct": "75",
    "target_language": "ita",
    "use_gpu": "true",
    "model_cache_cleanup_enabled": "true",
}


def _make(tmp_path, token=None, values=None):
    merged = dict(SETTINGS_VALUES, allowed_media_roots=[str(tmp_path)], **(values or {}))
    config = FakeConfig(merged)
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


def test_navigation_links_to_the_new_pages(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/")
        assert 'href="/history"' in page.text
        assert 'href="/settings"' in page.text


def test_history_page_lists_finished_jobs(tmp_path, media):
    app, manager = _make(tmp_path)
    with TestClient(app) as client:
        job = client.post("/api/jobs", json={"path": str(media)}).json()
        assert _wait(lambda: manager.get(job["id"])["status"] == "done")

        page = client.get("/history")
        assert page.status_code == 200
        assert media.name in page.text

        done = client.get("/history?status=done")
        assert media.name in done.text
        assert "No finished jobs" not in done.text

        failed = client.get("/history?status=failed")
        assert "No finished jobs" in failed.text

        partial = client.get("/ui/history?status=done")
        assert media.name in partial.text


def test_settings_page_renders_and_masks_secrets(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/settings")
        assert page.status_code == 200
        assert "Settings" in page.text
        assert "stored-secret" not in page.text
        assert 'name="secret:huggingface_token"' in page.text
        assert 'name="clear:huggingface_token"' in page.text
        assert 'name="allowed_media_roots"' in page.text


def test_settings_save_and_validation_error(tmp_path):
    app, _ = _make(tmp_path)
    config = app.state.config
    form = dict(SETTINGS_FORM, allowed_media_roots=str(tmp_path))
    with TestClient(app) as client:
        saved = client.post("/settings", data=form)
        assert saved.status_code == 200
        assert "Settings saved" in saved.text
        assert config.get("language") == "it"
        assert config.get("transcription_engine_mode") == "qwen3"
        assert config.get("translation_max_untranslated_pct") == 75.0
        assert config.get("allowed_media_roots") == [str(tmp_path)]

        rejected = client.post("/settings",
                               data=dict(form, translation_max_untranslated_pct="140"))
        assert rejected.status_code == 200
        assert "between 0 and 100" in rejected.text
        assert "140" in rejected.text            # the draft is shown again
        assert config.get("translation_max_untranslated_pct") == 75.0  # nothing saved


def test_settings_secret_update_is_never_echoed(tmp_path):
    app, _ = _make(tmp_path)
    form = dict(SETTINGS_FORM, allowed_media_roots=str(tmp_path))
    form["secret:huggingface_token"] = "brand-new-token"
    with TestClient(app) as client:
        response = client.post("/settings", data=form)
        assert response.status_code == 200
        assert "brand-new-token" not in response.text
        assert app.state.config.get("huggingface_token") == "brand-new-token"


def test_new_pages_require_login(tmp_path):
    app, _ = _make(tmp_path, token="s3cret")
    with TestClient(app) as client:
        for path in ("/history", "/settings"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"].startswith("/login")
