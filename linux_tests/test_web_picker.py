# -*- coding: utf-8 -*-
"""File picker tests: read-only browsing of the allowed roots and multi-add."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from web import browse  # noqa: E402
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
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


def _wait(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


SETTINGS_VALUES = {
    "allowed_media_roots": [],
    "picker_start_dir": "",
    "use_gpu": True,
    "language": "auto",
    "model_cache_cleanup_enabled": True,
    "transcription_engine_mode": "auto",
    "whisper_model": "large-v3",
    "punctuation_restore_mode": "auto",
    "enable_diarization": False,
    "dialogue_style_enabled": True,
    "gender_correction_enabled": False,
    "translation_model": "translategemma-12b-gguf",
    "llm_translator_model": "translategemma-12b",
    "llm_translator_gguf_quant": "Q4_K_M",
    "translation_max_untranslated_pct": 80.0,
    "target_language": "ita",
    "opensubtitles_upload_enabled": False,
    "mux_subtitle_into_video": False,
    "replace_mislabeled_italian_track": False,
    "huggingface_token": "",
}


def _make(tmp_path, token=None, values=None):
    merged = dict(SETTINGS_VALUES, allowed_media_roots=[str(tmp_path)], **(values or {}))
    config = FakeConfig(merged)
    manager = JobManager(runner=FakeRunner(), keep_alive=True, log_dir=tmp_path / "logs")
    return create_app(manager, token=token, config=config), manager, config


@pytest.fixture
def library(tmp_path):
    """A small tree: season folder, two videos, one with a subtitle, noise."""
    season = tmp_path / "Show" / "Season 1"
    season.mkdir(parents=True)
    (season / "Episode 2.mkv").write_text("x", encoding="utf-8")
    (season / "Episode 10.mkv").write_text("x", encoding="utf-8")
    (season / "Episode 2.it.srt").write_text("1\n", encoding="utf-8")
    (season / "notes.txt").write_text("x", encoding="utf-8")
    (season / ".hidden.mkv").write_text("x", encoding="utf-8")
    (season / ".hidden-dir").mkdir()
    (tmp_path / "Other").mkdir()
    return season


def _listing(client, path=""):
    response = client.get("/ui/browse", params={"path": path})
    assert response.status_code == 200
    return response.text


def test_picker_lists_folders_and_video_files(tmp_path, library):
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = _listing(client)
        assert "Show/" in page and "Other/" in page
        assert page.index("Other/") < page.index("Show/")   # natural, case-insensitive

        season = _listing(client, str(library))
        assert "Episode 2.mkv" in season and "Episode 10.mkv" in season
        assert "notes.txt" not in season          # not a video extension
        assert ".hidden.mkv" not in season        # hidden entries never listed
        assert ".hidden-dir" not in season
        assert "Episode 2.mkv" in season.split("Episode 10.mkv")[0]  # natural order


def test_picker_marks_files_with_a_subtitle(tmp_path, library):
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        season = _listing(client, str(library))
        assert "SRT" in season

    assert browse.has_subtitle(library / "Episode 2.mkv") is True
    assert browse.has_subtitle(library / "Episode 10.mkv") is False


def test_picker_rejects_paths_outside_the_roots(tmp_path, library):
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = _listing(client, "/etc")
        assert "outside the allowed media roots" in page
        # the listing falls back to the start folder instead of failing
        assert "Show/" in page


def test_picker_rejects_relative_paths_and_files(tmp_path, library):
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        assert "must be an absolute path" in _listing(client, "Show")
        assert "not a folder" in _listing(client, str(library / "Episode 2.mkv"))
        assert "not found" in _listing(client, str(tmp_path / "missing"))


def test_picker_skips_symlinks_pointing_outside_the_roots(tmp_path, library):
    outside = library / "outside.mkv"
    outside.symlink_to("/etc/hostname")
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        season = _listing(client, str(library))
        assert "outside.mkv" not in season


def test_picker_start_dir_and_fallback(tmp_path, library):
    app, _, config = _make(tmp_path)
    with TestClient(app) as client:
        # configured start folder is used
        config.set("picker_start_dir", str(library))
        assert "Episode 2.mkv" in _listing(client)
        # a start folder outside the roots is ignored, the first root wins
        config.set("picker_start_dir", "/etc")
        assert "Show/" in _listing(client)


def test_list_directory_limit_and_parent(tmp_path, library):
    roots = [tmp_path]
    listing = browse.list_directory(str(library), roots, start=tmp_path, limit=2)
    assert listing["truncated"] is True
    assert len(listing["dirs"]) + len(listing["files"]) == 2
    assert listing["parent"] == str(library.parent)

    root_listing = browse.list_directory("", roots, start=tmp_path)
    assert root_listing["parent"] == ""          # a root has no way up
    assert root_listing["path"] == str(tmp_path)


def test_api_browse_json_and_auth(tmp_path, library):
    app, _, _ = _make(tmp_path, token="s3cret")
    with TestClient(app) as client:
        assert client.get("/api/browse").status_code == 401
        response = client.get("/api/browse", params={"path": str(library)},
                              headers={"Authorization": "Bearer s3cret"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == str(library)
        names = [item["name"] for item in payload["files"]]
        assert names == ["Episode 2.mkv", "Episode 10.mkv"]

        rejected = client.get("/api/browse", params={"path": "/etc"},
                              headers={"Authorization": "Bearer s3cret"})
        assert rejected.status_code == 400
        assert "outside the allowed media roots" in rejected.json()["detail"]


def test_add_several_paths_at_once(tmp_path, library):
    app, manager, _ = _make(tmp_path)
    first = library / "Episode 2.mkv"
    second = library / "Episode 10.mkv"
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={"paths": [str(first), str(second)]})
        assert response.status_code == 200
        assert "Queued 2 file(s)" in response.text
        assert _wait(lambda: len(manager.snapshot()) == 2)


def test_add_skips_files_that_already_have_a_subtitle(tmp_path, library):
    app, manager, _ = _make(tmp_path)
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={
            "paths": [str(library / "Episode 2.mkv"), str(library / "Episode 10.mkv")],
            "skip_existing": "true",
        })
        assert response.status_code == 200
        assert "skipped 1" in response.text
        assert _wait(lambda: len(manager.snapshot()) == 1)
        assert manager.snapshot()[0]["name"] == "Episode 10.mkv"


def test_add_with_nothing_selected_is_an_error(tmp_path):
    app, manager, _ = _make(tmp_path)
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={})
        assert response.status_code == 200
        assert "Select at least one media file" in response.text
        assert manager.snapshot() == []


def test_add_reports_the_rejected_path_and_queues_the_valid_one(tmp_path, library):
    app, manager, _ = _make(tmp_path)
    valid = library / "Episode 10.mkv"
    with TestClient(app) as client:
        response = client.post("/ui/jobs", data={"paths": [str(valid), "/etc/passwd"]})
        assert response.status_code == 200
        assert "outside the allowed roots" in response.text
        assert "Queued" in response.text
        assert _wait(lambda: len(manager.snapshot()) == 1)


def test_picker_checkboxes_belong_to_the_add_form(tmp_path, library):
    app, _, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/").text
        assert 'name="paths"' in _listing(client, str(library))  # checkboxes in the partial
        assert '<div class="picker-wrap">' in page        # always visible, no JavaScript
        assert "Pick the files to process" in page
        assert 'hx-get="/ui/browse"' in page             # listing loaded by HTMX
        assert 'name="skip_existing"' in page
        assert 'id="picker"' in page


def test_settings_expose_the_picker_start_dir(tmp_path, library):
    app, _, config = _make(tmp_path)
    form = {
        "language": "auto",
        "transcription_engine_mode": "auto",
        "whisper_model": "large-v3",
        "punctuation_restore_mode": "auto",
        "translation_model": "translategemma-12b-gguf",
        "llm_translator_model": "translategemma-12b",
        "llm_translator_gguf_quant": "Q4_K_M",
        "translation_max_untranslated_pct": "80",
        "target_language": "ita",
        "use_gpu": "true",
        "allowed_media_roots": str(tmp_path),
        "picker_start_dir": str(library),
    }
    with TestClient(app) as client:
        page = client.get("/settings").text
        assert 'name="picker_start_dir"' in page
        assert 'placeholder="/set/root/dir"' in page

        saved = client.post("/settings", data=form)
        assert "Settings saved" in saved.text
        assert config.get("picker_start_dir") == str(library)

        rejected = client.post("/settings", data=dict(form, picker_start_dir="relative/path"))
        assert "must be absolute" in rejected.text
        assert config.get("picker_start_dir") == str(library)   # nothing saved

        missing = client.post("/settings", data=dict(form, picker_start_dir="/nope/missing"))
        assert "not a directory" in missing.text
