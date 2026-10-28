"""
Base Engine - Interfaccia comune degli engine di trascrizione
File: core/engines/base_engine.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Classe astratta TranscriptionEngine: contratto unico per tutti gli engine
   (faster-whisper, Qwen3-ASR, Canary-Qwen)
✅ Capability detection via is_available() (try-import, mai eccezioni)
✅ Contratto transcribe_chunks identico alla facade storica:
   (audio_chunks, output_path, language) -> (success, detected_language_639_1)
✅ Eccezione LanguageNotAlignable per il re-routing del router quando
   l'auto-detect Qwen3 rileva una lingua fuori dal set del ForcedAligner
"""
from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Tuple

from utils.logger import setup_logger
from utils.translations import tr

logger = setup_logger()


class LanguageNotAlignable(Exception):
    """Sollevata da un engine quando la lingua rilevata in auto-detect non è
    supportata dal suo sistema di timestamp (es. ForcedAligner Qwen3).

    Con ADR-008 non c'è più un motore su cui ri-trascrivere: l'eccezione risale
    e il job fallisce con un messaggio — (attributo detected_language_639_1).
    """

    def __init__(self, detected_language_639_1: Optional[str], message: str = ""):
        self.detected_language_639_1 = detected_language_639_1
        super().__init__(
            message or tr('be_language_cannot_be_aligned_by').format(detected_language_639_1=detected_language_639_1)
        )


class TranscriptionEngine(ABC):
    """
    Interfaccia comune per gli engine di trascrizione.

    Ciclo di vita: load() → transcribe_chunks() [1..N volte] → unload().
    Regola VRAM: UN SOLO engine residente per volta — il lifecycle è
    orchestrato da core/engine_router.py, gli engine non si scaricano a vicenda.
    """

    #: Nome breve dell'engine (usato nei log e nel routing)
    name: str = "base"

    def __init__(self, log_callback: Optional[Callable] = None):
        self.log_callback: Optional[Callable] = log_callback
        self._cancelled: bool = False
        self._last_segments: list = []   # esposto per diarization/alignment in pipeline

    # ------------------------------------------------------------------
    # Capability detection
    # ------------------------------------------------------------------
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True se le dipendenze dell'engine sono presenti sul sistema.
        NON deve mai sollevare eccezioni: assenza = False."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def supports_language(cls, lang_639_1: Optional[str]) -> bool:
        """True se l'engine supporta la lingua ISO 639-1 indicata
        (None = auto-detect: True solo se l'engine sa auto-rilevare)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @abstractmethod
    def load(self):
        """Carica il modello in VRAM/RAM. Può sollevare eccezioni: il router
        le intercetta e attiva il fallback."""
        raise NotImplementedError

    @abstractmethod
    def unload(self):
        """Scarica completamente il modello (del + empty_cache + synchronize).
        NON deve mai sollevare eccezioni."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Trascrizione
    # ------------------------------------------------------------------
    @abstractmethod
    def transcribe_chunks(
        self,
        audio_chunks: List[tuple],
        output_path: str,
        language: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrive i chunk audio e scrive il file SRT.

        Args:
            audio_chunks: lista di tuple (chunk_path, start_time, end_time).
                          Con un solo elemento il terzo campo è la durata totale
                          (convenzione storica della pipeline in modalità batched).
            output_path:  percorso del file SRT di output.
            language:     codice ISO 639-1 (es. 'it') oppure None per auto-detect.

        Returns:
            (success, detected_language_639_1)
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Utilità comuni
    # ------------------------------------------------------------------
    def cancel(self):
        """Segnala cancellazione — interrompe il loop tra un chunk e l'altro."""
        self._cancelled = True

    def set_log_callback(self, callback: Callable):
        """Imposta callback per logging GUI"""
        self.log_callback = callback

    def log(self, message: str):
        """Log messaggio sia su file che GUI"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    @property
    def last_segments(self) -> list:
        """Ultimi segmenti trascritti (per diarization/forced alignment)."""
        return self._last_segments
