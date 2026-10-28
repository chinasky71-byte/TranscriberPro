# -*- coding: utf-8 -*-
"""Endpoint della coda (fetta 1b). Le conferme all'utente (Stop, svuota) sono della pagina; qui i comandi sono idempotenti."""
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tpweb.queue_backend import EMPTY, RUNNING, WebQueue


class AddBody(BaseModel):
    paths: List[str]
    only_files: bool = False
    sizes: Optional[dict] = None


class RemoveBody(BaseModel):
    path: str


class ReorderBody(BaseModel):
    order: List[str]
    moved: Optional[str] = None


class OverridesBody(BaseModel):
    paths: List[str]
    key: str
    value: Optional[object] = None


def add_queue_routes(app: FastAPI, wq: WebQueue) -> None:
    @app.get('/api/queue')
    async def get_queue():
        return {'seq': app.state.bus.last_seq, **wq.state()}

    @app.post('/api/queue/add')
    async def add(body: AddBody):
        added = wq.add(body.paths, body.sizes, body.only_files)
        pool, skipped = list(added), []
        for p in body.paths:                     # un percorso ripetuto nella stessa chiamata: la prima volta aggiunto, poi saltato
            if p in pool:
                pool.remove(p)
            else:
                skipped.append(p)
        return {'added': added, 'skipped': skipped}

    @app.post('/api/queue/remove')
    async def remove(body: RemoveBody):
        return {'removed': wq.remove(body.path)}

    @app.post('/api/queue/reorder')
    async def reorder(body: ReorderBody):
        return {'ok': wq.reorder(body.order, body.moved)}

    @app.post('/api/queue/overrides')
    async def overrides(body: OverridesBody):
        return {'changed': wq.set_overrides(body.paths, body.key, body.value)}

    @app.post('/api/queue/clear')
    async def clear():
        ok = wq.clear()
        return JSONResponse({'ok': ok}, status_code=200 if ok else 409)

    @app.post('/api/queue/start')
    async def start():
        verdict = wq.start()
        return JSONResponse({'verdict': verdict}, status_code=409 if verdict == RUNNING else 200)

    @app.post('/api/queue/stop')
    async def stop():
        return {'stopping': wq.stop()}
