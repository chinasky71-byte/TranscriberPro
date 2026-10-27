"""Server-rendered WebUI (HTMX + Alpine)."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.jobs.models import TERMINAL
from utils.job_overrides import clean
from web import browse
from web.auth import SESSION_COOKIE, request_token, token_matches
from web.config_schema import (ENUM_CONFIG_KEYS, MEDIA_ROOTS_KEY, NUMBER_CONFIG_KEYS,
                               START_DIR_KEY, ConfigError, apply_values, read_values)
from web.ocr_review import OcrSessionError, OcrSessionNotFound
from web import glossary as fixed_glossary
from web.glossary import GlossaryError, GlossaryNotFound
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
        ("number", "whisper_vad_threshold", "Whisper VAD threshold (0-1)"),
        ("number", "whisper_vad_min_silence_ms", "Whisper VAD minimum silence (ms)"),
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
        ("dir", START_DIR_KEY, "File picker start folder"),
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
    system = getattr(app.state, "system", {}) or {}
    return {
        "version": app.state.version,
        "backend": gpu.get("backend", "unknown"),
        "gpu_name": gpus[0]["name"] if gpus else "no GPU",
        "vram_mib": gpus[0].get("vram_mib") if gpus else None,
        "gpu_count": len(gpus),
        "manager_state": app.state.manager.state,
        "counts": _counts(jobs),
        "total": len(jobs),
        "auth_enabled": bool(app.state.token),
        # stato del sistema: backend installato, GPU viva, spazio in /dev/shm
        "system": system,
        "tmp": system.get("tmpdir") or {},
        "tuned": bool(system.get("backend")),
    }


def _queue_context(request: Request, error: str = "", message: str = "") -> Dict[str, Any]:
    jobs = request.app.state.manager.snapshot()
    now = time.time()
    rows = []
    for job in jobs:
        row = dict(job)
        row["elapsed"] = _elapsed_of(job, now)
        row["total"] = _elapsed_of(job, now) if job.get("finished_at") else ""
        row["eta"] = _eta_of(job, now)
        rows.append(row)
    active = next((row for row in rows if row["status"] == "running"), None)
    return {
        "status": _status_context(request),
        "jobs": rows,
        "active": active,
        "counts": _counts(jobs),
        "error": error,
        "message": message,
    }


def _render(request: Request, name: str, context: Dict[str, Any]) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request=request, name=name,
                                      context={"request": request,
                                               "path": request.url.path,
                                               **context})


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
        "numbers": NUMBER_CONFIG_KEYS,
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


def _hms(seconds: float | None) -> str:
    """Durata leggibile: 42s, 4m 07s, 1h 02m."""
    if not seconds or seconds < 0:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _elapsed_of(job: Dict[str, Any], now: float | None = None) -> str:
    """Tempo dall'inizio (job in corso) o durata totale (job concluso)."""
    start = job.get("started_at")
    if not start:
        return ""
    end = job.get("finished_at") or (now if now is not None else time.time())
    return _hms(end - start)


def _eta_of(job: Dict[str, Any], now: float | None = None) -> str:
    """Stima grezza dal progresso raggiunto: solo indicativa, per questo 'est.'."""
    start = job.get("started_at")
    percent = float(job.get("percent") or 0)
    if not start or percent < 5 or job.get("finished_at"):
        return ""
    elapsed = (now if now is not None else time.time()) - start
    return "est. " + _hms(elapsed * (100.0 - percent) / percent)


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


def _ocr_sessions_context(request: Request, error: str = "", message: str = "") -> Dict[str, Any]:
    return {
        "status": _status_context(request),
        "sessions": request.app.state.ocr.list(),
        "error": error,
        "message": message,
    }


def _ocr_context(request: Request, session_id: str, index: int = 0,
                 flagged: bool = False, error: str = "", message: str = "") -> Dict[str, Any]:
    service = request.app.state.ocr
    meta = service.get(session_id)
    events = service.events(session_id)
    if flagged:
        visible = [event for event in events
                   if event.get("flags") and not event.get("verified")]
    else:
        visible = events
    current = None
    previous = following = None
    if visible:
        current = next((event for event in visible if event.get("index") == index), visible[0])
        position = visible.index(current)
        previous = visible[position - 1]["index"] if position > 0 else None
        following = visible[position + 1]["index"] if position + 1 < len(visible) else None
    return {
        "status": _status_context(request),
        "session": meta,
        "events": events,
        "visible": visible,
        "current": current,
        "previous": previous,
        "following": following,
        "flagged": flagged,
        "error": error,
        "message": message,
    }


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def index(request: Request) -> HTMLResponse:
    return _render(request, "index.html", {
        "status": _status_context(request),
        "queue": _queue_context(request),
        "languages": LANGUAGES,
        "translation_models": TRANSLATION_MODELS,
    })


def _picker_context(request: Request, path: str = "", error: str = "") -> Dict[str, Any]:
    """Listing for the file picker; a rejected path falls back to the start folder."""
    config = request.app.state.config
    roots = compute_roots(lambda key, default: config.get(key, default))
    start = browse.start_dir(config.get, roots)
    try:
        listing = browse.list_directory(path, roots, start=start)
    except browse.BrowseError as exc:
        listing = browse.list_directory("", roots, start=start)
        error = str(exc)
    return {"status": _status_context(request), "listing": listing, "error": error}


@router.get("/ui/browse", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_browse(request: Request, path: str = Query("")) -> HTMLResponse:
    return _render(request, "_picker.html", _picker_context(request, path))


@router.get("/ui/status", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_status(request: Request) -> HTMLResponse:
    return _render(request, "_status.html", {"status": _status_context(request)})


@router.get("/ui/queue", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_queue(request: Request) -> HTMLResponse:
    return _render(request, "_queue.html", {"queue": _queue_context(request)})


@router.post("/ui/jobs", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_add_job(request: Request,
               path: str = Form(""),
               paths: List[str] = Form([]),
               target_language: str = Form(""),
               translation_model: str = Form(""),
               force_audio: bool = Form(False),
               mux: bool = Form(False),
               upload: bool = Form(False),
               gender: bool = Form(False),
               allow_cpu: bool = Form(False),
               skip_existing: bool = Form(False)) -> HTMLResponse:
    config = request.app.state.config
    raw = {
        "target_language": target_language,
        "translation_model": translation_model,
        "force_audio_transcription": force_audio,
        "mux_subtitle_into_video": mux,
        "opensubtitles_upload_enabled": upload,
        "gender_correction_enabled": gender,
        "allow_cpu": allow_cpu,
    }
    overrides = clean({key: value for key, value in raw.items() if value not in ("", False, None)})

    selected = [item.strip() for item in [path, *paths] if item and item.strip()]
    if not selected:
        return _render(request, "_queue.html",
                       {"queue": _queue_context(request, error="Select at least one media file")})

    try:
        roots = compute_roots(lambda key, default: config.get(key, default))
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return _render(request, "_queue.html", {"queue": _queue_context(request, error=str(exc))})

    queued: List[str] = []
    skipped = 0
    errors: List[str] = []
    for item in dict.fromkeys(selected):  # keep the order, drop duplicates
        try:
            media = validate_media_path(item, roots)
        except (FileNotFoundError, PermissionError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if skip_existing and browse.has_subtitle(media):
            skipped += 1
            continue
        request.app.state.manager.add(media, overrides)
        queued.append(media.name)

    parts = []
    if queued:
        parts.append(f"Queued {len(queued)} file(s)" if len(queued) > 1
                     else f"Queued {queued[0]}")
    if skipped:
        parts.append(f"skipped {skipped} with an existing subtitle")
    message = ", ".join(parts)
    return _render(request, "_queue.html",
                   {"queue": _queue_context(request, error="; ".join(errors), message=message)})


@router.post("/ui/jobs/{job_id}/cancel", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_cancel_job(request: Request, job_id: str) -> HTMLResponse:
    ok = request.app.state.manager.cancel(job_id)
    message = "" if ok else "Job cannot be cancelled"
    return _render(request, "_queue.html", {"queue": _queue_context(request, error=message if not ok else "")})


@router.post("/ui/jobs/{job_id}/remove", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_remove_job(request: Request, job_id: str) -> HTMLResponse:
    ok = request.app.state.manager.remove(job_id)
    message = "" if ok else "Only queued jobs can be removed"
    return _render(request, "_queue.html", {"queue": _queue_context(request, error=message if not ok else "")})


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


@router.get("/status", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def status_page(request: Request) -> HTMLResponse:
    config = request.app.state.config
    from utils.cache_bootstrap import MODELS_ROOT
    return _render(request, "status.html", {
        "status": _status_context(request),
        "engine": config.get("transcription_engine_mode", ""),
        "target_language": config.get("target_language", ""),
        "data_dir": str(getattr(config, "CONFIG_DIR", "")),
        "models_dir": str(MODELS_ROOT),
    })


@router.get("/ocr", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ocr_page(request: Request) -> HTMLResponse:
    return _render(request, "ocr.html", _ocr_sessions_context(request))


@router.post("/ocr", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ocr_start(request: Request, path: str = Form(""), language: str = Form("")) -> HTMLResponse:
    config = request.app.state.config
    try:
        roots = compute_roots(lambda key, default: config.get(key, default))
        media = validate_media_path(path, roots)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error=str(exc)))
    session = request.app.state.ocr.create(str(media), language.strip())
    return RedirectResponse(f"/ocr/{session['id']}", status_code=303)


@router.get("/ocr/{session_id}", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ocr_session_page(request: Request, session_id: str, index: int = Query(0),
                     flagged: int = Query(0)) -> HTMLResponse:
    try:
        context = _ocr_context(request, session_id, index=index, flagged=bool(flagged))
    except OcrSessionNotFound:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error="Unknown OCR session"))
    return _render(request, "ocr_session.html", context)


@router.get("/ui/ocr/{session_id}", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ui_ocr_session(request: Request, session_id: str, index: int = Query(0),
                    flagged: int = Query(0)) -> HTMLResponse:
    try:
        context = _ocr_context(request, session_id, index=index, flagged=bool(flagged))
    except OcrSessionNotFound:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error="Unknown OCR session"))
    return _render(request, "_ocr_session_body.html", context)


@router.post("/ocr/{session_id}/events/{index}", response_class=HTMLResponse,
             dependencies=[Depends(_auth)])
def ocr_save_event(request: Request, session_id: str, index: int,
                   text: str = Form(""), verified: bool = Form(False),
                   flagged: int = Form(0)) -> HTMLResponse:
    try:
        request.app.state.ocr.update_event(session_id, index, text, verified)
        context = _ocr_context(request, session_id, flagged=bool(flagged))
        target = context["following"] or index
        suffix = "&flagged=1" if flagged else ""
        return RedirectResponse(f"/ocr/{session_id}?index={target}{suffix}", status_code=303)
    except OcrSessionNotFound:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error="Unknown OCR session"))
    except OcrSessionError as exc:
        context = _ocr_context(request, session_id, index=index, flagged=bool(flagged),
                              error=str(exc))
        return _render(request, "ocr_session.html", context)


@router.post("/ocr/{session_id}/srt", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ocr_writeback(request: Request, session_id: str) -> HTMLResponse:
    try:
        meta = request.app.state.ocr.writeback(session_id)
    except OcrSessionNotFound:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error="Unknown OCR session"))
    except OcrSessionError as exc:
        context = _ocr_context(request, session_id, error=str(exc))
        return _render(request, "ocr_session.html", context)
    return RedirectResponse(f"/ocr/{meta['id']}", status_code=303)


@router.post("/ocr/{session_id}/delete", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def ocr_delete(request: Request, session_id: str) -> HTMLResponse:
    try:
        request.app.state.ocr.delete(session_id)
    except OcrSessionNotFound:
        return _render(request, "ocr.html",
                       _ocr_sessions_context(request, error="Unknown OCR session"))
    return RedirectResponse("/ocr", status_code=303)


def _glossary_context(request: Request, name: str = "", error: str = "",
                      message: str = "") -> Dict[str, Any]:
    store = request.app.state.glossary
    context: Dict[str, Any] = {
        "status": _status_context(request),
        "reports": store.list(),
        "fixed": fixed_glossary.list_fixed_glossaries(),
        "show_key_hint": _show_key_hint(request),
        "report": None,
        "error": error,
        "message": message,
    }
    if name:
        context["report"] = store.view(name)
    return context


def _show_key_hint(request: Request) -> str:
    """Chiave glossario suggerita: `glossary_id` se impostato, altrimenti vuota.

    Senza TMDB il pipeline ricava la chiave dalla cartella della serie
    (`Monster (2022)/Season 4/x.mkv` -> `monster-2022`), quindi la stessa forma
    va usata qui.
    """
    return str(request.app.state.config.get("glossary_id", "") or "")


@router.post("/glossary/build", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def glossary_build(request: Request,
                   source: str = Form("manual"),
                   tmdb_id: str = Form(""),
                   show_key: str = Form(""),
                   cast_text: str = Form(""),
                   media_type: str = Form("tv")) -> HTMLResponse:
    """Crea il glossario a resa fissa dal cast TMDB o da un elenco incollato."""
    try:
        if source == "tmdb":
            terms = fixed_glossary.build_from_tmdb(tmdb_id, media_type or "tv")
            key = str(tmdb_id).strip()
            message = (f"Glossary built from TMDB id {key}: {len(terms)} characters. "
                       f"Saved as tmdb_{key}.json")
        else:
            key = (show_key or "").strip()
            if not key:
                raise fixed_glossary.GlossaryError(
                    "show key required (the same key the pipeline derives from the folder, "
                    "e.g. 'monster-2022')")
            terms = fixed_glossary.parse_cast_text(cast_text)
            fixed_glossary.write_fixed_glossary(key, terms)
            message = (f"Glossary saved for '{key}': {len(terms)} characters. "
                       f"ASR context and translation will use it from the next job.")
    except fixed_glossary.GlossaryError as exc:
        return _render(request, "glossary.html",
                       _glossary_context(request, error=str(exc)))
    return _render(request, "glossary.html", _glossary_context(request, message=message))


@router.get("/glossary", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def glossary_page(request: Request) -> HTMLResponse:
    return _render(request, "glossary.html", _glossary_context(request))


@router.get("/glossary/{name}", response_class=HTMLResponse, dependencies=[Depends(_auth)])
def glossary_report_page(request: Request, name: str) -> HTMLResponse:
    try:
        return _render(request, "glossary_report.html", _glossary_context(request, name))
    except GlossaryNotFound:
        return _render(request, "glossary.html",
                       _glossary_context(request, error="Unknown glossary report"))


@router.post("/glossary/{name}/terms/{index}", response_class=HTMLResponse,
             dependencies=[Depends(_auth)])
def glossary_decide(request: Request, name: str, index: int,
                    decision: str = Form("pending"), translation: str = Form(""),
                    note: str = Form("")) -> HTMLResponse:
    store = request.app.state.glossary
    try:
        rows = store.view(name)["rows"]
        if not 0 <= index < len(rows):
            raise GlossaryNotFound("unknown term")
        store.decide(name, rows[index]["term"], decision, translation, note)
    except GlossaryNotFound:
        return _render(request, "glossary.html",
                       _glossary_context(request, error="Unknown glossary report or term"))
    except GlossaryError as exc:
        return _render(request, "glossary_report.html",
                       _glossary_context(request, name, error=str(exc)))
    return RedirectResponse(f"/glossary/{name}", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    if not request.app.state.token:                 # accesso senza autenticazione
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
