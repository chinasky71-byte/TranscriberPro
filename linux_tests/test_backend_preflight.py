# -*- coding: utf-8 -*-
"""Preflight del backend: un job GPU non deve partire se la GPU non risponde.

Il probe reale (import di torch/ctranslate2 in un sottoprocesso) è sostituito da
un finto report: questi test non caricano torch e girano ovunque.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from utils import backend_preflight as bp  # noqa: E402
from utils.job_overrides import clean  # noqa: E402

GOOD = {"torch": "2.10.0+rocm7.0", "runtime": "7.0", "cuda_available": True, "devices": 2,
        "ctranslate2": "4.8.4", "ct2_devices": 2, "error": ""}
CPU_ONLY = {"torch": "2.8.0+cpu", "runtime": "", "cuda_available": False, "devices": 0,
            "ctranslate2": "4.6.0", "ct2_devices": 0, "error": ""}


class FakeConfig:
    def __init__(self, use_gpu=True):
        self.values = {"use_gpu": use_gpu}

    def get(self, key, default=None):
        return self.values.get(key, default)


class CountingRunner:
    def __init__(self):
        self.calls = 0

    def run(self, video, target_language, files_processed, log_path, on_line=None, on_event=None, cancel_event=None):
        self.calls += 1
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


@pytest.fixture(autouse=True)
def clear_cache():
    bp._cache.update({"at": 0.0, "report": None})
    yield
    bp._cache.update({"at": 0.0, "report": None})


@pytest.fixture
def stamp(tmp_path, monkeypatch):
    path = tmp_path / '.tp-backend'
    monkeypatch.setattr(bp, 'stamp_path', lambda: path)
    return path


def _probe(monkeypatch, payload):
    monkeypatch.setattr(bp, '_probe', lambda: dict(payload))


def test_stamp_letto_e_assente(stamp):
    assert bp.read_stamp() == {}
    stamp.write_text('backend=rocm\ntorch=2.10.0+rocm7.0\nrequirements=requirements-rocm.txt\n', encoding='utf-8')
    assert bp.read_stamp()['backend'] == 'rocm'
    assert bp.read_stamp()['requirements'] == 'requirements-rocm.txt'


def test_report_ok_con_backend_e_gpu_presenti(stamp, monkeypatch):
    stamp.write_text('backend=rocm\n', encoding='utf-8')
    _probe(monkeypatch, GOOD)
    current = bp.report()
    assert current['ok'] is True and current['problems'] == []
    assert 'rocm' in bp.banner()


def test_report_segnala_venv_cpu(stamp, monkeypatch):
    stamp.write_text('backend=rocm\n', encoding='utf-8')
    _probe(monkeypatch, CPU_ONLY)
    current = bp.report()
    assert current['ok'] is False
    assert any('non vede la GPU' in p for p in current['problems'])
    assert any('ctranslate2' in p for p in current['problems'])
    assert 'non disponibile' in bp.banner()


def test_report_segnala_timbro_mancante(stamp, monkeypatch):
    _probe(monkeypatch, GOOD)                       # GPU sana ma installazione non verificata (stamp: tmp, assente)
    current = bp.report()
    assert current['ok'] is False
    assert any('timbro' in p for p in current['problems'])


def test_report_segnala_runtime_sbagliato(stamp, monkeypatch):
    stamp.write_text('backend=cuda\n', encoding='utf-8')
    _probe(monkeypatch, dict(GOOD, runtime='', cuda_available=True))
    assert bp.report()['ok'] is False


def test_cache_evita_probe_ripetuti(stamp, monkeypatch):
    stamp.write_text('backend=rocm\n', encoding='utf-8')
    calls = []
    monkeypatch.setattr(bp, '_probe', lambda: (calls.append(1), dict(GOOD))[1])
    bp.report()
    bp.report()
    assert len(calls) == 1


def test_check_for_job_rispetta_use_gpu_e_override(stamp, monkeypatch):
    stamp.write_text('backend=rocm\n', encoding='utf-8')
    _probe(monkeypatch, CPU_ONLY)
    assert bp.check_for_job(FakeConfig(use_gpu=True))[0] is False
    allowed, message = bp.check_for_job(FakeConfig(use_gpu=True), {'allow_cpu': True})
    assert allowed is True and message == ''
    assert bp.check_for_job(FakeConfig(use_gpu=False))[0] is True


def test_messaggio_spiega_il_rimedio(stamp, monkeypatch):
    stamp.write_text('backend=rocm\n', encoding='utf-8')
    _probe(monkeypatch, CPU_ONLY)
    allowed, message = bp.check_for_job(FakeConfig())
    assert allowed is False
    assert 'install.sh' in message and 'Allow CPU' in message


def test_manager_fallisce_subito_senza_lanciare_il_runner(tmp_path):
    runner = CountingRunner()
    manager = JobManager(runner=runner, keep_alive=True, log_dir=tmp_path / 'logs',
                         preflight=lambda job: (False, 'GPU non disponibile: prova'))
    manager.add(tmp_path / 'movie.mkv')
    manager.start()
    deadline = time.time() + 5
    while time.time() < deadline and manager.snapshot()[0]['status'] not in ('failed', 'done'):
        time.sleep(0.02)
    job = manager.snapshot()[0]
    assert job['status'] == 'failed'
    assert 'GPU non disponibile' in job['error']
    assert runner.calls == 0
    manager.stop()


def test_manager_senza_preflight_invoca_il_runner(tmp_path):
    runner = CountingRunner()
    manager = JobManager(runner=runner, keep_alive=True, log_dir=tmp_path / 'logs')
    manager.add(tmp_path / 'movie.mkv')
    manager.start()
    deadline = time.time() + 5
    while time.time() < deadline and manager.snapshot()[0]['status'] != 'done':
        time.sleep(0.02)
    assert runner.calls == 1
    manager.stop()


def test_allow_cpu_sopravvive_a_clean():
    assert clean({'allow_cpu': True}) == {'allow_cpu': True}
    assert clean({'allow_cpu': 'yes'}) == {}
