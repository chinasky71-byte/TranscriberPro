# -*- coding: utf-8 -*-
"""Applicazione FastAPI di Transcriber Pro (fase 1 del piano). Nessun PyQt6, nessun import di torch/ctranslate2.

Endpoint di questa fetta: /api/ping, /api/i18n/{lingua}, /api/state, /events (SSE raggruppato con ripresa)."""
import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from tpweb.events import EventBus
from tpweb.security import install_guard

STATIC = Path(__file__).resolve().parent / 'static'
BATCH_S = 0.1
KEEPALIVE_S = 15


def create_app(token: str, port: int, bus: Optional[EventBus] = None,
               get_state: Optional[Callable[[], dict]] = None, queue=None, history=None, config=None,
               opener: Optional[Callable[[str], None]] = None, mapped_roots: Optional[Callable[[], list]] = None,
               sampler=None, on_quit: Optional[Callable[[], None]] = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bus = bus or EventBus()
    if get_state is None and queue is not None:
        get_state = lambda: {'queue': queue.state()}      # noqa: E731
    app.state.get_state = get_state or (lambda: {})
    app.state.queue = queue
    if opener is None:
        from tpweb.opener import open_path as opener
    app.state.opener = opener
    install_guard(app, token, port)

    if queue is not None:
        from tpweb.routes_queue import add_queue_routes
        add_queue_routes(app, queue)

    if history is not None:
        from tpweb.routes_history import add_history_routes
        add_history_routes(app, history)
    if config is not None:
        from tpweb.routes_settings import add_settings_routes
        add_settings_routes(app, config)
    if queue is not None and on_quit is not None:
        from tpweb.routes_lifecycle import add_lifecycle_routes
        add_lifecycle_routes(app, queue, on_quit)
    from tpweb.routes_resources import add_resource_routes
    add_resource_routes(app, sampler)
    from tpweb.routes_fs import add_fs_routes
    add_fs_routes(app, mapped_roots or (lambda: []))

    @app.get('/', response_class=HTMLResponse)
    async def index():
        page = STATIC / 'index.html'
        if not page.exists():
            return HTMLResponse('<!doctype html><title>Transcriber Pro</title><p>Interfaccia web in costruzione.</p>')
        return page.read_text(encoding='utf-8')

    @app.get('/api/ping')
    async def ping():
        return {'ok': True, 't': time.time()}

    @app.get('/api/i18n/{lang}')
    async def i18n(lang: str):
        from utils.translations import Translations
        texts = Translations.TEXTS.get(lang)
        if texts is None:
            return JSONResponse({'error': 'lingua non supportata'}, status_code=404)
        return {'lang': lang, 'texts': texts}

    @app.get('/api/state')
    async def state():
        return {'seq': app.state.bus.last_seq, 'state': app.state.get_state()}

    @app.get('/events')
    async def events(request: Request, after: Optional[int] = None):
        bus: EventBus = app.state.bus
        raw = request.headers.get('last-event-id')
        cursor = after if after is not None else (int(raw) if raw and raw.isdigit() else None)

        async def gen():
            nonlocal cursor
            loop = asyncio.get_running_loop()
            flag = asyncio.Event()
            w = bus.add_waiter(loop, flag)
            try:
                if cursor is None:               # nuova connessione: stato completo, poi il seguito
                    seq = bus.last_seq
                    snap = {'seq': seq, 'state': app.state.get_state()}
                    yield f'id: {seq}\nevent: state\ndata: ' + json.dumps(snap, separators=(',', ':')) + '\n\n'
                    cursor = seq
                else:
                    yield ': ripresa\n\n'
                last_ping = time.time()
                while True:
                    if await request.is_disconnected():
                        return
                    evs, gap = bus.since(cursor)
                    if gap:                      # eventi gia' scartati: di nuovo lo stato completo
                        seq = bus.last_seq
                        snap = {'seq': seq, 'state': app.state.get_state()}
                        yield f'id: {seq}\nevent: state\ndata: ' + json.dumps(snap, separators=(',', ':')) + '\n\n'
                        cursor = seq
                        continue
                    if not evs:
                        flag.clear()
                        if bus.since(cursor)[0]:
                            continue
                        try:
                            await asyncio.wait_for(flag.wait(), timeout=1.0)
                        except asyncio.TimeoutError:
                            if time.time() - last_ping > KEEPALIVE_S:
                                last_ping = time.time()
                                yield ': keepalive\n\n'
                            continue
                        await asyncio.sleep(BATCH_S)        # raggruppa quello che arriva subito dopo
                        continue
                    cursor = evs[-1]['seq']
                    yield f'id: {cursor}\ndata: ' + json.dumps({'msgs': evs}, separators=(',', ':')) + '\n\n'
            finally:
                bus.remove_waiter(w)
        return StreamingResponse(gen(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
    return app
