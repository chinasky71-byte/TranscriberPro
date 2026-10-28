# -*- coding: utf-8 -*-
"""Impostazioni OCR dei sottotitoli bitmap (PGS -> SRT), senza Qt.

Trasposizione fedele di gui/ocr_settings_widget.py: lettura normalizzata dei valori dal config e scrittura di ciascuna chiave.
Chiavi e valori vengono dal contratto core/pgs_types.py. Il widget resta la vista."""
from dataclasses import dataclass

from core.pgs_types import (
    CFG_CONF_THRESHOLD, CFG_LANGUAGE, CFG_OCR_WORKERS, CFG_STRATEGY, CFG_TESSERACT_PATH, CFG_WRITEBACK,
    DEFAULT_CONF_THRESHOLD, DEFAULT_LANGUAGE, DEFAULT_OCR_WORKERS, DEFAULT_STRATEGY, DEFAULT_WRITEBACK,
    STRATEGY_AUTO, STRATEGY_REVIEW,
)

MAX_WORKERS = 32


def _int_in(value, default: int, low: int, high: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass(frozen=True)
class OcrValues:
    strategy: str
    language: str
    conf_threshold: int
    workers: int
    writeback: str
    tesseract_path: str


class OcrSettingsService:
    def __init__(self, config):
        self._config = config

    def load(self, writeback_choices=None) -> OcrValues:
        """Valori correnti, normalizzati. `writeback_choices` (le voci della tendina) fa ripiegare su DEFAULT_WRITEBACK un
        valore sconosciuto; senza, il valore salvato passa com'e'."""
        c = self._config
        strategy = c.get(CFG_STRATEGY, DEFAULT_STRATEGY)
        strategy = STRATEGY_AUTO if strategy == STRATEGY_AUTO else STRATEGY_REVIEW
        writeback = c.get(CFG_WRITEBACK, DEFAULT_WRITEBACK)
        if writeback_choices is not None and writeback not in writeback_choices:
            writeback = DEFAULT_WRITEBACK
        return OcrValues(
            strategy=strategy,
            language=c.get(CFG_LANGUAGE, DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE,
            conf_threshold=_int_in(c.get(CFG_CONF_THRESHOLD, DEFAULT_CONF_THRESHOLD), DEFAULT_CONF_THRESHOLD, 0, 100),
            workers=_int_in(c.get(CFG_OCR_WORKERS, DEFAULT_OCR_WORKERS), DEFAULT_OCR_WORKERS, 0, MAX_WORKERS),
            writeback=writeback,
            tesseract_path=c.get(CFG_TESSERACT_PATH, '') or '',
        )

    def set_strategy(self, review: bool) -> str:
        strategy = STRATEGY_REVIEW if review else STRATEGY_AUTO
        self._config.set(CFG_STRATEGY, strategy)
        return strategy

    def set_language(self, text: str) -> str:
        language = text.strip() or DEFAULT_LANGUAGE
        self._config.set(CFG_LANGUAGE, language)
        return language

    def set_conf_threshold(self, value: int) -> None:
        self._config.set(CFG_CONF_THRESHOLD, int(value))

    def set_workers(self, value: int) -> None:
        self._config.set(CFG_OCR_WORKERS, int(value))

    def set_writeback(self, value) -> str:
        writeback = value or DEFAULT_WRITEBACK
        self._config.set(CFG_WRITEBACK, writeback)
        return writeback

    def set_tesseract_path(self, text: str) -> str:
        path = text.strip()
        self._config.set(CFG_TESSERACT_PATH, path)
        return path
