# -*- coding: utf-8 -*-
"""
OcrWorker — QThread per il modulo OCR sottotitoli bitmap (PGS → SRT).
File: gui/ocr_worker.py

Adattatore Qt sul motore senza Qt `core/jobs/ocr_run.py` (`OcrRunEngine`): resta un QThread con gli stessi segnali, emessi dal thread
del worker nello stesso ordine di prima. Due fasi attorno alla UI di revisione (che vive sul main thread):
  - mode 'ocr':        esegue PgsOcr.ocr_to_events() (ramo review) o run_auto() (ramo auto). Per il ramo review emette events_ready.
  - mode 'writeback':  applica un SRT (testo corretto dalla revisione) via PgsOcr.writeback() fuori dal main thread (il mux può
                       richiedere tempo).
"""
import weakref

from PyQt6.QtCore import QThread, pyqtSignal

from core.jobs.ocr_run import OcrListener, OcrRunEngine


class _SignalListener(OcrListener):
    """Riferimento DEBOLE al worker: niente ciclo worker -> motore -> listener -> worker."""

    def __init__(self, worker: 'OcrWorker'):
        self._ref = weakref.ref(worker)

    @property
    def _w(self):
        return self._ref()

    def on_log(self, text):
        self._w.log_message.emit(text)

    def on_error(self, message):
        self._w.error.emit(message)

    def on_finished(self):
        self._w.finished.emit()

    def on_events_ready(self, events, language):
        self._w.events_ready.emit(events, language)

    def on_auto_done(self, ok):
        self._w.auto_done.emit(ok)

    def on_writeback_done(self, ok):
        self._w.writeback_done.emit(ok)

    def on_unsupported(self, message):
        self._w.unsupported.emit(message)

    def on_lang_unsupported(self, message):
        self._w.lang_unsupported.emit(message)

    def on_progress(self, percent, label):
        self._w.progress.emit(percent, label)


class OcrWorker(QThread):
    """Worker per l'OCR PGS e per il write-back, fuori dal main thread."""

    log_message    = pyqtSignal(str)
    error          = pyqtSignal(str)
    finished       = pyqtSignal()
    events_ready   = pyqtSignal(object, str)   # (list[OcrEvent], language) — ramo review
    auto_done      = pyqtSignal(bool)          # ramo auto completato (ok?)
    writeback_done = pyqtSignal(bool)          # write-back completato (ok?)
    unsupported    = pyqtSignal(str)           # formato bitmap non supportato → failed
    lang_unsupported = pyqtSignal(str)         # lingua senza tessdata → skipped (completed)
    progress       = pyqtSignal(int, str)      # (percentuale 0-100, etichetta step)

    def __init__(self, video_path: str, config, strategy: str,
                 mode: str = "ocr", srt_text: str = "", language: str = "ita",
                 kind: str = "pgs", parent=None):
        super().__init__(parent)
        self._engine = OcrRunEngine(video_path, config, strategy, mode, srt_text, language, kind, _SignalListener(self))

    # Attributi pubblici (letti da chi usa il worker): vivono nel motore.
    video_path = property(lambda self: self._engine.video_path)
    config = property(lambda self: self._engine.config)
    strategy = property(lambda self: self._engine.strategy)
    mode = property(lambda self: self._engine.mode)
    srt_text = property(lambda self: self._engine.srt_text)
    language = property(lambda self: self._engine.language)
    kind = property(lambda self: self._engine.kind)

    @property
    def _ocr(self):
        return self._engine._ocr

    @_ocr.setter
    def _ocr(self, value):
        self._engine._ocr = value

    @property
    def is_cancelled(self) -> bool:
        return self._engine.is_cancelled

    @is_cancelled.setter
    def is_cancelled(self, value: bool) -> None:
        self._engine.is_cancelled = value

    def _make_ocr(self):
        """Istanzia il motore giusto in base al tipo di bitmap (logica condivisa)."""
        return self._engine._make_ocr()

    def run(self):
        self._engine.run()

    def cancel(self):
        self._engine.cancel()
