# -*- coding: utf-8 -*-
"""Strumenti (fase 4): Glossario per show. Il report del run resta sul server; la pagina manda solo cosa approvare."""
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from core.services import glossary_service as GS
from tpweb.tools import ToolRuns


class ResolveBody(BaseModel):
    names: List[str]


class RunBody(BaseModel):
    show_dir: str
    name: str = ''
    tmdb_id: Optional[int] = None
    names: List[str] = []


class ScanBody(BaseModel):
    video_dir: str = ''
    srt_dir: str = ''
    recursive: bool = False


class ChooseBody(BaseModel):
    row: int
    value: Optional[str] = None


class IncludeBody(BaseModel):
    row: int
    include: bool


class SyncRunBody(BaseModel):
    mode: str
    video: str = ''
    srt: str = ''


class Row(BaseModel):
    term: str
    approved: bool
    rendering: str = ''


class SaveBody(BaseModel):
    rows: List[Row]
    tmdb_id: Optional[int] = None


def add_tool_routes(app: FastAPI, tools: ToolRuns) -> None:
    g = tools.glossary

    @app.get('/api/tools')
    async def state():
        return tools.state()

    @app.get('/api/tools/glossary')
    async def glossary_state():
        return g.state()

    @app.get('/api/tools/glossary/names')
    async def glossary_names(folder: str):
        """Candidati per il nome dello show dalla cartella scelta (cartella, genitore, nome dei file) e se e' una cartella «Season N»."""
        p = Path(folder)
        if not p.is_dir():
            return JSONResponse({'error': 'no_folder'}, status_code=422)
        return {'names': await asyncio.to_thread(GS.name_candidates, folder), 'is_season': bool(GS.SEASON_DIR_RE.match(p.name)),
                'folder_name': p.name, 'parent_name': p.parent.name}

    @app.post('/api/tools/glossary/resolve')
    async def glossary_resolve(b: ResolveBody):
        result, used = await asyncio.to_thread(GS.resolve_tmdb, b.names)      # puo' impiegare decine di secondi: fuori dal ciclo degli eventi
        if not result or not result.get('id'):
            return {'found': False}
        return {'found': True, 'tmdb_id': result['id'], 'title': result.get('title') or used or '', 'used': used}

    @app.post('/api/tools/glossary/run')
    async def glossary_run(b: RunBody):
        if not b.show_dir.strip() or not Path(b.show_dir).is_dir():
            return JSONResponse({'error': 'no_folder'}, status_code=422)
        reason = await asyncio.to_thread(g.start, b.show_dir, b.name, b.tmdb_id, b.names)
        if reason is not None:
            return JSONResponse({'blocked': reason, 'title_key': 'tools_glossary'}, status_code=409)
        return {'started': True}

    @app.post('/api/tools/glossary/cancel')
    async def glossary_cancel():
        return {'cancelling': g.cancel()}

    @app.post('/api/tools/glossary/reset')
    async def glossary_reset():
        ok = g.reset()
        return JSONResponse({'reset': ok}, status_code=200 if ok else 409)

    @app.post('/api/tools/glossary/save')
    async def glossary_save(b: SaveBody):
        try:
            res = await asyncio.to_thread(g.save, [r.model_dump() for r in b.rows], b.tmdb_id)
        except Exception as e:
            return JSONResponse({'ok': False, 'reason': 'error', 'error': str(e)}, status_code=500)
        return JSONResponse(res, status_code=200 if res['ok'] or res['reason'] == 'no_terms' else 422)


def add_sync_routes(app: FastAPI, tools: ToolRuns) -> None:
    m = tools.sync

    @app.get('/api/tools/sync')
    async def sync_state():
        return m.state()

    @app.post('/api/tools/sync/scan')
    async def sync_scan(b: ScanBody):
        if not await asyncio.to_thread(m.scan, b.video_dir, b.srt_dir, b.recursive):       # le cartelle possono stare su un NAS lento
            return JSONResponse({'error': 'nothing'}, status_code=422)
        return m.plan_view()

    @app.post('/api/tools/sync/plan/srt')
    async def sync_choose(b: ChooseBody):
        return JSONResponse({'ok': m.choose_srt(b.row, b.value)})

    @app.post('/api/tools/sync/plan/include')
    async def sync_include(b: IncludeBody):
        return JSONResponse({'ok': m.set_include(b.row, b.include)})

    @app.post('/api/tools/sync/run')
    async def sync_run(b: SyncRunBody):
        if b.mode == 'single':
            if not b.video.strip():
                return JSONResponse({'error': 'missing_video'}, status_code=422)
            if not b.srt.strip():
                return JSONResponse({'error': 'missing_srt'}, status_code=422)
            reason = await asyncio.to_thread(m.start_single, b.video.strip(), b.srt.strip())
        elif b.mode == 'batch':
            reason = await asyncio.to_thread(m.start_batch)
            if reason == 'nothing':
                return JSONResponse({'error': 'nothing'}, status_code=422)
        else:
            return JSONResponse({'error': 'mode'}, status_code=422)
        if reason is not None:
            return JSONResponse({'blocked': reason, 'title_key': 'sync_dialog_title'}, status_code=409)
        return {'started': True}

    @app.post('/api/tools/sync/cancel')
    async def sync_cancel():
        return {'cancelling': m.cancel()}

    @app.post('/api/tools/sync/reset')
    async def sync_reset():
        ok = m.reset()
        return JSONResponse({'reset': ok}, status_code=200 if ok else 409)


class ImportBody(BaseModel):
    paths: List[str]
    log: bool = False


class AssBody(BaseModel):
    video_ids: List[int] = []


class CardBody(BaseModel):
    open: bool


def add_library_routes(app: FastAPI, lib) -> None:
    @app.get('/api/library/state')
    async def library_state():
        return lib.card_state()

    @app.put('/api/library/card')
    async def library_card(b: CardBody):
        lib.set_card_open(b.open)
        return lib.card_state()

    @app.get('/api/library')
    async def library_fetch(search: str = '', type: str = '', format: Optional[str] = None, min_days: int = 0):
        return await asyncio.to_thread(lib.fetch, search, type, format or None, max(0, min_days))        # rete: fuori dal ciclo degli eventi

    @app.get('/api/library/view')
    async def library_view(min_days: int = 0, format: Optional[str] = None):
        return lib.view(max(0, min_days), format or None)

    @app.post('/api/library/import')
    async def library_import(b: ImportBody):
        return {'added': lib.import_paths(b.paths, b.log)}

    @app.post('/api/library/ass')
    async def library_ass(b: AssBody):
        return await asyncio.to_thread(lib.convert_ass, b.video_ids)


class OcrStartBody(BaseModel):
    path: str
    kind: str = 'pgs'


class DeferredModeBody(BaseModel):
    paths: List[str]
    mode: Optional[str] = None


class TextBody(BaseModel):
    i: int
    text: str = ''


class ItalicBody(BaseModel):
    text: str
    sel: Optional[List[int]] = None


class DoneBody(BaseModel):
    accept: bool


def add_ocr_routes(app: FastAPI, ocr) -> None:
    @app.get('/api/ocr')
    async def ocr_state():
        return ocr.state()

    @app.post('/api/ocr/start')
    async def ocr_start(b: OcrStartBody):
        if b.kind not in ('pgs', 'vobsub'):
            return JSONResponse({'error': 'kind'}, status_code=422)
        result = await asyncio.to_thread(ocr.start, b.path, b.kind)
        return JSONResponse({'result': result}, status_code=409 if result == 'busy' else 200)

    @app.post('/api/ocr/superpower/check')
    async def superpower_check():
        warn = ocr.superpower_precheck()
        return {'ok': warn is None, **(warn or {})}

    @app.post('/api/ocr/superpower')
    async def superpower_run():
        return await asyncio.to_thread(ocr.superpower)

    @app.post('/api/ocr/cancel')
    async def ocr_cancel():
        return {'cancelling': ocr.cancel()}

    @app.post('/api/ocr/deferred-mode')
    async def ocr_deferred_mode(b: DeferredModeBody):
        if b.mode not in (None, 'review', 'auto'):
            return JSONResponse({'error': 'mode'}, status_code=422)
        return {'changed': ocr.set_deferred_mode(b.paths, b.mode)}

    @app.get('/api/ocr/review/list')
    async def review_list(only_flagged: bool = False):
        r = ocr.review_list(only_flagged)
        return JSONResponse(r, status_code=200) if r is not None else JSONResponse({'error': 'no_review'}, status_code=404)

    @app.get('/api/ocr/review/event/{i}')
    async def review_event(i: int):
        r = ocr.review_event(i)
        return JSONResponse(r) if r is not None else JSONResponse({'error': 'no_event'}, status_code=404)

    @app.put('/api/ocr/review/text')
    async def review_text(b: TextBody):
        r = ocr.review_text(b.i, b.text)
        return JSONResponse(r) if r is not None else JSONResponse({'error': 'no_event'}, status_code=404)

    @app.post('/api/ocr/review/verify')
    async def review_verify(b: TextBody):
        r = ocr.review_verify(b.i, b.text)
        return JSONResponse(r) if r is not None else JSONResponse({'error': 'no_event'}, status_code=404)

    @app.get('/api/ocr/review/next-flagged')
    async def review_next(i: int):
        return {'next': ocr.review_next_flagged(i)}

    @app.post('/api/ocr/review/italic')
    async def review_italic(b: ItalicBody):
        return ocr.italic(b.text, b.sel)

    @app.get('/api/ocr/review/image/{i}')
    async def review_image(i: int):
        png = await asyncio.to_thread(ocr.review_image, i)
        return Response(png, media_type='image/png', headers={'Cache-Control': 'no-store'}) if png else JSONResponse({'error': 'no_image'}, status_code=404)

    @app.post('/api/ocr/review/done')
    async def review_done(b: DoneBody):
        ok = await asyncio.to_thread(ocr.review_done, b.accept)
        return JSONResponse({'ok': ok}, status_code=200 if ok else 409)
