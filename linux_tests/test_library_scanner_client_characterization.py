# -*- coding: utf-8 -*-
"""G4a (fase 0 della web UI): CARATTERIZZAZIONE dei worker HTTP del Library Scanner (gui/library_scanner_worker.py e
_NotifyWorker/_ApiCallWorker di gui/library_scanner_widget.py).

Passa identica sul codice vecchio e su quello con il client in core/services/library_scanner_client.py: richieste (metodo, percorso,
parametri, intestazione X-API-Key, corpo), segnali e loro ordine, normalizzazione dell'endpoint ASS/SSA, messaggi d'errore, retry,
timeout. Il server e' un finto HTTP in-process (linux_tests/library_scanner_fake_server.py)."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        monkeypatch.delenv(k, raising=False)
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def srv():
    from library_scanner_fake_server import FakeLibraryScanner
    s = FakeLibraryScanner()
    yield s
    s.close()


def run(qt, w, signals):
    from PyQt6.QtCore import Qt
    ev = []
    for sig in signals:
        getattr(w, sig).connect(lambda *a, _s=sig: ev.append((_s, a)), Qt.ConnectionType.DirectConnection)
    w.start()
    assert w.wait(30000)
    qt.processEvents()
    return ev


SIGS = ('data_loaded', 'stats_loaded', 'error', 'connection_status')
VIDEOS = {'videos': [{'id': 1, 'filename': 'a.mkv', 'windows_path': r'V:\a.mkv'}], 'total': 1}
STATS = {'total_files': 10, 'without_subs': 3}


def worker(url, **kw):
    from gui.library_scanner_worker import LibraryScannerWorker
    return LibraryScannerWorker(server_url=url, api_key='KEY', **kw)


def test_both_ordine_dei_segnali_e_richieste(qt, srv):
    srv.route('GET', '/api/stats', STATS)
    srv.route('GET', '/api/videos', VIDEOS)
    ev = run(qt, worker(srv.url + '/', search='casa', media_type='movie'), SIGS)
    assert ev == [('stats_loaded', (STATS,)), ('data_loaded', (VIDEOS,)), ('connection_status', (True,))]
    (m1, p1, q1, h1, b1), (m2, p2, q2, h2, b2) = srv.requests
    assert (m1, p1, q1, h1['x-api-key'], b1) == ('GET', '/api/stats', {}, 'KEY', None)
    assert (m2, p2) == ('GET', '/api/videos')
    assert q2 == {'no_subs_only': 'true', 'limit': '500', 'offset': '0', 'sort_by': 'first_seen', 'sort_order': 'desc',
                  'search': 'casa', 'media_type': 'movie'}


def test_videos_senza_filtri_opzionali(qt, srv):
    srv.route('GET', '/api/videos', VIDEOS)
    ev = run(qt, worker(srv.url, request_type='videos'), SIGS)
    assert ev == [('data_loaded', (VIDEOS,)), ('connection_status', (True,))]
    assert srv.requests[0][2] == {'no_subs_only': 'true', 'limit': '500', 'offset': '0', 'sort_by': 'first_seen', 'sort_order': 'desc'}


def test_solo_stats(qt, srv):
    srv.route('GET', '/api/stats', STATS)
    ev = run(qt, worker(srv.url, request_type='stats'), SIGS)
    assert ev == [('stats_loaded', (STATS,)), ('connection_status', (True,))] and len(srv.requests) == 1


def test_filtro_ass_usa_l_endpoint_dedicato_e_normalizza(qt, srv):
    srv.route('GET', '/api/subtitles/list', {'videos': [{'id': 1}, {'id': 2, 'days_without_subs': 9, 'has_any_italian_sub': False,
                                                                    'first_seen': '2026-01-01'}]})
    ev = run(qt, worker(srv.url, request_type='videos', format_filter='assssa', search='ignorata', media_type='tvshow'), SIGS)
    data = ev[0][1][0]
    assert data['videos'][0] == {'id': 1, 'days_without_subs': 0, 'has_any_italian_sub': True, 'first_seen': None}
    assert data['videos'][1] == {'id': 2, 'days_without_subs': 9, 'has_any_italian_sub': False, 'first_seen': '2026-01-01'}
    assert srv.requests[0][1:3] == ('/api/subtitles/list', {'issue_type': 'convertible', 'limit': '500', 'offset': '0'})


def test_altri_filtri_formato_usano_l_endpoint_normale(qt, srv):
    srv.route('GET', '/api/videos', VIDEOS)
    run(qt, worker(srv.url, request_type='videos', format_filter='pgs'), SIGS)
    assert srv.requests[0][1] == '/api/videos'


@pytest.mark.parametrize('status', [401, 500])
def test_errore_http(qt, srv, status):
    srv.route('GET', '/api/stats', {'e': 1}, status=status)
    ev = run(qt, worker(srv.url), SIGS)
    assert ev == [('connection_status', (False,)), ('error', (f'Errore HTTP: {status}',))] and len(srv.requests) == 1


def test_errore_http_non_ritenta_neppure_con_retry(qt, srv):
    srv.route('GET', '/api/stats', {}, status=500)
    w = worker(srv.url)
    w.max_retries = 3
    run(qt, w, SIGS)
    assert len(srv.requests) == 1


def test_server_non_raggiungibile(qt):
    url = 'http://127.0.0.1:1'
    ev = run(qt, worker(url), SIGS)
    assert ev == [('connection_status', (False,)), ('error', (f'Server non raggiungibile: {url}',))]


def test_retry_su_connessione_rifiutata(qt, monkeypatch):
    import requests
    calls = []
    real = requests.get
    monkeypatch.setattr(requests, 'get', lambda *a, **k: calls.append(1) or real(*a, **k))
    w = worker('http://127.0.0.1:1')
    w.max_retries = 2
    run(qt, w, SIGS)
    assert len(calls) == 3


def test_timeout(qt, srv):
    srv.route('GET', '/api/stats', STATS, delay=1.5)
    w = worker(srv.url)
    w.timeout = 0.3
    ev = run(qt, w, SIGS)
    assert ev[0] == ('connection_status', (False,)) and ev[1][0] == 'error'
    assert ev[1][1][0] in ('Timeout connessione (0.3s)', f'Server non raggiungibile: {srv.url}')      # ReadTimeout -> Timeout


def test_risposta_non_json(qt, srv):
    srv.route('GET', '/api/stats', b'non json')
    ev = run(qt, worker(srv.url), SIGS)
    assert ev[0] == ('connection_status', (False,)) and ev[1][0] == 'error' and ev[1][1][0].startswith('Errore: ')


def test_timeout_predefinito_e_attributi(qt):
    w = worker('http://h:1/')
    assert (w.server_url, w.api_key, w.request_type, w.search, w.media_type, w.format_filter, w.timeout, w.max_retries) == \
        ('http://h:1', 'KEY', 'both', '', '', '', 4, 0)


# ------------------------------------------------------------------------------------------ _NotifyWorker / _ApiCallWorker
def test_notifica_sottotitolo(qt, srv):
    from gui.library_scanner_widget import _NotifyWorker
    srv.route('POST', '/api/videos/notify-subtitle', {'ok': True})
    ev = run(qt, _NotifyWorker(srv.url + '/', 'KEY', r'V:\Film\a.mkv'), ('done',))
    assert ev == [('done', (True,))]
    m, p, q, h, body = srv.requests[0]
    assert (m, p, body, h['x-api-key']) == ('POST', '/api/videos/notify-subtitle', {'windows_path': r'V:\Film\a.mkv'}, 'KEY')
    srv.route('POST', '/api/videos/notify-subtitle', {}, status=500)
    assert run(qt, _NotifyWorker(srv.url, 'KEY', 'x'), ('done',)) == [('done', (False,))]
    srv.route('POST', '/api/videos/notify-subtitle', {}, status=201)
    assert run(qt, _NotifyWorker(srv.url, 'KEY', 'x'), ('done',)) == [('done', (False,))]          # solo 200 e' successo
    assert run(qt, _NotifyWorker('http://127.0.0.1:1', 'KEY', 'x'), ('done',)) == [('done', (False,))]


def test_chiamata_api_generica(qt, srv):
    from gui.library_scanner_widget import _ApiCallWorker
    srv.route('POST', '/api/convert', {'n': 2}, status=202)
    ev = run(qt, _ApiCallWorker('POST', srv.url + '/api/convert', 'KEY', json_body={'video_ids': [1, 2]}, params={'a': '1'}), ('done',))
    status, text = ev[0][1]
    assert status == 202 and '"n": 2' in text
    m, p, q, h, body = srv.requests[0]
    assert (m, p, q, body, h['x-api-key']) == ('POST', '/api/convert', {'a': '1'}, {'video_ids': [1, 2]}, 'KEY')
    srv.route('GET', '/api/x', {'e': 1}, status=404)
    ev = run(qt, _ApiCallWorker('GET', srv.url + '/api/x', 'KEY'), ('done',))
    assert ev[0][1][0] == 404                                  # lo stato HTTP d'errore NON e' un'eccezione
    ev = run(qt, _ApiCallWorker('GET', 'http://127.0.0.1:1/x', 'KEY'), ('done',))
    assert ev[0][1][0] == 0 and ev[0][1][1]                    # errore di connessione: (0, messaggio)


def test_chiamata_api_timeout_passato(qt, srv, monkeypatch):
    import requests
    from gui.library_scanner_widget import _ApiCallWorker
    seen = {}
    monkeypatch.setattr(requests, 'request', lambda method, url, **k: seen.update(m=method, u=url, **k) or type('R', (), {'status_code': 200, 'text': 'ok'})())
    run(qt, _ApiCallWorker('GET', 'http://h/x', 'K', timeout=15), ('done',))
    assert seen['timeout'] == 15 and seen['headers'] == {'X-API-Key': 'K'} and seen['json'] is None and seen['params'] is None


def test_timeout_della_notifica_e_predefinito_della_chiamata(qt, monkeypatch):
    import requests
    from gui.library_scanner_widget import _ApiCallWorker, _NotifyWorker
    seen = {}
    monkeypatch.setattr(requests, 'post', lambda url, **k: seen.update(post=k) or type('R', (), {'status_code': 200})())
    monkeypatch.setattr(requests, 'request', lambda m, url, **k: seen.update(req=k) or type('R', (), {'status_code': 200, 'text': ''})())
    run(qt, _NotifyWorker('http://h/', 'K', 'p'), ('done',))
    run(qt, _ApiCallWorker('GET', 'http://h/x', 'K'), ('done',))
    assert seen['post']['timeout'] == 10 and seen['req']['timeout'] == 10
