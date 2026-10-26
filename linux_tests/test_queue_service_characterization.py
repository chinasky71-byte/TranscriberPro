# -*- coding: utf-8 -*-
"""F0/F3 del refactoring della coda: CARATTERIZZAZIONE di gui/services/queue_service.py::QueueService.

Descrive il comportamento che il servizio aveva PRIMA dello spostamento della coda in core/jobs (questi test passano identici sul
codice vecchio e su quello nuovo). Usa worker finti (lo stesso `worker_factory` che usa la suite locale del proprietario) e un
caso di integrazione con il vero ProcessingWorker, il finto pipeline_cli e un vero ciclo di eventi Qt (connessioni in coda).
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import _queue_testkit as kit  # noqa: E402


@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    cfg.reset_config()


def make_fake_worker_class():
    from PyQt6.QtCore import QObject, pyqtSignal

    class FakeWorker(QObject):
        progress = pyqtSignal(int)
        log_message = pyqtSignal(str)
        finished = pyqtSignal()
        file_completed = pyqtSignal(str)
        file_failed = pyqtSignal(str)
        file_started = pyqtSignal(str)
        file_progress = pyqtSignal(str, int)
        file_steps = pyqtSignal(str, object)
        file_history_entry = pyqtSignal(dict)
        error = pyqtSignal(str)
        queue_updated = pyqtSignal(int)
        instances = []

        def __init__(self, queue, mutex):
            super().__init__()
            self.queue, self.mutex = queue, mutex
            self.started = self.cancelled = False
            self.removed = 0
            FakeWorker.instances.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

        def note_removed(self, n=1):
            self.removed += n
    return FakeWorker


@pytest.fixture
def svc(qt):
    from gui.services.queue_service import QueueService
    FW = make_fake_worker_class()
    FW.instances = []
    s = QueueService(worker_factory=FW)
    rows = []                                         # righe della vista: i dict in UserRole
    s.jobs_provider = lambda: rows
    s.job_added.connect(lambda rec: rows.append(rec.to_item_data()))
    s._rows = rows
    s._fw = FW
    return s


def test_enqueue_senza_doppioni_e_con_ordine(svc):
    assert svc.enqueue(['/a.mkv', '/b.mkv', '/a.mkv']) == ['/a.mkv', '/b.mkv']
    assert svc.processing_queue == ['/a.mkv', '/b.mkv'] and svc.remaining() == 2
    assert svc.enqueue(['/b.mkv', '/c.mkv']) == ['/c.mkv']
    assert svc.processing_queue == ['/a.mkv', '/b.mkv', '/c.mkv']
    assert [r['path'] for r in svc._rows] == ['/a.mkv', '/b.mkv', '/c.mkv']      # una riga per file aggiunto


def test_enqueue_solo_file_esistenti(svc, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a.mkv')
    assert svc.enqueue([v, str(tmp_path / 'manca.mkv'), str(tmp_path)], only_files=True) == [v]


def test_file_in_lavorazione_non_si_riaccoda(svc):
    svc.enqueue(['/a.mkv'])
    svc.processing_queue.remove('/a.mkv')                        # il worker l'ha preso
    svc._rows[0]['status'] = 'processing'
    assert svc.is_active('/a.mkv') and svc.enqueue(['/a.mkv']) == []
    svc._rows[0]['status'] = 'completed'
    assert not svc.is_active('/a.mkv') and svc.enqueue(['/a.mkv']) == ['/a.mkv']


def test_enqueue_scanned_stessa_regola(svc):
    assert svc.enqueue_scanned('/a.mkv', '1 GB') is True and svc.enqueue_scanned('/a.mkv') is False
    assert svc.processing_queue == ['/a.mkv']


def test_lista_e_dizionario_non_si_riassegnano_mai(svc):
    q, o, m = svc.processing_queue, svc.job_overrides, svc.queue_mutex
    svc.enqueue(['/a.mkv', '/b.mkv'])
    svc.set_overrides(['/a.mkv'], 'target_language', 'eng')
    svc.reorder(['/b.mkv', '/a.mkv'], '/b.mkv')
    svc.remove('/a.mkv')
    svc.clear()
    assert svc.processing_queue is q and svc.job_overrides is o and svc.queue_mutex is m


def test_riordino(svc):
    svc.enqueue(['/a.mkv', '/b.mkv', '/c.mkv'])
    seen = []
    svc.queue_reordered.connect(lambda: seen.append(1))
    assert svc.reorder(['/c.mkv', '/a.mkv'], '/c.mkv') is True
    assert svc.processing_queue == ['/c.mkv', '/a.mkv', '/b.mkv']        # i non citati restano in fondo, nel loro ordine
    assert seen == [1]
    assert svc.reorder(['/b.mkv', '/zzz.mkv'], '/zzz.mkv') is False      # la riga spostata non e' in coda: annullato
    assert svc.processing_queue == ['/c.mkv', '/a.mkv', '/b.mkv'] and seen == [1]


def test_rimozione_di_un_file_in_attesa(svc):
    svc.enqueue(['/a.mkv', '/b.mkv'])
    svc.set_overrides(['/b.mkv'], 'target_language', 'eng')
    removed, remaining = [], []
    svc.job_removed.connect(removed.append)
    svc.remaining_changed.connect(remaining.append)
    assert svc.remove('/b.mkv') is True and svc.remove('/b.mkv') is False and svc.remove('/zzz') is False
    assert svc.processing_queue == ['/a.mkv'] and svc.job_overrides == {}
    assert removed == ['/b.mkv'] and remaining == [1]


def test_rimozione_durante_la_lavorazione_avvisa_il_worker(svc):
    svc.enqueue(['/a.mkv', '/b.mkv'])
    svc.start()
    w = svc._fw.instances[-1]
    assert svc.remove('/b.mkv') is True and w.removed == 1


def test_eccezioni_per_file(svc):
    svc.enqueue(['/a.mkv', '/b.mkv'])
    changed = []
    svc.job_overrides_changed.connect(changed.append)
    assert svc.set_overrides(['/a.mkv', '/zzz.mkv'], 'target_language', 'eng') == ['/a.mkv']      # i non in coda sono saltati
    assert svc.overrides_of('/a.mkv') == {'target_language': 'eng'} and changed == [['/a.mkv']]
    assert svc.set_overrides(['/a.mkv'], 'target_language', 'xxx') == []                         # valore non ammesso
    assert svc.set_overrides(['/a.mkv'], 'gender_correction_enabled', False) == ['/a.mkv']
    assert svc.overrides_of('/a.mkv') == {'target_language': 'eng', 'gender_correction_enabled': False}
    assert svc.set_overrides(['/a.mkv'], 'target_language', None) == ['/a.mkv']                  # None toglie
    assert svc.overrides_of('/a.mkv') == {'gender_correction_enabled': False}
    svc.set_overrides(['/a.mkv'], 'gender_correction_enabled', None)
    assert svc.job_overrides == {}                                                               # vuote: niente chiave
    svc.set_overrides(['/b.mkv'], 'target_language', 'eng')
    svc.remove('/b.mkv')
    svc.enqueue(['/b.mkv'])
    assert svc.overrides_of('/b.mkv') == {}                                                       # riaccodato: riparte vuoto


def test_svuota_rifiutato_durante_l_elaborazione(svc):
    svc.enqueue(['/a.mkv'])
    cleared = []
    svc.jobs_cleared.connect(lambda: cleared.append(1))
    svc.is_processing = True
    assert svc.clear() is False and svc.processing_queue == ['/a.mkv'] and cleared == []
    svc.is_processing = False
    assert svc.clear() is True and svc.processing_queue == [] and cleared == [1]


def test_can_start_precedenza(svc):
    from gui.services.queue_service import StartVerdict as V
    assert svc.can_start() == V.EMPTY
    svc.enqueue(['/a.mkv'])
    assert svc.can_start() == V.OK
    svc.sync_active = True
    assert svc.can_start() == V.SYNC
    svc.glossary_active = True
    assert svc.can_start() == V.GLOSSARY
    assert svc.can_start(ocr_running=True) == V.OCR
    svc.clear()
    assert svc.can_start(ocr_running=True) == V.EMPTY


def test_start_stop_e_collegamento_dei_segnali(svc):
    svc.enqueue(['/a.mkv'])
    started = []
    svc.processing_started.connect(started.append)
    svc.start()
    w = svc._fw.instances[-1]
    assert w.started and svc.is_processing and svc.worker is w and started == [1]
    assert w.queue is svc.processing_queue and w.mutex is svc.queue_mutex          # STESSA lista e STESSO mutex (nessuna copia)
    assert w.job_overrides is svc.job_overrides
    got = []
    svc.file_completed.connect(lambda p: got.append(('c', p)))
    svc.file_failed.connect(lambda p: got.append(('f', p)))
    svc.worker_error.connect(lambda m: got.append(('e', m)))
    w.file_completed.emit('/a.mkv')
    w.file_failed.emit('/b.mkv')
    w.error.emit('boom')
    assert got == [('c', '/a.mkv'), ('f', '/b.mkv'), ('e', 'boom')]
    assert (svc.completed_count, svc.error_count) == (1, 2)                         # il worker_error conta come errore
    finished = []
    svc.processing_finished.connect(lambda: finished.append(1))
    w.finished.emit()
    assert svc.is_processing is False and finished == [1]
    svc.stop()
    assert w.cancelled


def test_statistiche_ed_eta(svc):
    from gui.services.formatting import EN_DASH
    svc.enqueue(['/a.mkv', '/b.mkv'])
    s = svc.stats()
    assert (s.completed, s.in_progress, s.queued, s.errors, s.eta) == (0, 0, 2, 0, EN_DASH)
    assert svc.elapsed_text() is None


# ------------------------------------------------------------------------------------------- integrazione con il vero worker

def test_integrazione_servizio_worker_vero_e_finto_pipeline(qt, tmp_path, monkeypatch):
    from PyQt6.QtCore import QCoreApplication
    from gui.services.queue_service import QueueService
    import utils.cache_cleaner as cc
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches', lambda log_callback=None: {'removed': [], 'failed': []})
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_fail.mkv')
    s = QueueService()
    rows = []
    s.jobs_provider = lambda: rows
    s.job_added.connect(lambda rec: rows.append(rec.to_item_data()))
    ev = []
    for n in ('file_started', 'file_completed', 'file_failed', 'processing_finished', 'history_entry'):
        getattr(s, n).connect((lambda n: lambda *a: ev.append((n,) + tuple(Path(x).name if isinstance(x, str) else x for x in a)
                                                           if n != 'history_entry' else (n, a[0]['name'])))(n))
    s.enqueue(v)
    s.start()
    t0 = time.time()
    while s.is_processing and time.time() - t0 < 30:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    s.worker.wait(5000)
    QCoreApplication.processEvents()
    assert ev == [('file_started', 'a_ok.mkv'), ('history_entry', 'a_ok.mkv'), ('file_completed', 'a_ok.mkv'),
                  ('file_started', 'b_fail.mkv'), ('file_failed', 'b_fail.mkv'), ('processing_finished',)]
    assert (s.completed_count, s.error_count, s.is_processing, s.processing_queue) == (1, 1, False, [])
