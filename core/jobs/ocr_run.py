# -*- coding: utf-8 -*-
"""OcrRunEngine: OCR dei sottotitoli bitmap (PGS/VobSub -> SRT) e write-back, senza Qt e senza GUI.

Trasposizione fedele di `OcrWorker.run()` (gui/ocr_worker.py). Due modi attorno alla revisione (che vive sul thread della GUI):
  - 'ocr':        ramo review -> `ocr_to_events()` e `on_events_ready`; ramo auto -> `run_ocr_auto()` e `on_auto_done`;
  - 'writeback':  applica un SRT (testo corretto dalla revisione) con `writeback()` e `on_writeback_done`.
I ganci del `OcrListener` sono chiamati nel thread che esegue `run()`."""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OcrListener:
    """Ganci dell'OCR. Tutti facoltativi."""

    def on_log(self, text: str) -> None: ...

    def on_error(self, message: str) -> None: ...

    def on_finished(self) -> None: ...

    def on_events_ready(self, events, language: str) -> None:
        """Ramo review: lista di OcrEvent da rivedere e lingua ('it')."""

    def on_auto_done(self, ok: bool) -> None: ...

    def on_writeback_done(self, ok: bool) -> None: ...

    def on_unsupported(self, message: str) -> None:
        """Formato bitmap non supportato -> il file fallisce."""

    def on_lang_unsupported(self, message: str) -> None:
        """Lingua senza tessdata -> il file viene saltato (completato)."""

    def on_progress(self, percent: int, label: str) -> None: ...


class OcrRunEngine:
    def __init__(self, video_path: str, config, strategy: str, mode: str = "ocr", srt_text: str = "",
                 language: str = "ita", kind: str = "pgs", listener: Optional[OcrListener] = None):
        self.video_path = video_path
        self.config = config
        self.strategy = strategy
        self.mode = mode
        self.srt_text = srt_text
        self.language = language
        self.kind = kind  # 'pgs' | 'vobsub'
        self.listener = listener or OcrListener()
        self._ocr = None
        self.is_cancelled = False

    def _make_ocr(self):
        """Istanzia il motore giusto in base al tipo di bitmap (logica condivisa)."""
        from core.ocr_auto import make_bitmap_ocr
        return make_bitmap_ocr(self.video_path, self.config, self.kind,
                               log_callback=self._on_log, progress_callback=self._on_progress)

    def run(self) -> None:
        L = self.listener
        # BitmapNotSupported è definita in entrambi i moduli (classi distinte): catturale entrambe.
        from core.pgs_ocr import BitmapNotSupported as PgsNotSupported
        from core.vobsub_ocr import BitmapNotSupported as VobNotSupported
        from core.pgs_types import STRATEGY_AUTO, is_italian, UnsupportedLanguage
        _not_supported = (PgsNotSupported, VobNotSupported)
        try:
            self._ocr = self._make_ocr()

            if self.mode == "writeback":
                ok = self._ocr.writeback(self.srt_text, self.language)
                L.on_writeback_done(ok)
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
                L.on_auto_done(ok)
            else:
                # Review: singola traccia migliore per UI di revisione.
                events, content_lang = self._ocr.ocr_to_events()
                if is_italian(content_lang):
                    L.on_events_ready(events, 'it')
                else:
                    # Traccia NON italiana → automatico: OCR sorgente + traduzione → .it.srt.
                    from core.ocr_auto import convert_and_translate
                    ok = convert_and_translate(self._ocr, events, content_lang, self._on_log)
                    L.on_auto_done(ok)

        except _not_supported as exc:
            L.on_unsupported(str(exc))
        except UnsupportedLanguage as exc:
            L.on_log("⚠ Tesseract: lingua non supportata, file saltato")
            logger.warning(f"UnsupportedLanguage: {exc}")
            L.on_lang_unsupported(str(exc))
        except InterruptedError:
            L.on_log("❌ OCR annullato")
        except Exception as exc:
            logger.exception("OcrWorker: eccezione non gestita")
            L.on_log(f"❌ OCR errore: {exc}")
            L.on_error(str(exc))
        finally:
            L.on_finished()

    def cancel(self) -> None:
        self.is_cancelled = True
        if self._ocr is not None:
            self._ocr.cancel()

    def _on_log(self, msg: str) -> None:
        self.listener.on_log(msg)

    def _on_progress(self, percent: int, label: str) -> None:
        self.listener.on_progress(percent, label)
