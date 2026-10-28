# -*- coding: utf-8 -*-
"""WebQueue e /api/queue (fetta 1b): stesse regole di gui.services.queue_service.QueueService, con il motore vero e il finto
`core.pipeline_cli` (queue_stub_pipeline.py). Senza Qt."""
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
from tpweb.events import EventBus  # noqa: E402
from tpweb.queue_backend import EMPTY, OK, RUNNING, WebQueue  # noqa: E402
from tpweb.runner import ServerThread  # noqa: E402


@pytest.fixture
def wq(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    spy = kit.PopenSpy()
    monkeypatch.setattr(subprocess, 'Popen', spy)
    q = WebQueue(EventBus(), engine_factory=lambda w: QueueEngine(w.queue, w, cleanup_caches=False, project_root=ROOT))
    q.spy = spy
    yield q
    q.stop()
    q.join(20)
    cfg.reset_config()


def kinds(wq):
    return [e['k'] for e in wq.bus.since(0)[0]]


def wait_for(cond, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ------------------------------------------------------------------------------------------------ aggiunta e regole
def test_add_senza_doppioni_e_con_ordine(wq):
    assert wq.add(['/a.mkv', '/b.mkv', '/a.mkv']) == ['/a.mkv', '/b.mkv']
    assert wq.queue.snapshot() == ['/a.mkv', '/b.mkv']
    assert wq.add(['/b.mkv', '/c.mkv']) == ['/c.mkv']
    assert [r['path'] for r in wq.rows()] == ['/a.mkv', '/b.mkv', '/c.mkv']
    assert kinds(wq).count('job_added') == 3


def test_add_solo_file_esistenti(wq, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a.mkv')
    assert wq.add([v, str(tmp_path / 'manca.mkv'), str(tmp_path)], only_files=True) == [v]


def test_file_in_lavorazione_non_si_riaccoda(wq):
    wq.add(['/a.mkv'])
    wq.queue.take_next()                              # il motore l'ha preso
    wq.on_file_started('/a.mkv')
    assert wq.is_active('/a.mkv') and wq.add(['/a.mkv']) == []
    wq.on_file_completed('/a.mkv')
    assert not wq.is_active('/a.mkv') and wq.add(['/a.mkv']) == ['/a.mkv']


def test_percorsi_equivalenti_sono_lo_stesso_file(wq):
    wq.add(['/x/a.mkv'])
    assert wq.add(['/x//a.mkv', '/x/./a.mkv']) == []


def test_job_ocr_in_elenco_ma_non_nella_coda_e_non_blocca_lo_stesso_file(wq):
    assert wq.add_ocr_job('/a.mkv', 'PGS') is True
    assert wq.queue.snapshot() == [] and wq.rows()[0]['kind'] == 'ocr'
    assert wq.add(['/a.mkv']) == ['/a.mkv']           # il job OCR ha il path del video ma non e' una trascrizione


# ------------------------------------------------------------------------------------------ riordino, rimozione, eccezioni
def test_riordino(wq):
    wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    assert wq.reorder(['/c.mkv', '/a.mkv'], '/c.mkv') is True
    assert wq.queue.snapshot() == ['/c.mkv', '/a.mkv', '/b.mkv']
    assert [r['path'] for r in wq.rows()] == ['/c.mkv', '/a.mkv', '/b.mkv']
    assert wq.reorder(['/b.mkv', '/zzz.mkv'], '/zzz.mkv') is False
    assert wq.queue.snapshot() == ['/c.mkv', '/a.mkv', '/b.mkv']
    assert kinds(wq).count('queue_reordered') == 1


def test_riordino_lascia_ferme_le_righe_non_in_attesa(wq):
    wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    wq.queue.take_next()
    wq.on_file_started('/a.mkv')
    wq.on_file_completed('/a.mkv')
    assert wq.reorder(['/c.mkv', '/b.mkv'], '/c.mkv') is True
    assert [(r['path'], r['status']) for r in wq.rows()] == [('/a.mkv', 'completed'), ('/c.mkv', 'queued'), ('/b.mkv', 'queued')]


def test_rimozione_di_un_file_in_attesa(wq):
    wq.add(['/a.mkv', '/b.mkv'])
    wq.set_overrides(['/b.mkv'], 'target_language', 'eng')
    assert wq.remove('/b.mkv') is True and wq.remove('/b.mkv') is False and wq.remove('/zzz') is False
    assert wq.queue.snapshot() == ['/a.mkv'] and wq.overrides_of('/b.mkv') == {}
    assert [r['path'] for r in wq.rows()] == ['/a.mkv']
    assert kinds(wq).count('job_removed') == 1


def test_eccezioni_per_file(wq):
    wq.add(['/a.mkv', '/b.mkv'])
    assert wq.set_overrides(['/a.mkv', '/zzz.mkv'], 'target_language', 'eng') == ['/a.mkv']
    assert wq.overrides_of('/a.mkv') == {'target_language': 'eng'}
    assert wq.set_overrides(['/a.mkv'], 'target_language', 'valore-non-valido-xx') == []
    assert wq.set_overrides(['/a.mkv'], 'target_language', None) == ['/a.mkv']
    assert wq.overrides_of('/a.mkv') == {}


def test_etichetta_delle_eccezioni_sulla_riga_come_la_gui(wq):
    wq.add(['/a.mkv', '/b.mkv'])
    wq.set_overrides(['/a.mkv'], 'target_language', 'eng')
    wq.set_overrides(['/a.mkv'], 'mux_subtitle_into_video', True)
    assert [r.get('ov') for r in wq.rows()] == ['ENG · mux', None]
    wq.queue.take_next()                                        # il motore prende il file: le eccezioni escono dal servizio, l'etichetta resta
    assert wq.overrides_of('/a.mkv') == {} and wq.rows()[0]['ov'] == 'ENG · mux'
    wq.set_overrides(['/b.mkv'], 'target_language', 'eng')
    wq.set_overrides(['/b.mkv'], 'target_language', None)
    assert 'ov' not in wq.rows()[1]
    wq.set_overrides(['/b.mkv'], 'target_language', 'fra')
    wq.remove('/b.mkv')
    wq.add(['/b.mkv'])                                          # riaccodato: riparte senza eccezioni
    assert 'ov' not in wq.rows()[-1]
    wq.clear()
    assert wq.rows() == []
    wq.add(['/c.mkv'])
    wq.set_overrides(['/c.mkv'], 'target_language', 'eng')
    wq.queue.take_next()
    wq.on_file_started('/c.mkv')
    wq.on_file_completed('/c.mkv')
    assert wq.rows()[0]['ov'] == 'ENG'
    wq.add(['/c.mkv'])                                          # ricaricato dopo il completamento: la nuova riga non eredita l'etichetta
    assert [r.get('ov') for r in wq.rows()] == ['ENG', None]
    wq.set_overrides(['/c.mkv'], 'target_language', 'fra')      # va sulla riga IN ATTESA, non su quella gia' completata
    assert [r.get('ov') for r in wq.rows()] == ['ENG', 'FRA']
    wq.remove('/c.mkv')
    assert [r.get('ov') for r in wq.rows()] == ['ENG']


def test_tessere_eta_e_tempo_trascorso(wq, monkeypatch):
    from core.services.formatting import EN_DASH
    assert wq.stats() == {'completed': 0, 'in_progress': 0, 'queued': 0, 'errors': 0, 'eta': EN_DASH, 'elapsed': None}
    wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    assert wq.stats()['queued'] == 3 and wq.stats()['eta'] == EN_DASH
    clock = [1000.0]
    monkeypatch.setattr('tpweb.queue_backend.time.time', lambda: clock[0])
    wq.proc_start_time = 900.0
    wq.queue.take_next()
    wq.on_file_started('/a.mkv')
    wq.on_file_completed('/a.mkv')                              # 1 fatto in 100 s, 2 rimasti: ETA 200 s
    s = wq.stats()
    assert (s['completed'], s['queued'], s['eta'], s['elapsed']) == (1, 2, '3m 20s', '01:40')
    clock[0] = 900.0 + 3700
    assert wq.stats()['elapsed'] == '01:01:40'
    wq.queue.take_next()
    wq.on_file_started('/b.mkv')                                # b e' in lavorazione: conta fra i «rimasti» dell'ETA (1 fatto in 3700 s)
    assert wq.stats()['in_progress'] == 1 and wq.stats()['eta'] == '2h 03m'
    wq.on_file_failed('/b.mkv')
    assert wq.stats()['errors'] == 1 and wq.state()['stats'] == wq.stats()


# ------------------------------------------------------------------------------------------------------ avvio e arresto
def test_start_su_coda_vuota_e_doppio_start(wq, tmp_path):
    assert wq.start() == EMPTY
    wq.add(kit.make_videos(tmp_path, 'slow.mkv'))
    assert wq.start() == OK
    assert wait_for(lambda: wq.rows()[0]['status'] == 'processing')
    assert wq.start() == RUNNING


def test_esecuzione_completa_con_il_finto_pipeline(wq, tmp_path):
    vids = kit.make_videos(tmp_path, 'a.mkv', 'b.mkv')
    wq.add(vids)
    assert wq.start() == OK
    wq.join(60)
    assert not wq.is_processing
    assert [r['status'] for r in wq.rows()] == ['completed', 'completed'] and [r['progress'] for r in wq.rows()] == [100, 100]
    assert (wq.completed_count, wq.error_count) == (2, 0) and wq.counts()['completed'] == 2
    k = kinds(wq)
    assert k[0] == 'job_added' and 'processing_started' in k and k[-1] == 'finished'
    assert k.count('file_started') == 2 and k.count('file_completed') == 2 and k.count('history') == 2
    assert 'log' in k and 'steps' in k and 'progress' in k
    seq = [e for e in wq.bus.since(0)[0] if e['k'] in ('file_started', 'file_completed')]
    assert [(e['k'], e['d']) for e in seq] == [('file_started', vids[0]), ('file_completed', vids[0]),
                                               ('file_started', vids[1]), ('file_completed', vids[1])]
    assert wq.last_steps and wq.last_steps['file_name'] == 'b.mkv'


def test_file_fallito_e_crash_contano_come_errori(wq, tmp_path):
    vids = kit.make_videos(tmp_path, 'fail.mkv', 'ok.mkv')
    wq.add(vids)
    wq.start()
    wq.join(60)
    assert [r['status'] for r in wq.rows()] == ['failed', 'completed']
    assert (wq.completed_count, wq.error_count) == (1, 1)
    assert wq.diag()['errors'] == '1' and [e['d']['errors'] for e in wq.bus.since(0)[0] if e['k'] == 'diag'][-1] == '1'      # la tessera segue il file fallito (scelta B)
    errs = [e['d'] for e in wq.bus.since(0)[0] if e['k'] == 'file_error']
    assert errs and errs[0]['path'] == vids[0] and 'exit code' in errs[0]['message']


def test_stop_ferma_il_file_in_corso_e_lascia_gli_altri_in_coda(wq, tmp_path):
    vids = kit.make_videos(tmp_path, 'slow.mkv', 'b.mkv', 'c.mkv')
    wq.add(vids)
    wq.start()
    assert wait_for(lambda: wq.rows()[0]['status'] == 'processing')
    assert wq.stop() is True
    wq.join(30)
    assert not wq.is_processing
    assert [r['status'] for r in wq.rows()] == ['failed', 'queued', 'queued']
    assert wq.queue.snapshot() == vids[1:]


def test_svuota_rifiutato_durante_l_elaborazione(wq, tmp_path):
    wq.add(kit.make_videos(tmp_path, 'slow.mkv'))
    wq.start()
    assert wait_for(lambda: wq.rows()[0]['status'] == 'processing')
    assert wq.clear() is False and len(wq.rows()) == 1
    wq.stop()
    wq.join(30)
    assert wq.clear() is True and wq.rows() == [] and len(wq.queue) == 0


def test_rimozione_durante_la_lavorazione_abbassa_il_totale_del_motore(wq, tmp_path):
    vids = kit.make_videos(tmp_path, 'slow.mkv', 'b.mkv')
    wq.add(vids)
    wq.start()
    assert wait_for(lambda: wq.rows()[0]['status'] == 'processing')
    total = wq._engine.total_files_at_start
    assert wq.remove(vids[1]) is True
    assert wq._engine.total_files_at_start == total - 1


def test_eccezioni_arrivano_a_pipeline_cli(wq, tmp_path):
    vids = kit.make_videos(tmp_path, 'a.mkv')
    wq.add(vids)
    wq.set_overrides(vids, 'target_language', 'eng')
    wq.start()
    wq.join(60)
    assert wq.spy.calls[0]['args_json']['overrides'] == {'target_language': 'eng'}


# ------------------------------------------------------------------------------------------------------------- HTTP
@pytest.fixture
def web(wq):
    s = ServerThread(bus=wq.bus, queue=wq).start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    yield c, wq
    c.close()
    s.stop()


def test_http_aggiunta_riordino_rimozione_e_stato(web):
    c, wq = web
    assert c.post('/api/queue/add', json={'paths': ['/a.mkv', '/b.mkv', '/a.mkv']}).json() == {'added': ['/a.mkv', '/b.mkv'],
                                                                                                'skipped': ['/a.mkv']}
    assert c.post('/api/queue/reorder', json={'order': ['/b.mkv', '/a.mkv'], 'moved': '/b.mkv'}).json() == {'ok': True}
    assert c.post('/api/queue/reorder', json={'order': ['/zzz'], 'moved': '/zzz'}).json() == {'ok': False}
    st = c.get('/api/queue').json()
    assert [r['path'] for r in st['rows']] == ['/b.mkv', '/a.mkv'] and st['remaining'] == 2 and st['running'] is False
    assert st['counts']['queued'] == 2 and st['seq'] == wq.bus.last_seq
    assert c.post('/api/queue/remove', json={'path': '/a.mkv'}).json() == {'removed': True}
    assert c.post('/api/queue/remove', json={'path': '/a.mkv'}).json() == {'removed': False}
    assert c.post('/api/queue/overrides', json={'paths': ['/b.mkv'], 'key': 'target_language', 'value': 'eng'}).json() == {'changed': ['/b.mkv'], 'skipped': 0}
    assert c.get('/api/queue').json()['overrides'] == {'/b.mkv': {'target_language': 'eng'}}
    assert c.get('/api/state').json()['state']['queue']['rows'][0]['path'] == '/b.mkv'


def test_http_avvia_stop_svuota(web, tmp_path):
    c, wq = web
    assert c.post('/api/queue/start').json() == {'verdict': 'empty'}
    c.post('/api/queue/add', json={'paths': kit.make_videos(tmp_path, 'slow.mkv')})
    assert c.post('/api/queue/start').json() == {'verdict': 'ok'}
    assert wait_for(lambda: wq.rows()[0]['status'] == 'processing')
    r = c.post('/api/queue/start')
    assert r.status_code == 409 and r.json() == {'verdict': 'running'}
    assert c.post('/api/queue/clear').status_code == 409
    assert c.post('/api/queue/stop').json() == {'stopping': True}
    wq.join(30)
    assert c.post('/api/queue/stop').json() == {'stopping': False}
    assert c.post('/api/queue/clear').json() == {'ok': True}
    assert c.get('/api/queue').json()['rows'] == []


def test_http_corpo_non_valido_e_senza_token(web):
    c, wq = web
    assert c.post('/api/queue/add', json={'percorsi': []}).status_code == 422
    assert httpx.post(str(c.base_url) + '/api/queue/add', json={'paths': []}).status_code in (401, 403)


def test_tessera_errori_non_porta_con_se_i_file_fermati_della_coda_precedente(wq, tmp_path):
    wq.stopped_count = 1                                   # una coda precedente fermata con Stop
    wq.add(kit.make_videos(tmp_path, 'fail.mkv'))
    wq.start()
    wq.join(60)
    assert wq.stopped_count == 0 and wq.diag()['errors'] == '1'
