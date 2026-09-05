# -*- coding: utf-8 -*-
"""
SyncWorker — QThread per SubtitleSynchronizer
File: gui/sync_worker.py
"""

import re
import logging
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


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

    _STEP_PCT = {'1': 10, '2': 40, '3': 80, '4': 95}
    # Ancorato a inizio stringa con match() (non search()): senza l'ancora,
    # QUALUNQUE messaggio di log contenente "<cifre>. " in un punto
    # qualsiasi — es. un nome file come "1. Titolo.synced.it.srt" nel log
    # finale dello step 4 — farebbe combaciare il pattern e far retrocedere
    # la barra di progresso.
    _step_re  = re.compile(r'^\n?([1-4])\.\s')

    def __init__(self, video_path: str, external_srt_path: str, output_path: str = None, parent=None):
        super().__init__(parent)
        self.video_path        = video_path
        self.external_srt_path = external_srt_path
        self.output_path       = output_path
        self._synchronizer     = None
        self.is_cancelled      = False

    # ── QThread entry point ───────────────────────────────────────────────────

    def run(self):
        from core.subtitle_synchronizer import SubtitleSynchronizer

        self.file_started.emit(self.video_path)
        try:
            self._synchronizer = SubtitleSynchronizer(
                video_path        = self.video_path,
                external_srt_path = self.external_srt_path,
                output_path       = self.output_path,
                log_callback      = self._on_log,
                progress_callback = self._on_progress,
            )
            success = self._synchronizer.synchronize()

            if success:
                self.output_ready.emit(str(self._synchronizer._output_path))
                self.file_completed.emit(self.video_path)
            else:
                if not self.is_cancelled:
                    self.error.emit("Sincronizzazione fallita — controlla il log per i dettagli.")
        except Exception as exc:
            logger.exception("SyncWorker: eccezione non gestita")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    # ── Cancellazione ─────────────────────────────────────────────────────────

    def cancel(self):
        self.is_cancelled = True
        if self._synchronizer is not None:
            self._synchronizer.cancel()

    # ── Callbacks da SubtitleSynchronizer ─────────────────────────────────────

    def _on_log(self, msg: str):
        self.log_message.emit(msg)
        # Aggiorna file_progress in base al numero di step nel messaggio
        m = self._step_re.match(msg)
        if m:
            step_key = m.group(1)
            pct = self._STEP_PCT.get(step_key)
            if pct is not None:
                self.file_progress.emit(self.video_path, pct)

    def _on_progress(self, pct: int):
        self.progress.emit(pct)
        self.file_progress.emit(self.video_path, pct)
