"""FastAPI application for the WebUI (API only in this step)."""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.jobs.manager import JobManager
from core.jobs.models import TERMINAL
from utils.config import get_config
from utils.gpu_detect import detect_gpus
from web.auth import request_token, token_matches
from web.events import SSEBridge
from web.paths import compute_roots, validate_media_path

SAFE_CONFIG_KEYS = {
    "language",
    "allowed_media_roots",
    "transcription_engine_mode",
    "whisper_model",
    "use_gpu",
    "target_language",
    "translation_model",
    "llm_translator_model",
    "llm_translator_gguf_enabled",
    "translation_max_untranslated_pct",
    "enable_diarization",
    "dialogue_style_enabled",
    "gender_correction_enabled",
    "punctuation_restore_mode",
    "model_cache_cleanup_enabled",
    "opensubtitles_upload_enabled",
    "mux_subtitle_into_video",
    "replace_mislabeled_italian_track",
}

SECRET_CONFIG_KEYS = {
    "huggingface_token",
    "claude_api_key",
    "openai_api_key",
    "opensubtitles_password",
    "opensubtitles_api_key",
    "opensubtitles_xmlrpc_password",
    "library_scanner_api_key",
}


class JobIn(BaseModel):
    path: str
    overrides: Optional[Dict[str, Any]] = None


class ConfigIn(BaseModel):
    values: Dict[str, Any]


def _app_version() -> str:
    try:
        text = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', text)
        return match.group(1) if match else ""
    except Exception:
        return ""


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
               config: Any = None) -> FastAPI:
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
    def history() -> List[Dict[str, Any]]:
        return [job for job in manager.snapshot() if job["status"] in TERMINAL]

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

    @app.get("/api/config", dependencies=auth)
    def read_config() -> Dict[str, Any]:
        values = {}
        for key in sorted(SAFE_CONFIG_KEYS):
            values[key] = config.get(key)
        for key in sorted(SECRET_CONFIG_KEYS):
            values[key] = {"is_set": bool(config.get(key))}
        return values

    @app.put("/api/config", dependencies=auth)
    def update_config(payload: ConfigIn = Body(...)) -> Dict[str, Any]:
        unknown = [key for key in payload.values if key not in SAFE_CONFIG_KEYS
                   and key not in SECRET_CONFIG_KEYS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"keys not writable: {unknown}")
        for key, value in payload.values.items():
            config.set(key, value, save=True)
        return read_config()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        return response

    from web.ui import router as ui_router
    app.include_router(ui_router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
