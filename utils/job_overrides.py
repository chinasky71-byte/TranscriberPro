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
FORCE_AUDIO = 'force_audio_transcription'      # ignora i sottotitoli gia' presenti nel video e trascrive l'audio
ALLOW_CPU = 'allow_cpu'                        # accetta di elaborare senza GPU (molto piu' lento): salta il preflight

# Lingua di destinazione: una sola (ADR-009). Il motore traduce verso l'italiano
# e rifiuta tutto il resto, quindi offrire un elenco sarebbe una promessa falsa.
LANGUAGES = ('ita',)
# Un solo motore (ADR-009). Il valore e' quello canonico di `Config`.
TRANSLATION_MODELS = ('translategemma-12b-gguf',)
BOOL_KEYS = (UPLOAD, MUX, GENDER, FORCE_AUDIO, ALLOW_CPU)
ALL_KEYS = (TARGET_LANGUAGE, TRANSLATION, FORCE_AUDIO, GENDER, MUX, UPLOAD, ALLOW_CPU)

_TM_SHORT = {'translategemma-12b-gguf': 'TG'}


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
    if FORCE_AUDIO in o:
        parts.append('audio' if o[FORCE_AUDIO] else '¬audio')
    if GENDER in o:
        parts.append('⚧' if o[GENDER] else '¬⚧')
    if MUX in o:
        parts.append('mux' if o[MUX] else '¬mux')
    if UPLOAD in o:
        parts.append('OS' if o[UPLOAD] else '¬OS')
    return ' · '.join(parts)
