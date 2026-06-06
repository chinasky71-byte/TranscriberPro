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
        from core.pgs_types import STRATEGY_AUTO, is_italian, events_to_srt, UnsupportedLanguage
        _not_supported = (PgsNotSupported, VobNotSupported)
        try:
            self._ocr = self._make_ocr()

            if self.mode == "writeback":
                ok = self._ocr.writeback(self.srt_text, self.language)
                self.writeback_done.emit(ok)
                return

            if self.strategy == STRATEGY_AUTO:
                # Auto: run_auto() gestisce TUTTE le tracce italiane (singola o multi-stream).
                # Se non ci sono tracce italiane di questo codec, rilancia BitmapNotSupported
                # → catturata sotto → cade nel ramo OCR+traduzione via ocr_to_events().
                try:
                    ok = self._ocr.run_auto()
                    self.auto_done.emit(ok)
                    return
                except _not_supported:
                    # Nessuna traccia italiana di questo codec → prova tracce non-italiane.
                    events, content_lang = self._ocr.ocr_to_events()
                    ok = self._convert_and_translate(events, content_lang)
                    self.auto_done.emit(ok)
            else:
                # Review: singola traccia migliore per UI di revisione.
                events, content_lang = self._ocr.ocr_to_events()
                if is_italian(content_lang):
                    self.events_ready.emit(events, 'it')
                else:
                    # Traccia NON italiana → automatico: OCR sorgente + traduzione → .it.srt.
                    ok = self._convert_and_translate(events, content_lang)
                    self.auto_done.emit(ok)

        except _not_supported as exc:
            self.unsupported.emit(str(exc))
        except UnsupportedLanguage as exc:
            self.log_message.emit(f"Lingua non supportata da Tesseract, file saltato: {exc}")
            self.lang_unsupported.emit(str(exc))
        except InterruptedError:
            self.log_message.emit("OCR annullato")
        except Exception as exc:
            logger.exception("OcrWorker: eccezione non gestita")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _convert_and_translate(self, events, content_lang: str) -> bool:
        """
        Traccia non italiana: OCR sorgente → traduzione → .it.srt.
        Se la modalità è mux, rimux nel video e cancella i sidecar intermedi.
        Se la modalità è sidecar, mantiene .it.srt e cancella il sorgente intermedio.
        """
        from core.pgs_types import events_to_srt, CFG_WRITEBACK, WRITEBACK_MUX
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
            # NON emettere error qui: run() emette già auto_done(False) → evita doppio
            # popup (singolo) e doppio conteggio fail (batch).
            logger.exception("Traduzione OCR fallita")
            self._on_log(f"Traduzione fallita: {exc}")
            return False

        if not ok:
            return False

        is_mux = self._ocr._cfg(CFG_WRITEBACK, WRITEBACK_MUX) == WRITEBACK_MUX
        if is_mux:
            # Rimux .it.srt nel file video, poi cancella i sidecar.
            try:
                it_text = it_path.read_text(encoding='utf-8')
            except Exception as exc:
                self._on_log(f"Impossibile leggere {it_path.name}: {exc}")
                return False
            mux_ok = self._ocr.writeback(it_text, 'it')
            for p in (Path(src_path), it_path):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            if mux_ok:
                self._on_log(f"SRT italiano incorporato nel file video")
            return mux_ok
        else:
            # Modalità sidecar: it_path è l'output, rimuovi solo il sorgente intermedio.
            try:
                Path(src_path).unlink(missing_ok=True)
            except Exception:
                pass
            self._on_log(f"SRT italiano scritto: {it_path.name}")
            return True

    def cancel(self):
        self.is_cancelled = True
        if self._ocr is not None:
            self._ocr.cancel()

    def _on_log(self, msg: str):
        self.log_message.emit(msg)

    def _on_progress(self, percent: int, label: str):
        self.progress.emit(percent, label)
