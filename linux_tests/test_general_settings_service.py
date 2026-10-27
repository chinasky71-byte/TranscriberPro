# -*- coding: utf-8 -*-
"""core/services/general_settings_service.py: logica delle impostazioni generali, senza Qt."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.general_settings_service import (GeneralSettingsService, language_at, language_index,
                                                    ping_scanner)


class Cfg(dict):
    def __init__(self):
        super().__init__()
        self.writes = []

    def get(self, k, d=None):
        return super().get(k, d)

    def set(self, k, v):
        self.writes.append((k, v))
        self[k] = v


def test_lingua():
    assert [language_index(x) for x in ('auto', 'it', 'en', 'zz', None)] == [0, 1, 2, 0, 0]
    assert [language_at(i) for i in range(3)] == ['auto', 'it', 'en']


def test_scanner_normalizza_e_salva():
    c = Cfg()
    s = GeneralSettingsService(c)
    assert s.language() == 'auto' and s.scanner_url() == '' and s.scanner_api_key() == ''
    assert s.set_scanner_url('  http://x  ') == 'http://x' and s.set_scanner_api_key(' k ') == 'k'
    s.set_language('en')
    assert c['library_scanner_url'] == 'http://x' and c['library_scanner_api_key'] == 'k' and c['language'] == 'en'


def test_mappa_scrive_solo_se_cambia():
    c = Cfg()
    s = GeneralSettingsService(c)
    assert s.set_scanner_path_map('a=/b') is True
    assert s.set_scanner_path_map('a=/b') is False
    assert c.writes == [('library_scanner_path_map', 'a=/b')]


def test_ping(monkeypatch):
    import requests

    class R:
        status_code = 200

        def raise_for_status(self):
            pass
    seen = {}
    monkeypatch.setattr(requests, 'get', lambda u, **k: seen.update(u=u, **k) or R())
    assert ping_scanner('http://h/', 'K') == (True, 'Connesso — HTTP 200')
    assert seen == {'u': 'http://h/api/stats', 'headers': {'X-API-Key': 'K'}, 'timeout': 4}
    monkeypatch.setattr(requests, 'get', lambda *a, **k: (_ for _ in ()).throw(OSError('no')))
    assert ping_scanner('http://h', '') == (False, 'no')
