# -*- coding: utf-8 -*-
"""core/services/opensubtitles_settings_service.py: cio' che il widget non rende osservabile (valore restituito, ordine dei ganci)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.opensubtitles_settings_service import OpenSubtitlesSettingsService


class Cfg(dict):
    def set(self, k, v):
        self[k] = v

    def is_opensubtitles_configured(self):
        return False

    def get_opensubtitles_xmlrpc_credentials(self):
        return {'username': 'u', 'password': 'p'}


def test_normalizza_implementazione():
    c = Cfg(opensubtitles_preferred_implementation='boh')
    s = OpenSubtitlesSettingsService(c)
    assert s.normalize_implementation() == 'xmlrpc' and c['opensubtitles_preferred_implementation'] == 'xmlrpc'
    c['opensubtitles_preferred_implementation'] = 'rest'
    assert s.normalize_implementation() == 'rest' and c['opensubtitles_preferred_implementation'] == 'rest'


def test_on_start_prima_dell_autenticazione(monkeypatch):
    from utils.subtitle_uploader_interface import UploaderFactory
    order = []

    class Up:
        def authenticate(self):
            order.append('auth')
            return True

        def logout(self):
            order.append('logout')
    monkeypatch.setattr(UploaderFactory, 'create_uploader', classmethod(lambda cls, impl, **kw: order.append('create') or Up()))
    res = OpenSubtitlesSettingsService(Cfg()).test_connection(on_start=lambda: order.append('start'))
    assert res.kind == 'ok' and order == ['create', 'start', 'auth', 'logout']
