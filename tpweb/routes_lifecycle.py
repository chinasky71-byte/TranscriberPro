# -*- coding: utf-8 -*-
"""Chiusura esplicita del server (pulsante «Esci»): a differenza della GUI Qt, chiudere la scheda NON ferma l'elaborazione.
Con la coda al lavoro serve `force`; con `force` si ferma prima il file in corso (come Stop) e poi si esce."""
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tpweb.queue_backend import WebQueue


class QuitBody(BaseModel):
    force: bool = False


def add_lifecycle_routes(app: FastAPI, queue: WebQueue, on_quit: Callable[[], None]) -> None:
    @app.post('/api/quit')
    async def quit_server(body: QuitBody):
        if queue.is_processing:
            if not body.force:
                return JSONResponse({'quit': False, 'reason': 'processing'}, status_code=409)
            queue.stop()
        on_quit()
        return {'quit': True}
