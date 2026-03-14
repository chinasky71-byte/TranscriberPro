# -*- coding: utf-8 -*-
"""
Library Scanner - API FastAPI con Autenticazione
Protegge tutti gli endpoint con:
  - API Key (header X-API-Key) per accesso programmatico
  - Session cookie per dashboard web
  - Rate limiting su login
  - Health check pubblico (per Docker healthcheck)
"""
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc

from library_scanner.config import Config
from library_scanner.database import init_db, get_db
from library_scanner.models import ScanDirectory, VideoFile, ScanLog, SystemConfig
from library_scanner.scanner import get_scanner
from library_scanner.scheduler import start_scheduler, stop_scheduler, get_scheduler_status
from library_scanner.subtitle_checker import check_all_subtitles

# -- Logging --
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# -- FastAPI App --
app = FastAPI(
    title="Library Scanner API",
    description="Sistema di scansione video per rilevamento sottotitoli italiani",
    version="1.0.0",
    docs_url=None,   # Disabilita Swagger UI pubblica
    redoc_url=None,   # Disabilita ReDoc pubblica
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# AUTHENTICATION DEPENDENCY
# ============================================================================

SESSION_COOKIE = "scanner_session"


def _get_client_ip(request: Request) -> str:
    """Ottiene l'IP del client."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def require_auth(request: Request):
    """
    Dependency FastAPI: verifica autenticazione.
    Accetta API Key (header) OPPURE session cookie.
    """
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()

    # 1. Controlla API Key nell'header
    api_key = request.headers.get("X-API-Key")
    if api_key and auth.verify_api_key(api_key):
        return "api_key"

    # 2. Controlla session cookie
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token:
        username = auth.verify_session(session_token)
        if username:
            return username

    # 3. Non autenticato
    # Se e' una richiesta API (Accept: application/json o path /api/), ritorna 401
    accept = request.headers.get("Accept", "")
    if request.url.path.startswith("/api/") or "application/json" in accept:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta. Usa header X-API-Key o effettua il login.")

    # Se e' una richiesta web, redirect al login
    raise HTTPException(status_code=303, headers={"Location": "/login"})


# ============================================================================
# STARTUP / SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def on_startup():
    """Inizializzazione all'avvio."""
    Config.ensure_directories()

    # Setup logging su file
    try:
        file_handler = logging.FileHandler(Config.LOG_PATH / "scanner.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("Library Scanner API - Avvio")
    logger.info(f"  Database: {Config.DB_PATH}")
    logger.info(f"  Porta: {Config.PORT}")
    logger.info("=" * 60)

    init_db()
    _init_default_directories()

    # Inizializza auth DOPO il database
    from library_scanner.auth import get_auth_manager
    get_auth_manager()

    start_scheduler()
    logger.info("API pronta")


@app.on_event("shutdown")
async def on_shutdown():
    stop_scheduler()
    scanner = get_scanner()
    if scanner.is_running:
        scanner.cancel()
    logger.info("Library Scanner API - Chiusura")


def _init_default_directories():
    """Inserisce le directory di default se il database e' vuoto."""
    with get_db() as db:
        count = db.execute(select(func.count(ScanDirectory.id))).scalar()
        if count > 0:
            return
        defaults = [
            {"label": "Movies", "linux_path": "/mnt/movies", "windows_path": "\\\\192.168.1.18\\film", "media_type": "movie"},
            {"label": "Film 2", "linux_path": "/mnt/film2", "windows_path": "\\\\192.168.1.18\\film_2", "media_type": "movie"},
            {"label": "TV Shows", "linux_path": "/mnt/tvshows", "windows_path": "\\\\192.168.1.18\\tv", "media_type": "tvshow"},
        ]
        for d in defaults:
            db.add(ScanDirectory(**d, enabled=True, recursive=True))
        logger.info(f"Inserite {len(defaults)} directory di default")


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class DirectoryCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    linux_path: str = Field(..., min_length=1)
    windows_path: str = Field(..., min_length=1)
    media_type: str = Field(default="movie", pattern="^(movie|tvshow)$")
    enabled: bool = True
    recursive: bool = True


class DirectoryUpdate(BaseModel):
    label: Optional[str] = None
    linux_path: Optional[str] = None
    windows_path: Optional[str] = None
    media_type: Optional[str] = None
    enabled: Optional[bool] = None
    recursive: Optional[bool] = None


# ============================================================================
# PUBLIC ENDPOINTS (no auth)
# ============================================================================

@app.get("/health")
async def health():
    """Health check pubblico per Docker healthcheck."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    """Pagina di login."""
    # Se gia' autenticato, redirect alla dashboard
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token and auth.verify_session(session_token):
        return RedirectResponse(url="/", status_code=303)
    return _render_login_page(error)


@app.post("/login")
async def do_login(request: Request, response: Response,
                   username: str = Form(...), password: str = Form(...)):
    """Processa il login."""
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    client_ip = _get_client_ip(request)

    token = auth.verify_login(username, password, client_ip)
    if not token:
        return HTMLResponse(_render_login_page("Credenziali non valide"), status_code=401)

    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=Config.SESSION_MAX_AGE_HOURS * 3600,
    )
    return resp


@app.get("/logout")
async def do_logout(request: Request):
    """Logout e distruzione sessione."""
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token:
        auth.logout(session_token)
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ============================================================================
# PROTECTED: API INFO
# ============================================================================

@app.get("/api/info", dependencies=[Depends(require_auth)])
async def api_info():
    scanner = get_scanner()
    sched = get_scheduler_status()
    with get_db() as db:
        total_files = db.execute(select(func.count(VideoFile.id))).scalar()
        no_subs = db.execute(
            select(func.count(VideoFile.id)).where(VideoFile.has_any_italian_sub == False)
        ).scalar()
    return {
        "service": "Library Scanner",
        "version": "1.0.0",
        "scanner_running": scanner.is_running,
        "scheduler": sched,
        "total_files": total_files,
        "files_without_subs": no_subs,
    }


# ============================================================================
# PROTECTED: DIRECTORY MANAGEMENT
# ============================================================================

@app.get("/api/directories", dependencies=[Depends(require_auth)])
async def list_directories():
    with get_db() as db:
        dirs = db.execute(select(ScanDirectory).order_by(ScanDirectory.label)).scalars().all()
        return [
            {"id": d.id, "label": d.label, "linux_path": d.linux_path,
             "windows_path": d.windows_path, "media_type": d.media_type,
             "enabled": d.enabled, "recursive": d.recursive}
            for d in dirs
        ]


@app.post("/api/directories", status_code=201, dependencies=[Depends(require_auth)])
async def create_directory(data: DirectoryCreate):
    with get_db() as db:
        existing = db.execute(
            select(ScanDirectory).where(ScanDirectory.linux_path == data.linux_path)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(400, f"Directory gia' esistente: {data.linux_path}")
        scan_dir = ScanDirectory(**data.model_dump())
        db.add(scan_dir)
        db.flush()
        return {"id": scan_dir.id, "message": f"Directory '{data.label}' creata"}


@app.put("/api/directories/{dir_id}", dependencies=[Depends(require_auth)])
async def update_directory(dir_id: int, data: DirectoryUpdate):
    with get_db() as db:
        scan_dir = db.get(ScanDirectory, dir_id)
        if not scan_dir:
            raise HTTPException(404, "Directory non trovata")
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(scan_dir, key, value)
        return {"message": f"Directory '{scan_dir.label}' aggiornata"}


@app.delete("/api/directories/{dir_id}", dependencies=[Depends(require_auth)])
async def delete_directory(dir_id: int):
    with get_db() as db:
        scan_dir = db.get(ScanDirectory, dir_id)
        if not scan_dir:
            raise HTTPException(404, "Directory non trovata")
        label = scan_dir.label
        db.delete(scan_dir)
        return {"message": f"Directory '{label}' eliminata"}


# ============================================================================
# PROTECTED: SCANNER CONTROL
# ============================================================================

@app.post("/api/scan/start", dependencies=[Depends(require_auth)])
async def start_scan():
    scanner = get_scanner()
    if scanner.is_running:
        raise HTTPException(409, "Scansione gia' in corso")
    thread = threading.Thread(target=scanner.run_full_scan, daemon=True)
    thread.start()
    return {"message": "Scansione avviata", "status": "running"}


@app.post("/api/scan/cancel", dependencies=[Depends(require_auth)])
async def cancel_scan():
    scanner = get_scanner()
    if not scanner.is_running:
        raise HTTPException(400, "Nessuna scansione in corso")
    scanner.cancel()
    return {"message": "Cancellazione richiesta"}


@app.get("/api/scan/status", dependencies=[Depends(require_auth)])
async def scan_status():
    scanner = get_scanner()
    sched = get_scheduler_status()
    return {"scanning": scanner.is_running, "scheduler": sched}


@app.get("/api/scan/history", dependencies=[Depends(require_auth)])
async def scan_history(limit: int = Query(default=20, ge=1, le=100)):
    with get_db() as db:
        logs = db.execute(
            select(ScanLog).order_by(desc(ScanLog.started_at)).limit(limit)
        ).scalars().all()
        return [
            {"id": l.id,
             "started_at": l.started_at.isoformat() if l.started_at else None,
             "finished_at": l.finished_at.isoformat() if l.finished_at else None,
             "status": l.status, "files_found": l.files_found,
             "files_new": l.files_new, "files_updated": l.files_updated,
             "files_removed": l.files_removed, "files_with_subs": l.files_with_subs,
             "files_without_subs": l.files_without_subs, "errors": l.errors,
             "duration_seconds": l.duration_seconds}
            for l in logs
        ]


# ============================================================================
# PROTECTED: VIDEO FILES
# ============================================================================

@app.get("/api/videos", dependencies=[Depends(require_auth)])
async def list_videos(
    no_subs_only: bool = Query(default=True),
    media_type: Optional[str] = Query(default=None, pattern="^(movie|tvshow)$"),
    min_days: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    sort_by: str = Query(default="first_seen", pattern="^(first_seen|filename|file_size)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    with get_db() as db:
        query = select(VideoFile)
        if no_subs_only:
            query = query.where(VideoFile.has_any_italian_sub == False)
        if media_type:
            query = query.where(VideoFile.media_type == media_type)
        if search:
            query = query.where(VideoFile.filename.ilike(f"%{search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = db.execute(count_query).scalar()

        sort_col = getattr(VideoFile, sort_by)
        query = query.order_by(desc(sort_col) if sort_order == "desc" else sort_col)
        query = query.offset(offset).limit(limit)
        videos = db.execute(query).scalars().all()

        now = datetime.now(timezone.utc)
        results = []
        for v in videos:
            first_seen_utc = v.first_seen.replace(tzinfo=timezone.utc) if v.first_seen.tzinfo is None else v.first_seen
            days = (now - first_seen_utc).days
            if min_days > 0 and days < min_days:
                continue
            results.append({
                "id": v.id, "filename": v.filename,
                "windows_path": v.windows_path, "linux_path": v.linux_path,
                "relative_path": v.relative_path,
                "file_size_mb": round(v.file_size / (1024 * 1024), 1) if v.file_size else 0,
                "media_type": v.media_type,
                "has_italian_srt": v.has_italian_srt,
                "has_italian_embedded": v.has_italian_embedded,
                "has_any_italian_sub": v.has_any_italian_sub,
                "days_without_subs": days if not v.has_any_italian_sub else 0,
                "first_seen": v.first_seen.isoformat() if v.first_seen else None,
                "last_scanned": v.last_scanned.isoformat() if v.last_scanned else None,
                "directory_label": v.scan_directory.label if v.scan_directory else None,
            })
        return {"total": total, "offset": offset, "limit": limit, "count": len(results), "videos": results}


@app.get("/api/stats", dependencies=[Depends(require_auth)])
async def get_stats():
    with get_db() as db:
        total = db.execute(select(func.count(VideoFile.id))).scalar()
        with_subs = db.execute(select(func.count(VideoFile.id)).where(VideoFile.has_any_italian_sub == True)).scalar()
        without_subs = db.execute(select(func.count(VideoFile.id)).where(VideoFile.has_any_italian_sub == False)).scalar()
        total_size = db.execute(select(func.sum(VideoFile.file_size))).scalar() or 0

        dirs = db.execute(select(ScanDirectory)).scalars().all()
        dir_stats = []
        for d in dirs:
            d_total = db.execute(select(func.count(VideoFile.id)).where(VideoFile.directory_id == d.id)).scalar()
            d_no_subs = db.execute(select(func.count(VideoFile.id)).where(
                VideoFile.directory_id == d.id, VideoFile.has_any_italian_sub == False)).scalar()
            dir_stats.append({"label": d.label, "total": d_total, "without_subs": d_no_subs, "enabled": d.enabled})

        last_scan = db.execute(select(ScanLog).order_by(desc(ScanLog.started_at)).limit(1)).scalar_one_or_none()
        return {
            "total_files": total, "with_subs": with_subs, "without_subs": without_subs,
            "total_size_gb": round(total_size / (1024 ** 3), 1),
            "directories": dir_stats,
            "last_scan": {"started_at": last_scan.started_at.isoformat(), "status": last_scan.status,
                          "duration_seconds": last_scan.duration_seconds} if last_scan else None,
        }


# ============================================================================
# PROTECTED: TRANSCRIBER PRO NOTIFICATION
# ============================================================================

class SubtitleNotification(BaseModel):
    windows_path: str

@app.post("/api/videos/notify-subtitle", dependencies=[Depends(require_auth)])
async def notify_subtitle_created(notification: SubtitleNotification):
    """Transcriber Pro ha creato un sottotitolo: ri-controlla il file e aggiorna il DB."""
    with get_db() as db:
        vf = db.query(VideoFile).filter(
            VideoFile.windows_path == notification.windows_path
        ).first()

        if not vf:
            raise HTTPException(status_code=404, detail="File not found in database")

        sub_result = check_all_subtitles(Path(vf.linux_path))

        vf.has_italian_srt      = sub_result["has_external"]
        vf.has_italian_embedded = sub_result["has_embedded"]
        vf.has_any_italian_sub  = sub_result["has_any"]
        vf.last_scanned         = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"notify-subtitle: {vf.filename} → has_any_italian_sub={vf.has_any_italian_sub}"
        )
        return {
            "updated":             True,
            "has_any_italian_sub": vf.has_any_italian_sub,
            "has_italian_srt":     vf.has_italian_srt,
        }


# ============================================================================
# PROTECTED: SECURITY MANAGEMENT
# ============================================================================

@app.post("/api/security/change-password", dependencies=[Depends(require_auth)])
async def change_password(request: Request,
                          current_password: str = Form(...),
                          new_password: str = Form(...)):
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    if len(new_password) < 8:
        raise HTTPException(400, "La nuova password deve avere almeno 8 caratteri")
    if not auth.change_password(current_password, new_password):
        raise HTTPException(400, "Password corrente non valida")
    return {"message": "Password aggiornata"}


@app.post("/api/security/regenerate-api-key", dependencies=[Depends(require_auth)])
async def regenerate_api_key():
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    new_key = auth.regenerate_api_key()
    return {"api_key": new_key, "message": "API key rigenerata"}


@app.get("/api/security/api-key", dependencies=[Depends(require_auth)])
async def get_api_key():
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    return {"api_key": auth.get_api_key()}


# ============================================================================
# PROTECTED: WEB DASHBOARD
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def web_dashboard(request: Request):
    """Dashboard web protetta."""
    from library_scanner.auth import get_auth_manager
    auth = get_auth_manager()
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token or not auth.verify_session(session_token):
        return RedirectResponse(url="/login", status_code=303)
    return _render_web_ui()


# ============================================================================
# LOGIN PAGE HTML
# ============================================================================

def _render_login_page(error: str = "") -> str:
    error_html = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Library Scanner - Login</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f; color: #e0e0e0;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh;
        }}
        .login-box {{
            background: #1a1a2e; border-radius: 12px; padding: 40px;
            border: 1px solid #2a2a4a; width: 100%; max-width: 380px;
        }}
        h1 {{ color: #e94560; font-size: 1.4em; text-align: center; margin-bottom: 8px; }}
        .subtitle {{ color: #888; font-size: 0.85em; text-align: center; margin-bottom: 24px; }}
        .field {{ margin-bottom: 16px; }}
        label {{ display: block; color: #aaa; font-size: 0.85em; margin-bottom: 6px; }}
        input {{
            width: 100%; padding: 10px 14px; border: 1px solid #2a2a4a;
            border-radius: 6px; background: #111; color: #e0e0e0;
            font-size: 0.95em;
        }}
        input:focus {{ outline: none; border-color: #e94560; }}
        .btn {{
            width: 100%; padding: 12px; border: none; border-radius: 6px;
            background: #e94560; color: #fff; font-size: 1em;
            font-weight: 600; cursor: pointer; margin-top: 8px;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .error {{
            background: #3d0000; color: #ff6b6b; padding: 10px;
            border-radius: 6px; text-align: center; margin-bottom: 16px;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
<div class="login-box">
    <h1>Library Scanner</h1>
    <p class="subtitle">Accesso richiesto</p>
    {error_html}
    <form method="POST" action="/login">
        <div class="field">
            <label>Username</label>
            <input type="text" name="username" required autofocus>
        </div>
        <div class="field">
            <label>Password</label>
            <input type="password" name="password" required>
        </div>
        <button type="submit" class="btn">Accedi</button>
    </form>
</div>
</body>
</html>"""


# ============================================================================
# DASHBOARD HTML (con sezione sicurezza)
# ============================================================================

def _render_web_ui() -> str:
    return """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Library Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f; color: #e0e0e0; line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            padding: 20px; border-bottom: 2px solid #0f3460;
            display: flex; justify-content: space-between; align-items: center;
        }
        header h1 { font-size: 1.5em; color: #e94560; }
        header p { color: #888; font-size: 0.9em; }
        .header-right { display: flex; gap: 12px; align-items: center; }
        .header-right a {
            color: #e94560; text-decoration: none; font-size: 0.9em;
            padding: 6px 14px; border: 1px solid #e94560; border-radius: 6px;
        }
        .header-right a:hover { background: #e94560; color: #fff; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin: 20px 0; }
        .card {
            background: #1a1a2e; border-radius: 10px; padding: 20px;
            border: 1px solid #2a2a4a;
        }
        .card h3 { color: #e94560; margin-bottom: 10px; font-size: 1em; }
        .stat-big { font-size: 2em; font-weight: 700; color: #fff; }
        .stat-label { color: #888; font-size: 0.85em; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #2a2a4a; }
        th { color: #e94560; font-size: 0.85em; text-transform: uppercase; }
        td { font-size: 0.9em; }
        .badge {
            display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 0.75em; font-weight: 600;
        }
        .badge-ok { background: #1b4332; color: #52b788; }
        .badge-no { background: #3d0000; color: #ff6b6b; }
        .badge-warn { background: #3d3000; color: #ffd43b; }
        .btn {
            display: inline-block; padding: 10px 20px; border: none;
            border-radius: 6px; cursor: pointer; font-size: 0.9em;
            font-weight: 600; transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.85; }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn-primary { background: #e94560; color: #fff; }
        .btn-danger { background: #dc3545; color: #fff; }
        .btn-secondary { background: #2a2a4a; color: #e0e0e0; }
        .actions { display: flex; gap: 10px; margin: 16px 0; flex-wrap: wrap; }
        #log { background: #111; padding: 12px; border-radius: 6px; font-family: monospace;
               font-size: 0.8em; max-height: 200px; overflow-y: auto; color: #aaa; margin-top: 10px; }
        .section { margin-top: 24px; }
        .section h2 { color: #e94560; font-size: 1.2em; margin-bottom: 12px; border-bottom: 1px solid #2a2a4a; padding-bottom: 8px; }
        .refresh-note { color: #666; font-size: 0.8em; margin-top: 4px; }
        .form-row { display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
        .form-row input, .form-row select {
            padding: 8px 12px; border: 1px solid #2a2a4a; border-radius: 6px;
            background: #111; color: #e0e0e0; font-size: 0.9em;
        }
        .form-row input { flex: 1; min-width: 150px; }
        .api-key-box {
            background: #111; padding: 12px; border-radius: 6px;
            font-family: monospace; font-size: 0.85em; color: #52b788;
            word-break: break-all; margin: 8px 0;
        }
        .msg-ok { color: #52b788; font-size: 0.85em; margin-top: 6px; }
        .msg-err { color: #ff6b6b; font-size: 0.85em; margin-top: 6px; }
    </style>
</head>
<body>
<header>
    <div>
        <h1>Library Scanner</h1>
        <p>Monitoraggio sottotitoli italiani nella libreria video</p>
    </div>
    <div class="header-right">
        <a href="/logout">Logout</a>
    </div>
</header>
<div class="container">
    <!-- STATS -->
    <div class="grid">
        <div class="card"><h3>File Totali</h3><div class="stat-big" id="stat-total">-</div></div>
        <div class="card"><h3>Senza Sottotitoli ITA</h3><div class="stat-big" id="stat-nosubs" style="color:#ff6b6b">-</div></div>
        <div class="card"><h3>Con Sottotitoli ITA</h3><div class="stat-big" id="stat-withsubs" style="color:#52b788">-</div></div>
        <div class="card"><h3>Dimensione Totale</h3><div class="stat-big" id="stat-size">-</div><div class="stat-label">GB</div></div>
    </div>

    <!-- SCANNER -->
    <div class="section">
        <h2>Scanner</h2>
        <div class="actions">
            <button class="btn btn-primary" id="btn-scan" onclick="startScan()">Avvia Scansione</button>
            <button class="btn btn-danger" id="btn-cancel" onclick="cancelScan()" disabled>Annulla</button>
            <button class="btn btn-secondary" onclick="loadAll()">Aggiorna Dati</button>
        </div>
        <div id="scan-status" class="refresh-note"></div>
        <div id="log"></div>
    </div>

    <!-- DIRECTORIES -->
    <div class="section">
        <h2>Directory Configurate</h2>
        <table><thead><tr><th>Nome</th><th>Path Linux</th><th>Path Windows</th><th>Tipo</th><th>Stato</th><th>Azioni</th></tr></thead>
        <tbody id="dir-body"></tbody></table>
        <h3 style="margin-top:16px;color:#888;">Aggiungi Directory</h3>
        <div class="form-row">
            <input id="new-label" placeholder="Nome (es. Movies)">
            <input id="new-linux" placeholder="Path Linux (es. /mnt/movies)">
            <input id="new-windows" placeholder="Path Windows (es. \\\\192.168.1.18\\film)">
            <select id="new-type"><option value="movie">Film</option><option value="tvshow">Serie TV</option></select>
            <button class="btn btn-primary" onclick="addDirectory()">Aggiungi</button>
        </div>
    </div>

    <!-- FILE SENZA SOTTOTITOLI -->
    <div class="section">
        <h2>File Senza Sottotitoli Italiani</h2>
        <table><thead><tr><th>Nome File</th><th>Directory</th><th>Tipo</th><th>Dimensione</th><th>Giorni</th></tr></thead>
        <tbody id="video-body"></tbody></table>
        <div id="video-info" class="refresh-note"></div>
    </div>

    <!-- HISTORY -->
    <div class="section">
        <h2>Cronologia Scansioni</h2>
        <table><thead><tr><th>Data</th><th>Stato</th><th>Trovati</th><th>Nuovi</th><th>Rimossi</th><th>Con Sub</th><th>Senza Sub</th><th>Durata</th></tr></thead>
        <tbody id="history-body"></tbody></table>
    </div>

    <!-- SICUREZZA -->
    <div class="section">
        <h2>Sicurezza</h2>
        <div class="card" style="margin-bottom:16px">
            <h3>API Key (per Transcriber Pro)</h3>
            <div class="api-key-box" id="api-key-display">Caricamento...</div>
            <button class="btn btn-secondary" onclick="copyApiKey()" style="margin-top:8px;padding:6px 14px;font-size:0.85em">Copia</button>
            <button class="btn btn-danger" onclick="regenApiKey()" style="margin-top:8px;padding:6px 14px;font-size:0.85em">Rigenera</button>
            <div id="api-key-msg"></div>
        </div>
        <div class="card">
            <h3>Cambia Password</h3>
            <div class="form-row">
                <input id="pw-current" type="password" placeholder="Password attuale">
                <input id="pw-new" type="password" placeholder="Nuova password (min 8 car.)">
                <button class="btn btn-primary" onclick="changePassword()" style="padding:8px 16px">Cambia</button>
            </div>
            <div id="pw-msg"></div>
        </div>
    </div>
</div>

<script>
const API = '';

async function api(path, options={}) {
    const r = await fetch(API + path, {credentials:'same-origin', ...options});
    if (r.status === 401 || r.status === 303) { window.location.href = '/login'; return null; }
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || r.statusText); }
    return r.json();
}

function log(msg) {
    const el = document.getElementById('log');
    el.textContent = new Date().toLocaleTimeString() + ' - ' + msg + '\\n' + el.textContent;
}

async function loadStats() {
    try {
        const s = await api('/api/stats');
        if (!s) return;
        document.getElementById('stat-total').textContent = s.total_files;
        document.getElementById('stat-nosubs').textContent = s.without_subs;
        document.getElementById('stat-withsubs').textContent = s.with_subs;
        document.getElementById('stat-size').textContent = s.total_size_gb;
    } catch(e) { log('Errore stats: ' + e.message); }
}

async function loadDirectories() {
    try {
        const dirs = await api('/api/directories');
        if (!dirs) return;
        document.getElementById('dir-body').innerHTML = dirs.map(d => `<tr>
            <td>${d.label}</td>
            <td style="font-family:monospace;font-size:0.8em">${d.linux_path}</td>
            <td style="font-family:monospace;font-size:0.8em">${d.windows_path}</td>
            <td>${d.media_type==='movie'?'Film':'Serie TV'}</td>
            <td><span class="badge ${d.enabled?'badge-ok':'badge-warn'}">${d.enabled?'Attiva':'Disattiva'}</span></td>
            <td>
                <button class="btn btn-secondary" style="padding:4px 10px;font-size:0.8em" onclick="toggleDir(${d.id},${!d.enabled})">${d.enabled?'Disattiva':'Attiva'}</button>
                <button class="btn btn-danger" style="padding:4px 10px;font-size:0.8em" onclick="deleteDir(${d.id},'${d.label}')">Elimina</button>
            </td>
        </tr>`).join('');
    } catch(e) { log('Errore directory: ' + e.message); }
}

async function loadVideos() {
    try {
        const data = await api('/api/videos?no_subs_only=true&limit=200&sort_by=first_seen&sort_order=desc');
        if (!data) return;
        document.getElementById('video-body').innerHTML = data.videos.map(v => `<tr>
            <td title="${v.windows_path}">${v.filename}</td>
            <td>${v.directory_label||'-'}</td>
            <td>${v.media_type==='movie'?'Film':'Serie TV'}</td>
            <td>${v.file_size_mb} MB</td>
            <td><span class="badge badge-no">${v.days_without_subs}g</span></td>
        </tr>`).join('');
        document.getElementById('video-info').textContent = data.count+' di '+data.total+' file visualizzati';
    } catch(e) { log('Errore video: ' + e.message); }
}

async function loadHistory() {
    try {
        const logs = await api('/api/scan/history?limit=10');
        if (!logs) return;
        document.getElementById('history-body').innerHTML = logs.map(l => {
            const date = l.started_at ? new Date(l.started_at).toLocaleString('it-IT') : '-';
            const badge = l.status==='completed'?'badge-ok':l.status==='failed'?'badge-no':'badge-warn';
            return `<tr><td>${date}</td><td><span class="badge ${badge}">${l.status}</span></td>
                <td>${l.files_found||0}</td><td>${l.files_new||0}</td><td>${l.files_removed||0}</td>
                <td>${l.files_with_subs||0}</td><td>${l.files_without_subs||0}</td>
                <td>${l.duration_seconds?l.duration_seconds+'s':'-'}</td></tr>`;
        }).join('');
    } catch(e) { log('Errore history: ' + e.message); }
}

async function loadScanStatus() {
    try {
        const s = await api('/api/scan/status');
        if (!s) return;
        document.getElementById('btn-scan').disabled = s.scanning;
        document.getElementById('btn-cancel').disabled = !s.scanning;
        const info = s.scanning ? 'Scansione in corso...' :
            (s.scheduler.next_scan ? 'Prossima scansione: '+new Date(s.scheduler.next_scan).toLocaleString('it-IT') : '');
        document.getElementById('scan-status').textContent = info;
    } catch(e) {}
}

async function loadApiKey() {
    try {
        const data = await api('/api/security/api-key');
        if (!data) return;
        document.getElementById('api-key-display').textContent = data.api_key;
    } catch(e) { document.getElementById('api-key-display').textContent = 'Errore caricamento'; }
}

async function startScan() {
    try { await api('/api/scan/start',{method:'POST'}); log('Scansione avviata'); pollScan(); } catch(e) { log('Errore: '+e.message); }
}
async function cancelScan() {
    try { await api('/api/scan/cancel',{method:'POST'}); log('Cancellazione richiesta'); } catch(e) { log('Errore: '+e.message); }
}

let pollTimer=null;
function pollScan() {
    document.getElementById('btn-scan').disabled=true;
    document.getElementById('btn-cancel').disabled=false;
    if(pollTimer)clearInterval(pollTimer);
    pollTimer=setInterval(async()=>{
        const s=await api('/api/scan/status');
        if(!s||!s.scanning){clearInterval(pollTimer);pollTimer=null;log('Scansione terminata');loadAll();}
    },3000);
}

async function toggleDir(id,enabled) {
    try { await api('/api/directories/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})}); loadDirectories(); } catch(e) { log('Errore: '+e.message); }
}
async function deleteDir(id,label) {
    if(!confirm('Eliminare "'+label+'" e tutti i file associati?'))return;
    try { await api('/api/directories/'+id,{method:'DELETE'}); log('"'+label+'" eliminata'); loadAll(); } catch(e) { log('Errore: '+e.message); }
}
async function addDirectory() {
    const label=document.getElementById('new-label').value.trim();
    const linux=document.getElementById('new-linux').value.trim();
    const win=document.getElementById('new-windows').value.trim();
    const type=document.getElementById('new-type').value;
    if(!label||!linux||!win){log('Compila tutti i campi');return;}
    try {
        await api('/api/directories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label,linux_path:linux,windows_path:win,media_type:type})});
        document.getElementById('new-label').value='';document.getElementById('new-linux').value='';document.getElementById('new-windows').value='';
        log('"'+label+'" aggiunta'); loadDirectories();
    } catch(e) { log('Errore: '+e.message); }
}

function copyApiKey() {
    const key=document.getElementById('api-key-display').textContent;
    navigator.clipboard.writeText(key).then(()=>{
        document.getElementById('api-key-msg').innerHTML='<span class="msg-ok">Copiata!</span>';
        setTimeout(()=>document.getElementById('api-key-msg').innerHTML='',2000);
    });
}
async function regenApiKey() {
    if(!confirm('Rigenerare API key? Il client dovra\\' essere aggiornato.'))return;
    try {
        const data=await api('/api/security/regenerate-api-key',{method:'POST'});
        if(data){document.getElementById('api-key-display').textContent=data.api_key;
        document.getElementById('api-key-msg').innerHTML='<span class="msg-ok">Rigenerata!</span>';}
    } catch(e) { document.getElementById('api-key-msg').innerHTML='<span class="msg-err">Errore: '+e.message+'</span>'; }
}
async function changePassword() {
    const cur=document.getElementById('pw-current').value;
    const nw=document.getElementById('pw-new').value;
    if(!cur||!nw){document.getElementById('pw-msg').innerHTML='<span class="msg-err">Compila entrambi i campi</span>';return;}
    if(nw.length<8){document.getElementById('pw-msg').innerHTML='<span class="msg-err">Minimo 8 caratteri</span>';return;}
    try {
        const fd=new FormData(); fd.append('current_password',cur); fd.append('new_password',nw);
        await api('/api/security/change-password',{method:'POST',body:fd});
        document.getElementById('pw-current').value='';document.getElementById('pw-new').value='';
        document.getElementById('pw-msg').innerHTML='<span class="msg-ok">Password aggiornata!</span>';
    } catch(e) { document.getElementById('pw-msg').innerHTML='<span class="msg-err">'+e.message+'</span>'; }
}

function loadAll() { loadStats(); loadDirectories(); loadVideos(); loadHistory(); loadScanStatus(); loadApiKey(); }
loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>"""
