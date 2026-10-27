# -*- coding: utf-8 -*-
"""
SyncWorker — QThread per SubtitleSynchronizer
File: gui/sync_worker.py

Adattatore Qt sul motore senza Qt `core/jobs/sync_single.py` (`SyncRunner`): resta un QThread con gli stessi segnali, emessi dal thread
del worker nello stesso ordine di prima.
"""
from PyQt6.QtCore import QThread, pyqtSignal

from core.jobs.sync_single import STEP_PCT, STEP_RE, SyncListener, SyncRunner


class _SignalListener(SyncListener):
    def __init__(self, worker: 'SyncWorker'):
        self._w = worker

    def on_started(self, video):
        self._w.file_started.emit(video)

    def on_log(self, text):
        self._w.log_message.emit(text)

    def on_progress(self, pct):
        self._w.progress.emit(pct)

    def on_file_progress(self, video, pct):
        self._w.file_progress.emit(video, pct)

    def on_output_ready(self, output_path):
        self._w.output_ready.emit(output_path)

    def on_completed(self, video):
        self._w.file_completed.emit(video)

    def on_error(self, message):
        self._w.error.emit(message)

    def on_finished(self):
        self._w.finished.emit()


class SyncWorker(QThread):
    """Worker thread per la sincronizzazione sottotitoli."""

    progress       = pyqtSignal(int)
    log_message    = pyqtSignal(str)
    finished       = pyqtSignal()
    file_progress  = pyqtSignal(str, int)
    file_completed = pyqtSignal(str)
    file_started   = pyqtSignal(str)
    error          = pyqtSignal(str)
    # Percorso REALE del file scritto (deriva dall'SRT esterno, non dal
    # video — vedi SyncDialog._on_completed): SyncDialog lo mostra all'utente
    # invece di ricalcolarlo per conto proprio dal video_path, che con SRT e
    # video in cartelle diverse produceva un percorso che non esisteva.
    output_ready   = pyqtSignal(str)

    _STEP_PCT = STEP_PCT
    _step_re  = STEP_RE

    def __init__(self, video_path: str, external_srt_path: str, output_path: str = None, parent=None):
        super().__init__(parent)
        self.video_path        = video_path
        self.external_srt_path = external_srt_path
        self.output_path       = output_path
        self._runner = SyncRunner(video_path, external_srt_path, output_path, _SignalListener(self))

    @property
    def _synchronizer(self):
        return self._runner._synchronizer

    @property
    def is_cancelled(self) -> bool:
        return self._runner.is_cancelled

    @is_cancelled.setter
    def is_cancelled(self, value: bool) -> None:
        self._runner.is_cancelled = value

    def run(self):
        self._runner.run()

    def cancel(self):
        self._runner.cancel()
