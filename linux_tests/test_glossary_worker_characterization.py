# -*- coding: utf-8 -*-
"""G2 (fase 0 della web UI): CARATTERIZZAZIONE di gui/glossary_worker.py::GlossaryBuilderWorker.

Passa identica sul codice vecchio e su quello con la logica in core/jobs/glossary_run.py: sequenza e thread dei segnali, esiti, file
args.json, annullamento (terminate + kill dell'albero Qwen + pulizia dei file temporanei), assenza del venv. Il CLI e' un finto
(linux_tests/glossary_stub_cli.py) lanciato con l'interprete corrente al posto di venv_glossary."""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STUB = Path(__file__).resolve().parent / 'glossary_stub_cli.py'


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def gw(monkeypatch):
    import gui.glossary_worker as gw
    monkeypatch.setattr(gw, 'VENV_GLOSSARY_PYTHON', Path(sys.executable))
    monkeypatch.setattr(gw, 'CLI_SCRIPT', STUB)
    return gw


def run(qt, gw, tmp_path, name, payload_extra=None, cancel_on=None, timeout=60):
    from PyQt6.QtCore import QThread, Qt
    payload = {'name': name, 'show_dir': str(tmp_path)}
    payload.update(payload_extra or {})
    work = tmp_path / 'work'
    w = gw.GlossaryBuilderWorker(payload, work)
    main = QThread.currentThread()
    ev = []
    for sig in ('gate', 'progress', 'log_line', 'finished_ok', 'failed'):
        getattr(w, sig).connect(lambda *a, _s=sig: ev.append((_s, a, QThread.currentThread() == main)),
                                Qt.ConnectionType.DirectConnection)
    if cancel_on:
        w.log_line.connect(lambda m: w.cancel() if cancel_on in m else None, Qt.ConnectionType.DirectConnection)
    w.start()
    t0 = time.time()
    while not w.wait(50):
        qt.processEvents()
        assert time.time() - t0 < timeout
    qt.processEvents()
    return w, ev, work


def test_run_ok(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'ok')
    assert [(e[0], e[1]) for e in ev] == [
        ('log_line', ('avvio ok',)),
        ('log_line', ('STUB_ENV {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}',)),
        ('log_line', ('STUB_CWD ' + str(ROOT),)),
        ('log_line', ('STUB_RAW {"name": "ok", "show_dir": ' + json.dumps(str(tmp_path)) + '}',)),
        ('gate', ({'ev': 'gate', 'ok': True, 'blocks': 7000, 'need_blocks': 6000},)),
        ('progress', ('align', 1, 4, 'uno')),
        ('progress', ('', 0, 0, '')),
        ('log_line', ('fine',)),
        ('finished_ok', (str(work / 'report.json'),)),
    ]
    assert all(not e[2] for e in ev)
    assert json.loads((work / 'glossary_builder_args.json').read_text(encoding='utf-8'))['name'] == 'ok'


def test_errore_evento_ha_la_precedenza_sul_codice(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'err')
    assert ev[-1][:2] == ('failed', ('qualcosa e andato storto',)) and [e[0] for e in ev].count('failed') == 1


def test_senza_report(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'nodone')
    assert ev[-1][:2] == ('failed', ("Il processo e' terminato con codice 0 senza produrre un report",))
    w, ev, work = run(qt, gw, tmp_path, 'crash')
    assert ev == [('failed', ("Il processo e' terminato con codice 3 senza produrre un report",), False)]


def test_venv_mancante(qt, gw, tmp_path, monkeypatch):
    monkeypatch.setattr(gw, 'VENV_GLOSSARY_PYTHON', tmp_path / 'non_esiste')
    assert gw.venv_glossary_available() is False
    w, ev, work = run(qt, gw, tmp_path, 'ok')
    assert [e[0] for e in ev] == ['failed'] and ev[0][1][0].startswith('venv_glossary non trovato.')
    assert not work.exists()


def test_args_non_scrivibile(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'ok', payload_extra={'x': object()})          # non serializzabile in JSON
    assert ev[0][0] == 'failed' and ev[0][1][0].startswith('Impossibile scrivere args.json: ')


def test_avvio_fallito(qt, gw, tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise OSError('nope')
    monkeypatch.setattr(subprocess, 'Popen', boom)
    w, ev, work = run(qt, gw, tmp_path, 'ok')
    assert [e[:2] for e in ev] == [('failed', ('Avvio subprocess fallito: nope',))]


def test_annullamento(qt, gw, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    for n in ('glossary_qwen_gpu_request.json', 'glossary_qwen_gpu_result.json', 'glossary_qwen_gpu_pid.txt', 'altro.txt'):
        (work / n).write_text('0', encoding='utf-8')
    t0 = time.time()
    w, ev, _ = run(qt, gw, tmp_path, 'slow', cancel_on='STUB_SLOW_STARTED')
    assert time.time() - t0 < 30
    assert ev[-1][:2] == ('failed', ("Annullato dall'utente",))
    assert sorted(p.name for p in work.iterdir()) == ['altro.txt']       # args e file Qwen ripuliti, il resto resta


def test_cancel_uccide_l_albero_qwen(qt, gw, tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'glossary_qwen_gpu_pid.txt').write_text(' 4242\n', encoding='utf-8')
    killed = []
    monkeypatch.setattr(gw, 'kill_tree', lambda pid, wait=None: killed.append((pid, wait)))
    w, ev, _ = run(qt, gw, tmp_path, 'slow', cancel_on='STUB_SLOW_STARTED')
    assert killed == [(4242, 0)]


def test_cancel_con_file_pid_illeggibile(qt, gw, tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'glossary_qwen_gpu_pid.txt').write_text('boh', encoding='utf-8')
    monkeypatch.setattr(gw, 'kill_tree', lambda pid, wait=None: (_ for _ in ()).throw(AssertionError))
    w, ev, _ = run(qt, gw, tmp_path, 'slow', cancel_on='STUB_SLOW_STARTED')
    assert ev[-1][0] == 'failed'


def test_cancel_senza_processo(qt, gw, tmp_path):
    w = gw.GlossaryBuilderWorker({'name': 'ok'}, tmp_path / 'w')
    w.cancel()                                   # nessun errore se non c'e' ancora un processo
    assert w._cancelled is True


def test_args_utf8_non_escapato(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'ok_è')
    raw = next(e[1][0] for e in ev if e[0] == 'log_line' and e[1][0].startswith('STUB_RAW '))
    assert '"name": "ok_è"' in raw


def test_codice_di_uscita_non_zero_anche_con_report(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'rc1done')
    assert ev[-1][:2] == ('failed', ("Il processo e' terminato con codice 1 senza produrre un report",))


def test_errore_senza_messaggio(qt, gw, tmp_path):
    w, ev, work = run(qt, gw, tmp_path, 'err2')
    assert ev[-1][:2] == ('failed', ('errore sconosciuto',))


def test_flag_di_creazione_e_cwd(qt, gw, tmp_path, monkeypatch):
    import subprocess
    seen = {}
    real = subprocess.Popen

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', spy)
    run(qt, gw, tmp_path, 'ok')
    assert seen['creationflags'] == 0x08000000 and seen['cwd'] == str(ROOT)
    assert seen['bufsize'] == 1 and seen['encoding'] == 'utf-8' and seen['errors'] == 'replace' and seen['text'] is True
