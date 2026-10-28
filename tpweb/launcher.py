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
          port=None, token=None, tmdb_client=None, gpu_detect=None, tool_engines=None, library_deps=None, ocr_engine=None) -> ServerThread:
    """Compone il server completo (non lo avvia)."""
    from tpweb.lang import apply_to_process
    apply_to_process(config)
    bus = EventBus()
    history = HistoryService(history_path)
    history.load()
    job = JobOptionsService(config)
    queue = WebQueue(bus, engine_factory=lambda w: QueueEngine(w.queue, w, project_root=project_root),
                     history=history, shutdown_enabled=lambda: job.load().shutdown_after,
                     shutdown_fn=shutdown_fn if shutdown_fn is not None else (lambda: subprocess.run(ShutdownPolicy.command())),
                     shutdown_delay_s=ShutdownPolicy.DELAY_MS / 1000, config=config)
    from tpweb.preview import PreviewService
    if tmdb_client is not None:
        factory = lambda: tmdb_client                       # noqa: E731
    else:
        def factory():
            from utils.tmdb_client import get_tmdb_client
            return get_tmdb_client()
    preview = PreviewService(bus, factory)
    from tpweb.gpu import GpuBadge, default_detect
    gpu = GpuBadge(bus, gpu_detect or default_detect)
    queue.preview = preview
    srv = ServerThread(token=token, port=port, bus=bus, queue=queue, history=history, config=config, opener=opener,
                       sampler=sampler, on_quit=(quit_event.set if quit_event is not None else None), preview=preview, gpu=gpu, tool_engines=tool_engines, library_deps=library_deps, ocr_engine=ocr_engine)
    _startup_log(queue, config, preview)
    return srv


def _startup_log(queue, config, preview) -> None:
    """Le righe con cui la GUI apre il log (tr(), nella lingua del processo)."""
    from utils.engine_labels import ENGINE_MODE_LABELS
    from utils.translations import tr
    queue.log_message(tr('app_started'))
    try:
        has_key = bool(preview.client.api_key)
    except Exception:
        has_key = False
    queue.log_message(tr('mw_tmdb_client').format(state=tr('mw_state_on') if has_key else tr('mw_state_off')))
    queue.log_message(tr('mw_engine_log').format(engine=ENGINE_MODE_LABELS.get(config.get_transcription_engine_mode(), 'Auto')))


def use_shell(mode: str, no_browser: bool, available: Optional[bool] = None) -> bool:
    """Finestra nativa? `on` sempre (se manca pywebview si ricade sul browser), `auto` solo se installato e non e' un avvio senza browser."""
    if mode == 'off':
        return False
    if mode == 'on':
        return True
    from tpweb.shell import pywebview_available
    return (pywebview_available() if available is None else available) and not no_browser


def run_shell(srv, quit_event, webview=None) -> bool:
    """Apre la finestra e ci resta finche' non viene chiusa. True se la finestra si e' aperta (anche se poi e' stata chiusa)."""
    from tpweb.shell import Shell
    from utils.translations import tr
    if webview is None:
        try:
            import webview
        except Exception:
            return False
    ask = lambda window: window.evaluate_js("window.dispatchEvent(new Event('tp-quit-request'))")      # noqa: E731
    shell = Shell(webview, srv.url, srv.wait_page, quit_event.set, lambda: srv.queue.is_processing, ask, file_label=tr('web_shell_files'))

    def closer():
        quit_event.wait()
        time.sleep(0.2)                                   # lascia partire la risposta di /api/quit
        shell.close_window()
    threading.Thread(target=closer, name='tpweb-shell-closer', daemon=True).start()
    opened = shell.run()
    if opened:
        quit_event.set()                                  # chiusa la finestra si esce, come chiudere la finestra Qt
    return opened


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog='tpweb', description='Transcriber Pro, interfaccia web (solo questo computer).')
    ap.add_argument('--ui', choices=['qt', 'web'], default='web', help='accettato per compatibilita\' con main.py')
    ap.add_argument('--no-browser', action='store_true', help="non aprire il browser: stampa solo l'indirizzo")
    ap.add_argument('--shell', choices=['auto', 'on', 'off'], default='auto',
                    help="finestra nativa (pywebview): auto = se installato e senza --no-browser; on = obbligatoria; off = browser")
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
        shown = False
        if use_shell(args.shell, args.no_browser):
            shown = run_shell(srv, quit_event)
        if not shown and not args.no_browser:
            webbrowser.open(srv.url)                # senza guscio, o se la finestra non si e' aperta: browser predefinito
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
