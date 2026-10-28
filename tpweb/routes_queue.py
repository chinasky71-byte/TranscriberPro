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


class FlagBody(BaseModel):
    enabled: bool


class OpenBody(BaseModel):
    open: bool


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
    add_queue_scan_routes(app, wq)

    @app.get('/api/queue')
    async def get_queue():
        return {'seq': app.state.bus.last_seq, **wq.state()}

    @app.get('/api/queue/live')
    async def get_live():
        return wq.live()

    @app.post('/api/log/compact')
    async def set_compact(body: FlagBody):
        wq.set_compact(body.enabled)
        return wq.log_options()

    @app.post('/api/log/pipeline-card')
    async def set_pipeline_card(body: OpenBody):
        wq.set_pipeline_open(body.open)
        return wq.log_options()

    @app.get('/api/queue/stats')
    async def get_stats():
        return wq.stats()

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

    @app.get('/api/queue/override-options')
    async def override_options():
        """Valori ammessi delle eccezioni per file (i nomi delle lingue sono le chiavi `lang_name_<codice>` del dizionario)."""
        from utils import job_overrides as JO
        return {'keys': list(JO.ALL_KEYS), 'languages': list(JO.LANGUAGES), 'translation_models': list(JO.TRANSLATION_MODELS),
                'bool_keys': list(JO.BOOL_KEYS)}

    @app.post('/api/queue/overrides')
    async def overrides(body: OverridesBody):
        changed = wq.set_overrides(body.paths, body.key, body.value)
        skipped = len(body.paths) - len(changed)
        if skipped > 0 and (body.value is None or wq.valid_override(body.key, body.value)):
            from utils.translations import tr
            wq.log_message(tr('job_ov_skipped_log').format(n=skipped))      # come la GUI: file in lavorazione, finiti o non piu' in coda
        return {'changed': changed, 'skipped': skipped}

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


class ScanBody(BaseModel):
    folder: str
    exts: Optional[List[str]] = None


class SizesBody(BaseModel):
    paths: List[str]


def add_queue_scan_routes(app: FastAPI, wq: WebQueue) -> None:
    @app.post('/api/queue/scan')
    async def scan(body: ScanBody):
        ok = wq.scan_folder(body.folder, body.exts)
        return JSONResponse({'started': ok}, status_code=200 if ok else 409)

    @app.post('/api/queue/scan/cancel')
    async def scan_cancel():
        wq.cancel_scan()
        return {'ok': True}

    @app.post('/api/queue/sizes')
    async def sizes(body: SizesBody):
        wq.request_sizes(body.paths)
        return {'requested': len(body.paths)}
