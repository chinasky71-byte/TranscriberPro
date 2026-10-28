# -*- coding: utf-8 -*-
"""Endpoint dell'anteprima (fetta 2d)."""
import asyncio

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from tpweb.preview import PreviewService


class SelectBody(BaseModel):
    path: str
    force: bool = False


class TitleBody(BaseModel):
    path: str
    filename: str = ''


def add_preview_routes(app: FastAPI, preview: PreviewService) -> None:
    @app.post('/api/preview/select')
    async def select(body: SelectBody):
        if body.force:
            preview.reset_last()
        return {'started': preview.select(body.path), **preview.state()}

    @app.get('/api/preview')
    async def state():
        return preview.state()

    @app.post('/api/preview/title')
    async def title(body: TitleBody):
        """Il titolo puo' richiedere la rete (anime con il solo numero assoluto): fuori dal ciclo degli eventi."""
        text = await asyncio.get_running_loop().run_in_executor(None, preview.title_for, body.path, body.filename)
        return {'title': text}

    @app.get('/api/poster/{poster_id}')
    async def poster(poster_id: int):
        f = preview.poster_file
        if preview.status != 'found' or poster_id != preview.poster_id or f is None or not f.exists():
            return JSONResponse({'error': 'locandina non disponibile'}, status_code=404)
        return FileResponse(f)
