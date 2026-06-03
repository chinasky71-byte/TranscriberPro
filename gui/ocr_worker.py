# -*- coding: utf-8 -*-
"""
OcrWorker — QThread per il modulo OCR sottotitoli bitmap (PGS → SRT).
File: gui/ocr_worker.py

Due fasi attorno alla UI di revisione (che vive sul main thread):
  - mode 'ocr':        esegue PgsOcr.ocr_to_events() (ramo review) o run_auto()
                       (ramo auto). Per il ramo review emette events_ready.
  - mode 'writeback':  applica un SRT (testo corretto dalla revisione) via
                       PgsOcr.writeback() fuori dal main thread (il mux può
                       richiedere tempo).
"""
import logging
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class OcrWorker(QThread):
    """Worker per l'OCR PGS e per il write-back, fuori dal main thread."""

    log_message  = pyqtSignal(str)
    error        = pyqtSignal(str)
    finished     = pyqtSignal()
    events_ready = pyqtSignal(object, str)   # (list[OcrEvent], language) — ramo review
    auto_done    = pyqtSignal(bool)          # ramo auto completato (ok?)
    writeback_done = pyqtSignal(bool)        # write-back completato (ok?)
    unsupported  = pyqtSignal(str)           # bitmap non supportato (es. VOBSUB)
    progress     = pyqtSignal(int, str)      # (percentuale 0-100, etichetta step)

    def __init__(self, video_path: str, config, strategy: str,
                 mode: str = "ocr", srt_text: str = "", language: str = "ita",
                 kind: str = "pgs", parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.config = config
        self.strategy = strategy
        self.mode = mode
        self.srt_text = srt_text
        self.language = language
        self.kind = kind  # 'pgs' | 'vobsub'
        self._ocr = None
        self.is_cancelled = False

    def _make_ocr(self):
        """Istanzia il motore giusto in base al tipo di bitmap."""
        if self.kind == "vobsub":
            from core.vobsub_ocr import VobSubOcr
            return VobSubOcr(self.video_path, self.config,
                             log_callback=self._on_log, progress_callback=self._on_progress)
        from core.pgs_ocr import PgsOcr
        return PgsOcr(self.video_path, self.config,
                      log_callback=self._on_log, progress_callback=self._on_progress)

    def run(self):
        # BitmapNotSupported è definita in entrambi i moduli (classi distinte): catturale entrambe.
        from core.pgs_ocr import BitmapNotSupported as PgsNotSupported
        from core.vobsub_ocr import BitmapNotSupported as VobNotSupported
        from core.pgs_types import STRATEGY_AUTO
        _not_supported = (PgsNotSupported, VobNotSupported)
        try:
            self._ocr = self._make_ocr()

            if self.mode == "writeback":
                ok = self._ocr.writeback(self.srt_text, self.language)
                self.writeback_done.emit(ok)
                return

            if self.strategy == STRATEGY_AUTO:
                ok = self._ocr.run_auto()
                self.auto_done.emit(ok)
            else:
                events, lang = self._ocr.ocr_to_events()
                self.events_ready.emit(events, lang)

        except _not_supported as exc:
            self.unsupported.emit(str(exc))
        except InterruptedError:
            self.log_message.emit("OCR annullato")
        except Exception as exc:
            logger.exception("OcrWorker: eccezione non gestita")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def cancel(self):
        self.is_cancelled = True
        if self._ocr is not None:
            self._ocr.cancel()

    def _on_log(self, msg: str):
        self.log_message.emit(msg)

    def _on_progress(self, percent: int, label: str):
        self.progress.emit(percent, label)
