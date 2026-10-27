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
    "whisper_vad_threshold": "0.5",
    "whisper_vad_min_silence_ms": "500",
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


def test_system_card_mostra_backend_gpu_e_workdir(tmp_path):
    app, _ = _make(tmp_path)
    app.state.system = {
        "backend": "rocm", "gpu_ok": True, "problems": [],
        "torch": "2.10.0+rocm7.0", "runtime": "7.0.51831", "devices": 2, "ctranslate2": "4.8.4",
        "stamp_path": str(tmp_path / ".tp-backend"),
        "tmpdir": {"path": "/dev/shm/tp", "free_mib": 14000, "total_mib": 15000},
    }
    with TestClient(app) as client:
        page = client.get("/status")
        assert "System" in page.text
        assert "rocm" in page.text and "GPU ok" in page.text
        assert "2.10.0+rocm7.0" in page.text and "ctranslate2 4.8.4" in page.text
        assert "/dev/shm/tp" in page.text and "14000 MiB free" in page.text


def test_system_card_avvisa_se_la_gpu_non_risponde(tmp_path):
    app, _ = _make(tmp_path)
    app.state.system = {
        "backend": "rocm", "gpu_ok": False,
        "problems": ["torch non vede la GPU (cuda.is_available() = False)"],
        "torch": "2.8.0+cpu", "runtime": "", "devices": 0, "ctranslate2": "",
        "stamp_path": "", "tmpdir": {"path": "/tmp", "free_mib": 100, "total_mib": 200},
    }
    with TestClient(app) as client:
        page = client.get("/status")
        assert "GPU not usable" in page.text
        assert "install.sh --verify-only" in page.text
        assert "no GPU" in page.text


def test_senza_token_la_landing_avvisa_e_login_rimanda_alla_home(tmp_path):
    app, _ = _make(tmp_path)                       # nessun token: accesso libero
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "No authentication" in page.text
        login = client.get("/login", follow_redirects=False)
        assert login.status_code == 303              # niente pagina di login inutile
        assert login.headers["location"] == "/"


def test_api_status_espone_lo_stato_di_sistema(tmp_path):
    app, _ = _make(tmp_path)
    app.state.system = {"backend": "rocm", "gpu_ok": True, "problems": [],
                        "torch": "2.10.0+rocm7.0", "runtime": "7.0", "devices": 2,
                        "ctranslate2": "4.8.4", "stamp_path": "x",
                        "tmpdir": {"path": "/dev/shm/tp", "free_mib": 1, "total_mib": 2}}
    with TestClient(app) as client:
        payload = client.get("/api/status").json()
        assert payload["system"]["backend"] == "rocm"
        assert payload["system"]["gpu_ok"] is True
        assert payload["system"]["tmpdir"]["path"] == "/dev/shm/tp"
        assert payload["auth_enabled"] is False


# --------------------------------------------------------------- layout: sidebar + stato della coda
def test_layout_ha_il_menu_a_sinistra_e_il_contenuto_a_destra(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/").text
        assert '<aside class="sidebar">' in page and '<main class="content">' in page
        assert page.index('class="sidebar"') < page.index('class="content"')
        for label, href in (("Queue", 'href="/"'), ("Status", 'href="/status"'),
                            ("History", 'href="/history"'), ("OCR", 'href="/ocr"'),
                            ("Glossary", 'href="/glossary"'), ("Settings", 'href="/settings"')):
            assert f'>{label}</a>' in page and href in page
        assert 'class="nav-item active" href="/"' in page          # voce corrente evidenziata
        status_page = client.get("/status").text
        assert 'class="nav-item active" href="/status"' in status_page


def test_landing_mostra_lo_stato_della_coda_al_centro(tmp_path):
    app, manager = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/").text
        assert "Nothing running" in page                     # nessun job
        assert "0 queued" in page and "0 running" in page     # contatori in cima

        job = manager.add(tmp_path / "movie.mp4")
        with manager._lock:                                  # simula un job in corso
            job.status = "running"
            job.percent = 42
            job.phase = "asr"
            job.started_at = time.time() - 754                 # 12m 34s fa
        page = client.get("/").text
        assert "hero-job" in page and "movie.mp4" in page
        assert ">asr<" in page or "asr" in page
        assert "12m 34s" in page and "elapsed" in page        # tempo trascorso
        assert "42%" in page


def test_tabella_coda_mostra_tempo_trascorso_e_totale(tmp_path):
    app, manager = _make(tmp_path)
    done = manager.add(tmp_path / "done.mp4")
    with manager._lock:
        done.status = "done"
        done.percent = 100
        done.started_at = time.time() - 1500
        done.finished_at = done.started_at + 1512            # 25m 12s totali
    running = manager.add(tmp_path / "run.mp4")
    with manager._lock:
        running.status = "running"
        running.percent = 10
        running.started_at = time.time() - 65                 # 1m 05s
    with TestClient(app) as client:
        page = client.get("/ui/queue").text
        assert "25m 12s" in page                              # tempo totale del job concluso
        assert "1m 05s" in page or "1m 06s" in page           # trascorso del job in corso


def test_formattazione_dei_tempi():
    from web.ui import _elapsed_of, _eta_of, _hms
    assert _hms(0) == "" and _hms(None) == ""
    assert _hms(42) == "42s"
    assert _hms(754) == "12m 34s"
    assert _hms(3725) == "1h 02m"
    now = 1_000_000.0
    assert _elapsed_of({"started_at": now - 90}, now) == "1m 30s"          # in corso
    assert _elapsed_of({"started_at": now - 90, "finished_at": now - 60}, now) == "30s"   # totale
    assert _elapsed_of({"created_at": now}, now) == ""                      # in coda: nessun tempo
    assert _eta_of({"started_at": now - 100, "percent": 50}, now) == "est. 1m 40s"
    assert _eta_of({"started_at": now - 100, "percent": 3}, now) == ""      # troppo presto per stimare
    assert _eta_of({"started_at": now - 100, "percent": 50, "finished_at": now}, now) == ""


def test_status_page_mostra_i_dettagli_di_elaborazione(tmp_path):
    app, _ = _make(tmp_path)
    with TestClient(app) as client:
        page = client.get("/status").text
        assert "Processing" in page
        assert "Engine" in page and "auto" in page            # valore della fixture
        assert "Target language" in page and "ita" in page
        assert "Work dir" in page and "Models dir" in page


def test_vad_knobs_in_settings(tmp_path):
    app, _ = _make(tmp_path)
    config = app.state.config
    form = dict(SETTINGS_FORM, allowed_media_roots=str(tmp_path),
                whisper_vad_threshold="0.35", whisper_vad_min_silence_ms="300")
    with TestClient(app) as client:
        page = client.get("/settings").text
        assert 'name="whisper_vad_threshold"' in page and 'step="0.05"' in page
        assert 'name="whisper_vad_min_silence_ms"' in page and 'max="2000"' in page
        saved = client.post("/settings", data=form)
        assert "Settings saved" in saved.text
        assert config.get("whisper_vad_threshold") == 0.35
        assert config.get("whisper_vad_min_silence_ms") == 300
        for bad in ("1.5", "-0.1"):
            rejected = client.post("/settings", data=dict(form, whisper_vad_threshold=bad))
            assert "between 0 and 1" in rejected.text
        too_long = client.post("/settings", data=dict(form, whisper_vad_min_silence_ms="5000"))
        assert "between 0 and 2000" in too_long.text
        assert config.get("whisper_vad_threshold") == 0.35      # niente salvato sull'errore


def test_glossary_path_tmdb_e_manuale(tmp_path, monkeypatch):
    from core import glossary as gl
    monkeypatch.setattr(gl, "_glossary_dir", lambda: tmp_path)
    assert gl.glossary_path(1234).name == "tmdb_1234.json"
    assert gl.glossary_path("monster-2022").name == "manual_monster-2022.json"
    assert gl.glossary_path("Monster (2022)").name == "manual_monster-2022.json"
    (tmp_path / "manual_monster-2022.json").write_text('{"Borden": "Borden"}', encoding='utf-8')
    assert gl.load_glossary("monster-2022") == {"Borden": "Borden"}
    assert gl.load_glossary("") == {}
    assert gl.load_glossary(None) == {}


def test_show_key_dalla_cartella(tmp_path):
    from core.glossary import show_key_from_path
    season = tmp_path / "Monster (2022)" / "Season 4"
    season.mkdir(parents=True)
    video = season / "episodio.mkv"
    video.write_text("x", encoding="utf-8")
    assert show_key_from_path(video) == "monster-2022"
    other = tmp_path / "Film.mkv"
    other.write_text("x", encoding="utf-8")
    assert show_key_from_path(other) == tmp_path.name.lower().replace("_", "-")
