# -*- coding: utf-8 -*-
"""G2 (fase 0 della web UI): CARATTERIZZAZIONE di gui/sync_batch_worker.py::SyncBatchWorker.

Descrive il comportamento PRIMA dell'estrazione del ciclo in core/jobs/sync_batch.py: i test passano identici sul codice vecchio e
sul nuovo (sequenza e ordine dei segnali, thread di emissione, percentuali, esito per coppia, annullamento che uccide l'albero,
ambiente e file di args.json passati al sottoprocesso). Il sottoprocesso e' un finto (linux_tests/sync_stub_cli.py)."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def pair(tmp_path, name, output=None):
    return SimpleNamespace(video=str(tmp_path / name), srt=str(tmp_path / (name + '.srt')), output=output)


def run_worker(qt, pairs, cancel_after_marker=None, timeout=60):
    """Esegue il worker in un vero QThread e registra i segnali: [(nome, args, nome_del_thread_di_emissione)]."""
    from PyQt6.QtCore import QThread, Qt
    from gui.sync_batch_worker import SyncBatchWorker
    SyncBatchWorker.CLI_MODULE = 'linux_tests.sync_stub_cli'
    w = SyncBatchWorker(pairs)
    main_thread = QThread.currentThread()
    events = []
    for sig in ('log_message', 'pair_started', 'pair_progress', 'pair_finished', 'batch_progress', 'all_done'):
        getattr(w, sig).connect(lambda *a, _s=sig: events.append((_s, a, QThread.currentThread() == main_thread)),
                                Qt.ConnectionType.DirectConnection)     # diretta: registra il thread DI EMISSIONE
        if cancel_after_marker and sig == 'log_message':
            w.log_message.connect(lambda m: w.cancel() if cancel_after_marker in m else None, Qt.ConnectionType.DirectConnection)
    w.start()
    t0 = time.time()
    while not w.wait(50):
        qt.processEvents()
        assert time.time() - t0 < timeout
    qt.processEvents()
    return w, events


def names(events, kind):
    return [e[1] for e in events if e[0] == kind]


def test_coppie_ok_fallita_e_crash(qt, tmp_path):
    pairs = [pair(tmp_path, 'a.mkv'), pair(tmp_path, 'fail.mkv'), pair(tmp_path, 'crash.mkv'), pair(tmp_path, 'failnomsg.mkv')]
    w, ev = run_worker(qt, pairs)
    fin = names(ev, 'pair_finished')
    assert [f[:2] for f in fin] == [(0, True), (1, False), (2, False), (3, False)]
    assert fin[0][2].endswith('a.mkv.synced.it.srt')
    assert fin[1][2] == 'boom'
    assert fin[2][2] == 'processo terminato con codice 3 (crash?)'
    assert fin[3][2] == 'processo terminato con codice 1'
    assert names(ev, 'all_done') == [(1, 3, 0)]
    assert names(ev, 'batch_progress') == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert [s[:2] for s in names(ev, 'pair_started')] == [(i, p.video) for i, p in enumerate(pairs)]


def test_ordine_dei_segnali_e_thread(qt, tmp_path):
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv'), pair(tmp_path, 'b.mkv')])
    kinds = [e[0] for e in ev]
    assert kinds[:2] == ['pair_started', 'log_message']
    assert kinds[-1] == 'all_done'
    # ogni coppia: started ... finished, batch_progress, e solo dopo la coppia successiva
    assert [k for k in kinds if k in ('pair_started', 'pair_finished', 'batch_progress')] == \
        ['pair_started', 'pair_finished', 'batch_progress', 'pair_started', 'pair_finished', 'batch_progress']
    assert all(not e[2] for e in ev)                 # tutti emessi dal thread del worker, mai dal principale


def test_progresso_monotono_passi_e_pct(qt, tmp_path):
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv')])
    prog = [p[1] for p in names(ev, 'pair_progress')]
    assert prog == [10, 30, 30, 80, 90, 100]     # passo 1 -> 10, PCT 30, "20" -> ripete 30 (mai indietro), passo 3 -> 80, PCT 90, ok -> 100
    assert all(p[0] == 0 for p in names(ev, 'pair_progress'))


def test_righe_di_log(qt, tmp_path):
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv', output=str(tmp_path / 'out.srt')), pair(tmp_path, 'badpct.mkv')])
    logs = [a[0] for a in names(ev, 'log_message')]
    assert any(l == f"\n=== Coda sync 1/2: a.mkv ===" for l in logs)
    assert any(l == f"\n=== Coda sync 2/2: badpct.mkv ===" for l in logs)
    assert '1. Estrazione audio' in logs and '3. Allineamento' in logs and 'testo con 3. numero nel mezzo' in logs
    assert not any(l.startswith('[SYNC-PCT] 30') for l in logs)
    assert not any(l.startswith('[SYNC-PCT]') for l in logs)         # anche la riga non numerica NON arriva al log
    assert not any('STUB_STDERR' in l for l in logs)                  # stderr solo nel file di log
    assert any(l.startswith('   OK in ') for l in logs)
    stub_args = json.loads(next(l for l in logs if l.startswith('STUB_ARGS '))[len('STUB_ARGS '):])
    assert stub_args['output_path'] == str(tmp_path / 'out.srt')


def test_ambiente_del_figlio(qt, tmp_path):
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv')])
    logs = [a[0] for a in names(ev, 'log_message')]
    env = json.loads(next(l for l in logs if l.startswith('STUB_ENV '))[len('STUB_ENV '):])
    import os
    # PYTHONUTF8 non lo imposta il worker: arriva (o no) dall'ambiente del processo padre
    assert env == {'TP_SUBPROCESS': '1', 'TQDM_DISABLE': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': os.environ.get('PYTHONUTF8')}


def test_avvio_fallito(qt, tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise OSError('nope')
    monkeypatch.setattr(subprocess, 'Popen', boom)
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv')])
    assert names(ev, 'pair_finished') == [(0, False, 'avvio del processo fallito: nope')]
    assert names(ev, 'all_done') == [(0, 1, 0)]


def test_annullamento_uccide_il_figlio(qt, tmp_path):
    pairs = [pair(tmp_path, 'slow.mkv'), pair(tmp_path, 'b.mkv'), pair(tmp_path, 'c.mkv')]
    t0 = time.time()
    w, ev = run_worker(qt, pairs, cancel_after_marker='STUB_SLOW_STARTED')
    assert time.time() - t0 < 30 and w.is_cancelled
    assert names(ev, 'pair_finished') == [(0, False, 'annullato')]
    assert names(ev, 'all_done') == [(0, 0, 3)]
    assert names(ev, 'batch_progress') == []
    assert [s[0] for s in names(ev, 'pair_started')] == [0]


def test_cancel_prima_di_partire(qt, tmp_path):
    from gui.sync_batch_worker import SyncBatchWorker
    SyncBatchWorker.CLI_MODULE = 'linux_tests.sync_stub_cli'
    w = SyncBatchWorker([pair(tmp_path, 'a.mkv')])
    got = []
    w.all_done.connect(lambda *a: got.append(a))
    w.cancel()
    w.start()
    w.wait(10000)
    qt.processEvents()
    assert got == [(0, 0, 1)]


def test_eccezione_non_gestita_emette_sempre_all_done(qt, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('x')
    monkeypatch.setattr(json, 'dumps', boom)          # primo passo di _run_one, fuori da ogni try interno
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv')])
    assert names(ev, 'all_done') == [(0, 0, 1)]
    assert any(a[0] == 'ERRORE coda sync: x' for a in names(ev, 'log_message'))


def test_pulizia_cartella_temporanea(qt, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path / 'tmp'))
    (tmp_path / 'tmp').mkdir()
    run_worker(qt, [pair(tmp_path, 'a.mkv'), pair(tmp_path, 'fail.mkv')])
    assert [p for p in (tmp_path / 'tmp').iterdir() if p.name.startswith('tp_sync_')] == []


def test_kill_proc_tree_importabile_con_il_vecchio_nome():
    from gui.sync_batch_worker import kill_proc_tree
    assert callable(kill_proc_tree)


def test_la_barra_non_torna_indietro(qt, tmp_path):
    w, ev = run_worker(qt, [pair(tmp_path, 'late.mkv')])
    prog = [p[1] for p in names(ev, 'pair_progress')]
    assert prog == [10, 30, 30, 90, 90, 100]      # "[SYNC-PCT] 90" poi "2." (40): la riga di passo non emette (40 < 90)
    assert prog == sorted(prog)


def test_esito_dal_result_json_non_dal_codice(qt, tmp_path):
    pairs = [pair(tmp_path, 'rc0fail.mkv'), pair(tmp_path, 'rc1ok.mkv'), pair(tmp_path, 'both.mkv')]
    w, ev = run_worker(qt, pairs)
    fin = names(ev, 'pair_finished')
    assert fin[0] == (0, False, 'x')
    assert fin[1][:2] == (1, True) and fin[1][2].endswith('rc1ok.mkv.synced.it.srt')
    assert fin[2] == (2, True, 'O')


def test_ram_libera_nel_log(qt, tmp_path, monkeypatch):
    import types
    fake = types.SimpleNamespace(virtual_memory=lambda: types.SimpleNamespace(available=5e9))
    monkeypatch.setitem(sys.modules, 'psutil', fake)
    w, ev = run_worker(qt, [pair(tmp_path, 'a.mkv')])
    assert '   RAM libera dopo la coppia: 5.0 GB' in [a[0] for a in names(ev, 'log_message')]


def test_avvio_fallito_ripulisce_la_cartella(qt, tmp_path, monkeypatch):
    import subprocess
    import tempfile
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path / 'tmp'))
    (tmp_path / 'tmp').mkdir()
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
    run_worker(qt, [pair(tmp_path, 'a.mkv')])
    assert list((tmp_path / 'tmp').iterdir()) == []
