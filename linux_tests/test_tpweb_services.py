# -*- coding: utf-8 -*-
"""Endpoint di cronologia, impostazioni e navigatore dei file (fette 1c e 1d) e aggiunte alla coda (scansione, dimensioni,
spegnimento, salvataggio della cronologia). Config e cronologia isolate in una cartella temporanea."""
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _queue_testkit as kit  # noqa: E402
from core.jobs.engine import QueueEngine  # noqa: E402
from core.services.history_service import HistoryService  # noqa: E402
from tpweb.events import EventBus  # noqa: E402
from tpweb.queue_backend import WebQueue  # noqa: E402
from tpweb.runner import ServerThread  # noqa: E402

ENTRIES = [
    {'name': 'Film Uno', 'date_iso': '2026-10-27T21:05:09', 'src_lang': 'eng', 'dst_lang': 'ita', 'duration_seconds': 3725,
     'size_bytes': 1536, 'srt_path': '/v/uno.srt', 'video_path': '/v/uno.mkv'},
    {'name': 'Serie Due', 'date_iso': '2026-10-28T08:00:00', 'src_lang': 'auto', 'dst_lang': '', 'duration_seconds': 65,
     'size_bytes': 5 * 1024 ** 3},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    config = cfg.get_config()
    hist = HistoryService(tmp_path / 'hist' / 'history.json')
    hist.path.parent.mkdir()
    hist.path.write_text(json.dumps(ENTRIES), encoding='utf-8')
    opened = []
    spy = kit.PopenSpy()
    monkeypatch.setattr(subprocess, 'Popen', spy)
    bus = EventBus()
    shutdowns = []
    flag = {'on': False}
    wq = WebQueue(bus, engine_factory=lambda w: QueueEngine(w.queue, w, cleanup_caches=False, project_root=ROOT),
                  history=hist, shutdown_enabled=lambda: flag['on'], shutdown_fn=lambda: shutdowns.append(1), shutdown_delay_s=0.05)
    s = ServerThread(bus=bus, queue=wq, history=hist, config=config, opener=opened.append,
                     mapped_roots=lambda: ['/mnt/media']).start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    e = type('E', (), dict(c=c, wq=wq, hist=hist, opened=opened, config=config, shutdowns=shutdowns, flag=flag,
                           cfgfile=cfg.Config.CONFIG_FILE, tmp=tmp_path))
    yield e
    wq.stop()
    wq.join(20)
    c.close()
    s.stop()
    cfg.reset_config()


def wait_for(cond, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------------------------------------- cronologia
def test_cronologia_celle_e_statistiche_come_la_gui(env):
    r = env.c.get('/api/history').json()
    assert r['stats'] == {'total': 2, 'size_text': '5.0 GB', 'time_text': '1h 03m'}
    a, b = r['rows']
    assert (a['name'], a['date'], a['language'], a['duration'], a['size']) == ('Film Uno', '2026-10-27 21:05', 'eng→ita', '1h 02m 05s', '2 KB')
    assert (b['language'], b['duration'], b['size'], b['has_srt'], b['has_folder']) == ('auto', '1m 05s', '5 GB', False, False)
    assert (a['has_srt'], a['has_folder'], a['index']) == (True, True, 0)


def test_cronologia_ricerca_su_nome_e_lingua(env):
    assert [r['name'] for r in env.c.get('/api/history', params={'q': ' serie '}).json()['rows']] == ['Serie Due']
    assert [r['name'] for r in env.c.get('/api/history', params={'q': 'ENG→'}).json()['rows']] == ['Film Uno']
    assert len(env.c.get('/api/history', params={'q': 'zzz'}).json()['rows']) == 0


def test_cronologia_apri_solo_percorsi_della_cronologia(env):
    assert env.c.post('/api/history/open', json={'index': 0, 'what': 'srt'}).json() == {'opened': '/v/uno.srt'}
    assert env.c.post('/api/history/open', json={'index': 0, 'what': 'folder'}).json() == {'opened': '/v'}
    assert env.opened == [str(Path('/v/uno.srt')), str(Path('/v'))]
    assert env.c.post('/api/history/open', json={'index': 1, 'what': 'srt'}).status_code == 409
    assert env.c.post('/api/history/open', json={'index': 9, 'what': 'srt'}).status_code == 404
    assert env.c.post('/api/history/open', json={'index': -1, 'what': 'srt'}).status_code == 404
    assert env.c.post('/api/history/open', json={'index': 0, 'what': '/etc/passwd'}).status_code == 422
    assert len(env.opened) == 2


def test_cronologia_si_aggiorna_dal_file_e_la_coda_salva_le_voci(env):
    vids = kit.make_videos(env.tmp, 'a.mkv')
    env.wq.add(vids)
    env.wq.start()
    env.wq.join(60)
    saved = json.loads(env.hist.path.read_text(encoding='utf-8'))
    assert len(saved) == 3 and saved[-1]['name'] and saved[:2] == ENTRIES
    r = env.c.get('/api/history').json()
    assert r['stats']['total'] == 3 and len(r['rows']) == 3


# ------------------------------------------------------------------------------------------------------- impostazioni
def test_impostazioni_lettura_iniziale(env):
    s = env.c.get('/api/settings').json()
    assert s['general']['language'] == 'auto' and s['general']['languages'] == ['auto', 'it', 'en']
    assert s['job_options']['target_language'] == 'ita' and s['adaptive_batch']['max_size'] == 24
    assert s['ocr']['workers'] >= 0 and s['opensubtitles']['implementation'] == 'xmlrpc'


def test_impostazioni_scrittura_parziale_e_persistenza_su_disco(env):
    assert env.c.put('/api/settings/general', json={'language': 'en', 'scanner_url': ' http://nas:8000 '}).json()['language'] == 'en'
    assert env.c.put('/api/settings/job_options', json={'target_language': 'eng', 'mux_into_video': True}).json()['mux_into_video'] is True
    on_disk = json.loads(env.cfgfile.read_text(encoding='utf-8'))
    assert on_disk['language'] == 'en' and on_disk['library_scanner_url'] == 'http://nas:8000'
    assert on_disk['target_language'] == 'eng' and on_disk['mux_subtitle_into_video'] is True
    # un campo non inviato non cambia
    assert env.c.get('/api/settings').json()['general']['scanner_url'] == 'http://nas:8000'


def test_chiavi_e_password_non_escono_mai(env):
    env.c.put('/api/settings/general', json={'scanner_api_key': 'SEGRETISSIMA-CHIAVE'})
    env.c.put('/api/settings/opensubtitles/com', json={'username': 'u1', 'password': 'PW-COM-SEGRETA', 'api_key': 'KEY-OS-SEGRETA'})
    env.c.put('/api/settings/opensubtitles/org', json={'username': 'u2', 'password': 'PW-ORG-SEGRETA'})
    everything = env.c.get('/api/settings').text + env.c.get('/api/state').text + env.c.get('/api/queue').text
    for secret in ('SEGRETISSIMA-CHIAVE', 'PW-COM-SEGRETA', 'KEY-OS-SEGRETA', 'PW-ORG-SEGRETA'):
        assert secret not in everything
    g = env.c.get('/api/settings').json()
    assert g['general']['scanner_api_key_set'] is True and 'scanner_api_key' not in g['general']
    o = g['opensubtitles']
    assert (o['com_username'], o['org_username'], o['com_password_set'], o['org_password_set'], o['com_api_key_set']) == ('u1', 'u2', True, True, True)
    assert env.config.get('library_scanner_api_key') == 'SEGRETISSIMA-CHIAVE'


def test_credenziali_opensubtitles_vuote_rifiutate_senza_scrivere(env):
    r = env.c.put('/api/settings/opensubtitles/com', json={'username': ' ', 'password': 'x'})
    assert r.status_code == 422 and env.c.get('/api/settings').json()['opensubtitles']['com_password_set'] is False
    assert env.c.put('/api/settings/opensubtitles/org', json={'username': 'u', 'password': ''}).status_code == 422


@pytest.mark.parametrize('section,body', [
    ('general', {'language': 'fr'}), ('job_options', {'target_language': ''}),
    ('adaptive_batch', {'min_size': 0}), ('adaptive_batch', {'min_size': 17}), ('adaptive_batch', {'max_size': 65}),
    ('adaptive_batch', {'initial_size': 65}), ('adaptive_batch', {'warmup_batches': 21}),
    ('adaptive_batch', {'high_threshold': 0.49}), ('adaptive_batch', {'high_threshold': 1.01}),
    ('adaptive_batch', {'low_threshold': 0.09}), ('adaptive_batch', {'low_threshold': 0.91}),
    ('ocr', {'conf_threshold': 101}), ('ocr', {'conf_threshold': -1}), ('ocr', {'workers': 33}),
    ('ocr', {'writeback': 'altro'}), ('ocr', {'strategy': 'boh'}), ('opensubtitles', {'implementation': 'soap'})])
def test_valori_fuori_dai_limiti_della_gui_rifiutati(env, section, body):
    before = env.c.get('/api/settings').json()
    assert env.c.put(f'/api/settings/{section}', json=body).status_code == 422
    assert env.c.get('/api/settings').json() == before


@pytest.mark.parametrize('section,body', [
    ('adaptive_batch', {'min_size': 16, 'max_size': 64, 'initial_size': 64, 'warmup_batches': 20, 'high_threshold': 1.0, 'low_threshold': 0.1}),
    ('adaptive_batch', {'min_size': 1, 'max_size': 1, 'initial_size': 0, 'warmup_batches': 0, 'high_threshold': 0.5, 'low_threshold': 0.9}),
    ('ocr', {'conf_threshold': 0, 'workers': 0}), ('ocr', {'conf_threshold': 100, 'workers': 32})])
def test_valori_ai_limiti_accettati(env, section, body):
    r = env.c.put(f'/api/settings/{section}', json=body)
    assert r.status_code == 200 and all(r.json()[k] == v for k, v in body.items())


def test_batch_adattivo_scrive_tutte_le_chiavi_e_si_ripristina(env):
    r = env.c.put('/api/settings/adaptive_batch', json={'enabled': False, 'max_size': 32}).json()
    assert r['enabled'] is False and r['max_size'] == 32 and r['min_size'] == 1 and r['status_text']
    on_disk = json.loads(env.cfgfile.read_text(encoding='utf-8'))
    assert on_disk['adaptive_batch_enabled'] is False and on_disk['adaptive_batch_max_size'] == 32
    assert env.c.put('/api/settings/adaptive_batch', json={'min_size': 3, 'low_threshold': 0.4}).json()['max_size'] == 32
    r2 = env.c.put('/api/settings/adaptive_batch', json={'warmup_batches': 7}).json()          # i campi non inviati restano quelli salvati
    assert (r2['min_size'], r2['low_threshold'], r2['max_size'], r2['enabled']) == (3, 0.4, 32, False)
    d = env.c.post('/api/settings/adaptive_batch/reset').json()
    assert (d['enabled'], d['max_size'], d['min_size'], d['warmup_batches'], d['high_threshold'], d['low_threshold']) == (True, 24, 1, 5, 0.85, 0.6)


def test_ocr_scrittura(env):
    tess = str(env.tmp / 'bin' / 'tesseract')              # un percorso con lettera di unita' non si legge su Linux (config copiata)
    r = env.c.put('/api/settings/ocr', json={'strategy': 'auto', 'language': ' ita+eng ', 'writeback': 'sidecar',
                                              'tesseract_path': f' {tess} '}).json()
    assert (r['strategy'], r['language'], r['writeback'], r['tesseract_path']) == ('auto', 'ita+eng', 'sidecar', tess)
    assert env.c.put('/api/settings/ocr', json={'language': '  '}).json()['language'] != ''


def test_ping_scanner_usa_chiave_salvata_e_non_la_mostra(env, monkeypatch):
    calls = []
    import tpweb.routes_settings as rs
    monkeypatch.setattr(rs, 'ping_scanner', lambda url, key: calls.append((url, key)) or (True, 'Connesso — HTTP 200'))
    env.c.put('/api/settings/general', json={'scanner_url': 'http://nas:8000', 'scanner_api_key': 'K1'})
    assert env.c.post('/api/settings/general/ping', json={}).json() == {'ok': True, 'message': 'Connesso — HTTP 200'}
    assert env.c.post('/api/settings/general/ping', json={'url': 'http://altro', 'api_key': 'K2'}).json()['ok'] is True
    assert calls == [('http://nas:8000', 'K1'), ('http://altro', 'K2')]


def test_test_connessione_opensubtitles_senza_credenziali(env):
    r = env.c.post('/api/settings/opensubtitles/test').json()
    assert r['kind'] == 'missing_creds' and r['implementation'] == 'xmlrpc'


# ----------------------------------------------------------------------------------------------------------- file system
def test_fs_radici(env):
    roots = env.c.get('/api/fs/roots').json()['roots']
    assert roots[0]['kind'] == 'home' and roots[0]['path'] == str(Path.home())
    assert {'name': '/mnt/media', 'path': '/mnt/media', 'kind': 'mapped'} in roots
    assert any(r['kind'] in ('root', 'drive') for r in roots)


def test_fs_elenco_ordinato_con_filtro_e_nascosti(env):
    d = env.tmp / 'lib'
    (d / 'Zeta').mkdir(parents=True)
    (d / 'alfa').mkdir()
    (d / '.nascosta').mkdir()
    for n, size in (('b.mkv', 2048), ('A.MP4', 10), ('nota.txt', 1), ('.x.mkv', 1)):
        (d / n).write_bytes(b'x' * size)
    r = env.c.get('/api/fs/list', params={'path': str(d)}).json()
    assert [x['name'] for x in r['dirs']] == ['alfa', 'Zeta'] and [x['name'] for x in r['files']] == ['A.MP4', 'b.mkv', 'nota.txt']
    assert r['parent'] == str(env.tmp) and r['files'][1]['size'] == '2 KB'
    v = env.c.get('/api/fs/list', params={'path': str(d), 'exts': '.MKV, .mp4'}).json()
    assert [x['name'] for x in v['files']] == ['A.MP4', 'b.mkv']
    h = env.c.get('/api/fs/list', params={'path': str(d), 'hidden': 'true'}).json()
    assert '.nascosta' in [x['name'] for x in h['dirs']] and '.x.mkv' in [x['name'] for x in h['files']]


def test_fs_errori(env):
    f = env.tmp / 'file.txt'
    f.write_text('x')
    assert env.c.get('/api/fs/list', params={'path': 'relativo/qui'}).status_code == 422
    assert env.c.get('/api/fs/list', params={'path': str(env.tmp / 'no')}).status_code == 404
    assert env.c.get('/api/fs/list', params={'path': str(f)}).status_code == 422
    assert env.c.get('/api/fs/list').status_code == 422
    assert env.c.get('/api/fs/video-extensions').json()['exts'][:2] == ['.mp4', '.mkv']


def test_fs_ultima_cartella_solo_se_esiste_e_si_ricorda(env):
    d = env.tmp / 'ultima'
    d.mkdir()
    env.config.set('last_input_folder', str(env.tmp / 'sparita'), save=False)
    assert env.c.get('/api/fs/roots').json()['last'] is None
    assert env.c.post('/api/fs/last', json={'folder': str(env.tmp / 'sparita')}).status_code == 422
    assert env.c.post('/api/fs/last', json={'folder': str(d)}).json() == {'ok': True}
    assert env.config.get('last_input_folder') == str(d) and env.c.get('/api/fs/roots').json()['last'] == str(d)


def test_fs_radice_senza_genitore(env):
    assert env.c.get('/api/fs/list', params={'path': '/'}).json()['parent'] is None


# ------------------------------------------------------------------------------------- scansione, dimensioni, spegnimento
def test_scansione_cartella_aggiunge_senza_doppioni_e_notifica(env):
    d = env.tmp / 'lib'
    (d / 's').mkdir(parents=True)
    for n in ('a.mkv', 's/b.mp4', 's/c.txt'):
        (d / n).write_bytes(b'x' * 1024)
    env.wq.add([str(d / 'a.mkv'), '/altro/gia_in_coda.mkv'])        # il primo e' anche nella cartella
    assert env.c.post('/api/queue/scan', json={'folder': str(d)}).json() == {'started': True}
    env.wq.join_scan(10)
    assert sorted(Path(p).name for p in env.wq.queue.snapshot()) == ['a.mkv', 'b.mp4', 'gia_in_coda.mkv']
    ev = [e for e in env.wq.bus.since(0)[0] if e['k'].startswith('scan_')]
    assert [(e['k'], e['d']) for e in ev] == [('scan_started', str(d)), ('scan_finished', 2)]    # 'trovati', non 'aggiunti'
    assert [r['size'] for r in env.wq.rows() if r['filename'] == 'b.mp4'] == ['1 KB']


def test_scansione_gia_in_corso_rifiutata_e_annullabile(env, monkeypatch):
    import threading
    gate = threading.Event()
    import tpweb.queue_backend as qb
    real = qb.iter_videos
    monkeypatch.setattr(qb, 'iter_videos', lambda f, e, c: (gate.wait(10), iter(()))[1])
    assert env.c.post('/api/queue/scan', json={'folder': '/x'}).status_code == 200
    r = env.c.post('/api/queue/scan', json={'folder': '/y'})
    assert r.status_code == 409 and r.json() == {'started': False}
    gate.set()
    env.wq.join_scan(10)
    assert env.c.post('/api/queue/scan/cancel').json() == {'ok': True}
    monkeypatch.setattr(qb, 'iter_videos', real)
    assert env.c.post('/api/queue/scan', json={'folder': '/x'}).json() == {'started': True}
    env.wq.join_scan(10)


def test_dimensioni_in_background(env):
    (a,) = kit.make_videos(env.tmp, 'a.mkv')
    env.wq.add([a, '/manca.mkv'])
    assert env.c.post('/api/queue/sizes', json={'paths': [a, '/manca.mkv']}).json() == {'requested': 2}
    assert wait_for(lambda: sum(1 for e in env.wq.bus.since(0)[0] if e['k'] == 'size_ready') == 2)
    sizes = {e['d']['path']: e['d']['size'] for e in env.wq.bus.since(0)[0] if e['k'] == 'size_ready'}
    assert sizes == {a: '10 B', '/manca.mkv': ''}
    assert [r['size'] for r in env.wq.rows()] == ['10 B', '']


def test_spegnimento_a_fine_coda_solo_se_abilitato(env):
    env.wq.add(kit.make_videos(env.tmp, 'a.mkv'))
    env.wq.start()
    env.wq.join(60)
    time.sleep(0.3)
    assert env.shutdowns == []                              # casella spenta
    env.flag['on'] = True
    env.wq.add(kit.make_videos(env.tmp, 'b.mkv'))
    env.wq.start()
    env.wq.join(60)
    assert wait_for(lambda: env.shutdowns == [1], 5)
    assert 'shutdown_scheduled' in [e['k'] for e in env.wq.bus.since(0)[0]]


def test_spegnimento_anche_dopo_uno_stop(env):
    env.flag['on'] = True
    env.wq.add(kit.make_videos(env.tmp, 'slow.mkv'))
    env.wq.start()
    assert wait_for(lambda: env.wq.rows()[0]['status'] == 'processing')
    env.wq.stop()
    env.wq.join(30)
    assert wait_for(lambda: env.shutdowns == [1], 5)


def test_senza_azione_di_spegnimento_il_server_non_spegne_mai(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    monkeypatch.setenv('HOME', str(tmp_path))
    q = WebQueue(EventBus(), engine_factory=lambda w: QueueEngine(w.queue, w, cleanup_caches=False, project_root=ROOT),
                 shutdown_enabled=lambda: True)
    q.add(kit.make_videos(tmp_path, 'a.mkv'))
    q.start()
    q.join(60)
    assert 'shutdown_scheduled' not in [e['k'] for e in q.bus.since(0)[0]]
