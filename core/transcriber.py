# -*- coding: utf-8 -*-
"""Subtitles from audio: one engine, Qwen3-ASR (ADR-008).

The facade keeps the public contract the pipeline has always used —
`Transcriber(log_callback=...)` and `transcribe_chunks(chunks, output, language)`
returning `(success, detected_language)` — but behind it there is a single engine.
Whisper, Canary, the router and the fallback are gone: a failure is a failure, not
a silent switch to a slower model.

Qwen3-ASR covers Italian and English (the languages of the reference library),
provides word timestamps through its own aligner and needs no ctranslate2. For a
language outside its aligner the engine raises `LanguageNotAlignable`, which now
stops the job with a clear message instead of falling back.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from utils.config import get_config
from utils.logger import setup_logger

logger = setup_logger()


class Transcriber:
    """Qwen3-ASR behind the historical facade."""

    def __init__(self, method: Optional[str] = None, log_callback: Optional[Callable] = None,
                 language_hint: Optional[str] = None):
        """Nothing is loaded here: the model loads on first use (no preload).

        `method` and `language_hint` are accepted for API compatibility; the
        engine is always qwen3.
        """
        self.config = get_config()
        self.log_callback: Optional[Callable] = log_callback
        self.language_hint = language_hint
        self.device = "cuda"
        self._last_segments: list = []
        self._cancelled: bool = False
        self._engine = None

    # ------------------------------------------------------------------
    # Logging / cancellazione
    # ------------------------------------------------------------------
    def set_log_callback(self, callback: Callable) -> None:
        """Imposta callback per logging (GUI/WebUI)."""
        self.log_callback = callback
        if self._engine is not None:
            self._engine.set_log_callback(callback)

    def log(self, message: str) -> None:
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def cancel(self) -> None:
        """Interrompe la trascrizione tra un chunk e l'altro."""
        self._cancelled = True
        if self._engine is not None:
            try:
                self._engine.cancel()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Trascrizione
    # ------------------------------------------------------------------
    @property
    def last_segments(self) -> list:
        return self._last_segments

    def _ensure_engine(self):
        if self._engine is None:
            from core.engines.qwen3_asr_engine import Qwen3AsrEngine
            self._engine = Qwen3AsrEngine(log_callback=self.log_callback)
            self.device = getattr(self._engine, 'device', 'cuda')
            if self.language_hint:
                try:
                    self._engine.language_hint = self.language_hint
                except Exception:
                    pass
        return self._engine

    def transcribe_chunks(self, audio_chunks: List[tuple], output_path: str,
                          whisper_language: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Trascrive i chunk e scrive l'SRT. Ritorna (success, lingua 639-1).

        Nessun fallback: se l'engine non riesce, l'eccezione arriva alla pipeline
        che fa fallire il job con il motivo.
        """
        if not audio_chunks:
            return False, None
        engine = self._ensure_engine()
        success, detected = engine.transcribe_chunks(audio_chunks, output_path, whisper_language)
        self._last_segments = list(getattr(engine, 'last_segments', []) or [])
        return success, detected

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def unload_engines(self) -> None:
        """Scarica il modello dalla VRAM senza distruggere la facade."""
        if self._engine is not None:
            try:
                self._engine.unload()
            except Exception as exc:
                logger.warning(f"Errore unload engine: {exc}")

    def cleanup(self) -> None:
        """Rilascia le risorse GPU."""
        try:
            if self._engine is not None:
                self._engine.cleanup()
            logger.info("✅ Transcriber cleanup completato")
        except Exception as exc:
            logger.error(f"Errore durante cleanup: {exc}")
        finally:
            self._engine = None


# ============================================================================
# UTILITY FUNCTIONS (INVARIATE)
# ============================================================================

def clean_html_tags(text: str) -> str:
    """Rimuove tag HTML dal testo"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def format_timestamp(seconds: float) -> str:
    """Formatta timestamp in formato SRT (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: List[Dict]) -> str:
    """Converte segmenti in formato SRT.

    Se i segmenti hanno il campo 'speaker', aggiunge un trattino (-)
    solo al primo segmento di ogni nuovo parlante (stile sottotitoli
    dialogo italiano). Nessun ID numerico esposto.
    """
    srt_content = []
    prev_speaker = None
    idx = 0

    for segment in segments:
        text = clean_html_tags(segment['text'])

        if not text:
            continue

        idx += 1
        speaker = segment.get('speaker')
        if speaker and speaker != prev_speaker:
            text = f"- {text}"
        prev_speaker = speaker

        srt_content.append(str(idx))
        start_ts = format_timestamp(segment['start'])
        end_ts = format_timestamp(segment['end'])
        srt_content.append(f"{start_ts} --> {end_ts}")
        srt_content.append(text)
        srt_content.append("")

    return "\n".join(srt_content)


def save_srt_file(segments: List[Dict], output_path: Path) -> bool:
    """Salva segmenti in file SRT"""
    try:
        srt_content = segments_to_srt(segments)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)

        logger.info(f"✅ File SRT salvato: {output_path}")
        return True

    except Exception as e:
        logger.error(f"❌ Errore salvataggio SRT: {e}")
        return False
