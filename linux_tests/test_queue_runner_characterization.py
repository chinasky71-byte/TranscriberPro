# -*- coding: utf-8 -*-
"""F0 del refactoring della coda (docs/STUDIO_REFACTORING_CODA.md): CARATTERIZZAZIONE di core/queue_runner.py (coda headless).

Fissa il comportamento di OGGI, comprese le differenze con la GUI (vedi test_queue_gui_characterization.py): ogni passo del
refactoring deve lasciare questi test invariati, oppure cambiarli con una nota esplicita nella PR (decisione di prodotto).
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
from gui.file_progress import FileProgress  # noqa: E402


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
    yield spy
    cfg.reset_config()


def run_main(tmp_path, *inputs, extra=()):
    st, logs = tmp_path / 'st.json', tmp_path / 'logs'
    rc = qr.main([*map(str, inputs), '--status', str(st), '--log-dir', str(logs), *extra])
    return rc, json.loads(st.read_text(encoding='utf-8')), logs


def one(video, calls=None, log=None, tmp=None):
    got = [] if calls is None else calls
    res = qr.run_one(Path(video), 'ita', 0, FileProgress, lambda p, ph: got.append((p, ph)), log or (Path(tmp) / 'x.log'))
    return res, got


# --------------------------------------------------------------------------------------------------------------------- run_one

def test_run_one_ok(env, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    res, calls = one(v, tmp=tmp_path)
    assert res == {'ok': True, 'output': v + '.it.srt', 'error': None}
    # percentuali: la riga [DIAG-RAM] "Trascrizione: [..] 90%" qui MUOVE la barra (17), nella GUI no (1, 4, 11, 18, 98)
    assert calls == [(0, ''), (1, 'extract'), (4, 'asr'), (17, 'asr'), (18, 'asr'), (98, 'final')]


def test_run_one_esiti_non_ok(env, tmp_path):
    v = kit.make_videos(tmp_path, 'a_fail.mkv', 'b_crash.mkv')
    assert one(v[0], tmp=tmp_path)[0] == {'ok': False, 'output': '', 'error': 'exit code 1'}
    assert one(v[1], tmp=tmp_path)[0] == {'ok': False, 'output': None, 'error': 'exit code 3'}    # senza result.json


def test_run_one_log_del_file_contiene_tutto(env, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    log = tmp_path / 'f.log'
    one(v, log=log)
    txt = log.read_text(encoding='utf-8')
    for needle in ('STUB_ARGS', 'STUB riga di testo uno', 'Downloading: modello.bin', 'Using cache found in',    # rumore: qui si tiene
                   '[DIAG-RAM]', '@@TPEV@@ {"k":"phase","name":"asr"', '[stderr] STUB_STDERR'):                    # eventi e stderr: nel log
        assert needle in txt, needle


def test_run_one_contratto_del_sottoprocesso(env, tmp_path, monkeypatch):
    monkeypatch.delenv('PYTHONUTF8', raising=False)
    (v,) = kit.make_videos(tmp_path, 'a_ok.mkv')
    one(v, tmp=tmp_path)
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
    # differenza con la GUI: il headless NON passa le eccezioni per file ("overrides") a pipeline_cli
    assert set(call['args_json']) == {'video_path', 'target_language', 'files_processed', 'result_path'}
    assert not Path(call['args_json']['result_path']).parent.exists()          # cartella IPC rimossa


def test_run_one_ripulisce_sempre_il_residuo_converting(env, tmp_path):
    """Differenza con la GUI (che lo ripulisce solo se annullato): qui anche su successo."""
    (v,) = kit.make_videos(tmp_path, 'a_resid.mkv')
    res, _ = one(v, tmp=tmp_path)
    assert res['ok'] is True and not Path(v + '.converting').exists()


def test_run_one_ctrl_c_uccide_il_figlio_e_ripulisce(env, tmp_path):
    (v,) = kit.make_videos(tmp_path, 'a_conv.mkv')
    log = tmp_path / 'f.log'

    def interrupter():
        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                if 'STUB_SLOW_STARTED' in log.read_text(encoding='utf-8'):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        _thread.interrupt_main()
    threading.Thread(target=interrupter, daemon=True).start()
    with pytest.raises(KeyboardInterrupt):
        one(v, log=log)
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
        ('b_fail.mkv', 'failed', 98, '', '', 'exit code 1'),
        ('c_crash.mkv', 'failed', 98, '', None, 'exit code 3')]
    assert sorted(p.name[16:] for p in logs.iterdir()) == ['001.log', '002.log', '003.log']      # un log per file
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


def test_main_ctrl_c_a_meta_coda(env, tmp_path, monkeypatch):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv', 'c_ok.mkv')
    real = qr.run_one
    n = {'i': 0}

    def fake(*a, **k):
        n['i'] += 1
        if n['i'] == 2:
            raise KeyboardInterrupt
        return real(*a, **k)
    monkeypatch.setattr(qr, 'run_one', fake)
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 130 and st['state'] == 'cancelled'
    assert [f['status'] for f in st['files']] == ['completed', 'cancelled', 'queued']
    assert not (tmp_path / 'home' / '.transcriberpro' / 'queue.lock').exists()


def test_main_eccezione_in_un_file_non_ferma_la_coda(env, tmp_path, monkeypatch):
    kit.make_videos(tmp_path, 'a_ok.mkv', 'b_ok.mkv')
    real = qr.run_one
    n = {'i': 0}

    def fake(*a, **k):
        n['i'] += 1
        if n['i'] == 1:
            raise RuntimeError('boom')
        return real(*a, **k)
    monkeypatch.setattr(qr, 'run_one', fake)
    rc, st, _ = run_main(tmp_path, tmp_path)
    assert rc == 2
    assert [(f['status'], f['error']) for f in st['files']] == [('failed', 'RuntimeError: boom'), ('completed', None)]


def test_main_un_altra_coda_headless_attiva_esce_con_tre(env, tmp_path):
    from utils.translations import tr
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
