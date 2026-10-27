# -*- coding: utf-8 -*-
"""G2 (fase 0 della web UI): CARATTERIZZAZIONE di gui/sync_worker.py::SyncWorker.

Passa identica sul codice vecchio e su quello con la logica in core/jobs/sync_single.py. Il sincronizzatore e' un finto (nessun
modello): ordine dei segnali, percentuali, esito, annullamento, thread di emissione."""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def fake_sync(monkeypatch, behaviour):
    """Installa un core.subtitle_synchronizer finto. behaviour(sync) -> bool (esito) e puo' sollevare."""
    made = []

    class FakeSync:
        def __init__(self, video_path, external_srt_path, output_path, log_callback, progress_callback):
            self.args = (video_path, external_srt_path, output_path)
            self.log, self.prog = log_callback, progress_callback
            self._output_path = Path('/out/' + Path(external_srt_path).stem + '.synced.it.srt')
            self.cancelled = False
            made.append(self)

        def synchronize(self):
            return behaviour(self)

        def cancel(self):
            self.cancelled = True

    mod = types.ModuleType('core.subtitle_synchronizer')
    mod.SubtitleSynchronizer = FakeSync
    monkeypatch.setitem(sys.modules, 'core.subtitle_synchronizer', mod)
    return made


def run(qt, **kw):
    from PyQt6.QtCore import QThread, Qt
    from gui.sync_worker import SyncWorker
    w = SyncWorker('/v/Film.mkv', '/v/Film.it.srt', **kw)
    main = QThread.currentThread()
    ev = []
    for sig in ('progress', 'log_message', 'finished', 'file_progress', 'file_completed', 'file_started', 'error', 'output_ready'):
        getattr(w, sig).connect(lambda *a, _s=sig: ev.append((_s, a, QThread.currentThread() == main)),
                                Qt.ConnectionType.DirectConnection)
    return w, ev


def go(w, qt):
    w.start()
    assert w.wait(20000)
    qt.processEvents()


def test_successo(qt, monkeypatch):
    def beh(s):
        s.log('1. Estrazione')
        s.prog(25)
        s.log('\n3. Allineamento')
        s.log('nome "1. Titolo.synced.it.srt" nel mezzo')
        s.prog(90)
        return True
    made = fake_sync(monkeypatch, beh)
    w, ev = run(qt, output_path='/o.srt')
    go(w, qt)
    assert made[0].args == ('/v/Film.mkv', '/v/Film.it.srt', '/o.srt')
    assert [(e[0], e[1]) for e in ev] == [
        ('file_started', ('/v/Film.mkv',)),
        ('log_message', ('1. Estrazione',)), ('file_progress', ('/v/Film.mkv', 10)),
        ('progress', (25,)), ('file_progress', ('/v/Film.mkv', 25)),
        ('log_message', ('\n3. Allineamento',)), ('file_progress', ('/v/Film.mkv', 80)),
        ('log_message', ('nome "1. Titolo.synced.it.srt" nel mezzo',)),
        ('progress', (90,)), ('file_progress', ('/v/Film.mkv', 90)),
        ('output_ready', (str(Path('/out/Film.it.synced.it.srt')),)), ('file_completed', ('/v/Film.mkv',)),
        ('finished', ()),
    ]
    assert all(not e[2] for e in ev)


def test_fallimento_senza_eccezione(qt, monkeypatch):
    fake_sync(monkeypatch, lambda s: False)
    w, ev = run(qt)
    go(w, qt)
    assert [e[0] for e in ev] == ['file_started', 'error', 'finished']
    assert ev[1][1] == ('Sincronizzazione fallita — controlla il log per i dettagli.',)


def test_eccezione(qt, monkeypatch):
    def beh(s):
        raise RuntimeError('esploso')
    fake_sync(monkeypatch, beh)
    w, ev = run(qt)
    go(w, qt)
    assert [(e[0], e[1]) for e in ev] == [('file_started', ('/v/Film.mkv',)), ('error', ('esploso',)), ('finished', ())]


def test_annullamento(qt, monkeypatch):
    made = fake_sync(monkeypatch, lambda s: (setattr(s, 'cancelled', False) or False))
    w, ev = run(qt)
    w.cancel()                                  # prima di partire: nessun sincronizzatore ancora
    assert w.is_cancelled and w._synchronizer is None
    go(w, qt)
    assert [e[0] for e in ev] == ['file_started', 'finished']      # annullato: nessun errore (il worker lo sa gia')
    assert made[0].cancelled is False                               # il sincronizzatore nasce dopo il cancel


def test_cancel_in_corsa_inoltra_al_sincronizzatore(qt, monkeypatch):
    holder = {}

    def beh(s):
        holder['w'].cancel()
        return False
    made = fake_sync(monkeypatch, beh)
    w, ev = run(qt)
    holder['w'] = w
    go(w, qt)
    assert made[0].cancelled is True
    assert [e[0] for e in ev] == ['file_started', 'finished']
