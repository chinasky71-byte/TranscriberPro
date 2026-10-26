# -*- coding: utf-8 -*-
"""F0 del refactoring della coda (docs/STUDIO_REFACTORING_CODA.md): CARATTERIZZAZIONE di gui/workers.py::ProcessingWorker.

Fissa il comportamento di OGGI (non quello "giusto"): ogni passo successivo del refactoring deve lasciare questi test
invariati. Al posto di `core.pipeline_cli` gira un finto (queue_stub_pipeline.py); Qt in modalita' offscreen e config isolata.
I segnali si registrano con connessioni dirette, cosi' l'ordine registrato e' quello di emissione. I testi tradotti si confrontano
con tr(): i test non dipendono dalla lingua del sistema. Si saltano se PyQt6 (o libEGL) manca.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import _queue_testkit as kit  # noqa: E402

SIGNALS = ('progress', 'log_message', 'finished', 'file_completed', 'file_failed', 'file_started', 'file_progress',
           'file_steps', 'file_history_entry', 'error', 'queue_updated')


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


@pytest.fixture
def spy(monkeypatch):
    s = kit.PopenSpy()
    monkeypatch.setattr(subprocess, 'Popen', s)
    return s


@pytest.fixture
def caches(monkeypatch):
    """Conta le pulizie delle cache a fine coda (non si tocca la vera cache)."""
    import utils.cache_cleaner as cc
    calls = []
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches',
                        lambda log_callback=None: calls.append(1) or {'removed': ['x'], 'failed': []})
    return calls


class Rec:
    """Registra tutti i segnali di un ProcessingWorker, nell'ordine di emissione (thread-safe)."""

    def __init__(self, worker):
        from PyQt6.QtCore import Qt
        self.events = []
        self._lock = threading.Lock()
        for name in SIGNALS:
            getattr(worker, name).connect(self._slot(name), Qt.ConnectionType.DirectConnection)

    def _slot(self, name):
        def f(*a):
            with self._lock:
                self.events.append((name,) + tuple(a))
        return f

    def names(self):
        return [e[0] for e in self.events]

    def of(self, name):
        return [e[1:] for e in self.events if e[0] == name]

    def logs(self):
        return [e[1] for e in self.events if e[0] == 'log_message']

    def compact(self):
        """Sequenza senza log ne' anteprime dei passi: (segnale, nome file | valore)."""
        out = []
        for e in self.events:
            if e[0] in ('log_message', 'file_steps'):
                continue
            if e[0] == 'file_history_entry':
                out.append((e[0], e[1]['name']))
            elif e[0] in ('file_started', 'file_completed', 'file_failed'):
                out.append((e[0], Path(e[1]).name))
            elif e[0] == 'file_progress':
                out.append((e[0], Path(e[1]).name, e[2]))
            else:
                out.append((e[0],) + tuple(e[1:]))
        return out


def make_worker(paths):
    from PyQt6.QtCore import QMutex
    from gui.workers import ProcessingWorker
    queue = list(paths)
    w = ProcessingWorker(queue, QMutex())
    return w, queue, Rec(w)


def wait_for(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------------------------------------------- coda normale

def test_due_file_ok_sequenza_dei_segnali(qt, spy, caches, tmp_path):
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    w, queue, rec = make_worker(v)
    w.run()
    assert queue == []                                   # i file escono dalla coda quando vengono presi
    assert rec.compact() == [
        ('file_started', 'a_ok.mkv'),
        ('file_progress', 'a_ok.mkv', 1), ('file_progress', 'a_ok.mkv', 4), ('file_progress', 'a_ok.mkv', 11),
        ('file_progress', 'a_ok.mkv', 18), ('file_progress', 'a_ok.mkv', 98),
        ('file_history_entry', 'a_ok.mkv'), ('file_completed', 'a_ok.mkv'), ('progress', 50), ('queue_updated', 1),
        ('file_started', 'b_ok.mkv'),
        ('file_progress', 'b_ok.mkv', 1), ('file_progress', 'b_ok.mkv', 4), ('file_progress', 'b_ok.mkv', 11),
        ('file_progress', 'b_ok.mkv', 18), ('file_progress', 'b_ok.mkv', 98),
        ('file_history_entry', 'b_ok.mkv'), ('file_completed', 'b_ok.mkv'), ('progress', 100), ('queue_updated', 0),
        ('finished',)]
    assert (w.completed_files, w.failed_files, w.total_files_at_start) == (2, 0, 2)
    assert rec.of('error') == []
    assert len(caches) == 1                              # cache ripulite UNA volta, a coda conclusa


def test_anteprima_dei_passi_prima_e_dopo_ogni_evento(qt, spy, caches, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    w, _, rec = make_worker([v])
    w.run()
    steps = [e for e in rec.events if e[0] == 'file_steps']
    assert len(steps) == 7 and all(e[1] == v for e in steps)           # 1 iniziale + 5 eventi che cambiano lo stato + 1 finale
    # l'ordine: file_started, file_steps (iniziale) ... ultimo file_steps prima di file_history_entry
    names = rec.names()
    assert names.index('file_started') < names.index('file_steps') < names.index('file_history_entry')


def test_log_riga_per_riga_rumore_filtrato_e_diag_ram_inoltrato(qt, spy, caches, tmp_path):
    from utils.translations import tr
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    w, _, rec = make_worker([v])
    w.run()
    logs = rec.logs()
    stub = [l for l in logs if l.startswith('STUB') or l.startswith('[DIAG-RAM]')]
    assert [l.split(' ')[0] for l in stub] == ['STUB_ARGS', 'STUB_ENV', 'STUB', '[DIAG-RAM]', '[DIAG-RAM]', 'STUB', 'STUB']
    assert not any('Downloading:' in l or 'Using cache found in' in l for l in logs)     # rumore: solo nel log dell'app
    assert not any('STUB_STDERR' in l for l in logs)                                    # stderr: mai a schermo
    assert not any('@@TPEV@@' in l for l in logs)                                       # gli eventi non sono testo per l'utente
    assert tr('worker_start_single') in logs and tr('worker_completed').format(filename='a_ok.mkv') in logs
    assert logs[0] == tr('worker_start').format(n=1)
    assert logs[-2].count(tr('worker_done_header')) == 1                                # riepilogo finale...
    assert logs[-1].startswith('🗑️ Cache modelli liberata a fine coda')                # ...e poi la pulizia delle cache
    # la riga [DIAG-RAM] contiene "1. Passo" ma non muove la barra: il primo file_progress arriva dopo di lei
    assert logs.index([l for l in logs if l.startswith('[DIAG-RAM]')][0]) < logs.index('STUB riga di testo due')


def test_file_che_fallisce_non_ferma_la_coda(qt, spy, caches, tmp_path):
    from utils.translations import tr
    v = kit.make_videos(tmp_path, 'a_fail.mkv', 'b_ok.mkv', 'c_crash.mkv')
    w, queue, rec = make_worker(v)
    w.run()
    c = rec.compact()
    assert [e for e in c if e[0] in ('file_completed', 'file_failed')] == [
        ('file_failed', 'a_fail.mkv'), ('file_completed', 'b_ok.mkv'), ('file_failed', 'c_crash.mkv')]
    assert [e for e in c if e[0] == 'progress'] == [('progress', 33), ('progress', 66), ('progress', 100)]
    assert (w.completed_files, w.failed_files) == (1, 2)
    assert tr('worker_failed').format(filename='a_fail.mkv') in rec.logs() and tr('worker_hint') in rec.logs()
    assert [e for e in c if e[0] == 'file_history_entry'] == [('file_history_entry', 'b_ok.mkv')]   # solo i completati
    assert c[-1] == ('finished',)


def test_cronologia_ha_i_campi_attesi(qt, spy, caches, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    w, _, rec = make_worker([v])
    w.run()
    (entry,) = rec.of('file_history_entry')
    e = entry[0]
    assert set(e) == {'name', 'date_iso', 'src_lang', 'dst_lang', 'duration_seconds', 'size_bytes', 'srt_path', 'video_path'}
    assert (e['name'], e['src_lang'], e['dst_lang'], e['size_bytes'], e['srt_path'], e['video_path']) == (
        'a_ok.mkv', 'auto', 'ita', 10, v + '.it.srt', v)


def test_coda_vuota(qt, spy, caches):
    w, queue, rec = make_worker([])
    w.run()
    from utils.translations import tr
    assert rec.compact() == [('finished',)]
    assert rec.logs()[0] == tr('worker_start').format(n=0)
    assert spy.calls == [] and len(caches) == 1


# ---------------------------------------------------------------------------------------- il sottoprocesso (contratto da non cambiare)

def test_contratto_del_sottoprocesso(qt, spy, caches, tmp_path, monkeypatch):
    monkeypatch.delenv('PYTHONUTF8', raising=False)
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    w, _, _ = make_worker([v])
    w.run()
    (call,) = spy.calls
    assert call['argv'][:3] == [sys.executable, '-m', 'core.pipeline_cli'] and len(call['argv']) == 4
    kw = call['kwargs']
    assert Path(kw['cwd']) == ROOT
    assert (kw['stdout'], kw['stderr']) == (subprocess.PIPE, subprocess.PIPE)
    assert (kw['text'], kw['encoding'], kw['errors'], kw['bufsize']) == (True, 'utf-8', 'replace', 1)
    flags = 0
    for n in ('CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW'):
        flags |= getattr(subprocess, n, 0)
    assert kw['creationflags'] == flags
    env = kw['env']
    assert (env['PYTHONIOENCODING'], env['TP_SUBPROCESS'], env['TQDM_DISABLE'], env['TP_EVENTS']) == ('utf-8', '1', '1', '1')
    assert 'PYTHONUTF8' not in env                       # attiverebbe la UTF-8 mode nelle subprocess annidate
    added = {k for k in env if k not in os.environ}
    assert added == {'PYTHONIOENCODING', 'TP_SUBPROCESS', 'TQDM_DISABLE', 'TP_EVENTS'}
    a = call['args_json']
    assert set(a) == {'video_path', 'target_language', 'overrides', 'files_processed', 'result_path'}
    assert (a['video_path'], a['target_language'], a['overrides'], a['files_processed']) == (v, 'ita', {}, 0)
    assert not Path(a['result_path']).parent.exists()    # cartella IPC rimossa a fine file


def test_files_processed_cresce_di_file_in_file(qt, spy, caches, tmp_path):
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_fail.mkv', 'c_ok.mkv')
    w, _, _ = make_worker(v)
    w.run()
    assert [c['args_json']['files_processed'] for c in spy.calls] == [0, 1, 2]


# ------------------------------------------------------------------------------------------------------- eccezioni per file

def test_eccezioni_per_file_prese_insieme_al_file(qt, spy, caches, tmp_path):
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    w, _, rec = make_worker(v)
    w.job_overrides = {v[1]: {'target_language': 'eng', 'gender_correction_enabled': False, 'zzz': 1, 'mux_subtitle_into_video': 'no'}}
    w.run()
    a0, a1 = (c['args_json'] for c in spy.calls)
    assert (a0['target_language'], a0['overrides']) == ('ita', {})
    assert (a1['target_language'], a1['overrides']) == ('eng', {'target_language': 'eng', 'gender_correction_enabled': False})
    assert w.job_overrides == {}                         # tolte dal dizionario nel momento in cui il file e' preso
    (entry,) = [e for e in rec.of('file_history_entry') if e[0]['name'] == 'b_ok.mkv']
    assert entry[0]['dst_lang'] == 'eng'


# ------------------------------------------------------------------------------------- coda dinamica (mentre il worker lavora)

def test_rimozione_di_un_file_in_attesa_con_note_removed(qt, spy, caches, tmp_path):
    from PyQt6.QtCore import QMutexLocker, Qt
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv', 'c_ok.mkv')
    w, queue, rec = make_worker(v)

    def on_started(path):
        if path == v[0]:
            with QMutexLocker(w.queue_mutex):
                queue.remove(v[2])
            w.note_removed()
    w.file_started.connect(on_started, Qt.ConnectionType.DirectConnection)
    w.run()
    c = rec.compact()
    assert [e[1] for e in c if e[0] == 'file_completed'] == ['a_ok.mkv', 'b_ok.mkv']      # c_ok non e' mai lavorato
    assert [e for e in c if e[0] == 'progress'] == [('progress', 50), ('progress', 100)]   # totale sceso a 2: la barra arriva al 100%
    assert w.total_files_at_start == 2


def test_riordino_sul_posto_mentre_lavora(qt, spy, caches, tmp_path):
    from PyQt6.QtCore import QMutexLocker, Qt
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv', 'c_ok.mkv')
    w, queue, rec = make_worker(v)

    def on_started(path):
        if path == v[0]:
            with QMutexLocker(w.queue_mutex):
                queue[:] = [v[2], v[1]]                  # in place: il worker tiene lo stesso oggetto lista
    w.file_started.connect(on_started, Qt.ConnectionType.DirectConnection)
    w.run()
    assert [Path(p[0]).name for p in rec.of('file_started')] == ['a_ok.mkv', 'c_ok.mkv', 'b_ok.mkv']


def test_file_aggiunto_mentre_lavora_viene_preso(qt, spy, caches, tmp_path):
    from PyQt6.QtCore import QMutexLocker, Qt
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    w, queue, rec = make_worker([v[0]])

    def on_started(path):
        if path == v[0]:
            with QMutexLocker(w.queue_mutex):
                queue.append(v[1])
    w.file_started.connect(on_started, Qt.ConnectionType.DirectConnection)
    w.run()
    assert [Path(p[0]).name for p in rec.of('file_completed')] == ['a_ok.mkv', 'b_ok.mkv']
    assert w.total_files_at_start == 1                   # il totale e' quello iniziale: con file aggiunti si limita a 100
    assert [e for e in rec.compact() if e[0] == 'progress'] == [('progress', 100), ('progress', 100)]


# ----------------------------------------------------------------------------------------------------------------- Stop

def _run_threaded(w):
    w.start()


def test_stop_a_meta_file_il_corrente_fallisce_i_restanti_restano_in_coda(qt, spy, caches, tmp_path):
    from utils.translations import tr
    v = kit.make_videos(tmp_path, 'a_slow.mkv', 'b_ok.mkv')
    w, queue, rec = make_worker(v)
    w.start()
    assert wait_for(lambda: any('STUB_SLOW_STARTED' in l for l in rec.logs()))
    w.cancel()
    assert w.wait(20000)
    c = rec.compact()
    assert [e for e in c if e[0] in ('file_started', 'file_completed', 'file_failed', 'finished')] == [
        ('file_started', 'a_slow.mkv'), ('file_failed', 'a_slow.mkv'), ('finished',)]
    assert queue == [v[1]]                               # b_ok non e' stato toccato
    assert spy.procs[0].poll() is not None               # il figlio e' morto
    assert tr('worker_cancelled_file').format(filename='a_slow.mkv') in rec.logs()
    assert tr('worker_cancelled_user') in rec.logs()
    assert (w.completed_files, w.failed_files) == (0, 1)
    assert len(caches) == 1                              # le cache si ripuliscono comunque a fine coda (anche dopo Stop)


def test_stop_ripulisce_il_residuo_converting(qt, spy, caches, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_conv.mkv')
    w, queue, rec = make_worker([v])
    w.start()
    assert wait_for(lambda: any('STUB_SLOW_STARTED' in l for l in rec.logs()))
    assert Path(v + '.converting').exists()
    w.cancel()
    assert w.wait(20000)
    assert not Path(v + '.converting').exists()


def test_su_successo_il_residuo_converting_non_viene_toccato(qt, spy, caches, tmp_path):
    """Differenza con il headless (che lo ripulisce sempre): la GUI lo ripulisce solo se annullato."""
    (v,) = kit.make_videos(tmp_path, 'a_resid.mkv')
    w, _, _ = make_worker([v])
    w.run()
    assert Path(v + '.converting').exists()


def test_stop_con_sottoprocesso_non_partito_e_cancel_senza_processo(qt, spy, caches):
    w, _, rec = make_worker([])
    w.cancel()                                           # nessun figlio: non solleva
    assert w.is_cancelled is True


def test_spawn_fallito_il_file_fallisce_e_la_coda_prosegue(qt, caches, monkeypatch, tmp_path):
    from utils.translations import tr

    def boom(*a, **k):
        raise OSError('no spawn')
    monkeypatch.setattr(subprocess, 'Popen', boom)
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    w, queue, rec = make_worker(v)
    w.run()
    assert [e[0] for e in rec.compact() if e[0] in ('file_completed', 'file_failed')] == ['file_failed', 'file_failed']
    assert tr('worker_critical_error').format(filename='a_ok.mkv', error='no spawn') in rec.logs()
    assert queue == []


def test_pulizia_cache_che_solleva_non_blocca_il_finished(qt, spy, monkeypatch, tmp_path):
    import utils.cache_cleaner as cc

    def boom(log_callback=None):
        raise RuntimeError('cache')
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches', boom)
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    w, _, rec = make_worker([v])
    w.run()
    assert rec.names()[-1] == 'finished'


def test_finished_e_il_segnale_del_worker_non_quello_di_qthread(qt, spy, caches):
    """`finished` e' ridefinito nel worker (oscura QThread.finished): QueueService lo collega a worker_finished."""
    from gui.workers import ProcessingWorker
    from PyQt6.QtCore import QThread
    assert 'finished' in ProcessingWorker.__dict__ and ProcessingWorker.finished is not QThread.finished
