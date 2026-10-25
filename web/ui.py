"""Server-rendered WebUI (HTMX + Alpine)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from utils.job_overrides import clean
from web.auth import SESSION_COOKIE, request_token, token_matches
from web.paths import compute_roots, validate_media_path

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
router = APIRouter()

LANGUAGES = ("ita", "eng", "fra", "spa", "deu", "por", "rus", "jpn", "zho", "ara", "kor", "nld", "pol", "tur")
TRANSLATION_MODELS = ("nllb_finetuned", "llm")


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
