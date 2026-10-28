# -*- coding: utf-8 -*-
"""Fase 5a: Library Scanner sul server. Client e chiamate API finti (nessuna rete); coda, configurazione e bus veri."""
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from utils.translations import tr  # noqa: E402

VIDEOS = [
    {'id': 1, 'filename': 'Film.Uno.ITA.mkv', 'windows_path': 'V:\\film\\Film.Uno.ITA.mkv', 'media_type': 'movie', 'days_without_subs': 40,
     'bitmap_format': 'pgs', 'has_only_bitmap_subs': True},
    {'id': 2, 'filename': 'Serie.S01E01.mkv', 'windows_path': 'V:\\serie\\Serie.S01E01.mkv', 'media_type': 'tvshow', 'days_without_subs': 20,
     'bitmap_format': 'vobsub', 'has_only_bitmap_subs': True},
    {'id': 3, 'filename': 'Altro.mkv', 'windows_path': 'V:\\film\\Altro.mkv', 'media_type': 'movie', 'days_without_subs': 3,
     'bitmap_format': 'mixed', 'has_only_bitmap_subs': True},
    {'id': 4, 'filename': 'Con.Ass.mkv', 'windows_path': 'V:\\film\\Con.Ass.mkv', 'media_type': 'movie', 'days_without_subs': 10,
     'bitmap_format': None, 'has_italian_convertible_subs': True, 'conversion_status': 'done'},
    {'id': 5, 'filename': 'Pgs.Con.Testo.mkv', 'windows_path': 'V:\\film\\Pgs.Con.Testo.mkv', 'media_type': 'movie', 'days_without_subs': 15,
     'bitmap_format': 'pgs', 'has_only_bitmap_subs': False},
    {'id': 6, 'filename': 'Nessuna.mkv', 'windows_path': 'V:\\film\\Nessuna.mkv', 'media_type': 'movie', 'days_without_subs': 0, 'bitmap_format': None},
]


class FakeClient:
    calls, notified, fail = [], [], False

    def __init__(self, url, key):
        self.url, self.key = url, key

    def stats(self):
        if FakeClient.fail:
            raise ConnectionError('Server non raggiungibile: x')
        return {'without_subs': 6, 'total_files': 100}

    def videos(self, search='', media_type='', format_filter=''):
        FakeClient.calls.append((search, media_type, format_filter))
        return {'videos': [dict(v) for v in VIDEOS]}

    def notify_subtitle(self, windows_path):
        FakeClient.notified.append(windows_path)
        return True


class FakeApi:
    calls, reply = [], (200, '{}')

    def __call__(self, method, url, key, json_body=None, params=None, timeout=10):
        FakeApi.calls.append((method, url, key, json_body, timeout))
        return FakeApi.reply


@pytest.fixture
def srv(tmp_path, monkeypatch):
    FakeClient.calls, FakeClient.notified, FakeClient.fail = [], [], False
    FakeApi.calls, FakeApi.reply = [], (200, '{}')
    s, config = e2e.make_server(tmp_path, monkeypatch, library_deps={'client': FakeClient, 'api': FakeApi()})
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    c.srv, c.config, c.tmp = s, config, tmp_path
    yield c
    c.close()
    s.queue.stop(); s.queue.join(20)
    s.stop()


def clear_credentials(c):
    """La configurazione predefinita ha gia' un URL e una chiave: la prova «non configurato» li svuota."""
    c.config.set('library_scanner_url', '', save=False)
    c.config.set('library_scanner_api_key', '', save=False)


def configure(c, map_text=''):
    c.config.set('library_scanner_url', 'http://scanner:6680', save=False)
    c.config.set('library_scanner_api_key', 'k' * 24, save=False)
    c.config.set('library_scanner_path_map', map_text, save=False)


def test_senza_configurazione(srv):
    c = srv
    clear_credentials(c)
    r = c.get('/api/library').json()
    assert r['connected'] is False and r['error'] == 'config_missing' and r['rows'] == [] and r['import_enabled'] is False


def test_righe_badge_colori_e_statistiche(srv):
    c = srv
    configure(c)
    r = c.get('/api/library', params={'search': ' x ', 'type': 'movie', 'format': ''}).json()
    assert FakeClient.calls == [('x', 'movie', '')] and r['connected'] is True and r['error'] == ''
    assert r['stats_text'] == tr('files_stats').format(without=6, total=100) and r['without'] == 6 and r['visible'] == 6
    by = {x['id']: x for x in r['rows']}
    assert [by[i]['badge'] for i in range(1, 7)] == ['bitmap', 'bitmap', 'bitmap', 'ass', None, None]
    assert [(by[i]['badge_label'], by[i]['ocr_kind']) for i in (1, 2, 3)] == [('PGS', 'pgs'), ('VOB', 'vobsub'), ('MIX', 'pgs')]
    assert [by[i]['days_class'] for i in range(1, 7)] == ['danger', 'warn', None, None, 'warn', None]
    assert by[1]['audio_ita'] is True and by[2]['audio_ita'] is False and by[4]['ass_done'] is True and by[3]['ass_done'] is False


def test_filtri_giorni_e_formato_senza_ricaricare(srv):
    c = srv
    configure(c)
    c.get('/api/library')
    n = len(FakeClient.calls)
    hid = lambda **p: sorted(x['id'] for x in c.get('/api/library/view', params=p).json()['rows'] if not x['hidden'])      # noqa: E731
    assert hid(min_days=0) == [1, 2, 3, 4, 5, 6]
    assert hid(min_days=15) == [1, 2, 5]
    assert hid(format='pgs') == [1, 3]                      # solo bitmap che servono davvero OCR; «mixed» vale per entrambi
    assert hid(format='vobsub') == [2, 3]
    assert hid(format='assssa') == [4]
    assert hid(format='nosrt') == [4, 6]                    # nessuna traccia sottotitoli bitmap
    v = c.get('/api/library/view', params={'format': 'assssa'}).json()
    assert v['import_is_ass'] is True and v['visible'] == 1 and v['import_enabled'] is True
    assert c.get('/api/library/view', params={'min_days': 999}).json()['import_enabled'] is False
    assert len(FakeClient.calls) == n                        # i filtri locali non toccano il server
    c.get('/api/library', params={'format': 'assssa'})
    assert FakeClient.calls[-1][2] == 'assssa'               # ASS/SSA e' un altro endpoint: il formato arriva al client


def test_errore_di_rete(srv):
    c = srv
    configure(c)
    FakeClient.fail = True
    r = c.get('/api/library').json()
    assert r['connected'] is False and r['error'] == 'Server non raggiungibile: x'


def test_import_con_mappa_dei_percorsi_senza_doppioni_e_con_log(srv):
    c = srv
    configure(c, 'V:\\=/mnt/v')
    c.get('/api/library')
    q = c.srv.queue
    q.compact = False
    r = c.post('/api/library/import', json={'paths': ['V:\\film\\Altro.mkv', 'V:\\film\\Altro.mkv', ''], 'log': True}).json()
    assert r == {'added': 1} and q.queue.snapshot() == ['/mnt/v/film/Altro.mkv']
    assert c.post('/api/library/import', json={'paths': ['V:\\film\\Altro.mkv']}).json() == {'added': 0}          # gia' in coda
    q.queue.take_next(); q.on_file_started('/mnt/v/film/Altro.mkv')
    assert c.post('/api/library/import', json={'paths': ['V:\\film\\Altro.mkv']}).json() == {'added': 0}          # in lavorazione
    assert any(tr('files_imported_log').format(added=1) in l['text'] for l in q.log.lines)
    rows = {x['id']: x for x in c.get('/api/library/view').json()['rows']}
    assert rows[3]['queued'] is False                         # il file in lavorazione non e' piu' in coda: come la GUI
    c.post('/api/library/import', json={'paths': ['V:\\film\\Uno.mkv']})
    assert c.get('/api/library/view').json()['rows'][0]['queued'] is False


def test_conversione_ass_messaggi_come_la_gui(srv):
    c = srv
    c.srv.queue.compact = False
    clear_credentials(c)
    r = c.post('/api/library/ass', json={'video_ids': [4]}).json()
    assert r == {'level': 'warning', 'title_key': 'ls_ass_title', 'message': tr('ls_not_configured')} and FakeApi.calls == []
    configure(c)
    r = c.post('/api/library/ass', json={'video_ids': [4, 5]}).json()
    assert r['level'] == 'information' and r['message'] == tr('ls_ass_started_body').format(desc=tr('ls_n_files').format(n=2))
    assert FakeApi.calls[-1][:4] == ('post', 'http://scanner:6680/api/subtitles/convert/start', 'k' * 24, {'video_ids': [4, 5]})
    r = c.post('/api/library/ass', json={'video_ids': []}).json()
    assert FakeApi.calls[-1][3] == {} and r['message'] == tr('ls_ass_started_body').format(desc=tr('ls_all_pending'))
    FakeApi.reply = (0, 'timeout')
    assert c.post('/api/library/ass', json={}).json()['message'] == tr('ls_conn_err').format(text='timeout')
    FakeApi.reply = (500, 'x' * 300)
    assert c.post('/api/library/ass', json={}).json()['message'] == tr('ls_srv_err').format(status=500, text='x' * 200)
    assert any(tr('ls_ass_log_srv_err').format(status=500) in l['text'] for l in c.srv.queue.log.lines)


def test_notifica_al_server_solo_dopo_il_primo_caricamento(srv):
    c = srv
    configure(c, 'V:\\=/mnt/v')
    c.srv.queue.on_file_completed('/mnt/v/film/Altro.mkv')
    c.srv.app.state.library.join(5)
    assert FakeClient.notified == []                          # elenco mai caricato: nessuna notifica (come la GUI)
    c.get('/api/library')
    seq = c.srv.bus.last_seq
    kinds = lambda: [e['k'] for e in c.srv.bus.since(seq)[0]]      # noqa: E731
    c.srv.queue.on_file_completed('/mnt/v/film/Altro.mkv')
    c.srv.app.state.library.join(5)
    assert FakeClient.notified == ['V:\\film\\Altro.mkv'] and 'library_changed' in kinds()      # la pagina ricarica l'elenco
    seq = c.srv.bus.last_seq
    c.srv.app.state.library.batch_active = True                    # durante un batch si ricarica una volta sola, a fine batch
    c.srv.queue.on_file_completed('/mnt/v/film/Altro.mkv')
    c.srv.app.state.library.join(5)
    assert len(FakeClient.notified) == 2 and 'library_changed' not in kinds()


def test_scheda_aperta_e_abilitata(srv):
    c = srv
    assert c.get('/api/library/state').json() == {'enabled': True, 'open': False}
    assert c.put('/api/library/card', json={'open': True}).json()['open'] is True
    c.config.set('library_scanner_enabled', False, save=False)
    assert c.get('/api/library/state').json() == {'enabled': False, 'open': True}
