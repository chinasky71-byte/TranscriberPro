# -*- coding: utf-8 -*-
"""Avvio della web UI: `python -m tpweb` oppure `python main.py --ui web`. Senza Qt.

Compone config, cronologia, coda, server (solo 127.0.0.1, porta libera, token), blocca un solo server per utente, rifiuta di
partire se la GUI Qt o la coda headless possiedono gia' la coda, apre il browser (o stampa l'indirizzo) e attende «Esci» o Ctrl+C."""
import argparse
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Callable, List, Optional

from core.jobs.engine import QueueEngine
from core.services.history_service import HistoryService
from core.services.job_options_service import JobOptionsService
from core.services.shutdown_policy import ShutdownPolicy
from tpweb import lifecycle
from tpweb.ui_choice import requested_ui  # noqa: F401
from tpweb.events import EventBus
from tpweb.queue_backend import WebQueue
from tpweb.runner import ServerThread

EXIT_OK, EXIT_BUSY = 0, 3


def build(config, history_path=None, project_root=None, shutdown_fn=None, opener=None, sampler=None, quit_event=None,
          port=None, token=None) -> ServerThread:
    """Compone il server completo (non lo avvia)."""
    bus = EventBus()
    history = HistoryService(history_path)
    history.load()
    job = JobOptionsService(config)
    queue = WebQueue(bus, engine_factory=lambda w: QueueEngine(w.queue, w, project_root=project_root),
                     history=history, shutdown_enabled=lambda: job.load().shutdown_after,
                     shutdown_fn=shutdown_fn if shutdown_fn is not None else (lambda: subprocess.run(ShutdownPolicy.command())),
                     shutdown_delay_s=ShutdownPolicy.DELAY_MS / 1000)
    srv = ServerThread(token=token, port=port, bus=bus, queue=queue, history=history, config=config, opener=opener,
                       sampler=sampler, on_quit=(quit_event.set if quit_event is not None else None))
    return srv


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog='tpweb', description='Transcriber Pro, interfaccia web (solo questo computer).')
    ap.add_argument('--ui', choices=['qt', 'web'], default='web', help='accettato per compatibilita\' con main.py')
    ap.add_argument('--no-browser', action='store_true', help="non aprire il browser: stampa solo l'indirizzo")
    args = ap.parse_args(argv)
    lock = lifecycle.ServerLock()
    if not lock.acquire():
        print(f"Transcriber Pro web: un altro server e' gia' in esecuzione (processo {lock.holder()}).", file=sys.stderr)
        return EXIT_BUSY
    try:
        busy = lifecycle.conflicts()
        if busy:
            print("Transcriber Pro: la coda e' gia' in uso da " + ('la GUI' if busy[0] == 'gui' else 'la coda headless') +
                  ': chiudila prima di avviare la web UI.', file=sys.stderr)
            return EXIT_BUSY
        from utils.config import get_config
        quit_event = threading.Event()
        srv = build(get_config(), quit_event=quit_event)
        srv.start()
        print(srv.url, flush=True)
        if not args.no_browser:
            webbrowser.open(srv.url)
        try:
            while not quit_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            srv.queue.stop()
        time.sleep(0.2)                      # lascia partire la risposta di /api/quit
        srv.queue.join(10)
        srv.stop()
        return EXIT_OK
    finally:
        lock.release()
