# -*- coding: utf-8 -*-
"""Eccezioni per file alle opzioni job (nessun Qt, nessuna dipendenza): solo le chiavi ammesse, la pulizia dei valori e l'etichetta breve
mostrata sulla riga della coda. Un valore assente = "usa il predefinito" (config). Le eccezioni NON vengono mai scritte su disco: il
processo figlio le applica come sovrapposizione in memoria (utils/config.py::Config.set_overlay)."""
from typing import Any, Dict, Optional

TARGET_LANGUAGE = 'target_language'
UPLOAD = 'opensubtitles_upload_enabled'
MUX = 'mux_subtitle_into_video'
GENDER = 'gender_correction_enabled'
TRANSLATION = 'translation_model'

# lingue ammesse (stessi codici di gui/job_options_card.py::SUBTITLE_LANGUAGES)
LANGUAGES = ('ita', 'eng', 'fra', 'spa', 'deu', 'por', 'rus', 'jpn', 'zho', 'ara', 'kor', 'nld', 'pol', 'tur')
TRANSLATION_MODELS = ('nllb_finetuned', 'llm')
BOOL_KEYS = (UPLOAD, MUX, GENDER)
ALL_KEYS = (TARGET_LANGUAGE, TRANSLATION, GENDER, MUX, UPLOAD)

_TM_SHORT = {'nllb_finetuned': 'NLLB', 'llm': 'TG'}


def clean_value(key: str, value: Any) -> Optional[Any]:
    """Valore valido per la chiave, oppure None (= non ammesso)."""
    if key == TARGET_LANGUAGE:
        return value if value in LANGUAGES else None
    if key == TRANSLATION:
        return value if value in TRANSLATION_MODELS else None
    if key in BOOL_KEYS:
        return value if isinstance(value, bool) else None
    return None


def clean(overrides: Any) -> Dict[str, Any]:
    """Dizionario ripulito: solo chiavi note con valori validi. Mai eccezioni."""
    out: Dict[str, Any] = {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            cv = clean_value(k, v)
            if cv is not None:
                out[k] = cv
    return out


def label(overrides: Optional[Dict[str, Any]]) -> str:
    """Etichetta breve per la riga: 'ENG · TG · ⚧ · mux · ¬OS'. Vuota se non ci sono eccezioni."""
    o = clean(overrides)
    parts = []
    if TARGET_LANGUAGE in o:
        parts.append(o[TARGET_LANGUAGE].upper())
    if TRANSLATION in o:
        parts.append(_TM_SHORT[o[TRANSLATION]])
    if GENDER in o:
        parts.append('⚧' if o[GENDER] else '¬⚧')
    if MUX in o:
        parts.append('mux' if o[MUX] else '¬mux')
    if UPLOAD in o:
        parts.append('OS' if o[UPLOAD] else '¬OS')
    return ' · '.join(parts)
