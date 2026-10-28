# -*- coding: utf-8 -*-
"""Avvio del server in un thread (per i test e per il guscio pywebview). Ascolta SOLO su 127.0.0.1, porta libera."""
import secrets
import socket
import threading
import time
from typing import Callable, Optional

import uvicorn

from tpweb.app import create_app
from tpweb.events import EventBus


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServerThread:
    def __init__(self, token: Optional[str] = None, port: Optional[int] = None, bus: Optional[EventBus] = None,
                 get_state: Optional[Callable[[], dict]] = None, queue=None, history=None, config=None,
                 opener=None, mapped_roots=None, sampler=None, on_quit=None, preview=None, gpu=None, env_jobs=None, translator_ok=None, tool_engines=None):
        self.token = token or secrets.token_urlsafe(24)
        self.port = port or free_port()
        self.bus = bus or EventBus()
        self.queue = queue
        self.gpu = gpu
        self.app = create_app(self.token, self.port, self.bus, get_state, queue, history, config, opener, mapped_roots, sampler, on_quit, preview, gpu, env_jobs, translator_ok, tool_engines)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=self.port, log_level='warning'))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 15.0) -> 'ServerThread':
        self.thread.start()
        t0 = time.time()
        while not self.server.started and time.time() - t0 < timeout:
            time.sleep(0.02)
        if not self.server.started:
            raise RuntimeError("il server non e' partito")
        if self.gpu is not None:
            self.gpu.start()
        return self

    def stop(self) -> None:
        tools = self.app.state.tools
        if tools is not None:
            tools.shutdown()                     # nessun sottoprocesso di uno strumento resta orfano alla chiusura
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.port}/?t={self.token}'
