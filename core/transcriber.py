"""
Transcriber - FACADE MULTI-ENGINE (routing automatico per lingua)
File: core/transcriber.py

VERSIONE: v4.0 - SISTEMA MULTI-ENGINE

MODIFICHE v4.0:
✅ La classe Transcriber è ora una FACADE retrocompatibile sul sistema
   multi-engine (core/engine_router.py + core/engines/*):
   - Canary-Qwen-2.5B (NeMo, venv dedicato)  → solo inglese
   - Qwen3-ASR-1.7B + ForcedAligner-0.6B     → 11 lingue allineabili + LID
   - faster-whisper large-v3                 → fallback universale
✅ Firma pubblica INVARIATA: __init__(method, log_callback) e
   transcribe_chunks(audio_chunks, output_path, whisper_language)
   -> (success, detected_language) — il chiamante (pipeline) non cambia
✅ Il costruttore pre-carica SEMPRE faster-whisper (stesso comportamento
   storico: ctranslate2 deve inizializzare il contesto CUDA per primo,
   e il fallback resta caldo). Il routing avviene in transcribe_chunks,
   quando la lingua è nota; cambio engine = unload whisper → load nuovo.
✅ Guardia file-unico: la modalità batched (1 solo chunk = intero film) è
   gestibile SOLO da faster-whisper → routing bypassato in quel caso.
✅ Qualsiasi errore degli engine nuovi degrada su faster-whisper (router):
   la pipeline non fallisce MAI per colpa di un engine nuovo.

MODIFICHE v3.5 (storiche, preservate in FasterWhisperEngine):
✅ Gestione codice lingua 'und' → auto-detect
"""
import re
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple

from utils.logger import setup_logger
from utils.config import get_config

logger = setup_logger()


class Transcriber:
    """
    Facade di trascrizione multi-engine.

    Mantiene il contratto storico della classe (metodi, firma, tupla di
    ritorno) delegando la scelta dell'engine a EngineRouter. faster-whisper
    viene pre-caricato alla costruzione (come in v3.x) e resta il fallback
    universale sempre pronto.
    """

    def __init__(self, method: str = 'faster-whisper', log_callback: Optional[Callable] = None):
        """
        Args:
            method:       Mantenuto per retrocompatibilità (storicamente sempre
                          'faster-whisper'); l'engine effettivo è deciso dal
                          router in base a lingua e config.
            log_callback: Callback opzionale da passare all'init (usato dal
                          pre-load anticipato della pipeline).
        """
        from core.engine_router import EngineRouter

        self.config = get_config()
        self.method = 'faster-whisper'
        self.log_callback: Optional[Callable] = log_callback
        self._last_segments: list = []
        self._cancelled: bool = False

        # Router engine (lifecycle VRAM: un solo engine residente)
        self._router = EngineRouter(log_callback=log_callback)

        # Pre-carica faster-whisper: stesso comportamento del costruttore v3.x.
        # Garantisce l'ordine di init CUDA richiesto da ctranslate2 (PRIMA di
        # Demucs) e tiene il fallback pronto. Se il routing sceglierà un altro
        # engine, whisper verrà scaricato prima del load del nuovo.
        self._whisper_engine = self._router.ensure_loaded('faster-whisper')

        self.device = self._whisper_engine.device

        logger.info(f"Transcriber inizializzato - Device: {self.device}")
        logger.info(f"Profilo: {self.profile_name} | Workers: {self.num_workers} | Beam: {self.beam_size}")

    # ------------------------------------------------------------------
    # Proxy di compatibilità verso l'engine faster-whisper (profili, VAD)
    # ------------------------------------------------------------------
    @property
    def profile(self):
        return self._whisper_engine.profile

    @property
    def profile_name(self) -> str:
        return self._whisper_engine.profile_name

    @property
    def num_workers(self) -> int:
        return self._whisper_engine.num_workers

    @property
    def beam_size(self) -> int:
        return self._whisper_engine.beam_size

    @property
    def vad_available(self) -> bool:
        return self._whisper_engine.vad_available

    @property
    def faster_whisper_model(self):
        return self._whisper_engine.faster_whisper_model

    @property
    def batch_manager(self):
        return self._whisper_engine.batch_manager

    def reload_profile(self):
        """Ricarica parametri profilo dalla config (solo faster-whisper:
        gli altri engine leggono il profilo al load)."""
        self._whisper_engine.reload_profile()

    def set_files_processed(self, count: int):
        """Passa il contatore fatigue al batch_manager (OOM prevention)."""
        self._whisper_engine.set_files_processed(count)

    # ------------------------------------------------------------------
    # Logging / cancellazione
    # ------------------------------------------------------------------
    def set_log_callback(self, callback: Callable):
        """Imposta callback per logging GUI"""
        self.log_callback = callback
        self._router.set_log_callback(callback)

    def log(self, message: str):
        """Log messaggio sia su file che GUI"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def cancel(self):
        """Segnala cancellazione — interrompe il loop di trascrizione tra un
        chunk e l'altro (propagata a tutti gli engine e ai subprocess)."""
        self._cancelled = True
        self._router.cancel()

    # ------------------------------------------------------------------
    # Trascrizione (contratto storico invariato)
    # ------------------------------------------------------------------
    def transcribe_chunks(
        self,
        audio_chunks: List[tuple],
        output_path: str, # Questo è il percorso SRT di output
        whisper_language: str = None # Questo è il codice lingua (es. 'it')
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrive i chunk audio con l'engine selezionato dal router
        (Canary/Qwen3/faster-whisper) e scrive il file SRT.

        Contratto identico a v3.x: (success, detected_language_639_1).
        """
        if not audio_chunks:
            return False, None

        # ── Guardia file-unico (modalità batched: intero film in un chunk) ──
        # Solo faster-whisper (BatchedInferencePipeline + VAD) gestisce input
        # di durata arbitraria; Qwen3 ha limite 1200s e Canary 40s per input.
        if len(audio_chunks) == 1:
            engine = self._router.ensure_loaded('faster-whisper')
            success, detected = engine.transcribe_chunks(
                audio_chunks, output_path, whisper_language)
            self._last_segments = engine.last_segments
            return success, detected

        # ── Routing multi-engine con fallback garantito ──
        success, detected, engine = self._router.transcribe_with_fallback(
            audio_chunks, output_path, whisper_language)
        if engine is not None:
            self._last_segments = engine.last_segments
        return success, detected

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def unload_engines(self):
        """
        Scarica gli engine residenti in VRAM SENZA distruggere la facade.

        Usato dalla pipeline a fine STEP 3 quando l'engine pianificato non è
        faster-whisper: il load di Qwen3/Canary parte così con VRAM massima.
        Whisper resta ricaricabile in-process per il fallback (il pre-load
        allo STEP 2.5 ha già inizializzato ctranslate2 su contesto vergine).
        """
        try:
            self._router.unload_all()
        except Exception as e:
            logger.warning(f"Errore unload engine anticipato: {e}")

    def cleanup(self):
        """Pulizia risorse GPU (tutti gli engine)"""
        try:
            self._router.unload_all()
            logger.info("✅ Transcriber cleanup completato")
        except Exception as e:
            logger.error(f"Errore durante cleanup: {e}")


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


# ============================================================================
# TESTING & DEBUG
# ============================================================================

if __name__ == '__main__':
    """Test facade multi-engine con profili"""

    print("\n" + "="*80)
    print("TEST TRANSCRIBER FACADE MULTI-ENGINE")
    print("="*80 + "\n")

    # Test 1: Inizializzazione con profilo default
    print("Test 1: Inizializzazione...")
    transcriber = Transcriber()
    print(f"✅ Profilo corrente: {transcriber.profile_name}")
    print(f"   - Workers: {transcriber.num_workers}")
    print(f"   - Beam: {transcriber.beam_size}")

    # Test 2: Verifica parametri diversi profili
    print("\nTest 2: Verifica parametri profili...")
    from utils.config import get_config
    config = get_config()

    for profile in ['fast', 'balanced', 'quality', 'maximum', 'batch']:
        config.set_transcription_profile(profile)
        transcriber._whisper_engine._load_profile_params()
        print(f"Profilo '{profile}': workers={transcriber.num_workers}, beam={transcriber.beam_size}")

    # Test 3: Routing engine per lingua
    print("\nTest 3: Routing engine...")
    from core.engine_router import EngineRouter
    for lang in ['en', 'it', 'fr', 'fi', 'he', None]:
        name, reason = EngineRouter.plan(lang)
        print(f"   {str(lang):5s} → {name} ({reason})")

    transcriber.cleanup()
    print("\n" + "="*80)
    print("✅ Test completato")
    print("="*80)
