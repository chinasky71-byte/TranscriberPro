# -*- coding: utf-8 -*-
"""Scansione di cartelle, dimensioni e spegnimento: comportamento di gui/workers.py e gui/services/queue_service.py fissato PRIMA
dell'estrazione in core/services/file_scan.py e shutdown_policy.py. Lo stesso file passa identico sul codice vecchio e sul nuovo."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope='module')
def qt():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('n,txt', [(-1, ''), (0, '0 B'), (500, '500 B'), (1023, '1023 B'), (1024, '1 KB'), (1536, '2 KB'),
                                   (1024 ** 2, '1 MB'), (5 * 1024 ** 3, '5 GB'), (1024 ** 4, '1.0 TB'), (1536 * 1024 ** 4, '1536.0 TB')])
def test_format_file_size(qt, n, txt):
    from gui.workers import format_file_size
    assert format_file_size(n) == txt


def make_tree(tmp_path):
    (tmp_path / 'sub' / 'deep').mkdir(parents=True)
    names = ['a.mkv', 'B.MP4', 'x.txt', 'sub/c.avi', 'sub/deep/d.webm', 'sub/deep/e.srt', 'sub/f.M4V']
    for i, n in enumerate(names):
        (tmp_path / n).write_bytes(b'x' * (100 * (i + 1)))
    return names


def run_scan(folder, exts, cancel_after=None):
    from gui.workers import FolderScanWorker
    w = FolderScanWorker(str(folder), exts)
    found, done = [], []
    w.file_found.connect(lambda p, s: found.append((p, s)))
    w.scan_done.connect(done.append)
    if cancel_after is not None:
        w.file_found.connect(lambda p, s: len(found) >= cancel_after and w.cancel())
    w.run()
    return found, done


def test_scan_trova_i_video_ricorsivamente_con_la_dimensione(qt, tmp_path):
    make_tree(tmp_path)
    exts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
    found, done = run_scan(tmp_path, exts)
    rel = sorted((Path(p).relative_to(tmp_path).as_posix(), s) for p, s in found)
    assert rel == [('B.MP4', '200 B'), ('a.mkv', '100 B'), ('sub/c.avi', '400 B'), ('sub/deep/d.webm', '500 B'),
                   ('sub/f.M4V', '700 B')]
    assert done == [5]


def test_scan_estensioni_personalizzate_e_maiuscole(qt, tmp_path):
    make_tree(tmp_path)
    found, done = run_scan(tmp_path, ['.SRT'])
    assert [Path(p).name for p, _ in found] == ['e.srt'] and done == [1]


def test_scan_annullata_si_ferma_ma_riporta_il_totale_trovato(qt, tmp_path):
    make_tree(tmp_path)
    found, done = run_scan(tmp_path, ['.mkv', '.mp4', '.avi', '.webm', '.m4v'], cancel_after=2)
    assert len(found) == 2 and done == [2]


def test_scan_cartella_inesistente_non_solleva(qt, tmp_path):
    found, done = run_scan(tmp_path / 'non_esiste', ['.mkv'])
    assert found == [] and done == [0]


def test_dimensioni_in_background(qt, tmp_path):
    from gui.workers import FileSizeWorker
    (a,) = [tmp_path / 'a.mkv']
    a.write_bytes(b'x' * 2048)
    w = FileSizeWorker([str(a), str(tmp_path / 'manca.mkv')])
    got = []
    w.size_ready.connect(lambda p, s: got.append((Path(p).name, s)))
    w.run()
    assert got == [('a.mkv', '2 KB'), ('manca.mkv', '')]


def test_costanti_di_coda_e_spegnimento(qt):
    from gui.services.queue_service import ShutdownPolicy, VIDEO_EXTENSIONS
    assert VIDEO_EXTENSIONS == ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
    assert ShutdownPolicy.DELAY_MS == 5000
    assert ShutdownPolicy.command() == (['shutdown', '/s', '/t', '60'] if os.name == 'nt' else ['shutdown', '-h', '+1'])
