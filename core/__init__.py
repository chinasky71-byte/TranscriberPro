"""
Core Package Initialization
File: core/__init__.py

VERSIONE: v4.0 - Multi-Model Translation Support

Esporta tutti i componenti core per elaborazione video:
- Pipeline completa
- Trascrizione (Faster-Whisper)
- Traduzione (NLLB + Aya-23-8B)
- Estrazione sottotitoli
- Pulizia sottotitoli
- Processamento audio
- Selezione traccia audio
"""

# Pipeline principale
from .pipeline import ProcessingPipeline

# Trascrizione
from .transcriber import Transcriber

# Traduzione - Multi-Model Architecture (NLLB + Aya + Claude)
from .translator import (
    BaseTranslator,
    NLLBTranslator,
    AyaTranslator,
    ClaudeTranslator,     # ← NUOVO
    get_translator,       # Factory principale (sceglie NLLB / Aya / Claude)
    get_nllb_translator   # Legacy compatibility
)

# Sottotitoli
from .subtitle_extractor import SubtitleExtractor
from .subtitle_cleaner import SubtitleCleaner

# Audio
from .audio_processor import AudioProcessor
from .audio_track_selector import AudioTrackSelector

# Export list
__all__ = [
    # Pipeline
    'ProcessingPipeline',
    
    # Trascrizione
    'Transcriber',
    
    # Traduzione
    'BaseTranslator',
    'NLLBTranslator',
    'AyaTranslator',
    'ClaudeTranslator',
    'get_translator',
    'get_nllb_translator',
    
    # Sottotitoli
    'SubtitleExtractor',
    'SubtitleCleaner',
    
    # Audio
    'AudioProcessor',
    'AudioTrackSelector',
]
