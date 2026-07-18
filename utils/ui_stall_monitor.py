# -*- coding: utf-8 -*-
"""
UI Stall Monitor — telemetria TEMPORANEA (Fase 0, revisione freeze avvio).
File: utils/ui_stall_monitor.py

Un QTimer sul main thread aggiorna un heartbeat ogni 100 ms; un thread
watchdog daemon controlla il battito. Se il main thread non processa eventi
per più di STALL_THRESHOLD secondi, scrive nel file di log lo stack esatto
del main thread ([UI-STALL]) — così ogni freeze è attribuito alla riga di
codice che lo causa, senza dover indovinare dove strumentare.

- Durante uno stall lungo lo stack viene ri-campionato ogni REDUMP_INTERVAL
  secondi (il blocco può attraversare più operazioni).
- A fine stall viene loggata la durata totale.
- Il monitoraggio parte dal PRIMO heartbeat: lo startup (prima dell'event
  loop) non genera falsi positivi.

Costo a regime: un timer da 100 ms + un thread che dorme 50 ms.
DA RIMUOVERE (o mettere dietro flag config) a fine revisione ingegneristica.
"""
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QObject, QTimer

# setup_logger obbligatorio: logging.getLogger(__name__) NON avrebbe handler
# (il file handler condiviso viene agganciato solo dai setup_logger espliciti)
from utils.logger import setup_logger

logger = setup_logger('utils.ui_stall_monitor')

STALL_THRESHOLD = 0.30    # s senza heartbeat = main thread considerato bloccato
BEAT_INTERVAL_MS = 100    # periodo del QTimer heartbeat
POLL_INTERVAL = 0.05      # periodo di controllo del watchdog
REDUMP_INTERVAL = 2.0     # ri-campiona lo stack ogni N s durante stall lunghi


class UiStallMonitor(QObject):
    """Rileva e logga i blocchi del thread GUI con lo stack responsabile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_beat = None
        self._main_tid = threading.main_thread().ident
        self._timer = QTimer(self)
        self._timer.setInterval(BEAT_INTERVAL_MS)
        self._timer.timeout.connect(self._beat)

    def start(self):
        self._timer.start()
        threading.Thread(target=self._watch, name="ui-stall-watchdog",
                         daemon=True).start()
        logger.info("[UI-STALL] monitor attivo (soglia %d ms)",
                    int(STALL_THRESHOLD * 1000))

    def _beat(self):
        self._last_beat = time.monotonic()

    def _main_stack(self) -> str:
        frame = sys._current_frames().get(self._main_tid)
        if frame is None:
            return "<stack main thread non disponibile>"
        return "".join(traceback.format_stack(frame))

    def _watch(self):
        # Nessuna misura finché l'event loop non produce il primo battito
        while self._last_beat is None:
            time.sleep(POLL_INTERVAL)

        stall_start = None      # ultimo beat prima dello stall in corso
        last_dump = 0.0
        while True:
            time.sleep(POLL_INTERVAL)
            last = self._last_beat
            now = time.monotonic()

            # Beat ripreso dopo uno stall → logga la durata e chiudi lo stall
            if stall_start is not None and last != stall_start:
                logger.warning("[UI-STALL] fine stall — durata totale: %.0f ms",
                               (last - stall_start) * 1000)
                stall_start = None

            gap = now - last
            if gap > STALL_THRESHOLD:
                if stall_start is None:
                    stall_start = last
                    last_dump = 0.0
                if now - last_dump >= REDUMP_INTERVAL:
                    last_dump = now
                    logger.warning(
                        "[UI-STALL] main thread bloccato da %.0f ms — stack:\n%s",
                        gap * 1000, self._main_stack())
