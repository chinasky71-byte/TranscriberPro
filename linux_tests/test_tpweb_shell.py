# -*- coding: utf-8 -*-
"""Fase 6a: il guscio nativo con un finto `webview` (la finestra vera e i dialoghi di Windows si provano sulla macchina Windows)."""
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tpweb.shell import Shell, ShellApi, file_type_filter, ATTEMPTS  # noqa: E402
from tpweb import launcher  # noqa: E402


class Ev:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


class FakeWindow:
    def __init__(self, wv):
        self.wv, self.events, self.destroyed = wv, types.SimpleNamespace(closing=Ev()), threading.Event()
        self.dialogs, self.js = [], []

    def destroy(self):
        self.destroyed.set()

    def create_file_dialog(self, kind, **kw):
        self.dialogs.append((kind, kw))
        return self.wv.dialog_result

    def evaluate_js(self, code):
        self.js.append(code)


class FakeWebview:
    """create_window / start come pywebview: start() blocca finche' la finestra non viene distrutta (o `script` decide altro)."""
    OPEN_DIALOG, FOLDER_DIALOG = 10, 20

    def __init__(self, script=None):
        self.windows, self.starts, self.dialog_result = [], [], None
        self.script = script or []                   # per ogni start(): 'close' (finestra chiusa dalla persona) | 'wait' (resta aperta)
        self.create_error = None

    def create_window(self, title, url, **kw):
        if self.create_error:
            raise self.create_error
        w = FakeWindow(self)
        w.title, w.url, w.kw = title, url, kw
        self.windows.append(w)
        return w

    def start(self, **kw):
        self.starts.append(kw)
        w = self.windows[-1]
        action = self.script[len(self.starts) - 1] if len(self.starts) <= len(self.script) else 'wait'
        if action == 'close':
            return
        w.destroyed.wait(5)


def make_shell(wv, ready=lambda t: True, busy=False, **kw):
    log = types.SimpleNamespace(quit=0, asked=[])
    sh = Shell(wv, 'http://127.0.0.1:1/?t=x', ready, lambda: setattr(log, 'quit', log.quit + 1), lambda: busy,
               lambda w: log.asked.append(w), startup_timeout=0.2, **kw)
    return sh, log


def test_filtro_dei_tipi_di_file():
    assert file_type_filter('Video', ['.mp4', 'mkv']) == ('Video (*.mp4;*.mkv)',) and file_type_filter('x', None) == () and file_type_filter('x', []) == ()


def test_dialoghi_nativi_percorsi_e_annulla():
    wv = FakeWebview()
    sh, _ = make_shell(wv)
    sh.window = FakeWindow(wv)
    api = ShellApi(wv, lambda: sh.window, lambda: None, 'Video')
    wv.dialog_result = ('C:\\a.mkv', 'C:\\b.mkv')
    assert api.pick_files('t', ['.mkv']) == ['C:\\a.mkv', 'C:\\b.mkv']
    assert sh.window.dialogs[-1] == (10, {'allow_multiple': True, 'file_types': ('Video (*.mkv)',)})
    wv.dialog_result = None
    assert api.pick_files() is None
    wv.dialog_result = 'C:\\cartella'
    assert api.pick_folder('t') == ['C:\\cartella'] and sh.window.dialogs[-1] == (20, {})
    wv.dialog_result = []
    assert api.pick_folder() is None
    api2 = ShellApi(wv, lambda: None, lambda: None)
    assert api2.pick_files() is None                                  # nessuna finestra: nessun dialogo


def test_dialoghi_con_l_enum_delle_versioni_recenti():
    wv = FakeWebview()
    wv.FileDialog = types.SimpleNamespace(OPEN='open-enum', FOLDER='folder-enum')
    win = FakeWindow(wv)
    wv.dialog_result = ('x',)
    api = ShellApi(wv, lambda: win, lambda: None)
    api.pick_files(); api.pick_folder()
    assert [d[0] for d in win.dialogs] == ['open-enum', 'folder-enum']


def test_avvio_ok_al_primo_tentativo():
    wv = FakeWebview(script=['close'])                                # la persona chiude la finestra dopo l'avvio
    sh, log = make_shell(wv)
    assert sh.run() is True and sh.results == ['ok'] and len(wv.starts) == 1 and wv.starts[0] == {}
    w = wv.windows[0]
    assert (w.title, w.kw['width'], w.kw['height']) == ('Transcriber Pro', 1400, 900) and w.kw['min_size'] == (1000, 650)
    assert isinstance(w.kw['js_api'], ShellApi) and len(w.events.closing.handlers) == 1


def test_pagina_bianca_si_riprova_con_un_profilo_pulito(tmp_path):
    wv = FakeWebview(script=['wait', 'close'])
    calls = {'n': 0}

    def ready(timeout):
        calls['n'] += 1
        return calls['n'] > 1                                         # il primo tentativo non si collega mai
    sh, _ = make_shell(wv, ready=ready, profile_root=str(tmp_path / 'prof'))
    assert sh.run() is True and sh.results == ['timeout', 'ok']
    assert wv.windows[0].destroyed.is_set()                           # il watchdog ha chiuso la finestra bianca
    assert wv.starts[0] == {} and set(wv.starts[1]) == {'storage_path', 'private_mode'} and wv.starts[1]['private_mode'] is False and Path(wv.starts[1]['storage_path']).is_dir()


def test_tutti_i_tentativi_falliti_e_errori_di_creazione(tmp_path):
    wv = FakeWebview(script=['wait'] * ATTEMPTS)
    sh, _ = make_shell(wv, ready=lambda t: False, profile_root=str(tmp_path))
    assert sh.run() is False and sh.results == ['timeout'] * ATTEMPTS and len(wv.starts) == ATTEMPTS
    wv2 = FakeWebview()
    wv2.create_error = RuntimeError('WebView2 mancante')
    sh2, _ = make_shell(wv2, profile_root=str(tmp_path))
    assert sh2.run() is False and sh2.results[0] == 'error:WebView2 mancante' and wv2.starts == []


def test_chiusura_a_coda_libera_chiede_l_uscita_e_a_coda_al_lavoro_chiede_alla_pagina():
    wv = FakeWebview(script=['close'])
    sh, log = make_shell(wv)
    sh.run()
    closing = wv.windows[0].events.closing.handlers[0]
    assert closing() is True and log.quit == 1 and log.asked == []
    wv = FakeWebview(script=['close'])
    sh, log = make_shell(wv, busy=True)
    sh.run()
    closing = wv.windows[0].events.closing.handlers[0]
    assert closing() is False and log.quit == 0
    deadline = time.time() + 2
    while not log.asked and time.time() < deadline:                                       # la domanda parte in un thread a parte
        time.sleep(0.01)
    assert log.asked == [wv.windows[0]]                                                    # la finestra resta aperta: decide la pagina
    sh.close_window()
    assert wv.windows[0].destroyed.is_set() and closing() is True and log.quit == 0       # server gia' in uscita: si chiude e basta


def test_scelta_del_guscio():
    assert launcher.use_shell('off', False, True) is False and launcher.use_shell('on', True, False) is True
    assert launcher.use_shell('auto', False, True) is True and launcher.use_shell('auto', False, False) is False
    assert launcher.use_shell('auto', True, True) is False                          # --no-browser: avvio senza finestre


def test_run_shell_chiusura_della_finestra_ferma_il_server_e_quit_chiude_la_finestra():
    class Srv:
        url = 'http://x'
        queue = types.SimpleNamespace(is_processing=False)
        wait_page = staticmethod(lambda t: True)
    wv = FakeWebview(script=['close'])
    quit_event = threading.Event()
    assert launcher.run_shell(Srv, quit_event, wv) is True and quit_event.is_set()
    wv = FakeWebview()                                                                # finestra aperta: si chiude da /api/quit
    quit_event = threading.Event()
    threading.Timer(0.3, quit_event.set).start()
    assert launcher.run_shell(Srv, quit_event, wv) is True and wv.windows[0].destroyed.is_set()
    bad = FakeWebview()
    bad.create_error = RuntimeError('x')
    assert launcher.run_shell(Srv, threading.Event(), bad) is False                    # si ricade sul browser


def test_il_server_segnala_la_prima_pagina_collegata():
    import httpx
    from tpweb.runner import ServerThread
    s = ServerThread().start()
    try:
        assert s.wait_page(0.2) is False                               # nessuna pagina ancora: il watchdog scadrebbe
        with httpx.Client(base_url=f'http://127.0.0.1:{s.port}', headers={'X-TP-Token': s.token}, timeout=5) as c:
            with c.stream('GET', '/events') as r:
                assert r.status_code == 200
                next(r.iter_lines())
        assert s.wait_page(2.0) is True
    finally:
        s.stop()


def test_la_chiusura_dalla_pagina_non_distrugge_la_finestra_e_destroy_parte_una_volta_sola():
    wv = FakeWebview(script=['close'])
    sh, log = make_shell(wv)
    sh.run()
    api = ShellApi(wv, lambda: wv.windows[0], sh._request_quit_and_close)
    api.quit()
    assert log.quit == 1 and not wv.windows[0].destroyed.is_set()          # destroy() dentro la chiamata JS bloccava la finestra su Windows
    calls = []
    sh.window = types.SimpleNamespace(destroy=lambda: calls.append(1))
    sh.close_window(); sh.close_window()
    assert calls == [1]


def test_run_shell_rete_di_sicurezza_se_la_finestra_non_si_chiude():
    class Srv:
        url = 'http://x'
        queue = types.SimpleNamespace(is_processing=False)
        wait_page = staticmethod(lambda t: True)
    wv = FakeWebview()
    quit_event = threading.Event()
    hit = threading.Event()
    threading.Timer(0.2, quit_event.set).start()
    launcher.run_shell(Srv, quit_event, wv, hard_exit=hit.set, hard_exit_after=0.1)
    assert hit.wait(2)


def test_la_finestra_si_adatta_allo_schermo_e_si_centra():
    from tpweb.shell import fit_window
    scr = lambda w, h: [types.SimpleNamespace(width=w, height=h)]       # noqa: E731
    assert fit_window(scr(1920, 1080)) == (1400, 900, 260, 50)
    assert fit_window(scr(1366, 768)) == (1326, 650, 20, 19)            # altezza minima 650: meglio sporgere che una finestra inutilizzabile
    assert fit_window(scr(1600, 900)) == (1400, 760, 100, 30)
    assert fit_window(None) == (1400, 900, None, None) and fit_window([]) == (1400, 900, None, None)
