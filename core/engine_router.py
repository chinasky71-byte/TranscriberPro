# -*- coding: utf-8 -*-
"""Where the ASR engine is decided — and now there is only one.

ADR-008: Qwen3-ASR is the only engine. It covers Italian and English (the languages
of the reference library), returns word timestamps through its own aligner and needs
no ctranslate2. `plan()` is kept because the pipeline asks the question and logs the
answer, not because there is anything to route.

What changed with the removal:
- `faster-whisper` is gone, so an engine failure is a job failure instead of a
  silent switch to a slower model;
- `canary` is gone: English goes to qwen3 like everything else;
- the `language → engine` table, the fallback and the specialisation rules went
  with them.
"""
from __future__ import annotations

from typing import Optional, Tuple

from utils.config import get_config
from utils.translations import tr

ENGINE = 'qwen3'


class EngineRouter:
    """Single-engine planning, kept for the pipeline's contract."""

    @classmethod
    def plan(cls, language: Optional[str], config=None) -> Tuple[str, str]:
        """Ritorna (engine, motivo). Sempre qwen3: l'engine unico (ADR-008)."""
        return ENGINE, tr('er_only_engine_qwen3')

    @classmethod
    def engine_available(cls, name: str = ENGINE) -> bool:
        """True quando il pacchetto dell'engine è importabile."""
        if name != ENGINE:
            return False
        try:
            import qwen_asr  # noqa: F401
            return True
        except Exception:
            return False

    @classmethod
    def supports_language(cls, language: Optional[str]) -> bool:
        """True quando l'aligner di qwen3 copre la lingua (timestamp per parola)."""
        try:
            from core.engines.qwen3_asr_engine import Qwen3AsrEngine
            return bool(Qwen3AsrEngine.supports_language(language))
        except Exception:
            return False

    @classmethod
    def language_hint(cls) -> str:
        """Lingue coperte, per i messaggi d'errore."""
        try:
            from core.engines.qwen3_asr_engine import Qwen3AsrEngine
            from core.engines.qwen3_asr_engine import ALIGNER_LANGS_639_1
            return ", ".join(sorted(ALIGNER_LANGS_639_1))
        except Exception:
            return ""
