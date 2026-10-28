# -*- coding: utf-8 -*-
"""P1 (prototipo): server locale FastAPI con sicurezza di base e flusso di eventi SSE raggruppato.

Serve a misurare, non e' il codice definitivo. Regole di sicurezza provate qui (vedi p1_security_tests.py):
  - ascolta SOLO su 127.0.0.1;  - `Host` ammesso solo 127.0.0.1:<porta> / localhost:<porta> (anti DNS rebinding);
  - sessione = token casuale: il primo accesso `/?t=<token>` imposta un cookie HttpOnly SameSite=Strict e rimanda a `/`;
    ogni altra richiesta richiede il cookie (o l'intestazione X-TP-Token);
  - metodi non sicuri: `Origin` assente (client non-browser con X-TP-Token) oppure uguale all'origine del server;
  - nessun CORS; intestazioni di sicurezza; nessuna cache.
Gli eventi SSE sono raggruppati ogni BATCH_S secondi (un solo evento con una lista di messaggi).
"""
import asyncio
import json
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

STATIC = Path(__file__).resolve().parent / 'static'
BATCH_S = 0.1
COOKIE = 'tp_session'


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def create_app(token: str, port: int) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    allowed_origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
    app.state.queue = None     # asyncio.Queue dei messaggi in uscita (creata nel loop del server)
    app.state.loop = None

    @app.middleware('http')
    async def guard(request: Request, call_next):
        host = request.headers.get('host', '')
        if host not in allowed_hosts:
            return JSONResponse({'error': 'host non ammesso'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({'error': 'origin non ammessa'}, status_code=403)
        if request.method == 'OPTIONS':
            return JSONResponse({'error': 'CORS non supportato'}, status_code=405)
        # primo accesso con il token nell'URL: cookie di sessione e redirect a un URL pulito
        if request.url.path == '/' and request.query_params.get('t') is not None:
            if secrets.compare_digest(request.query_params['t'], token):
                r = RedirectResponse('/', status_code=303)
                r.set_cookie(COOKIE, token, httponly=True, samesite='strict', path='/')
                return r
            return JSONResponse({'error': 'token errato'}, status_code=401)
        sent = request.cookies.get(COOKIE) or request.headers.get('x-tp-token') or ''
        if not secrets.compare_digest(sent, token):
            return JSONResponse({'error': 'non autorizzato'}, status_code=401)
        resp = await call_next(request)
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        resp.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        return resp

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return (STATIC / 'index.html').read_text(encoding='utf-8')

    @app.get('/api/ping')
    async def ping():
        return {'ok': True, 't': time.time()}

    @app.post('/api/echo')
    async def echo(request: Request):
        return {'echo': await request.json()}

    @app.post('/api/bench/start')
    async def bench_start(request: Request):
        """Genera messaggi sintetici: `burst` righe subito, poi `rate` aggiornamenti/s per `seconds` secondi."""
        p = await request.json()
        asyncio.create_task(_produce(app, int(p.get('burst', 5000)), float(p.get('rate', 10)), float(p.get('seconds', 10))))
        return {'started': True}

    @app.get('/events')
    async def events(request: Request):
        if app.state.queue is None:
            app.state.queue = asyncio.Queue()
        q = app.state.queue

        async def gen():
            yield ': connesso\n\n'
            last_keepalive = time.time()
            while True:
                if await request.is_disconnected():
                    return
                batch = []
                try:
                    batch.append(await asyncio.wait_for(q.get(), timeout=1.0))
                except asyncio.TimeoutError:
                    if time.time() - last_keepalive > 15:
                        last_keepalive = time.time()
                        yield ': keepalive\n\n'
                    continue
                t_end = time.time() + BATCH_S                  # raggruppa quello che arriva nei prossimi BATCH_S
                while time.time() < t_end:
                    try:
                        batch.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.005)
                batch_t = time.time()
                yield 'data: ' + json.dumps({'sent': batch_t, 'msgs': batch}, separators=(',', ':')) + '\n\n'
        return StreamingResponse(gen(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
    return app


async def _produce(app: FastAPI, burst: int, rate: float, seconds: float):
    if app.state.queue is None:
        app.state.queue = asyncio.Queue()
    q = app.state.queue
    seq = 0
    for i in range(burst):
        seq += 1
        q.put_nowait({'k': 'log', 'seq': seq, 't': time.time(), 'text': f'[INFO] riga di log numero {seq} con un po\' di testo àèìòù per misurare'})
        if i % 500 == 499:
            await asyncio.sleep(0)       # cede il turno al ciclo degli eventi
    end = time.time() + seconds
    n = 0
    while time.time() < end:
        n += 1
        seq += 1
        q.put_nowait({'k': 'progress', 'seq': seq, 't': time.time(), 'pct': n % 100})
        await asyncio.sleep(1.0 / max(rate, 0.1))
    q.put_nowait({'k': 'done', 'seq': seq + 1, 't': time.time(), 'total': seq})


class ServerThread:
    """uvicorn in un thread (per i test e per il guscio pywebview)."""

    def __init__(self, token: Optional[str] = None, port: Optional[int] = None):
        self.token = token or secrets.token_urlsafe(24)
        self.port = port or free_port()
        self.app = create_app(self.token, self.port)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=self.port, log_level='warning'))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 15.0) -> 'ServerThread':
        self.thread.start()
        t0 = time.time()
        while not self.server.started and time.time() - t0 < timeout:
            time.sleep(0.02)
        if not self.server.started:
            raise RuntimeError('il server non e\' partito')
        return self

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.port}/?t={self.token}'


if __name__ == '__main__':
    s = ServerThread().start()
    print(s.url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        s.stop()
