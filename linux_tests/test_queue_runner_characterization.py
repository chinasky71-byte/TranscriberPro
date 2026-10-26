# -*- coding: utf-8 -*-
"""
Coda headless (core/queue_runner.py): comportamento fissato dal refactoring della coda (docs/STUDIO_REFACTORING_CODA.md).

Nata come caratterizzazione di F0 (test sul vecchio `run_one`); con F3 il headless usa lo STESSO motore della GUI
(core/jobs/engine.py) e questi test cambiano SOLO dove il proprietario ha deciso un comportamento nuovo (26/10/2026):
  - i log sono quelli della GUI (stessi testi, rumore filtrato) preceduti da [INFO]/[WARNING]/[ERROR], non piu' il flusso grezzo;
  - cronologia (history.json) e anteprima dei passi (`current.steps` nel file di stato) come nella GUI;
  - pulizia delle cache a fine coda come la GUI (`--keep-caches` per evitarla);
  - a pipeline_cli si passano anche le eccezioni per file (`overrides`, vuote dalla riga di comando);
  - la barra non legge piu' le righe [DIAG-RAM] (come la GUI); il residuo <video>.converting si toglie solo se fermato (come la GUI);
  - un fallimento ha `output` None (prima: '' se pipeline_cli lo scriveva vuoto).
Il resto (codici di uscita, stato JSON, lock, Ctrl+C, notifiche, ordine dei file, --skip-existing) e' invariato.
Al posto di `core.pipeline_cli` gira il finto di queue_stub_pipeline.py. Senza Qt: girano ovunque.
"""
import _thread
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
from core import queue_runner as qr  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    monkeypatch.setattr(qr, '_HOME', tmp_path / 'home' / '.transcriberpro')
    spy = kit.PopenSpy()
    monkeypatch.setattr(subprocess, 'Popen', spy)
    monkeypatch.setattr(qr, '_gui_running', lambda: False)
    import utils.cache_cleaner as cc
    spy.cache_calls = []
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches',
                        lambda log_callback=None: spy.cache_calls.append(1) or {'removed': ['x'], 'failed': []})
    yield spy
    cfg.reset_config()


def run_main(tmp_path, *inputs, extra=()):
    st, logs = tmp_path / 'st.json', tmp_path / 'logs'
    rc = qr.main([*map(str, inputs), '--status', str(st), '--log-dir', str(logs), *extra])
    return rc, json.loads(st.read_text(encoding='utf-8')), logs


def single(env_spy, tmp_path, name, *extra):
    """Una coda di un solo file (creato in una sottocartella dedicata). Ritorna (rc, stato, cartella dei log, percorso del video)."""
    d = tmp_path / ('d_' + name)
    d.mkdir()
    (v,) = kit.make_videos(d, name)
    rc, st, logs = run_main(tmp_path, v, extra=extra)
    return rc, st, logs, v


# ------------------------------------------------------------------------------------------------------ un file, via main()

def test_un_file_ok_stato_e_percentuali(env, tmp_path, monkeypatch):
    seen = []
    real = qr.QueueStatus.progress
    monkeypatch.setattr(qr.QueueStatus, 'progress', lambda self, i, pct, ph: (seen.append((pct, ph)), real(self, i, pct, ph))[1])
    rc, st, logs, v = single(env, tmp_path, 'a_ok.mkv')
    assert rc == 0 and st['files'][0]['output'] == v + '.it.srt' and st['files'][0]['error'] is None
    # come nella GUI: 1, 4, 11, 18, 98 (la riga [DIAG-RAM] "Trascrizione: [..] 90%" non muove la barra)
    assert [p for p, _ in seen] == [1, 4, 11, 18, 98]
    assert all(isinstance(ph, str) for _, ph in seen)


def test_esiti_non_ok(env, tmp_path):
    rc, st, _, _ = single(env, tmp_path, 'a_fail.mkv')
    f = st['files'][0]
    assert (rc, f['status'], f['output'], f['error']) == (2, 'failed', None, 'exit code 1')
    rc, st, _, _ = single(env, tmp_path, 'b_crash.mkv')
    f = st['files'][0]
    assert (rc, f['status'], f['output'], f['error']) == (2, 'failed', None, 'exit code 3')       # senza result.json


def test_log_come_quelli_della_gui_con_etichetta_di_livello(env, tmp_path):
    from utils.translations import tr
    rc, st, logs, v = single(env, tmp_path, 'a_fail.mkv')
    q = (next(logs.glob('*_queue.log'))).read_text(encoding='utf-8')
    f = (next(logs.glob('*_001.log'))).read_text(encoding='utf-8')
    for txt in (q, f):
        assert '[INFO] STUB riga di testo uno' in txt and '[INFO] STUB riga di testo due' in txt
        assert '[INFO] [DIAG-RAM]' in txt                                                    # inoltrata come nella GUI
        assert f"[ERROR] {tr('worker_failed').format(filename='a_fail.mkv')}" in txt
        assert f"[WARNING] {tr('worker_hint')}" in txt
        assert 'Downloading: modello.bin' not in txt and 'Using cache found in' not in txt      # rumore: solo nel log dell'applicazione
        assert '@@TPEV@@' not in txt and 'STUB_STDERR' not in txt                              # eventi e stderr: mai nel log
    assert [l for l in q.splitlines() if l.strip() and not l.startswith(('[INFO]', '[WARNING]', '[ERROR]'))] == []   # ogni riga ha l'etichetta
    assert tr('worker_start').format(n=1) in q and tr('worker_done_header') in q                  # intestazione e riepilogo: solo nel log di coda
    assert tr('worker_start').format(n=1) not in f


def test_cronologia_scritta_come_la_gui(env, tmp_path):
    rc, st, logs, v = single(env, tmp_path, 'a_ok.mkv')
    hp = tmp_path / 'home' / '.transcriberpro' / 'history.json'
    hist = json.loads(hp.read_text(encoding='utf-8'))
    assert len(hist) == 1
    e = hist[0]
    assert set(e) == {'name', 'date_iso', 'src_lang', 'dst_lang', 'duration_seconds', 'size_bytes', 'srt_path', 'video_path'}
    assert (e['name'], e['dst_lang'], e['size_bytes'], e['srt_path'], e['video_path']) == ('a_ok.mkv', 'ita', 10, v + '.it.srt', v)
    single(env, tmp_path, 'b_fail.mkv')
    assert len(json.loads(hp.read_text(encoding='utf-8'))) == 1                                  # i falliti non entrano


def test_anteprima_dei_passi_nel_file_di_stato(env, tmp_path, monkeypatch):
    snaps = []
    real = qr.QueueStatus.snapshot

    def spy_snapshot(self):
        d = real(self)
        snaps.append(d)
        return d
    monkeypatch.setattr(qr.QueueStatus, 'snapshot', spy_snapshot)
    single(env, tmp_path, 'a_ok.mkv')
    cur = [s['current'] for s in snaps if s['current'] and 'steps' in s['current']]
    assert cur, 'nessuna anteprima dei passi nello stato'
    last = cur[-1]['steps']
    assert set(last) == {'done', 'total', 'active', 'steps'} and last['total'] >= last['done'] >= 0
    assert all(set(st) == {'key', 'status', 'pct', 'eta'} for st in last['steps'])
    assert any(st['status'] == 'active' for c in cur for st in c['steps']['steps'])        # almeno un passo e' stato attivo
    assert snaps[-1]['current'] is None                                                      # a file concluso l'anteprima sparisce


def test_cache_ripulite_a_fine_coda_salvo_keep_caches(env, tmp_path):
    single(env, tmp_path, 'a_ok.mkv')
    assert len(env.cache_calls) == 1
    single(env, tmp_path, 'b_ok.mkv', '--keep-caches')
    assert len(env.cache_calls) == 1


def test_contratto_del_sottoprocesso(env, tmp_path, monkeypatch):
    monkeypatch.delenv('PYTHONUTF8', raising=False)
    rc, st, logs, v = single(env, tmp_path, 'a_ok.mkv')
    (call,) = env.calls
    assert call['argv'][:3] == [sys.executable, '-m', 'core.pipeline_cli'] and len(call['argv']) == 4
    kw = call['kwargs']
    assert Path(kw['cwd']) == ROOT
    assert (kw['stdout'], kw['stderr']) == (subprocess.PIPE, subprocess.PIPE)
    assert (kw['text'], kw['encoding'], kw['errors'], kw['bufsize']) == (True, 'utf-8', 'replace', 1)
    flags = 0
    for n in ('CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW'):
        flags |= getattr(subprocess, n, 0)
    assert kw['creationflags'] == flags
    e = kw['env']
    assert (e['PYTHONIOENCODING'], e['TP_SUBPROCESS'], e['TQDM_DISABLE'], e['TP_EVENTS']) == ('utf-8', '1', '1', '1')
    assert 'PYTHONUTF8' not in e
    assert {k for k in e if k not in os.environ} == {'PYTHONIOENCODING', 'TP_SUBPROCESS', 'TQDM_DISABLE', 'TP_EVENTS'}
    a = call['args_json']
    assert set(a) == {'video_path', 'target_language', 'overrides', 'files_processed', 'result_path'}   # ora anche `overrides` (vuote)
    assert a['overrides'] == {} and not Path(a['result_path']).parent.exists()          # cartella IPC rimossa


def test_residuo_converting_solo_se_fermato(env, tmp_path):
    """Come la GUI: su successo non si tocca (prima il headless lo ripuliva sempre)."""
    rc, st, logs, v = single(env, tmp_path, 'a_resid.mkv')
    assert rc == 0 and Path(v + '.converting').exists()


def test_ctrl_c_uccide_il_figlio_e_ripulisce(env, tmp_path):
    d = tmp_path / 'd'
    d.mkdir()
    (v,) = kit.make_videos(d, 'a_conv.mkv')
    logs = tmp_path / 'logs'

    def interrupter():
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                if any('STUB_SLOW_STARTED' in p.read_text(encoding='utf-8') for p in logs.glob('*_queue.log')):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        _thread.interrupt_main()
    threading.Thread(target=interrupter, daemon=True).start()
    rc = qr.main([v, '--status', str(tmp_path / 'st.json'), '--log-dir', str(logs)])
    st = json.loads((tmp_path / 'st.json').read_text(encoding='utf-8'))
    assert rc == 130 and st['state'] == 'cancelled' and st['files'][0]['status'] == 'cancelled'
    assert env.procs[0].poll() is not None
    assert not Path(v + '.converting').exists()
    assert not Path(env.calls[0]['args_json']['result_path']).parent.exists()


# ----------------------------------------------------------------------------------------------------------------------- main()

def test_main_stato_finale_e_codice_di_uscita(env, tmp_path):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_fail.mkv', 'c_crash.mkv')
    d = tmp_path
    rc, st, logs = run_main(tmp_path, d)
    assert rc == 2                                     # almeno un file fallito
    assert {k: st[k] for k in ('version', 'state', 'total', 'completed', 'failed', 'cancelled', 'queued', 'current')} == {
        'version': 1, 'state': 'finished', 'total': 3, 'completed': 1, 'failed': 2, 'cancelled': 0, 'queued': 0, 'current': None}
    assert {'pid', 'started', 'updated', 'eta_queue_seconds', 'files'} <= set(st)
    rows = [(f['name'], f['status'], f['percent'], f['phase'], f['output'], f['error']) for f in st['files']]
    assert rows == [
        ('a_ok.mkv', 'completed', 100, '', str(d / 'a_ok.mkv.it.srt'), None),
        ('b_fail.mkv', 'failed', 98, '', None, 'exit code 1'),
        ('c_crash.mkv', 'failed', 98, '', None, 'exit code 3')]
    assert sorted(p.name[16:] for p in logs.iterdir()) == ['001.log', '002.log', '003.log', 'queue.log']   # un log per file + il flusso
    assert not (tmp_path / 'home' / '.transcriberpro' / 'queue.lock').exists()                    # lock rilasciato
    assert [c['args_json']['files_processed'] for c in env.calls] == [0, 1, 2]


def test_main_tutto_ok_esce_con_zero(env, tmp_path):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 0 and st['completed'] == 2 and st['failed'] == 0


def test_main_nessun_video_esce_con_uno(env, tmp_path, capsys):
    from utils.translations import tr
    rc = qr.main([str(tmp_path), '--status', str(tmp_path / 'st.json')])
    assert rc == 1 and tr('qr_no_video_file_found') in capsys.readouterr().out
    assert not (tmp_path / 'st.json').exists()


def test_main_file_sparito_prima_del_suo_turno(env, tmp_path, monkeypatch):
    from utils.translations import tr
    (a,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    ghost = tmp_path / 'sparito.mkv'
    monkeypatch.setattr(qr, 'collect_files', lambda *x, **k: [ghost, Path(a)])
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 2
    assert [(f['name'], f['status'], f['error']) for f in st['files']] == [
        ('sparito.mkv', 'failed', tr('qr_file_not_found')), ('a_ok.mkv', 'completed', None)]
    assert len(env.calls) == 1                         # per il file sparito non parte nessun sottoprocesso


def _patch_runner(monkeypatch, fail_on, exc):
    from core.jobs import file_runner
    real = file_runner.FileRunner.run
    n = {'i': 0}

    def fake(self, *a, **k):
        n['i'] += 1
        if n['i'] == fail_on:
            raise exc
        return real(self, *a, **k)
    monkeypatch.setattr(file_runner.FileRunner, 'run', fake)


def test_main_ctrl_c_a_meta_coda(env, tmp_path, monkeypatch):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv', 'c_ok.mkv')
    _patch_runner(monkeypatch, 2, KeyboardInterrupt())
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 130 and st['state'] == 'cancelled'
    assert [f['status'] for f in st['files']] == ['completed', 'cancelled', 'queued']
    assert not (tmp_path / 'home' / '.transcriberpro' / 'queue.lock').exists()


def test_main_eccezione_in_un_file_non_ferma_la_coda(env, tmp_path, monkeypatch):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    _patch_runner(monkeypatch, 1, RuntimeError('boom'))
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 2
    assert [(f['status'], f['error']) for f in st['files']] == [('failed', 'RuntimeError: boom'), ('completed', None)]


def test_main_un_altra_coda_headless_attiva_esce_con_tre(env, tmp_path):
    kit.make_videos(tmp_path, 'a_ok.mkv')
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)  # queue_runner'])
    try:
        lock = tmp_path / 'home' / '.transcriberpro' / 'queue.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({'pid': other.pid, 'since': 'x'}), encoding='utf-8')
        rc = qr.main([str(tmp_path), '--status', str(tmp_path / 'st.json')])
        assert rc == 3 and env.calls == []
    finally:
        other.kill()
        other.wait()


def test_main_notifiche(env, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(qr, 'notify', lambda t, m: sent.append((t, m)))
    kit.make_videos(tmp_path, 'a_fail.mkv', 'b_fail.mkv', 'c_ok.mkv')
    rc, _, _ = run_main(tmp_path, tmp_path, extra=('--notify',))
    assert rc == 2 and len(sent) == 2                  # una al PRIMO errore, una a fine coda
    sent.clear()
    rc, _, _ = run_main(tmp_path, tmp_path, extra=())
    assert sent == []                                  # senza --notify nessuna


def test_main_skip_existing_e_ricorsione(env, tmp_path):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    (tmp_path / 'a_ok.it.srt').write_text('x')
    sub = tmp_path / 'sub'
    sub.mkdir()
    kit.make_videos(sub, 'c_ok.mkv')
    rc, st, _ = run_main(tmp_path, tmp_path, extra=('--skip-existing',))
    assert [f['name'] for f in st['files']] == ['b_ok.mkv']                      # a_ok ha gia' il suo .it.srt; sub/ senza --recursive
    rc, st, _ = run_main(tmp_path, tmp_path, extra=('--recursive',))
    assert sorted(f['name'] for f in st['files']) == ['a_ok.mkv', 'b_ok.mkv', 'c_ok.mkv']


# ---------------------------------------------------------------------------------------------------------------- funzioni pure

def test_collect_files_ordine_naturale_e_senza_duplicati(tmp_path):
    for n in ('Ep 10.mkv', 'Ep 2.mkv', 'Ep 1.mkv', 'nota.txt'):
        (tmp_path / n).write_bytes(b'x')
    got = qr.collect_files([str(tmp_path), str(tmp_path / 'Ep 2.mkv')])
    names = [p.name for p in got]
    assert names == ['Ep 2.mkv', 'Ep 1.mkv', 'Ep 10.mkv'] or names == ['Ep 1.mkv', 'Ep 2.mkv', 'Ep 10.mkv']   # il file passato per primo resta primo
    assert len({str(p).lower() for p in got}) == len(got)                        # nessun duplicato


def test_eta_seconds():
    assert qr.eta_seconds(2, 100) is None and qr.eta_seconds(50, 19) is None and qr.eta_seconds(99, 100) is None
    assert qr.eta_seconds(50, 100) == 100 and qr.eta_seconds(25, 60) == 180
