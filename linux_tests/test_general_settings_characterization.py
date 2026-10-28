# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/general_settings_widget.py::GeneralSettingsWidget.

Descrive il comportamento PRIMA dell'estrazione della logica in core/services/general_settings_service.py: i test passano
identici sul codice vecchio e sul nuovo (chiavi di config scritte, mappatura lingua, richiesta di ping, testi di esito).
Qt offscreen, config temporaneo, rete finta."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    yield app
    cfg.reset_config()


@pytest.fixture
def popups(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: shown.append(a[1:]) or 0))
    return shown


def make():
    from gui.general_settings_widget import GeneralSettingsWidget
    return GeneralSettingsWidget()


def cfg():
    from utils.config import get_config
    return get_config()


def test_valori_iniziali_di_default(qt):
    w = make()
    assert w.lang_combo.currentData() == 'auto' and w.lang_combo.count() == 3
    assert [w.lang_combo.itemData(i) for i in range(3)] == ['auto', 'it', 'en']
    c = cfg()
    assert w.ls_url_edit.text() == c.get('library_scanner_url', '') and w.ls_key_edit.text() == c.get('library_scanner_api_key', '')


@pytest.mark.parametrize('pref,idx', [('auto', 0), ('it', 1), ('en', 2), ('xx', 0)])
def test_lingua_salvata_selezionata_senza_avvisi(qt, popups, pref, idx):
    cfg().set('language', pref)
    w = make()
    assert w.lang_combo.currentIndex() == idx and popups == []


@pytest.mark.parametrize('idx,val', [(1, 'it'), (2, 'en'), (0, 'auto')])
def test_cambio_lingua_scrive_config_e_avvisa(qt, popups, idx, val):
    cfg().set('language', 'it' if val == 'auto' else 'auto')
    w = make()
    w.lang_combo.setCurrentIndex(idx)
    assert cfg().get('language') == val and len(popups) == 1


def test_url_e_chiave_scanner_tagliano_gli_spazi(qt):
    w = make()
    w.ls_url_edit.setText('  http://h:1  ')
    w.ls_url_edit.editingFinished.emit()
    w.ls_key_edit.setText(' k ')
    w.ls_key_edit.editingFinished.emit()
    assert cfg().get('library_scanner_url') == 'http://h:1' and cfg().get('library_scanner_api_key') == 'k'


def test_valori_scanner_caricati(qt):
    cfg().set('library_scanner_url', 'http://a')
    cfg().set('library_scanner_api_key', 'kk')
    w = make()
    assert w.ls_url_edit.text() == 'http://a' and w.ls_key_edit.text() == 'kk'


@pytest.mark.skipif(sys.platform == 'win32', reason='mappa solo fuori da Windows')
def test_mappa_cartelle_scrive_solo_se_cambia(qt, monkeypatch):
    w = make()
    saves = []
    monkeypatch.setattr(type(cfg()), 'set', lambda self, k, v, save=True: saves.append((k, v)))
    w.ls_map_edit.setPlainText('a=/b')
    w.ls_map_edit.setPlainText('a=/b')
    assert saves and all(k == 'library_scanner_path_map' for k, _ in saves) and saves[-1][1] == 'a=/b'


def test_mostra_nascondi_chiave(qt):
    from PyQt6.QtWidgets import QLineEdit
    w = make()
    assert w.ls_key_edit.echoMode() == QLineEdit.EchoMode.Password
    w._show_key_btn.setChecked(True)
    assert w.ls_key_edit.echoMode() == QLineEdit.EchoMode.Normal
    t_hide = w._show_key_btn.text()
    w._show_key_btn.setChecked(False)
    assert w.ls_key_edit.echoMode() == QLineEdit.EchoMode.Password and w._show_key_btn.text() != t_hide


def test_ping_senza_url(qt):
    from utils.translations import tr
    w = make()
    w.ls_url_edit.setText('   ')
    w._test_connection()
    assert w._ping_status.text() == tr('gs_invalid_url') and w._ping_btn.isEnabled()


class _Resp:
    def __init__(self, code=200):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def _run_ping(w, monkeypatch, fn):
    import requests
    calls = []
    monkeypatch.setattr(requests, 'get', lambda *a, **k: calls.append((a, k)) or fn())
    w.ls_url_edit.setText('http://srv:9/')
    w.ls_key_edit.setText('KEY')
    w._test_connection()
    w._ping_worker.wait(5000)
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    return calls


def test_ping_ok(qt, monkeypatch):
    w = make()
    calls = _run_ping(w, monkeypatch, lambda: _Resp(200))
    (args, kw), = calls
    assert args == ('http://srv:9/api/stats',) and kw['headers'] == {'X-API-Key': 'KEY'} and kw['timeout'] == 4
    assert w._ping_status.text() == '✓ Connesso — HTTP 200' and w._ping_btn.isEnabled()


def test_ping_errore(qt, monkeypatch):
    w = make()
    _run_ping(w, monkeypatch, lambda: _Resp(500))
    assert w._ping_status.text() == '✗ HTTP 500' and w._ping_btn.isEnabled()


def test_ping_eccezione_di_rete(qt, monkeypatch):
    def boom():
        raise ConnectionError('giù')
    w = make()
    _run_ping(w, monkeypatch, boom)
    assert w._ping_status.text() == '✗ giù'
