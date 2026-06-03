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
        from core.pgs_types import STRATEGY_AUTO, is_italian, events_to_srt
        _not_supported = (PgsNotSupported, VobNotSupported)
        try:
            self._ocr = self._make_ocr()

            if self.mode == "writeback":
                ok = self._ocr.writeback(self.srt_text, self.language)
                self.writeback_done.emit(ok)
                return

            events, content_lang = self._ocr.ocr_to_events()

            if is_italian(content_lang):
                # Traccia già italiana → flusso normale (review o auto).
                if self.strategy == STRATEGY_AUTO:
                    srt = events_to_srt(events)
                    ok = self._ocr.writeback(srt, 'it') if srt.strip() else False
                    self.auto_done.emit(ok)
                else:
                    self.events_ready.emit(events, 'it')
            else:
                # Traccia NON italiana → SEMPRE automatico: OCR sorgente + traduzione → .it.srt.
                ok = self._convert_and_translate(events, content_lang)
                self.auto_done.emit(ok)

        except _not_supported as exc:
            self.unsupported.emit(str(exc))
        except InterruptedError:
            self.log_message.emit("OCR annullato")
        except Exception as exc:
            logger.exception("OcrWorker: eccezione non gestita")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _convert_and_translate(self, events, content_lang: str) -> bool:
        """
        Traccia non italiana: scrive il sidecar nella lingua sorgente, poi traduce
        verso l'italiano e salva <stem>.it.srt (si tengono ENTRAMBI i file).
        """
        from core.pgs_types import events_to_srt
        from pathlib import Path

        src_text = events_to_srt(events)
        if not src_text.strip():
            self._on_log("Nessun testo OCR prodotto")
            return False

        src_path = self._ocr.write_sidecar(src_text, content_lang)   # <stem>.<lang>.srt
        video = self._ocr.video_path
        it_path = video.with_name(f"{video.stem}.it.srt")

        self._on_log(f"Traduzione {content_lang}→it in corso...")
        try:
            from core.translator import get_translator
            translator = get_translator()
            ok = translator.translate_file(
                Path(src_path), it_path, src_lang=content_lang, tgt_lang='it')
            try:
                translator.unload()
            except Exception:
                pass
        except Exception as exc:
            logger.exception("Traduzione OCR fallita")
            self.error.emit(f"Traduzione fallita: {exc}")
            return False

        if ok:
            self._on_log(f"SRT italiano scritto: {it_path.name}")
        return bool(ok)

    def cancel(self):
        self.is_cancelled = True
        if self._ocr is not None:
            self._ocr.cancel()

    def _on_log(self, msg: str):
        self.log_message.emit(msg)

    def _on_progress(self, percent: int, label: str):
        self.progress.emit(percent, label)
