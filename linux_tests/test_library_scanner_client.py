# -*- coding: utf-8 -*-
"""core/services/library_scanner_client.py: valori predefiniti del client usato direttamente (i worker passano sempre i propri)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.library_scanner_client import DEFAULT_TIMEOUT, LibraryScannerClient


def test_predefiniti_e_url_senza_barra_finale():
    c = LibraryScannerClient('http://h:1///', 'K')
    assert (c.server_url, c.timeout, c.max_retries, DEFAULT_TIMEOUT) == ('http://h:1', 4, 0, 4)


def test_intestazione_e_timeout_effettivi(monkeypatch):
    import requests
    seen = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'ok': 1}
    monkeypatch.setattr(requests, 'get', lambda url, **k: seen.update(url=url, **k) or R())
    assert LibraryScannerClient('http://h:1/', 'K').get('/api/stats') == {'ok': 1}
    assert seen == {'url': 'http://h:1/api/stats', 'headers': {'X-API-Key': 'K'}, 'params': None, 'timeout': 4}
