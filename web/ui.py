"""Server-rendered WebUI (HTMX + Alpine)."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.jobs.models import TERMINAL
from utils.job_overrides import clean
from web.auth import SESSION_COOKIE, request_token, token_matches
from web.config_schema import (ENUM_CONFIG_KEYS, MEDIA_ROOTS_KEY, ConfigError,
                               apply_values, read_values)
from web.paths import compute_roots, validate_media_path

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
router = APIRouter()

LANGUAGES = ("ita", "eng", "fra", "spa", "deu", "por", "rus", "jpn", "zho", "ara", "kor", "nld", "pol", "tur")
TRANSLATION_MODELS = ("nllb_finetuned", "llm")

HISTORY_STATUSES = ("done", "failed", "cancelled", "interrupted")

# Declarative description of the settings page. `kind` selects the input and
# the normalisation applied by `web/config_schema.py`; the template loops over
# the groups, so adding a key means adding one tuple here.
SETTINGS_GROUPS = (
    ("General", (
        ("bool", "use_gpu", "Use the GPU"),
        ("enum", "language", "Interface language"),
        ("bool", "model_cache_cleanup_enabled", "Clean up unused model caches"),
    )),
    ("Transcription", (
        ("enum", "transcription_engine_mode", "ASR engine mode"),
        ("text", "whisper_model", "Whisper model"),
        ("enum", "punctuation_restore_mode", "Punctuation restoration"),
        ("bool", "enable_diarization", "Diarization"),
        ("bool", "dialogue_style_enabled", "Netflix dialogue style"),
        ("bool", "gender_correction_enabled", "Gender correction"),
    )),
    ("Translation", (
        ("enum", "translation_model", "Translation engine"),
        ("text", "llm_translator_model", "LLM model key"),
        ("bool", "llm_translator_gguf_enabled", "Prefer GGUF models"),
        ("number", "translation_max_untranslated_pct", "Max untranslated share (%)"),
        ("text", "target_language", "Target language (ISO 639-2)"),
    )),
    ("Upload and mux", (
        ("bool", "opensubtitles_upload_enabled", "Upload finished subtitles"),
        ("bool", "mux_subtitle_into_video", "Mux the SRT into the video"),
        ("bool", "replace_mislabeled_italian_track", "Replace a mistagged Italian track"),
    )),
    ("Media", (
        ("roots", MEDIA_ROOTS_KEY, "Allowed media roots (one path per line)"),
    )),
    ("Secrets", (
        ("secret", "huggingface_token", "Hugging Face token"),
        ("secret", "claude_api_key", "Claude API key"),
        ("secret", "openai_api_key", "OpenAI API key"),
        ("secret", "opensubtitles_password", "OpenSubtitles password"),
        ("secret", "opensubtitles_api_key", "OpenSubtitles API key"),
        ("secret", "opensubtitles_xmlrpc_password", "OpenSubtitles XML-RPC password"),
        ("secret", "library_scanner_api_key", "Library scanner API key"),
    )),
)


def _auth(request: Request) -> None:
    expected = request.app.state.token
    if expected and not token_matches(request_token(request), expected):
        target = "/login?next=" + quote(request.url.path)
        raise HTTPException(status_code=303, headers={"Location": target})


def _login_target(next_path: str) -> str:
    value = (next_path or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _counts(jobs: List[Dict[str, Any]]) -> Dict[str, int]:
    names = ("queued", "running", "done", "failed", "cancelled", "interrupted")
    return {name: sum(1 for job in jobs if job["status"] == name) for name in names}


def _status_context(request: Request) -> Dict[str, Any]:
    app = request.app
    jobs = app.state.manager.snapshot()
    gpu = app.state.gpu or {}
    gpus = gpu.get("gpus") or []
    return {
        "version": app.state.version,
        "backend": gpu.get("backend", "unknown"),
        "gpu_name": gpus[0]["name"] if gpus else "no GPU",
        "vram_mib": gpus[0].get("vram_mib") if gpus else None,
        "manager_state": app.state.manager.state,
        "counts": _counts(jobs),
        "total": len(jobs),
        "auth_enabled": bool(app.state.token),
    }


def _queue_context(request: Request, error: str = "", message: str = "") -> Dict[str, Any]:
    return {
        "jobs": request.app.state.manager.snapshot(),
        "error": error,
        "message": message,
        "counts": _counts(request.app.state.manager.snapshot()),
    }


def _render(request: Request, name: str, context: Dict[str, Any]) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request=request, name=name,
                                      context={"request": request, **context})


def _settings_context(request: Request, error: str = "", message: str = "",
                      draft: Dict[str, Any] | None = None) -> Dict[str, Any]:
    values = read_values(request.app.state.config)
    roots = values.get(MEDIA_ROOTS_KEY)
    if isinstance(roots, (list, tuple)):
        values[MEDIA_ROOTS_KEY] = "\n".join(str(item) for item in roots)
    return {
        "status": _status_context(request),
        "groups": SETTINGS_GROUPS,
        "choices": ENUM_CONFIG_KEYS,
        "values": values,
        "draft": _draft_view(draft or {}),
        "error": error,
        "message": message,
        "pathsep": os.pathsep,
    }


def _draft_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Make submitted values renderable again after a validation error."""
    view = dict(raw)
    roots = view.get(MEDIA_ROOTS_KEY)
    if isinstance(roots, (list, tuple)):
        view[MEDIA_ROOTS_KEY] = "\n".join(str(item) for item in roots)
    return view


async def _read_settings_form(request: Request) -> Dict[str, Any]:
    """Map the settings form onto config keys.

    Checkboxes are absent when unchecked; secret inputs use the `secret:` and
    `clear:` prefixes so an empty box never overwrites a stored token.
    """
    form = await request.form()
    raw: Dict[str, Any] = {}
    for _title, fields in SETTINGS_GROUPS:
        for kind, key, _label in fields:
            if kind == "bool":
                raw[key] = form.get(key) is not None
            elif kind == "secret":
                value = (form.get(f"secret:{key}") or "").strip()
                if value:
                    raw[key] = value
                elif form.get(f"clear:{key}") is not None:
                    raw[key] = ""
            elif kind == "roots":
                text = (form.get(key) or "")
                raw[key] = [line.strip() for line in text.splitlines() if line.strip()]
            else:
                raw[key] = form.get(key) or ""
    return raw


def _duration(job: Dict[str, Any]) -> str:
    start = job.get("started_at")
    if not start:
        return ""
    end = job.get("finished_at") or start
    seconds = max(int(end - start), 0)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def _timestamp(value: Any) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def _history_context(request: Request, job_status: str = "") -> Dict[str, Any]:
    jobs = [job for job in request.app.state.manager.snapshot()
            if job["status"] in TERMINAL]
    if job_status in TERMINAL:
        jobs = [job for job in jobs if job["status"] == job_status]
    jobs.sort(key=lambda job: job.get("finished_at") or job.get("created_at") or 0.0,
              reverse=True)
    rows = [dict(job, duration=_duration(job), finished=_timestamp(job.get("finished_at")))
            for job in jobs]
    return {
        "status": _status_context(request),
        "jobs": rows,
        "filter": job_status if job_status in TERMINAL else "",
        "filters": HISTORY_STATUSES,
    }


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def index(request: Request) -> HTMLResponse:
    return _render(request, "index.html", {
        "status": _status_context(request),
        "queue": _queue_context(request),
        "languages": LANGUAGES,
        "translation_models": TRANSLATION_MODELS,
    })


@router.get("/ui/status", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_status(request: Request) -> HTMLResponse:
    return _render(request, "_status.html", {"status": _status_context(request)})


@router.get("/ui/queue", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_queue(request: Request) -> HTMLResponse:
    return _render(request, "_queue.html", _queue_context(request))


@router.post("/ui/jobs", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_add_job(request: Request,
               path: str = Form(""),
               target_language: str = Form(""),
               translation_model: str = Form(""),
               force_audio: bool = Form(False),
               mux: bool = Form(False),
               upload: bool = Form(False),
               gender: bool = Form(False)) -> HTMLResponse:
    config = request.app.state.config
    raw = {
        "target_language": target_language,
        "translation_model": translation_model,
        "force_audio_transcription": force_audio,
        "mux_subtitle_into_video": mux,
        "opensubtitles_upload_enabled": upload,
        "gender_correction_enabled": gender,
    }
    overrides = clean({key: value for key, value in raw.items() if value not in ("", False, None)})
    try:
        roots = compute_roots(lambda key, default: config.get(key, default))
        media = validate_media_path(path, roots)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return _render(request, "_queue.html", _queue_context(request, error=str(exc)))
    request.app.state.manager.add(media, overrides)
    return _render(request, "_queue.html", _queue_context(request, message=f"Queued {media.name}"))


@router.post("/ui/jobs/{job_id}/cancel", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_cancel_job(request: Request, job_id: str) -> HTMLResponse:
    ok = request.app.state.manager.cancel(job_id)
    message = "" if ok else "Job cannot be cancelled"
    return _render(request, "_queue.html", _queue_context(request, error=message if not ok else ""))


@router.post("/ui/jobs/{job_id}/remove", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_remove_job(request: Request, job_id: str) -> HTMLResponse:
    ok = request.app.state.manager.remove(job_id)
    message = "" if ok else "Only queued jobs can be removed"
    return _render(request, "_queue.html", _queue_context(request, error=message if not ok else ""))


@router.get("/history", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def history_page(request: Request, job_status: str = Query("", alias="status")) -> HTMLResponse:
    return _render(request, "history.html", _history_context(request, job_status))


@router.get("/ui/history", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_history(request: Request, job_status: str = Query("", alias="status")) -> HTMLResponse:
    return _render(request, "_history.html", _history_context(request, job_status))


@router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def settings_page(request: Request) -> HTMLResponse:
    return _render(request, "settings.html", _settings_context(request))


@router.post("/settings", response_class=HTMLResponse, dependencies=[Depends(_auth)])
async def settings_save(request: Request) -> HTMLResponse:
    raw = await _read_settings_form(request)
    try:
        apply_values(request.app.state.config, raw)
    except ConfigError as exc:
        return _render(request, "settings.html",
                       _settings_context(request, error=str(exc), draft=raw))
    return _render(request, "settings.html",
                   _settings_context(request, message="Settings saved"))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    expected = request.app.state.token
    if not expected or token_matches(request_token(request), expected):
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", {"error": "", "next": _login_target(next)})


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, token: str = Form(""), next: str = Form("/")) -> HTMLResponse:
    expected = request.app.state.token
    if not expected:
        return RedirectResponse("/", status_code=303)
    if not token_matches(token, expected):
        return _render(request, "login.html",
                       {"error": "Invalid token", "next": _login_target(next)})
    response = RedirectResponse(_login_target(next), status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
