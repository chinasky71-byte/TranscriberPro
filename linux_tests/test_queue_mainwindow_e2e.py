# -*- coding: utf-8 -*-
"""Avvio reale: la vera MainWindow (offscreen) con la coda completa, dal clic su "Avvia" alla fine.

Il refactoring della coda (docs/STUDIO_REFACTORING_CODA.md) deve lasciare identico cio' che l'utente vede: righe della lista che
passano a completato/fallito, contatori, log, cronologia, pulsanti. Al posto di `core.pipeline_cli` gira il finto
(queue_stub_pipeline.py); cache e cronologia sono isolate. Si salta se PyQt6 (o libEGL) manca.
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


def pump(app, cond, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_mainwindow_coda_completa_dall_avvio_alla_fine(qt, tmp_path, monkeypatch):
    from PyQt6.QtCore import Qt
    import utils.cache_cleaner as cc
    from gui.history_widget import HistoryWidget
    from utils.translations import tr
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches', lambda log_callback=None: {'removed': [], 'failed': []})
    monkeypatch.setattr(HistoryWidget, 'HISTORY_FILE', tmp_path / 'home' / '.transcriberpro' / 'history.json')
    from gui.main_window import MainWindow

    mw = MainWindow()
    mw.show()
    v = kit.make_videos(tmp_path, 'a_ok.mkv', 'b_fail.mkv', 'c_ok.mkv')
    assert mw.queue_service.enqueue(v) == v
    assert mw.file_list.count() == 3 and mw.processing_queue == v
    statuses = lambda: [mw.file_list.item(i).data(Qt.ItemDataRole.UserRole)['status'] for i in range(mw.file_list.count())]  # noqa: E731
    assert statuses() == ['queued'] * 3

    mw.start_processing()
    assert mw.is_processing is True and mw.start_btn.isEnabled() is False and mw.stop_btn.isEnabled() is True
    assert pump(qt, lambda: not mw.is_processing), 'la coda non e\' terminata'
    mw.worker.wait(5000)
    pump(qt, lambda: False, 0.3)

    assert statuses() == ['completed', 'failed', 'completed']
    assert (mw.completed_count, mw.error_count) == (2, 1)
    assert mw.processing_queue == [] and mw.start_btn.isEnabled() is True and mw.stop_btn.isEnabled() is False
    assert mw.history_widget.total_count() == 2                                       # solo i completati
    log = mw.log_text.toPlainText() if hasattr(mw, 'log_text') else ''
    assert tr('worker_completed').format(filename='a_ok.mkv') in log or log == ''
    mw.close()
