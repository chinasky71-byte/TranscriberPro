# -*- coding: utf-8 -*-
"""
SyncBatchWorker — coda multi-file del Subtitle Sync
File: gui/sync_batch_worker.py

Adattatore Qt sul motore senza Qt `core/jobs/sync_batch.py` (`SyncBatchEngine`): resta un QThread con gli stessi 6 segnali, emessi dal
thread del worker nello stesso ordine di prima. Il ciclo, il sottoprocesso `core.sync_cli` per coppia, l'ambiente, l'avanzamento e
l'annullamento (kill dell'albero) vivono nel motore.
"""
from typing import List

from PyQt6.QtCore import QThread, pyqtSignal

from core.jobs.sync_batch import SyncBatchEngine, SyncBatchListener, kill_proc_tree  # noqa: F401  (kill_proc_tree: vecchio nome)


class _SignalListener(SyncBatchListener):
    def __init__(self, worker: 'SyncBatchWorker'):
        self._w = worker

    def on_log(self, text):
        self._w.log_message.emit(text)

    def on_pair_started(self, idx, video):
        self._w.pair_started.emit(idx, video)

    def on_pair_progress(self, idx, pct):
        self._w.pair_progress.emit(idx, pct)

    def on_pair_finished(self, idx, ok, info):
        self._w.pair_finished.emit(idx, ok, info)

    def on_batch_progress(self, done, total):
        self._w.batch_progress.emit(done, total)

    def on_all_done(self, ok, fail, skipped):
        self._w.all_done.emit(ok, fail, skipped)


class SyncBatchWorker(QThread):
    """pairs: lista di oggetti con .video, .srt, .output (core.sync_pairing.Pair già filtrata con runnable())."""

    log_message = pyqtSignal(str)
    pair_started = pyqtSignal(int, str)          # indice, percorso video
    pair_progress = pyqtSignal(int, int)         # indice, percentuale della coppia
    pair_finished = pyqtSignal(int, bool, str)   # indice, ok, output oppure messaggio d'errore
    batch_progress = pyqtSignal(int, int)        # coppie concluse, totale
    all_done = pyqtSignal(int, int, int)         # riuscite, fallite, non eseguite (annullate)

    CLI_MODULE = 'core.sync_cli'                 # sostituibile nei test

    def __init__(self, pairs: List, parent=None):
        super().__init__(parent)
        self._pairs = list(pairs)
        self._engine = SyncBatchEngine(self._pairs, _SignalListener(self), cli_module=lambda: self.CLI_MODULE)

    @property
    def is_cancelled(self) -> bool:
        return self._engine.is_cancelled

    @is_cancelled.setter
    def is_cancelled(self, value: bool) -> None:
        self._engine.is_cancelled = value

    def cancel(self) -> None:
        self._engine.cancel()

    def run(self) -> None:
        self._engine.run()
