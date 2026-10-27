"""FastAPI application for the WebUI (API only in this step)."""
from __future__ import annotations

import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.jobs.manager import JobManager
from core.jobs.models import TERMINAL
from utils.config import Config, get_config
from utils.gpu_detect import detect_gpus
from web.auth import request_token, token_matches
from web.browse import BrowseError, list_directory, start_dir
from web.config_schema import ConfigError, read_values, apply_values
from web.config_schema import SAFE_CONFIG_KEYS, SECRET_CONFIG_KEYS  # re-exported
from web.events import SSEBridge
from web.glossary import GlossaryError, GlossaryNotFound, GlossaryStore
from web.glossary import env_root as glossary_root
from web.ocr_review import (OcrReviewService, OcrSessionError, OcrSessionNotFound,
                            env_root)
from web.paths import compute_roots, validate_media_path

class JobIn(BaseModel):
    path: str
    overrides: Optional[Dict[str, Any]] = None


class ConfigIn(BaseModel):
    values: Dict[str, Any]


class OcrSessionIn(BaseModel):
    path: str
    language: Optional[str] = None


class OcrEventIn(BaseModel):
    text: str = ""
    verified: bool = False


class GlossaryDecisionIn(BaseModel):
    decision: str = "pending"
    translation: str = ""
    note: str = ""


def _app_version() -> str:
    try:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', text)
        return match.group(1) if match else ""
    except Exception:
        return ""


def _system_status(config: Any) -> Dict[str, Any]:
    """Backend installato, GPU disponibile, spazio del TMPDIR: quello che serve per capire
    a colpo d'occhio se questo host puo' elaborare, senza aprire un terminale."""
    from utils import backend_preflight
    try:
        preflight = backend_preflight.report()
    except Exception as exc:                                  # pragma: no cover - difensivo
        preflight = {"backend": "", "ok": False, "problems": [str(exc)], "runtime": {}, "stamp_path": ""}
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    try:
        usage = shutil.disk_usage(tmpdir)
        tmp = {"path": tmpdir, "free_mib": usage.free // (1024 * 1024),
               "total_mib": usage.total // (1024 * 1024)}
    except OSError:
        tmp = {"path": tmpdir, "free_mib": 0, "total_mib": 0}
    return {
        "backend": preflight.get("backend", ""),
        "gpu_ok": bool(preflight.get("ok")),
        "problems": list(preflight.get("problems") or []),
        "torch": preflight.get("runtime", {}).get("torch", ""),
        "runtime": preflight.get("runtime", {}).get("runtime", ""),
        "devices": preflight.get("runtime", {}).get("devices", 0),
        "stamp_path": preflight.get("stamp_path", ""),
        "tmpdir": tmp,
    }


def _gpu_status() -> Dict[str, Any]:
    try:
        report = detect_gpus()
    except Exception as exc:
        return {"backend": "unknown", "gpus": [], "error": str(exc)}
    backends = report.backends or {}
    backend = next((name for name in ("rocm", "cuda", "vulkan", "cpu")
                    if (backends.get(name) or {}).get("available")), "cpu")
    gpus = [{"name": gpu.name, "vram_mib": gpu.vram_mib, "gfx": gpu.gfx,
             "amd_family": gpu.amd_family, "backends": gpu.backends}
            for gpu in report.gpus]
    return {"backend": backend, "gpus": gpus}


def create_app(manager: JobManager, token: Optional[str] = None,
               config: Any = None,
               ocr_service: Optional[OcrReviewService] = None,
               glossary_store: Optional[GlossaryStore] = None) -> FastAPI:
    config = config or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="Transcriber Pro", version=_app_version() or "dev",
                  lifespan=lifespan)
    app.state.version = _app_version() or "dev"
    app.state.manager = manager
    app.state.token = token
    app.state.config = config
    app.state.gpu = _gpu_status()
    app.state.system = _system_status(config)
    app.state.ocr = ocr_service or OcrReviewService(env_root(config))
    app.state.glossary = glossary_store or GlossaryStore(glossary_root(config))

    def require_auth(request: Request) -> None:
        expected = app.state.token
        if not expected:
            return
        if not token_matches(request_token(request), expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="invalid or missing token")

    auth = [Depends(require_auth)]

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", dependencies=auth)
    def api_status() -> Dict[str, Any]:
        jobs = manager.snapshot()
        counts = {name: sum(1 for job in jobs if job["status"] == name)
                  for name in ("queued", "running", "done", "failed", "cancelled", "interrupted")}
        from utils.cache_bootstrap import MODELS_ROOT
        return {
            "version": app.state.version,
            "line": "development",
            "manager_state": manager.state,
            "queue": counts,
            "backend": app.state.gpu["backend"],
            "gpus": app.state.gpu["gpus"],
            "data_dir": str(getattr(config, "CONFIG_DIR", "")),
            "models_dir": str(MODELS_ROOT),
            "auth_enabled": bool(app.state.token),
            "system": app.state.system,
        }

    @app.get("/api/jobs", dependencies=auth)
    def list_jobs() -> List[Dict[str, Any]]:
        return manager.snapshot()

    @app.post("/api/jobs", status_code=201, dependencies=auth)
    def add_job(payload: JobIn) -> Dict[str, Any]:
        try:
            roots = compute_roots(lambda key, default: config.get(key, default))
            path = validate_media_path(payload.path, roots)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        job = manager.add(path, payload.overrides or {})
        return job.to_dict()

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: str) -> Dict[str, Any]:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: str) -> Dict[str, Any]:
        if not manager.cancel(job_id):
            raise HTTPException(status_code=409, detail="job cannot be cancelled")
        return manager.get(job_id) or {}

    @app.delete("/api/jobs/{job_id}", dependencies=auth)
    def delete_job(job_id: str) -> Dict[str, Any]:
        if not manager.remove(job_id):
            raise HTTPException(status_code=409, detail="only queued jobs can be removed")
        return {"removed": job_id}

    @app.get("/api/jobs/{job_id}/logs", dependencies=auth)
    def job_logs(job_id: str, lines: int = Query(200, ge=1, le=5000)) -> Dict[str, Any]:
        if manager.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        events = manager.hub.history(job_id)
        text = [event.get("line", "") for event in events if event.get("kind") == "log"]
        return {"lines": text[-lines:]}

    @app.get("/api/history", dependencies=auth)
    def history(job_status: Optional[str] = Query(None, alias="status"),
                limit: int = Query(100, ge=1, le=1000)) -> List[Dict[str, Any]]:
        """Finished jobs, newest first.

        `status` narrows the list to one terminal state; `limit` caps the
        payload (the queue can be long after a batch).
        """
        jobs = [job for job in manager.snapshot() if job["status"] in TERMINAL]
        if job_status:
            if job_status not in TERMINAL:
                raise HTTPException(status_code=400,
                                    detail=f"status must be one of {sorted(TERMINAL)}")
            jobs = [job for job in jobs if job["status"] == job_status]
        jobs.sort(key=lambda job: job.get("finished_at") or job.get("created_at") or 0.0,
                  reverse=True)
        return jobs[:limit]

    @app.get("/api/browse", dependencies=auth)
    def browse(path: str = Query("", description="absolute folder under a root")) -> Dict[str, Any]:
        """Read-only folder listing for the file picker (no writes, no recursion)."""
        roots = compute_roots(lambda key, default: config.get(key, default))
        try:
            return list_directory(path, roots, start=start_dir(config.get, roots))
        except BrowseError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=str(exc)) from None

    @app.get("/api/models", dependencies=auth)
    def models() -> Dict[str, Any]:
        """Model and engine choices the UI may offer.

        Reads the registry only: no weights are loaded and no GPU is touched.
        """
        payload: Dict[str, Any] = {
            "transcription_engine_modes": list(Config.VALID_TRANSCRIPTION_ENGINE_MODES),
            "translation_models": list(Config.VALID_TRANSLATION_MODELS),
            "llm_models": [],
            "error": "",
        }
        try:
            from core.llm_subtitle_translator.engine import MODEL_SPECS
            payload["llm_models"] = [
                {"key": key, "label": spec.label, "model_id": spec.model_id}
                for key, spec in MODEL_SPECS.items()
            ]
        except Exception as exc:  # optional module, never break the page
            payload["error"] = str(exc)
        return payload

    @app.get("/api/events", dependencies=auth)
    async def events(job_id: Optional[str] = None, after: int = 0) -> StreamingResponse:
        bridge = SSEBridge(manager.hub, job_id=job_id, after_seq=after)

        async def stream():
            async for frame in bridge.frames():
                yield frame

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no",
                                          "Connection": "keep-alive"})

    @app.get("/api/ocr/sessions", dependencies=auth)
    def ocr_sessions() -> List[Dict[str, Any]]:
        return app.state.ocr.list()

    @app.post("/api/ocr/sessions", status_code=201, dependencies=auth)
    def ocr_create(payload: OcrSessionIn) -> Dict[str, Any]:
        try:
            roots = compute_roots(lambda key, default: config.get(key, default))
            path = validate_media_path(payload.path, roots)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        language = (payload.language or "").strip()
        if language and not re.fullmatch(r"[a-z]{3}", language):
            raise HTTPException(status_code=400,
                                detail="language: expected an ISO 639-2 code such as 'ita'")
        return app.state.ocr.create(str(path), language)

    @app.get("/api/ocr/sessions/{session_id}", dependencies=auth)
    def ocr_session(session_id: str) -> Dict[str, Any]:
        try:
            return {"session": app.state.ocr.get(session_id),
                    "events": app.state.ocr.events(session_id)}
        except OcrSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.put("/api/ocr/sessions/{session_id}/events/{index}", dependencies=auth)
    def ocr_update_event(session_id: str, index: int, payload: OcrEventIn) -> Dict[str, Any]:
        try:
            return app.state.ocr.update_event(session_id, index, payload.text,
                                              payload.verified)
        except OcrSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except OcrSessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/ocr/sessions/{session_id}/images/{index}", dependencies=auth)
    def ocr_image(session_id: str, index: int) -> FileResponse:
        try:
            path = app.state.ocr.image_path(session_id, index)
        except OcrSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except OcrSessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/ocr/sessions/{session_id}/srt", dependencies=auth)
    def ocr_writeback(session_id: str) -> Dict[str, Any]:
        try:
            return app.state.ocr.writeback(session_id)
        except OcrSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except OcrSessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.delete("/api/ocr/sessions/{session_id}", dependencies=auth)
    def ocr_delete(session_id: str) -> Dict[str, str]:
        try:
            app.state.ocr.delete(session_id)
        except OcrSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"removed": session_id}

    @app.get("/api/glossary/reports", dependencies=auth)
    def glossary_reports() -> List[Dict[str, Any]]:
        return app.state.glossary.list()

    @app.get("/api/glossary/reports/{name}", dependencies=auth)
    def glossary_report(name: str) -> Dict[str, Any]:
        try:
            return app.state.glossary.view(name)
        except GlossaryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.put("/api/glossary/reports/{name}/terms/{index}", dependencies=auth)
    def glossary_decide(name: str, index: int,
                        payload: GlossaryDecisionIn) -> Dict[str, Any]:
        try:
            rows = app.state.glossary.view(name)["rows"]
        except GlossaryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if not 0 <= index < len(rows):
            raise HTTPException(status_code=404, detail="unknown term")
        try:
            decision = app.state.glossary.decide(
                name, rows[index]["term"], payload.decision,
                payload.translation, payload.note)
        except GlossaryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except GlossaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"term": rows[index]["term"], **decision}

    @app.get("/api/config", dependencies=auth)
    def read_config() -> Dict[str, Any]:
        return read_values(config)

    @app.put("/api/config", dependencies=auth)
    def update_config(payload: ConfigIn = Body(...)) -> Dict[str, Any]:
        unknown = [key for key in payload.values
                   if key not in SAFE_CONFIG_KEYS and key not in SECRET_CONFIG_KEYS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"keys not writable: {unknown}")
        try:
            return apply_values(config, payload.values)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        # Pages and partials are rendered per request: a cached copy shows a UI
        # that no longer matches the server (and hid a new feature once).
        # Static assets keep their own caching rules.
        if not request.url.path.startswith("/static"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    from web.ui import router as ui_router
    app.include_router(ui_router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
