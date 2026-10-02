"""
Engine Router - Selezione engine di trascrizione e lifecycle VRAM
File: core/engine_router.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Routing automatico per lingua (ISO 639-1, già convertito dal chiamante):
   1. 'en' + Canary disponibile e abilitato               → canary
   2. lingua ∈ (ASR Qwen3 ∩ ForcedAligner) + abilitato    → qwen3
   3. 'und'/None/invalida                                 → qwen3 auto-detect
      (LID superiore a Whisper); se rileva lingua fuori dal set aligner →
      ri-trascrizione con faster-whisper, UNA volta, con log esplicito
   4. tutto il resto                                      → faster-whisper
   0. lingua in whisper_model_by_language (fr, de)        → faster-whisper col
      modello specializzato (v1.26.0, prima di tutte le altre regole)
✅ transcription_engine_mode: 'auto' | 'canary' | 'qwen3' | 'faster-whisper'
   (forzatura esplicita; se l'engine forzato non è disponibile → fallback)
✅ QUALSIASI eccezione in load/trascrizione di Canary/Qwen3 → fallback
   automatico su faster-whisper con log del motivo. La pipeline non deve
   MAI fallire per colpa di un engine nuovo.
✅ Lifecycle VRAM: UN SOLO engine residente per volta — unload dell'engine
   corrente prima di caricarne un altro, con log dei tempi e della VRAM.
"""
import time
from typing import Callable, List, Optional, Tuple

import torch

from core.engines.base_engine import TranscriptionEngine, LanguageNotAlignable
from utils.logger import setup_logger
from utils.config import get_config

logger = setup_logger()

# Codici lingua invalidi/indefiniti (stessa lista storica del transcriber)
INVALID_LANGUAGE_CODES = ['und', 'unknown', 'undefined', 'n/a', 'none', '']

# Mappa difensiva 639-2 → 639-1 (il chiamante passa già 639-1, ma il router
# accetta anche 3 lettere per robustezza — es. chiamate dirette nei test)
LANG_MAP_3_TO_2 = {
    'ita': 'it', 'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
    'deu': 'de', 'ger': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
    'kor': 'ko', 'chi': 'zh', 'zho': 'zh', 'ara': 'ar', 'hin': 'hi',
    'pol': 'pl', 'tur': 'tr', 'nld': 'nl', 'dut': 'nl', 'swe': 'sv',
    'dan': 'da', 'fin': 'fi', 'ces': 'cs', 'cze': 'cs', 'hun': 'hu',
    'ron': 'ro', 'rum': 'ro', 'ell': 'el', 'gre': 'el', 'vie': 'vi',
    'tha': 'th', 'ind': 'id', 'msa': 'ms', 'may': 'ms', 'fas': 'fa',
    'per': 'fa', 'mkd': 'mk', 'mac': 'mk', 'fil': 'fil', 'tgl': 'fil',
}


def normalize_language(language: Optional[str]) -> Optional[str]:
    """Normalizza un codice lingua a ISO 639-1 minuscolo; None se indefinito."""
    if language is None:
        return None
    lang = language.lower().strip()
    if lang in INVALID_LANGUAGE_CODES:
        return None
    if len(lang) == 3:
        lang = LANG_MAP_3_TO_2.get(lang, lang)
    return lang


class EngineRouter:
    """
    Router degli engine di trascrizione: selezione per lingua, fallback
    automatico su faster-whisper e gestione del lifecycle VRAM.
    """

    def __init__(self, log_callback: Optional[Callable] = None):
        self.config = get_config()
        self.log_callback = log_callback
        self._engines: dict = {}          # nome → istanza (cache)
        self._current: Optional[TranscriptionEngine] = None
        self._cancelled = False

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def log(self, message: str):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def set_log_callback(self, callback: Callable):
        self.log_callback = callback
        for eng in self._engines.values():
            eng.set_log_callback(callback)

    # ------------------------------------------------------------------
    # Disponibilità engine (capability detection, mai eccezioni)
    # ------------------------------------------------------------------
    @staticmethod
    def _engine_class(name: str):
        if name == 'canary':
            from core.engines.canary_engine import CanaryEngine
            return CanaryEngine
        if name == 'qwen3':
            from core.engines.qwen3_asr_engine import Qwen3AsrEngine
            return Qwen3AsrEngine
        from core.engines.faster_whisper_engine import FasterWhisperEngine
        return FasterWhisperEngine

    @classmethod
    def engine_available(cls, name: str) -> bool:
        try:
            return cls._engine_class(name).is_available()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Selezione (statica: nessun caricamento — usata anche dalla pipeline
    # per pianificare il chunking PRIMA di Demucs)
    # ------------------------------------------------------------------
    @classmethod
    def plan(cls, language: Optional[str], config=None) -> Tuple[str, str]:
        """
        Decide l'engine per la lingua data SENZA caricare nulla.

        Returns:
            (nome_engine, motivo) — nome ∈ {'canary', 'qwen3', 'faster-whisper'}
        """
        config = config or get_config()
        lang = normalize_language(language)

        mode = config.get('transcription_engine_mode', 'auto')
        if mode not in ('auto', 'canary', 'qwen3', 'faster-whisper'):
            mode = 'auto'

        # ── Forzatura esplicita ──
        if mode != 'auto':
            if mode == 'faster-whisper':
                return 'faster-whisper', "engine forzato da impostazioni"
            if cls.engine_available(mode) and cls._engine_class(mode).supports_language(lang):
                return mode, "engine forzato da impostazioni"
            return 'faster-whisper', (
                f"engine forzato '{mode}' non disponibile o lingua "
                f"'{lang}' non supportata → faster-whisper")

        # ── Routing automatico ──
        # Lingue con un Whisper specializzato (whisper_model_by_language):
        # faster-whisper con quel modello, prima di Canary/Qwen3.
        from core.engines.faster_whisper_engine import FasterWhisperEngine
        spec = FasterWhisperEngine.language_model_spec(config, lang)
        if spec:
            return 'faster-whisper', f"lingua '{lang}' → Whisper specializzato {spec}"

        canary_ok = bool(config.get('canary_enabled', True)) and cls.engine_available('canary')
        qwen3_ok = bool(config.get('qwen3_enabled', True)) and cls.engine_available('qwen3')

        if lang == 'en' and canary_ok:
            return 'canary', "inglese → Canary-Qwen-2.5B (WER migliore)"

        if lang is not None and qwen3_ok and cls._engine_class('qwen3').supports_language(lang):
            return 'qwen3', f"lingua '{lang}' ∈ ASR∩Aligner Qwen3"

        if lang is None and qwen3_ok:
            return 'qwen3', "lingua indefinita → auto-detect Qwen3 (LID superiore)"

        if lang == 'en' and qwen3_ok:
            # Canary assente: l'inglese ricade su Qwen3 (qualità comunque ottima)
            return 'qwen3', "inglese, Canary non disponibile → Qwen3"

        return 'faster-whisper', (
            f"lingua '{lang}' fuori dalle coperture degli engine nuovi"
            if lang is not None else "engine nuovi non disponibili → faster-whisper")

    # ------------------------------------------------------------------
    # Lifecycle VRAM
    # ------------------------------------------------------------------
    def get_engine(self, name: str, log_callback: Optional[Callable] = None) -> TranscriptionEngine:
        """Restituisce (creandola se serve) l'istanza dell'engine richiesto."""
        if name not in self._engines:
            cls = self._engine_class(name)
            self._engines[name] = cls(log_callback=log_callback or self.log_callback)
        return self._engines[name]

    def ensure_loaded(self, name: str) -> TranscriptionEngine:
        """
        Garantisce che SOLO l'engine richiesto sia residente in VRAM:
        scarica l'engine corrente se diverso, poi carica quello nuovo.
        """
        engine = self.get_engine(name)

        if self._current is not None and self._current is not engine:
            self._unload_engine(self._current)
            self._current = None

        t0 = time.time()
        free0 = self._free_vram_gb()
        engine.load()
        free1 = self._free_vram_gb()
        if free0 or free1:
            self.log(f"  📊 VRAM dopo load '{name}': {free1:.1f} GB liberi "
                     f"(load in {time.time() - t0:.1f}s)")
        self._current = engine
        return engine

    def _unload_engine(self, engine: TranscriptionEngine):
        t0 = time.time()
        free0 = self._free_vram_gb()
        self.log(f"  🔄 Unload engine '{engine.name}' (cambio engine)...")
        engine.unload()
        free1 = self._free_vram_gb()
        self.log(f"  ✅ Engine '{engine.name}' scaricato in {time.time() - t0:.1f}s"
                 + (f" │ VRAM: {free0:.1f} → {free1:.1f} GB liberi" if free0 or free1 else ""))

    def unload_all(self):
        """Scarica tutti gli engine istanziati (chiamato dai cleanup pipeline)."""
        for eng in self._engines.values():
            try:
                eng.unload()
            except Exception as e:
                logger.warning(f"Errore unload engine '{eng.name}': {e}")
        self._current = None

    @staticmethod
    def _free_vram_gb() -> float:
        try:
            if torch.cuda.is_available():
                free_b, _ = torch.cuda.mem_get_info()
                return free_b / 1024**3
        except Exception:
            pass
        return 0.0

    # ------------------------------------------------------------------
    # Cancellazione
    # ------------------------------------------------------------------
    def cancel(self):
        self._cancelled = True
        for eng in self._engines.values():
            try:
                eng.cancel()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Trascrizione con fallback garantito
    # ------------------------------------------------------------------
    def transcribe_with_fallback(
        self,
        audio_chunks: List[tuple],
        output_path: str,
        language: Optional[str],
    ) -> Tuple[bool, Optional[str], Optional[TranscriptionEngine]]:
        """
        Trascrive con l'engine pianificato; su QUALSIASI errore degli engine
        nuovi degrada automaticamente su faster-whisper.

        Returns:
            (success, detected_language_639_1, engine_usato)
        """
        lang = normalize_language(language)
        planned, reason = self.plan(lang, self.config)
        self.log(f"  🧭 Engine selezionato: {planned} ({reason})")

        attempts: List[Tuple[str, Optional[str]]] = [(planned, lang)]
        if planned != 'faster-whisper':
            attempts.append(('faster-whisper', lang))

        last_error: Optional[str] = None
        # Ciclo a indice (NON for-in): il handler LanguageNotAlignable deve
        # poter aggiornare la lingua dei tentativi successivi in corsa — un
        # rebinding della lista dentro un for-in non avrebbe effetto
        # sull'iteratore già creato.
        attempt_idx = 0
        while attempt_idx < len(attempts):
            engine_name, attempt_lang = attempts[attempt_idx]
            attempt_idx += 1
            if self._cancelled:
                return False, None, None
            try:
                engine = self.ensure_loaded(engine_name)
                if engine_name != 'faster-whisper':
                    # Whisper la emette da solo (con il modello realmente caricato)
                    try:
                        from utils.engine_labels import model_display
                        self.log(f"🧩 Modello trascrizione: {model_display(engine_name, self.config)}")
                    except Exception:
                        pass
                success, detected = engine.transcribe_chunks(
                    audio_chunks, output_path, attempt_lang)
                if success:
                    return True, detected, engine
                # Nessuna eccezione ma esito negativo (es. zero segmenti):
                # su engine nuovi tentiamo comunque il fallback
                last_error = f"engine '{engine_name}' ha restituito esito negativo"
                if engine_name == 'faster-whisper':
                    return False, detected, engine
                self.log(f"  ⚠️ {last_error} → fallback su faster-whisper")

            except LanguageNotAlignable as e:
                # Auto-detect Qwen3 su lingua fuori dal set aligner:
                # ri-trascrizione con faster-whisper passando la lingua rilevata
                detected = e.detected_language_639_1
                last_error = str(e)
                self.log(f"  ⚠️ {e} → ri-trascrizione con faster-whisper"
                         + (f" (lingua: {detected})" if detected else " (auto-detect)"))
                # Aggiorna IN PLACE la lingua del tentativo faster-whisper già
                # in coda (il while a indice rilegge la lista aggiornata)
                attempts[:] = [(n, detected if n == 'faster-whisper' else l)
                               for n, l in attempts]

            except Exception as e:
                last_error = str(e)
                logger.error(f"❌ Engine '{engine_name}' fallito: {e}", exc_info=True)
                if engine_name == 'faster-whisper':
                    # Anche il fallback è fallito: la pipeline gestirà l'errore
                    self.log(f"  ❌ Errore trascrizione (faster-whisper): {e}")
                    return False, None, None
                self.log(f"  ⚠️ Engine '{engine_name}' fallito: {e}")
                self.log("  🛟 Fallback automatico su faster-whisper...")

        self.log(f"  ❌ Trascrizione fallita: {last_error}")
        return False, None, None
