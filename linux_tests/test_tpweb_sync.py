# -*- coding: utf-8 -*-
"""Fase 4c: Sincronizzazione sul server. Singola con un finto SubtitleSynchronizer (nessun modello), coda con il finto `core.sync_cli`
(linux_tests/sync_stub_cli.py) lanciato dal motore vero; tabella delle coppie, mutua esclusione, annullamento, chiusura."""
import sys
import threading
import time
import types
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from core.jobs.sync_batch import SyncBatchEngine  # noqa: E402
from core.jobs.sync_single import SyncRunner  # noqa: E402
from core.services.log_filter import UPDATABLE_PATTERNS  # noqa: E402

BAR = next(iter(UPDATABLE_PATTERNS))


class FakeSync:
    behaviour = staticmethod(lambda s: True)
    made = []

    def __init__(self, video_path, external_srt_path, output_path, log_callback, progress_callback):
        self.args = (video_path, external_srt_path, output_path)
        self.log, self.prog = log_callback, progress_callback
        self._output_path = Path('/out/' + Path(external_srt_path).stem + '.synced.it.srt')
        self.cancelled = threading.Event()
        FakeSync.made.append(self)

    def synchronize(self):
        return FakeSync.behaviour(self)

    def cancel(self):
        self.cancelled.set()


def single_engine(video, srt, listener):
    return SyncRunner(video, srt, None, listener)


def batch_engine(pairs, listener):
    return SyncBatchEngine(pairs, listener, cli_module=lambda: 'linux_tests.sync_stub_cli')


@pytest.fixture
def srv(tmp_path, monkeypatch):
    mod = types.ModuleType('core.subtitle_synchronizer')
    mod.SubtitleSynchronizer = FakeSync
    monkeypatch.setitem(sys.modules, 'core.subtitle_synchronizer', mod)
    FakeSync.made, FakeSync.behaviour = [], staticmethod(lambda s: True)
    s, config = e2e.make_server_with_tools(tmp_path, monkeypatch, {'sync_single': single_engine, 'sync_batch': batch_engine})
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=20, headers={'X-TP-Token': s.token})
    c.srv, c.tmp = s, tmp_path
    yield c
    c.close()
    s.stop()


def wait_status(c, want, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get('/api/tools/sync').json()
        if st['status'] in want:
            return st
        time.sleep(0.05)
    raise AssertionError(f'stato {st["status"]} invece di {want}')


def run_single(c):
    return c.post('/api/tools/sync/run', json={'mode': 'single', 'video': '/v/Film.mkv', 'srt': '/v/Film.it.srt'})


def test_singola_ok_progresso_log_e_uscita(srv):
    c = srv
    def beh(s):
        s.log('1. Estrazione audio')
        s.prog(25)
        s.log(f'{BAR} 10%')
        s.log(f'{BAR} 60%')                      # la barra si riscrive sul posto
        return True
    FakeSync.behaviour = staticmethod(beh)
    assert run_single(c).json() == {'started': True}
    st = wait_status(c, {'finished'})
    assert st['outcome'] == {'kind': 'completed', 'video': '/v/Film.mkv'} and st['progress'] == 100 and st['mode'] == 'single'
    assert st['output_path'] == '/out/Film.it.synced.it.srt'
    assert st['log'] == ['1. Estrazione audio', f'{BAR} 60%']
    assert c.srv.queue.gate.snapshot()['sync'] is False


def test_singola_fallita_e_campi_mancanti(srv):
    c = srv
    assert c.post('/api/tools/sync/run', json={'mode': 'single', 'video': '', 'srt': 'x'}).json() == {'error': 'missing_video'}
    assert c.post('/api/tools/sync/run', json={'mode': 'single', 'video': 'v', 'srt': ' '}).json() == {'error': 'missing_srt'}
    assert c.post('/api/tools/sync/run', json={'mode': 'zzz'}).status_code == 422
    FakeSync.behaviour = staticmethod(lambda s: False)
    run_single(c)
    st = wait_status(c, {'finished'})
    assert st['outcome'] == {'kind': 'error'} and len(st['errors']) == 1 and 'fallita' in st['errors'][0]
    c.post('/api/tools/sync/reset')
    def boom(s):
        raise RuntimeError('esploso')
    FakeSync.behaviour = staticmethod(boom)
    run_single(c)
    assert wait_status(c, {'finished'})['errors'] == ['esploso']


def test_annullamento_subito_e_uscita_cancelled(srv):
    c = srv
    started = threading.Event()
    def beh(s):
        started.set()
        s.cancelled.wait(20)
        return False
    FakeSync.behaviour = staticmethod(beh)
    run_single(c)
    assert started.wait(10)
    t0 = time.time()
    assert c.post('/api/tools/sync/cancel').json() == {'cancelling': True} and time.time() - t0 < 2
    st = wait_status(c, {'finished'})
    assert st['outcome'] == {'kind': 'cancelled'} and st['errors'] == [] and st['log'][-1]
    assert c.post('/api/tools/sync/cancel').json() == {'cancelling': False}


def make_tree(tmp, names=('Show.S01E01', 'Show.S01E02')):
    v, s = tmp / 'vid', tmp / 'srt'
    v.mkdir(); s.mkdir()
    for n in names:
        (v / f'{n}.mkv').write_text('x')
        (s / f'{n}.it.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nx\n')
    return v, s


def test_tabella_scansione_scelta_e_spunte(srv):
    c = srv
    v, s = make_tree(c.tmp)
    assert c.post('/api/tools/sync/scan', json={'video_dir': '', 'srt_dir': str(s)}).status_code == 422
    plan = c.post('/api/tools/sync/scan', json={'video_dir': str(v), 'srt_dir': str(s), 'recursive': False}).json()
    assert [r['video_name'] for r in plan['rows']] == ['Show.S01E01.mkv', 'Show.S01E02.mkv']
    assert all(r['checked'] and r['state'] == 'ready' and r['srt'] for r in plan['rows'])
    assert plan['summary'] == {'ready': 2, 'check': 0, 'nosrt': 0, 'left': 0}
    assert [f['label'] for f in plan['srt_files']] == ['Show.S01E01.it.srt', 'Show.S01E02.it.srt']
    assert c.post('/api/tools/sync/plan/include', json={'row': 1, 'include': False}).json() == {'ok': True}
    assert c.post('/api/tools/sync/plan/srt', json={'row': 0, 'value': None}).json() == {'ok': True}
    plan = c.get('/api/tools/sync').json()['plan']
    assert plan['rows'][0]['state'] == 'nosrt' and plan['rows'][0]['checked'] is False and plan['rows'][1]['checked'] is False
    assert c.post('/api/tools/sync/plan/srt', json={'row': 9, 'value': None}).json() == {'ok': False}


def test_coda_di_coppie_righe_progresso_e_riepilogo(srv):
    c = srv
    v, s = make_tree(c.tmp, ('Show.S01E01', 'Show.S01E02', 'Show.S01E03'))
    c.post('/api/tools/sync/scan', json={'video_dir': str(v), 'srt_dir': str(s)})
    c.post('/api/tools/sync/plan/include', json={'row': 1, 'include': False})
    assert c.post('/api/tools/sync/run', json={'mode': 'batch'}).json() == {'started': True}
    st = wait_status(c, {'finished'})
    assert st['outcome'] == {'kind': 'batch_done', 'ok': 2, 'fail': 0, 'skipped': 0} and st['progress'] == 100
    assert st['rows_rt'] == {'0': {'kind': 'ok'}, '1': {'kind': ''}, '2': {'kind': 'ok'}}
    assert any('=== Coda sync 1/2' in l for l in st['log'])
    assert c.srv.queue.gate.snapshot()['sync'] is False


def test_coda_senza_nulla_da_fare_e_con_annullamento(srv):
    c = srv
    assert c.post('/api/tools/sync/run', json={'mode': 'batch'}).json() == {'error': 'nothing'}
    assert c.srv.queue.gate.snapshot()['sync'] is False                              # nessuna prenotazione lasciata
    v, s = make_tree(c.tmp, ('A.slow.S01E01', 'B.Show.S01E02'))
    c.post('/api/tools/sync/scan', json={'video_dir': str(v), 'srt_dir': str(s)})
    c.post('/api/tools/sync/run', json={'mode': 'batch'})
    t0 = time.time()
    while not any('STUB_SLOW_STARTED' in l for l in c.get('/api/tools/sync').json()['log']) and time.time() - t0 < 20:
        time.sleep(0.05)
    assert c.post('/api/tools/sync/plan/include', json={'row': 1, 'include': False}).json() == {'ok': False}      # tabella bloccata col run in corso
    assert c.post('/api/tools/sync/scan', json={'video_dir': str(v), 'srt_dir': str(s)}).status_code == 422
    assert c.post('/api/tools/sync/reset').status_code == 409
    c.post('/api/tools/sync/cancel')
    st = wait_status(c, {'finished'})
    assert st['outcome']['kind'] == 'batch_done' and st['outcome']['ok'] == 0 and st['outcome']['skipped'] >= 1
    assert st['rows_rt']['0']['kind'] == 'failed' and st['rows_rt']['1']['kind'] == 'skipped'
    assert c.post('/api/tools/sync/reset').json() == {'reset': True}
    assert c.get('/api/tools/sync').json()['plan']['rows'] == []


def test_mutua_esclusione_con_coda_e_glossario(srv):
    c = srv
    gate = c.srv.queue.gate
    gate.glossary_active = True
    r = run_single(c)
    assert r.status_code == 409 and r.json()['blocked'] == 'sync_blocked_glossary'
    gate.glossary_active = False
    FakeSync.behaviour = staticmethod(lambda s: (time.sleep(0.6), True)[1])
    run_single(c)
    r = run_single(c)
    assert r.status_code == 409 and r.json()['blocked'] == 'sync_already_running'
    c.srv.queue.add(['/a.mkv'])
    assert c.post('/api/queue/start').json()['verdict'] == 'sync'
    wait_status(c, {'finished'})


def test_chiusura_del_server_annulla_e_attende(srv):
    c = srv
    started = threading.Event()
    FakeSync.behaviour = staticmethod(lambda s: (started.set(), s.cancelled.wait(20), False)[2])
    run_single(c)
    assert started.wait(10)
    mgr = c.srv.app.state.tools.sync
    c.srv.stop()
    assert not mgr._thread.is_alive() and FakeSync.made[0].cancelled.is_set()
