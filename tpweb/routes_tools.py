# -*- coding: utf-8 -*-
"""Strumenti (fase 4): Glossario per show. Il report del run resta sul server; la pagina manda solo cosa approvare."""
import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
