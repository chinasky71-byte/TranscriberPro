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
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


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
        """Istanzia il motore giusto in base al tipo di bitmap (logica condivisa)."""
        from core.ocr_auto import make_bitmap_ocr
        return make_bitmap_ocr(self.video_path, self.config, self.kind,
                               log_callback=self._on_log, progress_callback=self._on_progress)

    def run(self):
        # BitmapNotSupported è definita in entrambi i moduli (classi distinte): catturale entrambe.
        from core.pgs_ocr import BitmapNotSupported as PgsNotSupported
        from core.vobsub_ocr import BitmapNotSupported as VobNotSupported
        from core.pgs_types import STRATEGY_AUTO, is_italian, events_to_srt, UnsupportedLanguage
        _not_supported = (PgsNotSupported, VobNotSupported)
        try:
            self._ocr = self._make_ocr()

            if self.mode == "writeback":
                ok = self._ocr.writeback(self.srt_text, self.language)
                self.writeback_done.emit(ok)
                return

            kind_label = 'VOBSUB' if self.kind == 'vobsub' else 'PGS'
            self._on_log(f"🎬 OCR {kind_label} — {Path(self.video_path).name}")

            if self.strategy == STRATEGY_AUTO:
                # Auto: run_ocr_auto() gestisce TUTTE le tracce italiane (run_auto) e,
                # se non ce ne sono, OCR della traccia migliore + traduzione. Logica
                # condivisa con la pipeline principale (core.ocr_auto). Propaga
                # BitmapNotSupported / UnsupportedLanguage → catturate sotto.
                from core.ocr_auto import run_ocr_auto
                ok = run_ocr_auto(self._ocr, log_callback=self._on_log)
                self.auto_done.emit(ok)
            else:
                # Review: singola traccia migliore per UI di revisione.
                events, content_lang = self._ocr.ocr_to_events()
                if is_italian(content_lang):
                    self.events_ready.emit(events, 'it')
                else:
                    # Traccia NON italiana → automatico: OCR sorgente + traduzione → .it.srt.
                    from core.ocr_auto import convert_and_translate
                    ok = convert_and_translate(self._ocr, events, content_lang, self._on_log)
                    self.auto_done.emit(ok)

        except _not_supported as exc:
            self.unsupported.emit(str(exc))
        except UnsupportedLanguage as exc:
            self.log_message.emit(f"⚠ Tesseract: lingua non supportata, file saltato")
            logger.warning(f"UnsupportedLanguage: {exc}")
            self.lang_unsupported.emit(str(exc))
        except InterruptedError:
            self.log_message.emit("❌ OCR annullato")
        except Exception as exc:
            logger.exception("OcrWorker: eccezione non gestita")
            self.log_message.emit(f"❌ OCR errore: {exc}")
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
