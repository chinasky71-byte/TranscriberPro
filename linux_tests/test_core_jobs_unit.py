# -*- coding: utf-8 -*-
"""Moduli di core/jobs (senza Qt): JobQueue (anche con thread concorrenti), FileRunner, QueueEngine, cronologia.
Al posto di `core.pipeline_cli` gira il finto di queue_stub_pipeline.py."""
import json
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
from core.jobs import history_store  # noqa: E402
from core.jobs.engine import QueueEngine, QueueListener, level_of  # noqa: E402
from core.jobs.file_progress import FileProgress  # noqa: E402
from core.jobs.file_runner import FileHooks, FileRunner, creation_flags  # noqa: E402
from core.jobs.job_queue import JobQueue  # noqa: E402


# ----------------------------------------------------------------------------------------------------------------- JobQueue

def test_job_queue_add_take_remove_reorder():
    q = JobQueue()
    assert q.add('/a') and q.add('/b') and q.add('/c') and not q.add('/a')
    assert q.snapshot() == ['/a', '/b', '/c'] and len(q) == 3 and q.contains('/b')
    assert q.reorder(['/c', '/a'], '/c') and q.snapshot() == ['/c', '/a', '/b']
    assert q.reorder(['/b'], '/zzz') is False and q.snapshot() == ['/c', '/a', '/b']
    assert q.remove('/a') and not q.remove('/a')
    assert q.take_next() == ('/c', {}) and q.take_next() == ('/b', {}) and q.take_next() is None


def test_job_queue_accept_e_riaccodo_azzera_le_eccezioni():
    q = JobQueue()
    assert q.add('/a', accept=lambda p: False) is False and len(q) == 0
    q.add('/a')
    assert q.set_override(['/a', '/zzz'], 'target_language', 'eng') == ['/a']
    assert q.overrides_of('/a') == {'target_language': 'eng'}
    assert q.take_next() == ('/a', {'target_language': 'eng'}) and q.overrides == {}      # prelievo + eccezioni: una operazione
    q.add('/a')
    q.set_override(['/a'], 'target_language', 'eng')
    q.remove('/a')
    q.add('/a')
    assert q.overrides_of('/a') == {}
    q.set_override(['/a'], 'x', 1)
    q.set_override(['/a'], 'x', None)
    assert q.overrides == {}
    q.clear()
    assert len(q) == 0


def test_job_queue_lista_e_dizionario_sono_sempre_gli_stessi_oggetti():
    q = JobQueue()
    items, ov = q.items, q.overrides
    q.add('/a')
    q.add('/b')
    q.reorder(['/b', '/a'], '/b')
    q.set_override(['/a'], 'k', 1)
    q.take_next()
    q.clear()
    assert q.items is items and q.overrides is ov


def test_job_queue_lock_iniettato_e_riferimento_condiviso():
    class L:
        n = 0

        def __enter__(self):
            L.n += 1

        def __exit__(self, *a):
            return False
    shared = ['/x']
    q = JobQueue(lock=L(), items=shared)
    q.add('/y')
    assert shared == ['/x', '/y'] and L.n >= 1                  # stessa lista: chi la tiene la vede cambiare


def test_job_queue_prelievi_concorrenti_nessun_file_perso_ne_doppio():
    q = JobQueue()
    N = 2000
    for i in range(N):
        q.add(f'/f{i}')
    got, lock = [], threading.Lock()

    def worker():
        while True:
            it = q.take_next()
            if it is None:
                return
            with lock:
                got.append(it[0])
    ts = [threading.Thread(target=worker) for _ in range(8)]
    stopper = threading.Thread(target=lambda: [q.reorder(q.snapshot()[::-1], q.snapshot()[0]) for _ in range(200) if q.snapshot()])
    [t.start() for t in ts]
    stopper.start()
    [t.join() for t in ts]
    stopper.join()
    assert sorted(got) == sorted(f'/f{i}' for i in range(N)) and len(set(got)) == N


# --------------------------------------------------------------------------------------------------------------- FileRunner

@pytest.fixture
def spy(monkeypatch):
    s = kit.PopenSpy()
    monkeypatch.setattr(subprocess, 'Popen', s)
    return s


class Collect(FileHooks):
    def __init__(self):
        self.raw, self.text, self.noise, self.events, self.progress, self.err, self.spawned = [], [], [], [], [], [], []

    def on_spawn(self, proc): self.spawned.append(proc)
    def on_raw(self, line): self.raw.append(line)
    def on_text(self, line): self.text.append(line)
    def on_noise(self, line): self.noise.append(line)
    def on_event(self, kind, fields): self.events.append(kind)
    def on_progress(self, value, phase, changed): self.progress.append((value, changed))
    def on_stderr(self, line): self.err.append(line)


def run(tmp_path, name, **kw):
    (v,) = kit.make_videos(tmp_path, name)
    h = Collect()
    r = FileRunner().run(v, 'ita', 0, progress=FileProgress('ita'), hooks=h, **kw)
    return v, r, h


def test_runner_ok_ganci_e_esito(spy, tmp_path):
    v, r, h = run(tmp_path, 'a_ok.mkv')
    assert (r.success, r.cancelled, r.returncode, r.output, r.spawn_error) == (True, False, 0, v + '.it.srt', None)
    assert r.duration > 0 and len(h.spawned) == 1
    assert h.events == ['phase', 'phase', 'phase', 'bar', 'bar', 'phase']
    assert [t.split(' ')[0] for t in h.text] == ['STUB_ARGS', 'STUB_ENV', 'STUB', '[DIAG-RAM]', '[DIAG-RAM]', 'STUB', 'STUB']
    assert h.noise == ['Downloading: modello.bin', 'Using cache found in /tmp/x']
    assert any('STUB_STDERR' in e for e in h.err)
    assert any(l.startswith('@@TPEV@@') for l in h.raw) and all(l.endswith('\n') for l in h.raw)    # on_raw: tutto, con a capo
    assert [v for v, ch in h.progress if ch] == [1, 4, 11, 18, 98]                                  # i punti in cui la barra aumenta


def test_runner_diag_ram_muove_la_barra_solo_se_richiesto(spy, tmp_path):
    _, _, h = run(tmp_path, 'a_ok.mkv', feed_diag_progress=True)
    assert [v for v, ch in h.progress if ch] == [1, 4, 17, 18, 98]


def test_runner_esiti_non_ok_e_overrides_opzionali(spy, tmp_path):
    _, r, _ = run(tmp_path, 'a_fail.mkv')
    assert (r.success, r.returncode, r.output) == (False, 1, '')
    _, r, _ = run(tmp_path, 'b_crash.mkv')
    assert (r.success, r.returncode, r.output) == (False, 3, None)
    assert 'overrides' not in spy.calls[0]['args_json'] and 'overrides' not in spy.calls[1]['args_json']   # None: chiave assente
    run(tmp_path, 'c_ok.mkv', overrides={'target_language': 'eng'})
    assert spy.calls[2]['args_json']['overrides'] == {'target_language': 'eng'}


def test_runner_spawn_fallito(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError('no spawn')
    monkeypatch.setattr(subprocess, 'Popen', boom)
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    r = FileRunner().run(v, 'ita', 0, progress=FileProgress('ita'))
    assert (r.success, r.spawn_error) == (False, 'no spawn')
    with pytest.raises(OSError):
        FileRunner().run(v, 'ita', 0, progress=FileProgress('ita'), raise_on_spawn_error=True)


def test_runner_cancel_da_un_altro_thread(spy, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_conv.mkv')
    h = Collect()
    runner = FileRunner()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=runner.run(v, 'ita', 0, progress=FileProgress('ita'), hooks=h)))
    t.start()
    t0 = time.time()
    while not any('STUB_SLOW_STARTED' in x for x in h.text) and time.time() - t0 < 20:
        time.sleep(0.05)
    runner.cancel()
    t.join(20)
    assert out['r'].cancelled and out['r'].success is False
    assert spy.procs[0].poll() is not None and not Path(v + '.converting').exists()      # fermato: residuo ripulito


def test_runner_is_cancelled_callable_ferma_alla_riga_successiva(spy, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    h = Collect()
    r = FileRunner().run(v, 'ita', 0, progress=FileProgress('ita'), hooks=h, is_cancelled=lambda: len(h.text) >= 2)
    assert r.cancelled and len(h.text) == 2


def test_runner_contratto_flag_e_ambiente(spy, tmp_path, monkeypatch):
    monkeypatch.delenv('PYTHONUTF8', raising=False)
    run(tmp_path, 'a_ok.mkv')
    kw = spy.calls[0]['kwargs']
    assert kw['creationflags'] == creation_flags()
    assert {k for k in kw['env'] if k not in os.environ} == {'PYTHONIOENCODING', 'TP_SUBPROCESS', 'TQDM_DISABLE', 'TP_EVENTS'}


# ------------------------------------------------------------------------------------------------------------------ motore

class Rec(QueueListener):
    def __init__(self):
        self.ev = []

    def __getattribute__(self, name):
        if name.startswith('on_'):
            ev = object.__getattribute__(self, 'ev')
            return lambda *a: ev.append((name,) + tuple(Path(x).name if isinstance(x, str) and '/' in x and name != 'on_log' else x
                                                         for x in a if name not in ('on_file_steps', 'on_history')))
        return object.__getattribute__(self, name)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    import utils.cache_cleaner as cc
    calls = []
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches', lambda log_callback=None: calls.append(1) or {'removed': [], 'failed': []})
    yield calls
    cfg.reset_config()


def test_motore_senza_qt_ciclo_completo(spy, isolated, tmp_path):
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_fail.mkv')
    q = JobQueue()
    [q.add(p) for p in v]
    rec = Rec()
    eng = QueueEngine(q, rec)
    eng.run()
    names = [e[0] for e in rec.ev]
    assert [e for e in rec.ev if e[0] in ('on_file_started', 'on_file_completed', 'on_file_failed', 'on_file_error')] == [
        ('on_file_started', 'a_ok.mkv'), ('on_file_completed', 'a_ok.mkv'),
        ('on_file_started', 'b_fail.mkv'), ('on_file_error', 'b_fail.mkv', 'exit code 1'), ('on_file_failed', 'b_fail.mkv')]
    assert names[-1] == 'on_finished' and (eng.completed_files, eng.failed_files, eng.total_files_at_start) == (1, 1, 2)
    assert [e[1] for e in rec.ev if e[0] == 'on_progress'] == [50, 100] and isolated == [1]


def test_motore_check_exists_e_cache_disattivate(spy, isolated, tmp_path):
    q = JobQueue()
    q.add(str(tmp_path / 'manca.mkv'))
    rec = Rec()
    QueueEngine(q, rec, check_exists=True, cleanup_caches=False).run()
    assert spy.calls == [] and isolated == []
    assert [e for e in rec.ev if e[0] in ('on_file_error', 'on_file_failed')][0][2] != ''


def test_motore_eccezione_in_un_file_non_ferma_la_coda(isolated, tmp_path, monkeypatch):
    import core.jobs.file_runner as fr
    real = fr.FileRunner.run
    n = {'i': 0}

    def fake(self, *a, **k):
        n['i'] += 1
        if n['i'] == 1:
            raise RuntimeError('boom')
        return real(self, *a, **k)
    monkeypatch.setattr(fr.FileRunner, 'run', fake)
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    q = JobQueue()
    [q.add(p) for p in v]
    rec = Rec()
    QueueEngine(q, rec).run()
    assert [(e[0], e[-1]) for e in rec.ev if e[0] in ('on_file_error', 'on_file_completed')] == [
        ('on_file_error', 'RuntimeError: boom'), ('on_file_completed', 'b_ok.mkv')]


def test_level_of():
    assert level_of('❌ x failed') == 'ERROR' and level_of('  ⚠️ Hint') == 'WARNING' and level_of('STUB ok') == 'INFO'
    assert level_of('') == 'INFO' and level_of('🗑️ Cache') == 'INFO'


# ---------------------------------------------------------------------------------------------------------------- cronologia

def test_cronologia_append_atomica_e_formato_della_gui(tmp_path):
    p = tmp_path / 'sub' / 'history.json'
    assert history_store.append_entry({'name': 'a', 'x': 'è'}, p) and history_store.append_entry({'name': 'b'}, p)
    assert json.loads(p.read_text(encoding='utf-8')) == [{'name': 'a', 'x': 'è'}, {'name': 'b'}]
    assert 'è' in p.read_text(encoding='utf-8') and p.read_text(encoding='utf-8').startswith('[\n  {')       # ensure_ascii=False, indent=2
    p.write_text('non json', encoding='utf-8')
    assert history_store.append_entry({'name': 'c'}, p) and json.loads(p.read_text(encoding='utf-8')) == [{'name': 'c'}]   # come la GUI
    assert list(p.parent.glob('*.tmp')) == []


def test_cronologia_percorso_di_default(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    assert history_store.history_path() == tmp_path / '.transcriberpro' / 'history.json'
