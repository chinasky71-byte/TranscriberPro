# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/opensubtitles_settings_widget.py.

Passa identica sul codice vecchio e su quello con la logica in core/services/opensubtitles_settings_service.py: stato e testi,
abilitazione dei controlli, validazione e salvataggio delle due serie di credenziali (.org / .com), metodo API, upload, test di
connessione (uploader finto). Qt offscreen, config temporaneo, finestre di dialogo registrate."""
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
def boxes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    seen = []
    for kind in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda p, t, m, *a, _k=kind, **k: seen.append((_k, t, m)) or 0))
    return seen


def cfg():
    from utils.config import get_config
    return get_config()


def make():
    from gui.opensubtitles_settings_widget import OpenSubtitlesSettingsWidget
    w = OpenSubtitlesSettingsWidget()
    w.emitted = []
    w.settings_changed.connect(lambda: w.emitted.append(1))
    return w


def set_org(u='u', p='p'):
    cfg().set('opensubtitles_preferred_implementation', 'xmlrpc')
    cfg().set('opensubtitles_xmlrpc_username', u)
    cfg().set('opensubtitles_xmlrpc_password', p)


def test_non_configurato(qt):
    from utils.translations import tr
    cfg().set('opensubtitles_preferred_implementation', 'xmlrpc')
    cfg().set('opensubtitles_xmlrpc_username', '')
    w = make()
    assert w.status_label.text() == tr('os_not_configured') + '\n' + tr('os_not_available')
    assert w.credentials_label.text() == tr('os_configure_hint')
    assert not w.upload_enabled_checkbox.isEnabled() and not w.test_btn.isEnabled()


def test_configurato_org(qt):
    from utils.translations import tr
    set_org('mario', 'pw')
    cfg().set('opensubtitles_upload_enabled', False)
    w = make()
    assert w.status_label.text() == tr('os_configured')
    assert w.credentials_label.text() == tr('os_account').format(username='mario')
    assert w.test_btn.isEnabled() and w.upload_enabled_checkbox.isEnabled() and not w.upload_enabled_checkbox.isChecked()
    assert w.xmlrpc_username_input.text() == 'mario' and w.xmlrpc_password_input.text() == 'pw'
    assert w.implementation_combo.currentData() == 'xmlrpc'


def test_configurato_rest_richiede_api_key(qt):
    from utils.translations import tr
    c = cfg()
    c.set('opensubtitles_preferred_implementation', 'rest')
    c.set('opensubtitles_username', 'a')
    c.set('opensubtitles_password', 'b')
    c.set('opensubtitles_api_key', '')
    assert make().status_label.text() != tr('os_configured')
    c.set('opensubtitles_api_key', 'K')
    w = make()
    assert w.status_label.text() == tr('os_configured') and w.credentials_label.text() == tr('os_account').format(username='a')
    assert (w.username_input.text(), w.password_input.text(), w.apikey_input.text()) == ('a', 'b', 'K')


def test_implementazione_sconosciuta_normalizzata(qt):
    cfg().set('opensubtitles_preferred_implementation', 'boh')
    w = make()
    assert cfg().get('opensubtitles_preferred_implementation') == 'xmlrpc' and w.implementation_combo.currentData() == 'xmlrpc'


def test_cambio_metodo_non_tocca_i_campi(qt):
    set_org()
    w = make()
    w.username_input.setText('digitato')
    w.implementation_combo.setCurrentIndex(w.implementation_combo.findData('rest'))
    assert cfg().get('opensubtitles_preferred_implementation') == 'rest' and w.username_input.text() == 'digitato'
    assert w.emitted == [1]


def test_toggle_upload(qt):
    set_org()
    w = make()
    w.upload_enabled_checkbox.setChecked(False)
    assert cfg().get('opensubtitles_upload_enabled') is False and w.emitted == [1]


def test_refresh_from_config_senza_segnali(qt):
    set_org()
    w = make()
    cfg().set('opensubtitles_upload_enabled', False)
    w.refresh_from_config()
    assert not w.upload_enabled_checkbox.isChecked() and w.emitted == []


@pytest.mark.parametrize('u,p', [('', 'p'), ('u', ''), ('  ', 'p')])
def test_salva_com_campi_mancanti(qt, boxes, u, p):
    from utils.translations import tr
    w = make()
    w.username_input.setText(u)
    w.password_input.setText(p)
    w.save_credentials()
    assert boxes == [('warning', tr('os_missing_fields_title'), tr('os_missing_fields_msg'))] and w.emitted == []
    assert cfg().get('opensubtitles_username', '') == ''


def test_salva_com_taglia_e_avvisa(qt, boxes):
    from utils.translations import tr
    w = make()
    w.username_input.setText(' a ')
    w.password_input.setText(' b ')
    w.apikey_input.setText(' k ')
    w.save_credentials()
    assert cfg().get_opensubtitles_credentials()['username'] == 'a'
    assert (cfg().get('opensubtitles_password'), cfg().get('opensubtitles_api_key')) == ('b', 'k')
    assert boxes == [('information', tr('os_creds_saved_title'), tr('os_creds_saved_msg'))] and w.emitted == [1]


def test_salva_org(qt, boxes):
    w = make()
    w.xmlrpc_username_input.setText(' x ')
    w.xmlrpc_password_input.setText(' y ')
    w.save_xmlrpc_credentials()
    assert (cfg().get('opensubtitles_xmlrpc_username'), cfg().get('opensubtitles_xmlrpc_password')) == ('x', 'y')
    assert boxes[0][0] == 'information' and w.emitted == [1]
    w.xmlrpc_password_input.setText('')
    boxes.clear()
    w.save_xmlrpc_credentials()
    assert boxes[0][0] == 'warning' and w.emitted == [1]


class FakeUploader:
    def __init__(self, ok=True, boom=False):
        self.ok, self.boom, self.calls = ok, boom, []

    def authenticate(self):
        if self.boom:
            raise RuntimeError('rete')
        self.calls.append('auth')
        return self.ok

    def logout(self):
        self.calls.append('logout')


def patch_uploader(monkeypatch, up):
    from utils.subtitle_uploader_interface import UploaderFactory
    seen = []
    monkeypatch.setattr(UploaderFactory, 'create_uploader', classmethod(lambda cls, impl, **kw: seen.append((impl, kw)) or up))
    return seen


def test_test_senza_credenziali(qt, boxes, monkeypatch):
    from utils.translations import tr
    cfg().set('opensubtitles_preferred_implementation', 'xmlrpc')
    w = make()
    w.test_connection()
    assert boxes == [('warning', tr('os_missing_creds_title'), tr('os_missing_creds_msg'))]


def test_test_ok_e_logout(qt, boxes, monkeypatch):
    from utils.translations import tr
    set_org('mario', 'pw')
    up = FakeUploader()
    seen = patch_uploader(monkeypatch, up)
    w = make()
    w.test_connection()
    assert seen[0][0] == 'xmlrpc' and seen[0][1]['username'] == 'mario' and seen[0][1]['password'] == 'pw'
    assert up.calls == ['auth', 'logout'] and boxes == [('information', tr('os_test_ok_title'), tr('os_test_ok_msg'))]
    assert w.test_btn.isEnabled() and w.test_btn.text() == tr('os_test_conn')


def test_test_fallito_xmlrpc_aggiunge_suggerimento(qt, boxes, monkeypatch):
    from utils.translations import tr
    set_org()
    patch_uploader(monkeypatch, FakeUploader(ok=False))
    make().test_connection()
    assert boxes == [('critical', tr('os_test_fail_title'), tr('os_test_fail_msg') + '\n\n' + tr('os_xmlrpc_org_com_hint'))]


def test_test_fallito_rest_senza_suggerimento(qt, boxes, monkeypatch):
    from utils.translations import tr
    c = cfg()
    c.set('opensubtitles_preferred_implementation', 'rest')
    for k, v in (('opensubtitles_username', 'a'), ('opensubtitles_password', 'b'), ('opensubtitles_api_key', 'K')):
        c.set(k, v)
    seen = patch_uploader(monkeypatch, FakeUploader(ok=False))
    make().test_connection()
    assert seen[0][0] == 'rest' and boxes == [('critical', tr('os_test_fail_title'), tr('os_test_fail_msg'))]


def test_test_eccezione(qt, boxes, monkeypatch):
    from utils.translations import tr
    set_org()
    patch_uploader(monkeypatch, FakeUploader(boom=True))
    w = make()
    w.test_connection()
    assert boxes == [('critical', tr('os_error_title'), tr('os_error_msg').format(error='rete'))]
    assert w.test_btn.isEnabled() and w.test_btn.text() == tr('os_test_conn')
