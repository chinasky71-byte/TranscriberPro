# -*- coding: utf-8 -*-
"""
OCR bitmap automatico — logica condivisa (senza Qt).
File: core/ocr_auto.py

Estrae la logica di OCR AUTO che prima viveva solo in gui/ocr_worker.py, così
che possa essere usata sia dall'OcrWorker (GUI, Library Scanner) sia dalla
ProcessingPipeline (coda principale, subprocess headless) quando un film ha solo
sottotitoli bitmap (PGS/VOBSUB).

Comportamento AUTO:
- `run_auto()` converte TUTTE le tracce ITALIANE (singola → writeback; multi →
  mux single-pass);
- se non c'è alcuna traccia italiana di quel codec (`BitmapNotSupported`), OCR
  della traccia migliore + traduzione in italiano → `.it.srt` (+ mux se configurato).

Propaga `BitmapNotSupported` (nessun bitmap) e `UnsupportedLanguage` (tessdata
mancante): il chiamante decide come gestirle (es. fallback a trascrizione).
"""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def make_bitmap_ocr(video_path, config, kind: str,
                    log_callback=None, progress_callback=None):
    """Istanzia il motore OCR giusto in base al tipo di bitmap ('pgs' | 'vobsub')."""
    if kind == "vobsub":
        from core.vobsub_ocr import VobSubOcr
        return VobSubOcr(video_path, config,
                         log_callback=log_callback, progress_callback=progress_callback)
    from core.pgs_ocr import PgsOcr
    return PgsOcr(video_path, config,
                  log_callback=log_callback, progress_callback=progress_callback)


def run_ocr_auto(ocr, log_callback=None) -> bool:
    """Esegue l'OCR AUTO su un motore già istanziato (`make_bitmap_ocr`).

    - tracce ITALIANE → `run_auto()` (writeback / mux);
    - nessuna italiana (`BitmapNotSupported`) → OCR traccia migliore + traduzione.

    Propaga `BitmapNotSupported` se non c'è alcun bitmap e `UnsupportedLanguage`
    se manca il tessdata della lingua.
    """
    from core.pgs_ocr import BitmapNotSupported as PgsNotSupported
    from core.vobsub_ocr import BitmapNotSupported as VobNotSupported
    _not_supported = (PgsNotSupported, VobNotSupported)

    try:
        return ocr.run_auto()
    except _not_supported:
        # Nessuna traccia italiana di questo codec → OCR della traccia migliore
        # (non italiana) + traduzione verso l'italiano. Se non c'è NESSUN bitmap,
        # ocr_to_events rilancia BitmapNotSupported → propagata al chiamante.
        events, content_lang = ocr.ocr_to_events()
        return convert_and_translate(ocr, events, content_lang, log_callback)


def convert_and_translate(ocr, events, content_lang: str, log_callback=None) -> bool:
    """Traccia NON italiana: OCR sorgente → traduzione → `.it.srt`.
    Se la modalità è mux, rimux nel video e cancella i sidecar intermedi; se
    sidecar, mantiene `.it.srt` e cancella il sorgente intermedio.
    """
    from core.pgs_types import events_to_srt, CFG_WRITEBACK, WRITEBACK_MUX

    def _log(msg):
        if log_callback:
            log_callback(msg)

    src_text = events_to_srt(events)
    if not src_text.strip():
        _log("Nessun testo OCR prodotto")
        return False

    src_path = ocr.write_sidecar(src_text, content_lang)   # <stem>.<lang>.srt
    video = ocr.video_path
    it_path = video.with_name(f"{video.stem}.it.srt")

    _log(f"⚙️ OCR — Traduzione {content_lang}→it...")
    try:
        from core.translator import get_translator, route_non_english_away_from_llm
        # Instradamento automatico (v1.25.0): questo percorso (OCR bitmap, coda
        # principale E Library Scanner) chiama get_translator() a parte dallo
        # STEP 6 di core/pipeline.py, quindi ha bisogno dello stesso instradamento
        # esplicito. Senza, un PGS/VOBSUB francese finirebbe comunque su
        # TranslateGemma etichettato "en" (vedi traduzione_non_inglese_2026_09_27.md).
        try:
            from utils.config import get_config
            model_type = get_config().get_translation_model()
        except Exception:
            model_type = None
        routed = route_non_english_away_from_llm(model_type, content_lang) if model_type else None
        if routed and routed != model_type:
            _log(f"⚠️ TranslateGemma non e' pronto per sorgenti diverse "
                 f"dall'inglese ({content_lang}): instradato automaticamente "
                 f"su NLLB fine-tuned.")
        translator = get_translator(model_type=routed or model_type)
        ok = translator.translate_file(
            Path(src_path), it_path, src_lang=content_lang, tgt_lang='it')
        try:
            translator.unload()
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Traduzione OCR fallita")
        _log(f"Traduzione fallita: {exc}")
        return False

    if not ok:
        return False

    is_mux = ocr._cfg(CFG_WRITEBACK, WRITEBACK_MUX) == WRITEBACK_MUX
    if is_mux:
        try:
            it_text = it_path.read_text(encoding='utf-8')
        except Exception as exc:
            _log(f"Impossibile leggere {it_path.name}: {exc}")
            return False
        mux_ok = ocr.writeback(it_text, 'it')
        for p in (Path(src_path), it_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        if mux_ok:
            _log("✅ SRT italiano incorporato nel file")
        return mux_ok
    else:
        try:
            Path(src_path).unlink(missing_ok=True)
        except Exception:
            pass
        _log(f"✅ SRT italiano scritto: {it_path.name}")
        return True
