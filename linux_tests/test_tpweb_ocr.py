# -*- coding: utf-8 -*-
"""Fase 5b: conversione OCR sul server. Motore OCR finto (nessun Tesseract), coda, configurazione e bus veri."""
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from core.pgs_types import FLAG_LOW_CONF, OcrEvent, events_to_srt  # noqa: E402
from test_tpweb_library import FakeClient, FakeApi  # noqa: E402
from core.services import library_actions as LA  # noqa: E402
from utils.translations import tr  # noqa: E402


def make_events():
    from PIL import Image
    img = Image.new('RGBA', (30, 12), (255, 0, 0, 255))
    return [OcrEvent(1, 1000, 2000, 'Ciao a tutti', 95.0, img),
            OcrEvent(2, 3000, 4000, 'Dubb1o', 55.0, img, {FLAG_LOW_CONF}),
            OcrEvent(3, 5000, 6000, 'Fine', 90.0, None),
            OcrEvent(4, 7000, 8000, 'Altro dubbio', 60.0, img, {FLAG_LOW_CONF})]


class FakeEngine:
    """Scenario dal nome del video: auto_ok | auto_fail | unsupported | lang | error | review | slow."""
    made = []
    writeback_ok = True
    gate = None

    def __init__(self, video_path, config, strategy, mode='ocr', srt_text='', language='ita', kind='pgs', listener=None):
        self.args = dict(video_path=video_path, strategy=strategy, mode=mode, srt_text=srt_text, language=language, kind=kind)
        self.L, self.cancelled = listener, threading.Event()
        FakeEngine.made.append(self)

    def cancel(self):
        self.cancelled.set()

    def run(self):
        L, a = self.L, self.args
        name = Path(a['video_path']).name
        try:
            if a['mode'] == 'writeback':
                L.on_writeback_done(FakeEngine.writeback_ok)
                return
            L.on_log(f'OCR {name}')
            L.on_progress(30, 'OCR')
            if FakeEngine.gate is not None:
                FakeEngine.gate.wait(10)
            if name.startswith('slow'):
                self.cancelled.wait(20)
                L.on_log('annullato')
            elif name.startswith('auto_ok'):
                L.on_auto_done(True)
            elif name.startswith('auto_fail'):
                L.on_auto_done(False)
            elif name.startswith('unsupported'):
                L.on_unsupported('formato non supportato')
            elif name.startswith('lang'):
                L.on_lang_unsupported('lingua xx')
            elif name.startswith('error'):
                L.on_error('boom')
            elif name.startswith('review'):
                L.on_events_ready(make_events(), 'it')
            else:
                L.on_auto_done(True)
        finally:
            L.on_finished()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    FakeClient.calls, FakeClient.notified, FakeClient.fail = [], [], False
    FakeEngine.made, FakeEngine.writeback_ok, FakeEngine.gate = [], True, None
    s, config = e2e.make_server(tmp_path, monkeypatch, library_deps={'client': FakeClient, 'api': FakeApi()}, ocr_engine=FakeEngine)
    config.set('library_scanner_url', 'http://scanner:6680', save=False)
    config.set('library_scanner_api_key', 'k' * 24, save=False)
    config.set('library_scanner_path_map', 'V:\\=/mnt/v', save=False)
    s.queue.compact = False
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    c.srv, c.config, c.ocr, c.q = s, config, s.app.state.ocr, s.queue
    c.app = s.app
    c.app.state.library.loaded = True
    yield c
    c.close()
    s.queue.stop(); s.queue.join(20)
    s.stop()


def wait(cond, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.03)
    raise AssertionError('condizione non raggiunta')


def events_of(c, kind, after=0):
    return [e['d'] for e in c.srv.bus.since(after)[0] if e['k'] == kind]


def row(c, path):
    return next((r for r in c.q.rows() if r['path'] == path and r['kind'] == 'ocr'), None)


def idle(c):
    wait(lambda: not c.ocr.state()['busy'] and not c.q.gate.ocr_running)


def test_auto_ok_righe_stato_notifica_messaggio_e_gate(srv):
    c = srv
    seq = c.srv.bus.last_seq
    FakeEngine.gate = threading.Event()
    assert c.post('/api/ocr/start', json={'path': 'V:\\film\\auto_ok.mkv', 'kind': 'pgs'}).json() == {'result': 'started'}
    wait(lambda: c.ocr.state()['busy'])
    assert c.q.gate.ocr_running is True
    r = row(c, 'V:\\film\\auto_ok.mkv')
    assert r['status'] == 'processing'
    wait(lambda: row(c, 'V:\\film\\auto_ok.mkv')['progress'] == 30)
    assert c.ocr.state()['progress_text'] == LA.progress_text('auto_ok.mkv', 'OCR', 30, False, 0, 0, 0) and 'auto_ok.mkv' in c.ocr.state()['progress_text']
    FakeEngine.gate.set()
    idle(c)
    assert row(c, 'V:\\film\\auto_ok.mkv')['status'] == 'completed'
    assert FakeEngine.made[0].args['video_path'] == '/mnt/v/film/auto_ok.mkv'          # percorso mappato sul computer
    msgs = events_of(c, 'ocr_message', seq)
    assert msgs == [{'kind': 'info', 'title': tr('ocr_section_title'), 'text': tr('ls_conv_done').format(name='auto_ok.mkv')}]
    c.srv.app.state.library.join(5)
    assert FakeClient.notified == ['V:\\film\\auto_ok.mkv'] and events_of(c, 'library_changed', seq)
    assert c.ocr.state()['progress_text'] == '' and c.q.gate.ocr_running is False


def test_esiti_negativi_e_strategia(srv):
    c = srv
    seq = c.srv.bus.last_seq
    for name in ('auto_fail', 'unsupported', 'lang', 'error'):
        c.post('/api/ocr/start', json={'path': f'V:\\{name}.mkv', 'kind': 'vobsub'})
        idle(c)
    got = [(m['kind'], m['text']) for m in events_of(c, 'ocr_message', seq)]
    assert got == [('warning', tr('ls_conv_failed').format(name='auto_fail.mkv')),
                   ('info', 'unsupported.mkv\n\nformato non supportato'),
                   ('info', tr('ls_lang_skipped').format(name='lang.mkv', msg='lingua xx')),
                   ('warning', tr('ls_ocr_error').format(name='error.mkv', msg='boom'))]
    st = {n: row(c, f'V:\\{n}.mkv')['status'] for n in ('auto_fail', 'unsupported', 'lang', 'error')}
    assert st == {'auto_fail': 'failed', 'unsupported': 'failed', 'lang': 'completed', 'error': 'failed'}
    assert all(e.args['kind'] == 'vobsub' for e in FakeEngine.made)
    c.config.set('ocr_strategy', 'auto', save=False)
    c.post('/api/ocr/start', json={'path': 'V:\\auto_ok2.mkv', 'kind': 'pgs'})
    idle(c)
    assert FakeEngine.made[-1].args['strategy'] == 'auto'
    assert c.post('/api/ocr/start', json={'path': 'x', 'kind': 'zzz'}).status_code == 422
    assert c.post('/api/ocr/start', json={'path': '', 'kind': 'pgs'}).json() == {'result': 'ignored'}


def test_un_solo_ocr_alla_volta_e_annulla(srv):
    c = srv
    c.post('/api/ocr/start', json={'path': 'V:\\slow.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['busy'])
    r = c.post('/api/ocr/start', json={'path': 'V:\\auto_ok.mkv', 'kind': 'pgs'})
    assert r.status_code == 409 and r.json() == {'result': 'busy'}
    c.q.add(['/a.mkv'])
    assert c.q.start() == 'ocr'                                        # la coda non parte mentre c'e' un OCR
    assert c.post('/api/ocr/cancel').json() == {'cancelling': True}
    idle(c)
    assert c.post('/api/ocr/cancel').json() == {'cancelling': False}


def test_con_la_coda_al_lavoro_il_job_aspetta_poi_parte_con_la_revisione_scelta(srv, monkeypatch):
    c = srv
    from tpweb.queue_backend import WebQueue
    flag = {'v': True}
    monkeypatch.setattr(WebQueue, 'is_processing', property(lambda self: flag['v']))
    seq = c.srv.bus.last_seq
    assert c.post('/api/ocr/start', json={'path': 'V:\\auto_ok.mkv', 'kind': 'pgs'}).json() == {'result': 'deferred'}
    assert FakeEngine.made == [] and c.ocr.state()['deferred'] == ['V:\\auto_ok.mkv']
    assert row(c, 'V:\\auto_ok.mkv')['status'] == 'queued'
    assert any(tr('ls_ocr_queued_log').format(name='auto_ok.mkv') in l['text'] for l in c.q.log.lines)
    assert c.post('/api/ocr/deferred-mode', json={'paths': ['V:\\auto_ok.mkv', 'V:\\non_differito.mkv'], 'mode': 'review'}).json() == {'changed': ['V:\\auto_ok.mkv']}
    assert row(c, 'V:\\auto_ok.mkv')['ov'] == tr('job_ov_ocr_targeted_short')
    assert any(tr('job_ov_skipped_log').format(n=1) in l['text'] for l in c.q.log.lines)
    c.ocr.drain_deferred()
    assert FakeEngine.made == [] and c.ocr.state()['deferred'] == ['V:\\auto_ok.mkv']        # coda ancora al lavoro: resta in attesa
    assert len([r for r in c.q.rows() if r['kind'] == 'ocr']) == 1                          # e non si ripete la riga del job
    flag['v'] = False
    c.ocr.drain_deferred()
    idle(c)
    assert FakeEngine.made[0].args['strategy'] == 'review' and c.ocr.state()['deferred'] == [] and c.ocr.mode_override == {}
    assert c.post('/api/ocr/deferred-mode', json={'paths': [], 'mode': 'zzz'}).status_code == 422


def test_fine_coda_fa_partire_i_differiti(srv, monkeypatch):
    c = srv
    from tpweb.queue_backend import WebQueue
    flag = {'v': True}
    monkeypatch.setattr(WebQueue, 'is_processing', property(lambda self: flag['v']))
    c.post('/api/ocr/start', json={'path': 'V:\\auto_ok.mkv', 'kind': 'pgs'})
    flag['v'] = False
    c.q._thread = None
    c.q.on_finished()                                                  # fine coda: gli hook partono su un thread a parte
    wait(lambda: len(FakeEngine.made) == 1)
    idle(c)
    assert row(c, 'V:\\auto_ok.mkv')['status'] == 'completed'


def test_revisione_elenco_testo_verifica_corsivo_immagine_e_scrittura(srv):
    c = srv
    seq = c.srv.bus.last_seq
    c.post('/api/ocr/start', json={'path': 'V:\\review.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['review'])
    assert c.q.gate.ocr_running is True                                # la revisione conta come OCR in corso
    r = c.get('/api/ocr/review/list').json()
    assert r['total'] == 4 and r['first'] == 1 and r['counter'] == tr('ocr_counter').format(total=4, flagged=2)
    assert [i['i'] for i in r['items']] == [0, 1, 2, 3]
    assert [i['i'] for i in c.get('/api/ocr/review/list', params={'only_flagged': True}).json()['items']] == [1, 3]
    ev = c.get('/api/ocr/review/event/1').json()
    assert ev['text'] == 'Dubb1o' and ev['has_image'] is True and ev['can_prev'] is True and ev['can_next'] is True
    assert c.get('/api/ocr/review/event/2').json()['has_image'] is False and c.get('/api/ocr/review/event/9').status_code == 404
    png = c.get('/api/ocr/review/image/1')
    assert png.status_code == 200 and png.content[:8] == b'\x89PNG\r\n\x1a\n' and c.get('/api/ocr/review/image/2').status_code == 404
    assert c.put('/api/ocr/review/text', json={'i': 1, 'text': 'Dubbio'}).json()['counter'] == tr('ocr_counter').format(total=4, flagged=2)
    v = c.post('/api/ocr/review/verify', json={'i': 1, 'text': 'Dubbio ok'}).json()
    assert v['next'] == 3 and v['counter'] == tr('ocr_counter').format(total=4, flagged=1) and '✓' in v['label']
    assert c.get('/api/ocr/review/next-flagged', params={'i': 3}).json() == {'next': 3}
    assert c.post('/api/ocr/review/italic', json={'text': 'ciao mondo', 'sel': [0, 4]}).json() == {'text': '<i>ciao</i> mondo', 'sel': [0, 11]}
    assert c.post('/api/ocr/review/italic', json={'text': 'ciao'}).json() == {'text': '<i>ciao</i>', 'sel': None}
    srt_expected = events_to_srt(c.ocr.review['events'])
    assert c.post('/api/ocr/review/done', json={'accept': True}).json() == {'ok': True}
    idle(c)
    wb = FakeEngine.made[-1].args
    assert wb['mode'] == 'writeback' and wb['srt_text'] == srt_expected and 'Dubbio ok' in srt_expected and wb['language'] == 'it'
    assert row(c, 'V:\\review.mkv')['status'] == 'completed'
    assert events_of(c, 'ocr_message', seq)[-1]['text'] == tr('ls_srt_written').format(name='review.mkv')
    assert c.get('/api/ocr/review/list').status_code == 404 and c.post('/api/ocr/review/done', json={'accept': True}).status_code == 409


def test_revisione_annullata_e_scrittura_fallita(srv):
    c = srv
    c.post('/api/ocr/start', json={'path': 'V:\\review.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['review'])
    assert c.post('/api/ocr/review/done', json={'accept': False}).json() == {'ok': True}
    assert row(c, 'V:\\review.mkv')['status'] == 'failed' and c.q.gate.ocr_running is False
    assert any(tr('ls_ocr_cancel_log').format(name='review.mkv') in l['text'] for l in c.q.log.lines)
    FakeEngine.writeback_ok = False
    seq = c.srv.bus.last_seq
    c.post('/api/ocr/start', json={'path': 'V:\\review.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['review'])
    c.post('/api/ocr/review/done', json={'accept': True})
    idle(c)
    assert events_of(c, 'ocr_message', seq)[-1] == {'kind': 'warning', 'title': tr('ocr_section_title'), 'text': tr('ls_srt_write_failed').format(name='review.mkv')}


def test_batch_conteggi_messaggio_finale_spegnimento_e_drain(srv, monkeypatch):
    c = srv
    sched = []
    monkeypatch.setattr(type(c.q), 'schedule_shutdown', lambda self, d: sched.append(d) or True)
    monkeypatch.setattr(type(c.q), 'shutdown_wanted', lambda self: True)
    seq = c.srv.bus.last_seq
    c.ocr.superpower_active = True
    items = [('V:\\auto_ok1.mkv', 'pgs'), ('V:\\unsupported.mkv', 'pgs'), ('V:\\lang.mkv', 'vobsub'), ('V:\\error.mkv', 'pgs'), ('V:\\auto_ok2.mkv', 'pgs')]
    assert c.ocr.start_batch(items) == 'started'
    wait(lambda: not c.ocr.state()['batch']['active'])
    idle(c)
    assert all(e.args['strategy'] == 'auto' for e in FakeEngine.made)                  # in batch sempre automatico
    msgs = events_of(c, 'ocr_message', seq)
    assert msgs == [{'kind': 'info', 'title': tr('ocr_section_title'), 'text': tr('ls_batch_done').format(ok=2, fail=2, total=5)}]      # la lingua saltata non e' un fallimento
    assert sched == [5] and c.ocr.superpower_active is False
    assert any(tr('ls_batch_started_log').format(n=5) in l['text'] for l in c.q.log.lines) and any(tr('ls_sp_done_log') in l['text'] for l in c.q.log.lines)
    assert [row(c, p)['status'] for p, _ in items] == ['completed', 'failed', 'completed', 'failed', 'completed']
    assert c.ocr.start_batch([]) == 'ignored'


def test_batch_rifiutato_se_occupato_e_stato_nello_snapshot(srv):
    c = srv
    c.post('/api/ocr/start', json={'path': 'V:\\slow.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['busy'])
    assert c.ocr.start_batch([('V:\\auto_ok.mkv', 'pgs')]) == 'busy'
    assert c.get('/api/state').json()['state']['ocr']['busy'] is True
    c.post('/api/ocr/cancel'); idle(c)


def test_chiusura_del_server_annulla_l_ocr(srv):
    c = srv
    c.post('/api/ocr/start', json={'path': 'V:\\slow.mkv', 'kind': 'pgs'})
    wait(lambda: c.ocr.state()['busy'])
    eng = FakeEngine.made[0]
    c.srv.stop()
    assert eng.cancelled.is_set() and not c.ocr._thread.is_alive()


def test_l_avanzamento_non_rilegge_la_coda_ma_il_cambio_di_stato_si(srv):
    c = srv
    FakeEngine.gate = threading.Event()
    seq = c.srv.bus.last_seq
    c.post('/api/ocr/start', json={'path': 'V:\\film\\auto_ok.mkv', 'kind': 'pgs'})
    wait(lambda: row(c, 'V:\\film\\auto_ok.mkv') is not None and row(c, 'V:\\film\\auto_ok.mkv')['progress'] == 30)
    kinds = [e['k'] for e in c.srv.bus.since(seq)[0]]
    assert kinds.count('job_changed') == 1 and 'file_progress' in kinds        # una volta lo stato (queued -> processing); il 30% solo sul posto
    FakeEngine.gate.set()
    idle(c)
