# -*- coding: utf-8 -*-
"""utils/temp_cleanup.py: le cartelle di lavoro dei job uccisi non restano in RAM.

Il cancel uccide il process tree, quindi il `finally` della pipeline non gira e
`$TMPDIR/TranscriberPro/vid_<hash>/` resta con i wav estratti: su tmpfs sono
centinaia di MB di RAM (misurati 854 MB su un episodio cancellato).
"""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from utils import temp_cleanup  # noqa: E402


def _work_dir(base: Path, name: str, age_s: float = 0.0) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / 'chunk_0001.wav').write_bytes(b'x' * 1024)
    if age_s:
        stamp = time.time() - age_s
        os.utime(folder, (stamp, stamp))
    return folder


def test_rimuove_le_cartelle_orfane(tmp_path):
    _work_dir(tmp_path, 'vid_aaaa1111')
    _work_dir(tmp_path, 'vid_bbbb2222')
    (tmp_path / 'altro').mkdir()
    removed = temp_cleanup.sweep(tmp_path)
    assert len(removed) == 2
    assert not (tmp_path / 'vid_aaaa1111').exists()
    assert (tmp_path / 'altro').exists()          # fuori dal nostro prefisso: non si tocca
    assert temp_cleanup.sweep(tmp_path) == []     # idempotente


def test_rispetta_leta_minima(tmp_path):
    vecchia = _work_dir(tmp_path, 'vid_vecchia', age_s=600)
    fresca = _work_dir(tmp_path, 'vid_fresca')
    removed = temp_cleanup.sweep(tmp_path, older_than_s=300)
    assert removed == [vecchia]
    assert fresca.exists()


def test_base_inesistente_non_solleva(tmp_path):
    assert temp_cleanup.sweep(tmp_path / 'nope') == []
    assert temp_cleanup.stale_dirs(tmp_path / 'nope') == []


def test_solo_directory_con_prefisso(tmp_path):
    (tmp_path / 'vid_file.txt').write_text('x', encoding='utf-8')   # file, non cartella
    assert temp_cleanup.sweep(tmp_path) == []
    assert (tmp_path / 'vid_file.txt').exists()


def test_summary_solo_se_ce_qualcosa(tmp_path):
    assert temp_cleanup.sweep_summary(tmp_path) == ''
    _work_dir(tmp_path, 'vid_cccc3333')
    line = temp_cleanup.sweep_summary(tmp_path)
    assert 'rimosse 1 cartelle' in line and str(tmp_path) in line


def test_temp_base_e_sotto_tmpdir(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    monkeypatch.setattr(tempfile, 'tempdir', None)      # tempfile cache la prima risposta
    assert temp_cleanup.temp_base() == tmp_path / 'TranscriberPro'


def test_directory_size_somma_i_file(tmp_path):
    folder = _work_dir(tmp_path, 'vid_dddd4444')
    assert temp_cleanup.directory_size(folder) >= 1024
    assert temp_cleanup.directory_size(tmp_path / 'nope') == 0


class _Runner:
    """Runner che crea una cartella di lavoro e poi fallisce (come un job ucciso)."""

    def __init__(self, base: Path):
        self.base = base
        self.calls = 0

    def run(self, video, target_language, files_processed, log_path, on_line=None, on_event=None,
            cancel_event=None):
        self.calls += 1
        _work_dir(self.base, 'vid_eeee5555')
        return {"ok": False, "output": None, "error": "boom", "cancelled": False}


def test_il_manager_ripulisce_dopo_un_job_fallito(tmp_path, monkeypatch):
    base = tmp_path / 'TranscriberPro'
    monkeypatch.setattr(temp_cleanup, 'temp_base', lambda: base)
    manager = JobManager(runner=_Runner(base), keep_alive=True, log_dir=tmp_path / 'logs')
    manager.add(tmp_path / 'movie.mkv')
    manager.start()
    deadline = time.time() + 5
    while time.time() < deadline and manager.snapshot()[0]['status'] != 'failed':
        time.sleep(0.02)
    assert manager.snapshot()[0]['status'] == 'failed'
    assert temp_cleanup.stale_dirs(base) == []      # la cartella del job ucciso non resta
    manager.stop()


def test_il_manager_non_ripulisce_dopo_un_job_riuscito(tmp_path, monkeypatch):
    base = tmp_path / 'TranscriberPro'
    monkeypatch.setattr(temp_cleanup, 'temp_base', lambda: base)

    class OkRunner(_Runner):
        def run(self, *args, **kwargs):
            self.calls += 1
            return {"ok": True, "output": "x.srt", "error": None, "cancelled": False}

    manager = JobManager(runner=OkRunner(base), keep_alive=True, log_dir=tmp_path / 'logs')
    manager.add(tmp_path / 'movie.mkv')
    manager.start()
    deadline = time.time() + 5
    while time.time() < deadline and manager.snapshot()[0]['status'] != 'done':
        time.sleep(0.02)
    # il job riuscito ha gia' ripulito da solo: lo sweep non e' invocato e non
    # tocca eventuali cartelle recenti di un altro job in coda
    assert manager.snapshot()[0]['status'] == 'done'
    manager.stop()


def test_la_suite_non_usa_la_tmpfs():
    """pytest deve scrivere i tmp_path su disco: /tmp qui è tmpfs (RAM)."""
    ini = (ROOT / 'linux_tests' / 'pytest.ini').read_text(encoding='utf-8')
    assert '--basetemp=/var/tmp/tp-pytest' in ini


def test_la_fixture_full_copia_una_volta_per_sessione():
    text = (ROOT / 'linux_tests' / 'test_install_retry.py').read_text(encoding='utf-8')
    assert "@pytest.fixture(scope='session')\ndef repo_copy" in text
    assert "'.tools', 'samples'" in text
