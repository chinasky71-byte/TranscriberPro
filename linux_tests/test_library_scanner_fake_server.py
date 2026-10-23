# -*- coding: utf-8 -*-
"""Library Scanner con un server finto (HTTP locale): mappa "Cartelle montate" (utils/path_map.py) dall'inizio alla fine.

Le parti senza Qt (server finto + mappa) girano ovunque; quelle con Qt (worker, impostazioni, widget) si saltano se PyQt6 manca
e usano `QT_QPA_PLATFORM=offscreen` e un HOME temporaneo (la config e' in ~/.transcriberpro).
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.path_map import parse_map, to_local, to_server  # noqa: E402

BS = chr(92)
KEY = 'chiave-di-prova'
SRV_PATH = BS * 2 + 'srv.example.lan' + BS + 'film' + BS + 'Heat (1995)' + BS + 'Heat.mkv'
MAP_TEXT = BS * 2 + 'srv.example.lan' + BS + 'film=/mnt/film\nV:' + BS + '=/mnt/v'
VIDEOS = [{'id': 1, 'windows_path': SRV_PATH, 'filename': 'Heat.mkv', 'days_without_subs': 3,
           'has_any_italian_sub': False, 'first_seen': '2026-10-01T10:00:00'}]


class _Fake(BaseHTTPRequestHandler):
    notified = []   # corpi ricevuti da notify-subtitle

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        if self.headers.get('X-API-Key') != KEY:
            self._send(401, {'detail': 'API key non valida'})
            return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        if self.path.startswith('/api/stats'):
            self._send(200, {'without_subs': len(VIDEOS), 'total': 10})
        elif self.path.startswith('/api/videos'):
            self._send(200, {'videos': [dict(v) for v in VIDEOS], 'total': len(VIDEOS)})
        elif self.path.startswith('/api/subtitles/list'):
            self._send(200, {'videos': [dict(v, bitmap_format='PGS') for v in VIDEOS]})
        else:
            self._send(404, {})

    def do_POST(self):
        if not self._auth():
            return
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if self.path == '/api/videos/notify-subtitle':
            type(self).notified.append(json.loads(raw))
            self._send(200, {'ok': True})
        else:
            self._send(404, {})


@pytest.fixture
def server(monkeypatch):
    # con HTTP(S)_PROXY impostato (CI, reti aziendali) requests instraderebbe anche 127.0.0.1 verso il proxy (405): localhost si esclude
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
    _Fake.notified = []
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()
    srv.server_close()


# ---- senza Qt ---------------------------------------------------------------------------------------------------------

def test_server_finto_risponde_e_rifiuta_chiave_errata(server):
    ok = requests.get(f'{server}/api/videos', headers={'X-API-Key': KEY}, timeout=4)
    assert ok.status_code == 200 and ok.json()['videos'][0]['windows_path'] == SRV_PATH
    assert requests.get(f'{server}/api/stats', headers={'X-API-Key': 'no'}, timeout=4).status_code == 401


def test_percorso_del_server_diventa_locale_e_torna_uguale_nella_notifica(server):
    rules = parse_map(MAP_TEXT)
    local = to_local(requests.get(f'{server}/api/videos', headers={'X-API-Key': KEY}, timeout=4).json()['videos'][0]['windows_path'], rules)
    assert local == '/mnt/film/Heat (1995)/Heat.mkv'
    r = requests.post(f'{server}/api/videos/notify-subtitle', json={'windows_path': to_server(local, rules)},
                      headers={'X-API-Key': KEY}, timeout=4)
    assert r.status_code == 200 and _Fake.notified == [{'windows_path': SRV_PATH}]   # il server rivede il SUO percorso


# ---- con Qt (offscreen) -----------------------------------------------------------------------------------------------

@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)   # senza Qt o senza librerie di sistema (libEGL): salta
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / '.transcriberpro' / 'config.json', raising=False)   # fissato all'import: senza questo si scrive nel config.json VERO
    cfg.reset_config()
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    cfg.reset_config()


def _wait(app, thread, ms=8000):
    assert thread.wait(ms)
    app.processEvents()   # consegna i segnali in coda


def test_worker_legge_video_e_statistiche(qt, server):
    from gui.library_scanner_worker import LibraryScannerWorker
    got = {}
    w = LibraryScannerWorker(server, KEY, request_type='both')
    w.data_loaded.connect(lambda d: got.__setitem__('data', d))
    w.stats_loaded.connect(lambda d: got.__setitem__('stats', d))
    w.connection_status.connect(lambda ok: got.__setitem__('ok', ok))
    w.start()
    _wait(qt, w)
    assert got['ok'] is True and got['stats']['without_subs'] == 1
    assert got['data']['videos'][0]['windows_path'] == SRV_PATH


def test_worker_chiave_errata_e_server_spento_danno_errore(qt, server):
    from gui.library_scanner_worker import LibraryScannerWorker
    for url, key, atteso in ((server, 'sbagliata', '401'), ('http://127.0.0.1:1', KEY, 'non raggiungibile')):
        errs, st = [], []
        w = LibraryScannerWorker(url, key, request_type='videos')
        w.error.connect(errs.append)
        w.connection_status.connect(st.append)
        w.start()
        _wait(qt, w)
        assert st == [False] and len(errs) == 1 and atteso in errs[0]


def test_impostazioni_campo_cartelle_montate_solo_fuori_da_windows(qt, server):
    from gui.general_settings_widget import GeneralSettingsWidget
    from utils.config import get_config
    w = GeneralSettingsWidget()
    if sys.platform == 'win32':
        assert not hasattr(w, 'ls_map_edit')
        return
    assert hasattr(w, 'ls_map_edit') and w.ls_map_edit.toPlainText() == ''
    w.ls_map_edit.setPlainText(MAP_TEXT)
    assert get_config().get('library_scanner_path_map') == MAP_TEXT          # salvata (e non scartata come "percorso Windows")
    w2 = GeneralSettingsWidget()
    assert w2.ls_map_edit.toPlainText() == MAP_TEXT                           # riletta alla riapertura
    # "Testa connessione" contro il server finto
    w2.ls_url_edit.setText(server)
    w2.ls_key_edit.setText(KEY)
    w2._test_connection()
    _wait(qt, w2._ping_worker)
    assert 'Connesso' in w2._ping_status.text()


class _Win:
    """main_window minimo: coda e lista file, come li usa LibraryScannerWidget._import_paths."""
    def __init__(self, qt_mods):
        from PyQt6.QtCore import QMutex
        self.queue_mutex = QMutex()
        self.processing_queue = []
        self.items = []
        self.logs = []
        outer = self

        class _List:
            def addItem(self, i): outer.items.append(i)
            def count(self): return len(outer.items)
            def setCurrentRow(self, r): pass
        self.file_list = _List()

    def _make_file_item(self, p): return p
    def update_remaining_files_label(self): pass
    def log_message(self, m): self.logs.append(m)


def test_widget_importa_con_percorso_locale_e_notifica_con_percorso_del_server(qt, server):
    if sys.platform == 'win32':
        pytest.skip('la mappa serve fuori da Windows')
    from PyQt6.QtWidgets import QWidget
    from gui import library_scanner_widget as lsw
    from utils.config import get_config
    cfg = get_config()
    cfg.set('library_scanner_url', server)
    cfg.set('library_scanner_api_key', KEY)
    cfg.set('library_scanner_path_map', MAP_TEXT)
    win = _Win(None)
    w = lsw.LibraryScannerWidget(win)
    assert w._import_paths([SRV_PATH]) == 1
    assert win.processing_queue == ['/mnt/film/Heat (1995)/Heat.mkv']
    assert w._import_paths([SRV_PATH]) == 0                                    # niente doppioni
    w.is_loaded = True
    w.notify_subtitle_created(win.processing_queue[0])
    for n in list(w._notify_workers):
        _wait(qt, n)
    assert _Fake.notified == [{'windows_path': SRV_PATH}]
