# -*- coding: utf-8 -*-
"""Cronologia (fetta 1c): le stesse celle e le stesse statistiche della GUI (core/services/history_service.py).
Le azioni «Apri .srt» e «Cartella» si danno per INDICE di voce: il server apre solo i percorsi che stanno nella cronologia,
mai un percorso scelto dalla pagina."""
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.services import history_service as hs


class OpenBody(BaseModel):
    index: int
    what: Literal['srt', 'folder']


def add_history_routes(app: FastAPI, history: hs.HistoryService) -> None:
    @app.get('/api/history')
    async def get_history(q: str = ''):
        history.load()
        st = history.stats()
        rows = []
        for i in history.search(q):
            e = history.entries[i]
            srt, folder = hs.actions_of(e)
            rows.append({'index': i, **dict(zip(('name', 'date', 'language', 'duration', 'size'), hs.row_of(e).as_tuple())),
                         'has_srt': bool(srt), 'has_folder': bool(folder)})
        return {'stats': {'total': st.total, 'size_text': st.size_text, 'time_text': st.time_text}, 'rows': rows}

    @app.post('/api/history/open')
    async def open_entry(body: OpenBody):
        history.load()
        if not 0 <= body.index < len(history.entries):
            return JSONResponse({'error': 'voce inesistente'}, status_code=404)
        srt, folder = hs.actions_of(history.entries[body.index])
        target = srt if body.what == 'srt' else folder
        if not target:
            return JSONResponse({'error': 'azione non disponibile'}, status_code=409)
        app.state.opener(str(Path(target)))
        return {'opened': target}
