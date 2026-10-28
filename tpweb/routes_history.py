# -*- coding: utf-8 -*-
"""Cronologia (fetta 1c): le stesse celle e le stesse statistiche della GUI (core/services/history_service.py).
Le azioni «Apri .srt» e «Cartella» si danno per INDICE di voce: il server apre solo i percorsi che stanno nella cronologia,
mai un percorso scelto dalla pagina."""
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.services import history_service as hs


class OpenBody(BaseModel):
    index: int
    what: Literal['srt', 'folder']
    name: Optional[str] = None       # nome e data della riga che la pagina sta mostrando: se non coincidono con la voce a quell'indice
    date: Optional[str] = None       # (cronologia cambiata nel frattempo: cancellata, nuove voci) si rifiuta, non si apre un altro file


class ClearBody(BaseModel):
    confirm: bool = False


def add_history_routes(app: FastAPI, history: hs.HistoryService) -> None:
    @app.get('/api/history')
    async def get_history(q: str = '', sort: Optional[Literal['name', 'date', 'language', 'duration', 'size']] = None,
                          direction: Literal['asc', 'desc'] = Query('asc', alias='dir')):
        """`sort` (+ `dir`): ordina per colonna sui dati veri; senza `sort` resta l'ordine del file. L'`index` di ogni riga e' sempre la
        posizione nel file, qualunque sia l'ordine mostrato (le azioni «Apri» lo usano)."""
        with history._lock:                     # la coda puo' riassegnare `entries` in un altro thread: lettura coerente
            history.load()
            st = history.stats()
            rows = []
            order = history.search(q)
            if sort:
                order = history.sort_indices(order, sort, direction == 'desc')
            for i in order:
                e = history.entries[i]
                srt, folder = hs.actions_of(e)
                rows.append({'index': i, **dict(zip(('name', 'date', 'language', 'duration', 'size'), hs.row_of(e).as_tuple())),
                             'has_srt': bool(srt), 'has_folder': bool(folder)})
        return {'stats': {'total': st.total, 'size_text': st.size_text, 'time_text': st.time_text}, 'rows': rows}

    @app.post('/api/history/clear')
    async def clear_history(body: ClearBody):
        """Svuota la cronologia: NON reversibile. Il server pretende `confirm: true` (la pagina lo manda solo dopo l'avvertimento)."""
        if body.confirm is not True:
            return JSONResponse({'error': 'conferma mancante'}, status_code=400)
        n = history.clear()
        if n is None:
            return JSONResponse({'error': 'cronologia non scrivibile'}, status_code=500)
        return {'cleared': n}

    @app.post('/api/history/open')
    async def open_entry(body: OpenBody):
        with history._lock:
            history.load()
            if not 0 <= body.index < len(history.entries):
                return JSONResponse({'error': 'voce inesistente'}, status_code=404)
            entry = history.entries[body.index]
        shown = '' if entry.get('name') is None else str(entry.get('name'))
        if body.name is not None and (shown != body.name or hs.format_date(entry) != (body.date or '')):
            return JSONResponse({'error': 'cronologia cambiata'}, status_code=409)
        srt, folder = hs.actions_of(entry)
        target = srt if body.what == 'srt' else folder
        if not target:
            return JSONResponse({'error': 'azione non disponibile'}, status_code=409)
        app.state.opener(str(Path(target)))
        return {'opened': target}
