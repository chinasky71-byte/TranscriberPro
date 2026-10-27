# -*- coding: utf-8 -*-
"""G3 (fase 0 della web UI): CARATTERIZZAZIONE di gui/ocr_worker.py::OcrWorker.

Passa identica sul codice vecchio e su quello con la logica in core/jobs/ocr_run.py: segnali ed esiti dei due modi (ocr/writeback), dei
due rami (review/auto), degli errori (formato non supportato, lingua senza tessdata, annullamento, eccezione), cancel e thread di
emissione. Il motore OCR e' un finto (nessun Tesseract, nessun video): si sostituiscono core.ocr_auto.make_bitmap_ocr & C."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class FakeOcr:
    def __init__(self, behaviour=None):
        self.behaviour = behaviour or {}
        self.cancelled = False
        self.calls = []

    def writeback(self, srt_text, language):
        self.calls.append(('writeback', srt_text, language))
        if 'raise' in self.behaviour:
            raise self.behaviour['raise']
        return self.behaviour.get('writeback_ok', True)

    def ocr_to_events(self):
        self.calls.append(('ocr_to_events',))
        if 'raise' in self.behaviour:
            raise self.behaviour['raise']
        return self.behaviour.get('events', ['E1', 'E2']), self.behaviour.get('lang', 'ita')

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def fake(monkeypatch):
    import core.ocr_auto as oa
    state = {'ocr': FakeOcr(), 'made': [], 'auto': [], 'conv': [], 'auto_ok': True, 'conv_ok': True, 'auto_raise': None}

    def make(video_path, config, kind, log_callback=None, progress_callback=None):
        state['made'].append((video_path, config, kind))
        state['log'], state['progress'] = log_callback, progress_callback
        if state.get('make_raise'):
            raise state['make_raise']
        return state['ocr']

    def run_auto(ocr, log_callback=None, italian=True):
        state['auto'].append(ocr)
        log_callback('log dall\'auto')
        if state['auto_raise']:
            raise state['auto_raise']
        return state['auto_ok']

    def conv(ocr, events, lang, log_callback=None):
        state['conv'].append((events, lang))
        log_callback('log dalla traduzione')
        return state['conv_ok']
    monkeypatch.setattr(oa, 'make_bitmap_ocr', make)
    monkeypatch.setattr(oa, 'run_ocr_auto', run_auto)
    monkeypatch.setattr(oa, 'convert_and_translate', conv)
    return state


SIGS = ('log_message', 'error', 'finished', 'events_ready', 'auto_done', 'writeback_done', 'unsupported', 'lang_unsupported', 'progress')


def run(qt, **kw):
    from PyQt6.QtCore import QThread, Qt
    from gui.ocr_worker import OcrWorker
    args = dict(video_path='/v/Film.mkv', config='CFG', strategy='review')
    args.update(kw)
    w = OcrWorker(**args)
    main = QThread.currentThread()
    ev = []
    for sig in SIGS:
        getattr(w, sig).connect(lambda *a, _s=sig: ev.append((_s, a, QThread.currentThread() == main)), Qt.ConnectionType.DirectConnection)
    w.start()
    assert w.wait(20000)
    qt.processEvents()
    return w, ev


def sig(ev):
    return [(e[0], e[1]) for e in ev]


def test_review_italiano(qt, fake):
    w, ev = run(qt)
    assert fake['made'] == [('/v/Film.mkv', 'CFG', 'pgs')]
    assert sig(ev) == [('log_message', ('🎬 OCR PGS — Film.mkv',)), ('events_ready', (['E1', 'E2'], 'it')), ('finished', ())]
    assert all(not e[2] for e in ev)


def test_review_non_italiano_traduce(qt, fake):
    fake['ocr'] = FakeOcr({'lang': 'eng', 'events': ['X']})
    w, ev = run(qt)
    assert fake['conv'] == [(['X'], 'eng')]
    assert sig(ev) == [('log_message', ('🎬 OCR PGS — Film.mkv',)), ('log_message', ('log dalla traduzione',)),
                       ('auto_done', (True,)), ('finished', ())]
    fake['conv_ok'] = False
    w, ev = run(qt)
    assert ('auto_done', (False,)) in sig(ev)


def test_auto(qt, fake):
    w, ev = run(qt, strategy='auto', kind='vobsub')
    assert fake['made'][0][2] == 'vobsub'
    assert sig(ev) == [('log_message', ('🎬 OCR VOBSUB — Film.mkv',)), ('log_message', ("log dall'auto",)), ('auto_done', (True,)), ('finished', ())]
    assert fake['ocr'].calls == []                       # nel ramo auto non si chiamano ocr_to_events/writeback
    fake['auto_ok'] = False
    w, ev = run(qt, strategy='auto')
    assert ('auto_done', (False,)) in sig(ev)


def test_writeback(qt, fake):
    w, ev = run(qt, mode='writeback', srt_text='1\nSRT', language='ita')
    assert fake['ocr'].calls == [('writeback', '1\nSRT', 'ita')]
    assert sig(ev) == [('writeback_done', (True,)), ('finished', ())]            # nessun log di intestazione
    fake['ocr'] = FakeOcr({'writeback_ok': False})
    w, ev = run(qt, mode='writeback')
    assert ('writeback_done', (False,)) in sig(ev)


def test_formato_non_supportato(qt, fake):
    from core.pgs_ocr import BitmapNotSupported as P
    from core.vobsub_ocr import BitmapNotSupported as V
    for exc in (P('pgs no'), V('vob no')):
        fake['ocr'] = FakeOcr({'raise': exc})
        w, ev = run(qt)
        assert sig(ev)[-2:] == [('unsupported', (str(exc),)), ('finished', ())]


def test_lingua_non_supportata(qt, fake):
    from core.pgs_types import UnsupportedLanguage
    fake['ocr'] = FakeOcr({'raise': UnsupportedLanguage('klingon')})
    w, ev = run(qt)
    assert sig(ev)[1:] == [('log_message', ('⚠ Tesseract: lingua non supportata, file saltato',)),
                           ('lang_unsupported', ('klingon',)), ('finished', ())]


def test_annullato_e_eccezione(qt, fake):
    fake['ocr'] = FakeOcr({'raise': InterruptedError()})
    w, ev = run(qt)
    assert sig(ev)[1:] == [('log_message', ('❌ OCR annullato',)), ('finished', ())]
    fake['ocr'] = FakeOcr({'raise': RuntimeError('boom')})
    w, ev = run(qt)
    assert sig(ev)[1:] == [('log_message', ('❌ OCR errore: boom',)), ('error', ('boom',)), ('finished', ())]
    fake['make_raise'] = OSError('niente motore')
    w, ev = run(qt)
    assert sig(ev) == [('log_message', ('❌ OCR errore: niente motore',)), ('error', ('niente motore',)), ('finished', ())]


def test_progresso_e_log_passano_dal_motore(qt, fake):
    from gui.ocr_worker import OcrWorker
    w = OcrWorker('/v/a.mkv', 'C', 'review')
    got = []
    w.progress.connect(lambda p, l: got.append(('p', p, l)))
    w.log_message.connect(lambda m: got.append(('l', m)))
    w._make_ocr()
    fake['log']('msg')
    fake['progress'](40, 'step')
    qt.processEvents()
    assert got == [('l', 'msg'), ('p', 40, 'step')]


def test_cancel(qt, fake):
    from gui.ocr_worker import OcrWorker
    w = OcrWorker('/v/a.mkv', 'C', 'review')
    w.cancel()
    assert w.is_cancelled is True                        # senza motore: nessun errore
    w._ocr = fake['ocr']
    w.cancel()
    assert fake['ocr'].cancelled is True


def test_attributi_pubblici(qt, fake):
    from gui.ocr_worker import OcrWorker
    w = OcrWorker('/v/a.mkv', 'C', 'auto', mode='writeback', srt_text='s', language='eng', kind='vobsub')
    assert (w.video_path, w.config, w.strategy, w.mode, w.srt_text, w.language, w.kind, w.is_cancelled) == \
        ('/v/a.mkv', 'C', 'auto', 'writeback', 's', 'eng', 'vobsub', False)
