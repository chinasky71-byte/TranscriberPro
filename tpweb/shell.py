# -*- coding: utf-8 -*-
"""Guscio nativo della web UI: una finestra pywebview (WebView2 su Windows) che mostra la pagina del server locale.

Cosa aggiunge al browser: finestra propria (niente schede), dialoghi di Windows per scegliere file e cartelle (`ShellApi`, esposta alla
pagina come `window.pywebview.api`), trascinamento di file da Esplorer (la pagina legge `pywebviewFullPath`) e la chiusura che rispetta
la coda al lavoro. Il server NON dipende dal guscio: senza pywebview, o se la finestra non si apre, si ricade sul browser predefinito.

Watchdog all'avvio: WebView2 ogni tanto resta bianco (profilo rovinato, runtime mancante). Se la pagina non si collega al server entro il
tempo concesso la finestra si chiude e si riprova con un profilo pulito (cartella nuova); finiti i tentativi si apre il browser.
Il modulo `webview` si riceve come argomento: i test lo sostituiscono con un finto, il vero giro (finestra, dialoghi) si prova su Windows."""
import logging
import os
import shutil
import tempfile
import threading
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

TITLE = 'Transcriber Pro'
WINDOW_SIZE = (1400, 900)
MIN_SIZE = (1000, 650)
STARTUP_TIMEOUT_S = 20.0
ATTEMPTS = 2                                   # il primo col profilo di sempre, il secondo con un profilo pulito


def pywebview_available() -> bool:
    import importlib.util
    return importlib.util.find_spec('webview') is not None


def file_type_filter(label: str, exts: Optional[Sequence[str]]) -> tuple:
    """('Video (*.mp4;*.mkv)',) nel formato di `create_file_dialog`; senza estensioni, nessun filtro."""
    if not exts:
        return ()
    pats = ';'.join('*' + (e if e.startswith('.') else '.' + e) for e in exts)
    return (f'{label} ({pats})',)


class ShellApi:
    """Esposta alla pagina come `window.pywebview.api`. Ogni metodo torna una lista di percorsi o None se la persona annulla."""

    def __init__(self, webview, window_getter: Callable[[], object], request_quit: Callable[[], None], file_label: str = 'Files'):
        self._wv, self._window, self._quit, self._label = webview, window_getter, request_quit, file_label

    def _dialog_kind(self, name: str):
        fd = getattr(self._wv, 'FileDialog', None)                  # pywebview >= 6: enum; prima: costanti del modulo
        return getattr(fd, name) if fd is not None and hasattr(fd, name) else getattr(self._wv, name + '_DIALOG')

    def _run(self, kind: str, **kw) -> Optional[List[str]]:
        w = self._window()
        if w is None:
            return None
        res = w.create_file_dialog(self._dialog_kind(kind), **kw)
        if not res:
            return None
        return [str(p) for p in (res if isinstance(res, (list, tuple)) else [res])]

    def pick_files(self, title: str = '', exts: Optional[List[str]] = None) -> Optional[List[str]]:
        return self._run('OPEN', allow_multiple=True, file_types=file_type_filter(self._label, exts))

    def pick_folder(self, title: str = '') -> Optional[List[str]]:
        return self._run('FOLDER')

    def quit(self) -> None:
        self._quit()


class Shell:
    def __init__(self, webview, url: str, ready: Callable[[float], bool], request_quit: Callable[[], None],
                 is_busy: Callable[[], bool], on_busy_close: Callable[[object], None],
                 startup_timeout: float = STARTUP_TIMEOUT_S, attempts: int = ATTEMPTS, profile_root: Optional[str] = None,
                 title: str = TITLE, file_label: str = 'Files'):
        """ready(timeout) -> True quando la pagina si e' collegata; is_busy() -> coda al lavoro; on_busy_close(window) chiede alla pagina
        (finestra di conferma) cosa fare; request_quit() ferma il server."""
        self.wv, self.url, self._ready, self._request_quit = webview, url, ready, request_quit
        self._is_busy, self._on_busy_close = is_busy, on_busy_close
        self.startup_timeout, self.attempts, self.title, self.file_label = startup_timeout, attempts, title, file_label
        self.profile_root = profile_root or os.path.join(tempfile.gettempdir(), 'tpweb_webview')
        self.window = None
        self.closing_for_good = False
        self.results: List[str] = []            # esito di ogni tentativo: 'ok' | 'timeout' | 'error:...' (per i log e i test)

    # ------------------------------------------------------------------------------------------------------------------------ chiusura
    def _on_closing(self):
        """Evento «closing» di pywebview: False annulla la chiusura. A coda al lavoro decide la persona, dalla pagina."""
        if self.closing_for_good:
            return True
        if self._is_busy():
            self._on_busy_close(self.window)
            return False
        self._request_quit()
        return True

    def close_window(self) -> None:
        """Chiude la finestra senza altre domande (il server sta gia' uscendo)."""
        self.closing_for_good = True
        w = self.window
        if w is not None:
            try:
                w.destroy()
            except Exception:
                logger.debug('chiusura della finestra', exc_info=True)

    # ---------------------------------------------------------------------------------------------------------------------- esecuzione
    def run(self) -> bool:
        """Mostra la finestra finche' non viene chiusa. False se non si e' mai aperta (l'ultimo tentativo e' fallito)."""
        for attempt in range(self.attempts):
            clean = attempt > 0
            profile = None
            if clean:
                profile = os.path.join(self.profile_root, f'profilo_{os.getpid()}_{attempt}')
                shutil.rmtree(profile, ignore_errors=True)
                os.makedirs(profile, exist_ok=True)
            outcome = self._attempt(profile)
            self.results.append(outcome)
            if outcome == 'ok':
                return True
            logger.warning('guscio: tentativo %d fallito (%s)%s', attempt + 1, outcome, ', riprovo con un profilo pulito' if attempt + 1 < self.attempts else '')
        return False

    def _attempt(self, profile: Optional[str]) -> str:
        wv = self.wv
        api = ShellApi(wv, lambda: self.window, self._request_quit_and_close, self.file_label)
        try:
            self.window = wv.create_window(self.title, self.url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=MIN_SIZE, js_api=api)
            self.window.events.closing += self._on_closing
        except Exception as e:
            return f'error:{e}'
        state = {'connected': False}
        stop = threading.Event()

        def watchdog():
            ok = self._ready(self.startup_timeout)
            state['connected'] = ok
            if not ok and not stop.is_set():
                self.close_window()                            # pagina bianca: si chiude per riprovare
        t = threading.Thread(target=watchdog, name='tpweb-shell-watchdog', daemon=True)
        t.start()
        try:
            wv.start(storage_path=profile) if profile else wv.start()
        except Exception as e:
            stop.set()
            return f'error:{e}'
        stop.set()
        t.join(0.5)
        self.closing_for_good = False
        if state['connected']:
            return 'ok'
        return 'timeout'

    def _request_quit_and_close(self) -> None:
        self._request_quit()
        self.close_window()
