# -*- coding: utf-8 -*-
"""
Contratto dati del modulo OCR sottotitoli bitmap (PGS→SRT).
File: core/pgs_types.py

Questo file è la SINGOLA FONTE DI VERITÀ dello schema condiviso tra:
  - core/pgs_ocr.py        (produce gli OcrEvent)
  - gui/ocr_review_dialog.py (consuma/edita gli OcrEvent → SRT)
  - gui/ocr_settings_widget.py (usa le chiavi config qui definite)

Congelato dopo lo spike validato del 2026-06-03 (vedi memory/project_pgs_ocr_module.md).
NON modificare lo schema senza aggiornare tutti i consumatori.

Principio non negoziabile: VERBATIM. Il campo `text` deve contenere ESATTAMENTE ciò
che l'OCR legge dal bitmap (refusi inclusi). Nessuna correzione automatica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set, List, Any


# ============================================================================
# Chiavi di configurazione (config.json gestito da utils.config.get_config)
# ============================================================================
CFG_STRATEGY = "ocr_strategy"                 # 'review' | 'auto'
CFG_LANGUAGE = "ocr_language"                 # codice Tesseract, default 'ita'
CFG_CONF_THRESHOLD = "ocr_confidence_threshold"  # int 0-100, default 75
CFG_WRITEBACK = "ocr_writeback"              # 'mux' | 'sidecar'
CFG_TESSERACT_PATH = "ocr_tesseract_path"   # path al binario tesseract (opz., '' = auto)
CFG_OCR_WORKERS = "ocr_workers"             # n. thread OCR paralleli (0 = auto)

# Valori della strategia
STRATEGY_REVIEW = "review"   # OCR pgsreader + Tesseract nostro → UI revisione mirata
STRATEGY_AUTO = "auto"       # stesso motore del review, senza UI di revisione

# Valori write-back
WRITEBACK_MUX = "mux"        # rimuxa l'SRT come nuova traccia nell'MKV (in-place)
WRITEBACK_SIDECAR = "sidecar"  # scrive un file .srt accanto al video

# Default
DEFAULT_STRATEGY = STRATEGY_REVIEW
DEFAULT_LANGUAGE = "ita"
DEFAULT_CONF_THRESHOLD = 75
DEFAULT_WRITEBACK = WRITEBACK_MUX
DEFAULT_OCR_WORKERS = 0      # 0 = auto: min(os.cpu_count(), 8)


# Mappa ISO 639-2 (3 lettere, da ffprobe) → ISO 639-1 (2 lettere, per estensione/traduzione)
class UnsupportedLanguage(Exception):
    """Sollevata quando la lingua della traccia non ha traineddata Tesseract installato."""


LANG_3_TO_2 = {
    'ita': 'it', 'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
    'deu': 'de', 'ger': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
    'kor': 'ko', 'chi': 'zh', 'zho': 'zh', 'ara': 'ar', 'hin': 'hi',
    'pol': 'pl', 'tur': 'tr', 'nld': 'nl', 'dut': 'nl', 'swe': 'sv',
    'dan': 'da', 'nor': 'no', 'fin': 'fi', 'ces': 'cs', 'cze': 'cs',
    'hun': 'hu', 'ron': 'ro', 'rum': 'ro', 'ukr': 'uk', 'ell': 'el',
    'gre': 'el', 'heb': 'he', 'vie': 'vi', 'tha': 'th', 'und': 'und',
}
_ITALIAN_CODES = {'it', 'ita', 'italian', 'italiano'}


def lang_to_2(code) -> str:
    """Normalizza un codice lingua a ISO 639-1 (2 lettere); un codice non riconosciuto -> 'und'
    (prima prendeva le prime 2 lettere: 'zxx' -> 'zx')."""
    from core.subtitle_lang import normalize_lang
    return normalize_lang(code)


def is_italian(code) -> bool:
    return str(code or '').lower() in _ITALIAN_CODES or lang_to_2(code) == 'it'


class ContentNotItalian(Exception):
    """Una traccia bitmap data per italiana (tag) ha prodotto, dopo l'OCR, testo di un'altra lingua:
    va tradotta come una traccia non italiana. Porta il testo SRT dell'OCR (non gli eventi con le immagini:
    occuperebbero molta RAM) e la lingua riconosciuta."""

    def __init__(self, srt_text: str, lang: str, stream_index=None):
        super().__init__(f"contenuto OCR non italiano ({lang})")
        self.srt_text = srt_text
        self.lang = lang
        self.stream_index = stream_index


def resolve_ocr_workers(value) -> int:
    """Risolve il numero di worker OCR: 0/None/invalid → auto = min(cpu, 8)."""
    import os
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    if v > 0:
        return v
    return max(1, min(os.cpu_count() or 4, 8))

# ============================================================================
# Flag eventi (campo OcrEvent.flags)
# ============================================================================
FLAG_LOW_CONF = "low_conf"     # confidenza media sotto soglia → mostra in revisione
FLAG_EMPTY = "empty"           # OCR non ha prodotto testo
FLAG_MULTI_ODS = "multi_ods"   # evento con più ODS concatenati (immagine composita)
FLAG_ITALIC = "italic"         # euristica corsivo (solo per FLAG, mai auto-tag <i>)


@dataclass
class OcrEvent:
    """
    Un singolo sottotitolo OCR.

    Attributi:
        index:       progressivo 1-based dell'evento nell'SRT.
        start_ms:    timestamp inizio in millisecondi (da PGS PCS pts).
        end_ms:      timestamp fine in millisecondi (clear successivo).
        image:       PIL.Image RGBA del bitmap originale (per la revisione; può
                     essere None nel ramo 'auto' che non espone immagini).
        text:        testo OCR VERBATIM (può contenere '\\n' per il multilinea).
        confidence:  media delle confidenze per-parola Tesseract (0-100).
        flags:       insieme di flag (vedi costanti FLAG_*).
        verified:    True dopo conferma umana in revisione.
    """
    index: int
    start_ms: int
    end_ms: int
    text: str = ""
    confidence: float = 0.0
    image: Optional[Any] = None          # PIL.Image.Image
    flags: Set[str] = field(default_factory=set)
    verified: bool = False

    @property
    def is_flagged(self) -> bool:
        """True se l'evento va mostrato nella revisione mirata."""
        return bool(self.flags) and not self.verified


# ============================================================================
# Helper SRT
# ============================================================================
def ms_to_srt_timestamp(ms: int) -> str:
    """Converte millisecondi in 'HH:MM:SS,mmm'."""
    ms = max(0, int(round(ms)))
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1000
    mmm = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{mmm:03d}"


def events_to_srt(events: List[OcrEvent]) -> str:
    """
    Serializza una lista di OcrEvent in testo SRT (UTF-8).
    Salta gli eventi con testo vuoto. Riassegna gli indici 1-based in ordine.
    """
    blocks: List[str] = []
    idx = 0
    for ev in events:
        text = (ev.text or "").strip()
        if not text:
            continue
        idx += 1
        blocks.append(
            f"{idx}\n"
            f"{ms_to_srt_timestamp(ev.start_ms)} --> {ms_to_srt_timestamp(ev.end_ms)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)
