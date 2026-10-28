# -*- coding: utf-8 -*-
"""SyncRunner: sincronizzazione di UN video con un SRT esterno, senza Qt e senza GUI.

Trasposizione fedele di `SyncWorker.run()` (gui/sync_worker.py): usa `SubtitleSynchronizer` nel processo chiamante, traduce i suoi
log/avanzamenti in percentuali e chiama i ganci del `SyncListener`. I ganci sono chiamati nel thread che esegue `run()`.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

STEP_PCT = {'1': 10, '2': 40, '3': 80, '4': 95}
# Ancorato a inizio stringa con match() (non search()): senza l'ancora, QUALUNQUE messaggio di log contenente "<cifre>. " in un punto
# qualsiasi — es. un nome file come "1. Titolo.synced.it.srt" nel log finale dello step 4 — farebbe combaciare il pattern e far
# retrocedere la barra di progresso.
STEP_RE = re.compile(r'^\n?([1-4])\.\s')


class SyncListener:
    """Ganci del sync singolo. Tutti facoltativi."""

    def on_started(self, video: str) -> None: ...

    def on_log(self, text: str) -> None: ...

    def on_progress(self, pct: int) -> None: ...

    def on_file_progress(self, video: str, pct: int) -> None: ...

    def on_output_ready(self, output_path: str) -> None:
        """Percorso REALE del file scritto (deriva dall'SRT esterno, non dal video)."""

    def on_completed(self, video: str) -> None: ...

    def on_error(self, message: str) -> None: ...

    def on_finished(self) -> None: ...


class SyncRunner:
    def __init__(self, video_path: str, external_srt_path: str, output_path: Optional[str] = None,
                 listener: Optional[SyncListener] = None):
        self.video_path = video_path
        self.external_srt_path = external_srt_path
        self.output_path = output_path
        self.listener = listener or SyncListener()
        self._synchronizer = None
        self.is_cancelled = False

    def run(self) -> None:
        from core.subtitle_synchronizer import SubtitleSynchronizer

        L = self.listener
        L.on_started(self.video_path)
        try:
            self._synchronizer = SubtitleSynchronizer(
                video_path=self.video_path,
                external_srt_path=self.external_srt_path,
                output_path=self.output_path,
                log_callback=self._on_log,
                progress_callback=self._on_progress,
            )
            success = self._synchronizer.synchronize()

            if success:
                L.on_output_ready(str(self._synchronizer._output_path))
                L.on_completed(self.video_path)
            else:
                if not self.is_cancelled:
                    L.on_error("Sincronizzazione fallita — controlla il log per i dettagli.")
        except Exception as exc:
            logger.exception("SyncWorker: eccezione non gestita")
            L.on_error(str(exc))
        finally:
            L.on_finished()

    def cancel(self) -> None:
        self.is_cancelled = True
        if self._synchronizer is not None:
            self._synchronizer.cancel()

    # ── Callbacks da SubtitleSynchronizer ─────────────────────────────────────
    def _on_log(self, msg: str) -> None:
        self.listener.on_log(msg)
        # Aggiorna file_progress in base al numero di step nel messaggio
        m = STEP_RE.match(msg)
        if m:
            pct = STEP_PCT.get(m.group(1))
            if pct is not None:
                self.listener.on_file_progress(self.video_path, pct)

    def _on_progress(self, pct: int) -> None:
        self.listener.on_progress(pct)
        self.listener.on_file_progress(self.video_path, pct)
