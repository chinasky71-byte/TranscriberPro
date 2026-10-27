# -*- coding: utf-8 -*-
"""Etichette brevi dei motori di trascrizione e dei loro modelli, per la GUI.

Usato da core/pipeline.py (riga di log "Modello trascrizione: ...", letta dalla
finestra principale) e da gui/main_window.py (valore a riposo della tessera
"Modello" e testo del pulsante motore).
"""
from typing import Optional

ENGINE_MODE_LABELS = {
    'auto': 'Auto',
    'canary': 'Canary-Qwen',
    'qwen3': 'Qwen3-ASR',
    'faster-whisper': 'Faster-Whisper',
}


def short_model_name(spec: Optional[str]) -> str:
    """Nome breve da un id/percorso modello.

    'bofenghuang/whisper-large-v3-french/ctranslate2' -> 'large-v3-french'
    'TiMoMuc/whisper-large-v3-german-ct2'             -> 'large-v3-german'
    '<cartella locale>/whisper-large-v3-es-hitz-ct2'   -> 'large-v3-es-hitz'
    'Qwen/Qwen3-ASR-1.7B'                              -> 'Qwen3-ASR-1.7B'
    """
    if not spec:
        return ''
    parts = [p for p in str(spec).replace(chr(92), '/').split('/') if p]
    while parts and parts[-1].lower() == 'ctranslate2':
        parts.pop()
    name = parts[-1] if parts else str(spec)
    if name.lower().startswith('whisper-'):
        name = name[len('whisper-'):]
    if name.lower().endswith('-ct2'):
        name = name[:-len('-ct2')]
    return name


def whisper_label(spec: Optional[str]) -> str:
    """'Whisper <nome breve>' da una specifica modello Whisper."""
    name = short_model_name(spec) or 'large-v3'
    if name.startswith('large-v3-'):
        name = name[len('large-'):]     # 'Whisper v3-french' entra nella tessera senza troncarsi
    return 'Whisper ' + name


def model_display(engine: str, config, lang: Optional[str] = None) -> str:
    """Modello usato dall'engine: con ADR-008 c'e' solo Qwen3-ASR."""
    return short_model_name(config.get('qwen3_asr_model_id', 'Qwen/Qwen3-ASR-1.7B')) or 'Qwen3-ASR'


def idle_model_label(config) -> str:
    """Valore della tessera "Modello" quando non si sta elaborando."""
    return model_display('qwen3', config)
