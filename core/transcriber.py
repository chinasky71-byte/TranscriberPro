"""
Transcriber - WITH DYNAMIC PROFILES INTEGRATION
File: core/transcriber.py

VERSIONE: v3.5 - FIX LINGUA INDEFINITA

MODIFICHE v3.5:
✅ FIX CRITICO: Gestione codice lingua 'und' (undefined)
   Quando la traccia audio ha lingua indefinita ('und'), faster-whisper
   rileva automaticamente la lingua impostando language=None
✅ Aggiunta lista codici lingua invalidi per rilevamento robusto
"""
import re
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple
import torch

from utils.logger import setup_logger
from utils.config import get_config
from utils.transcription_profiles import ProfileConfig, TranscriptionProfile

logger = setup_logger()


class Transcriber:
    """
    Gestisce trascrizione audio con Faster-Whisper
    Con supporto profili dinamici per ottimizzazione parametri
    """
    
    def __init__(self, method: str = 'faster-whisper'):
        """
        Args:
            method: Sempre 'faster-whisper' (unico metodo supportato)
        """
        self.config = get_config()
        self.method = 'faster-whisper'
        
        device_config = self.config.get('whisper_device', 'auto')
        
        if device_config == 'auto':
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device_config
        
        self.log_callback: Optional[Callable] = None
        self.faster_whisper_model = None
        self.vad_available = False
        
        # ========================================
        # ✅ NUOVO v3.2: Carica parametri profilo
        # ========================================
        self._load_profile_params()

        # Adaptive batch manager (future-ready per BatchedInferencePipeline)
        from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        profile_config = ProfileConfig.get_profile_config(self.profile)
        batch_hint = profile_config.get('batch_size_hint', None)
        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=(self.device == 'cuda'),
            initial_size=batch_hint,
            log_callback=self.log_callback,
        )
        self.batch_size_for_transcription = None  # None finché BatchedInferencePipeline non disponibile

        # Inizializza modello con parametri profilo
        self._init_faster_whisper()
        
        logger.info(f"Transcriber inizializzato - Device: {self.device}")
        logger.info(f"Profilo: {self.profile_name} | Workers: {self.num_workers} | Beam: {self.beam_size}")
    
    def _load_profile_params(self):
        """
        Carica parametri dal profilo corrente
        """
        profile_str = self.config.get_transcription_profile()
        
        try:
            self.profile = ProfileConfig.from_string(profile_str) 
        except ValueError:
            logger.warning(f"Profilo '{profile_str}' non valido, uso 'balanced'")
            self.profile = TranscriptionProfile.BALANCED
        
        params = ProfileConfig.get_transcription_params(self.profile)
        profile_config = ProfileConfig.get_profile_config(self.profile)
        
        self.num_workers = params['num_workers']
        self.beam_size = params['beam_size']
        self.profile_name = profile_config['name']
        
        logger.info(f"✅ Parametri profilo caricati: {self.profile_name}")
        logger.info(f"   - num_workers: {self.num_workers}")
        logger.info(f"   - beam_size: {self.beam_size}")
    
    def reload_profile(self):
        """
        Ricarica parametri profilo dalla config
        """
        old_workers = self.num_workers
        old_beam = self.beam_size
        
        self._load_profile_params()
        
        if old_workers != self.num_workers:
            logger.info(f"⚠️ num_workers cambiato ({old_workers}→{self.num_workers}), reinizializzo modello...")
            self.cleanup()
            self._init_faster_whisper()
        
        if old_beam != self.beam_size:
            logger.info(f"✅ beam_size aggiornato ({old_beam}→{self.beam_size})")
    
    def set_log_callback(self, callback: Callable):
        """Imposta callback per logging GUI"""
        self.log_callback = callback
    
    def log(self, message: str):
        """Log messaggio sia su file che GUI"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def _init_faster_whisper(self):
        """
        Inizializza modello faster-whisper
        """
        try:
            from faster_whisper import WhisperModel
            try:
                from faster_whisper import BatchedInferencePipeline
                _batched_available = True
            except ImportError:
                _batched_available = False
            
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                logger.info("🧹 Cache CUDA svuotata prima del caricamento modello")
            
            model_size = self.config.get('whisper_model', 'large-v3')
            
            self.log(f"  📦 Caricamento modello {model_size}...")
            self.log(f"  ⚙️ Profilo: {self.profile_name}")
            self.log(f"  👷 Workers: {self.num_workers} | 🎯 Beam: {self.beam_size}")
            
            if self.device == "cuda":
                compute_type = "float16"
                device_index = 0
                
                self.faster_whisper_model = WhisperModel(
                    model_size,
                    device="cuda",
                    device_index=device_index,
                    compute_type=compute_type,
                    num_workers=self.num_workers,  
                    cpu_threads=self.num_workers   
                )
                
                self.log(f"  ✅ Modello {model_size} caricato su CUDA con {self.num_workers} workers")
            else:
                self.faster_whisper_model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    num_workers=self.num_workers,
                    cpu_threads=self.num_workers
                )
                
                self.log(f"  ✅ Modello {model_size} caricato su CPU con {self.num_workers} workers")

            # Future-ready: attiva BatchedInferencePipeline se disponibile
            if _batched_available:
                self.faster_whisper_model = BatchedInferencePipeline(self.faster_whisper_model)
                self.batch_size_for_transcription = self.batch_manager.current_batch_size
                self.log(f"  BatchedInferencePipeline attivo (batch_size={self.batch_size_for_transcription})")
            else:
                self.batch_size_for_transcription = None
                self.log("  BatchedInferencePipeline non disponibile — elaborazione sequenziale")

            self._check_vad_availability()
            
        except Exception as e:
            error_msg = f"❌ Errore caricamento modello Faster-Whisper: {e}"
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            raise
    
    def _check_vad_availability(self):
        """Verifica se il VAD è disponibile/funzionante"""
        try:
            import numpy as np
            dummy_audio = np.zeros(16000, dtype=np.float32)
            
            segments, info = self.faster_whisper_model.transcribe(
                dummy_audio,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            _ = list(segments)
            self.vad_available = True
            self.log("  ✅ VAD (Voice Activity Detection) disponibile")
            logger.info("VAD test successful - enabled")
            
        except Exception as e:
            self.vad_available = False
            self.log("  ⚠️ VAD non disponibile, uso modalità standard")
            logger.warning(f"VAD not available: {e}")
    
    
    def transcribe_chunks(
        self, 
        audio_chunks: List[tuple], 
        output_path: str, # Questo è il percorso SRT di output
        whisper_language: str = None # Questo è il codice lingua (es. 'it')
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrizione usando Faster-Whisper di chunk multipli
        """
        total_chunks = len(audio_chunks)
        
        # Lista di codici lingua invalidi o indefiniti
        invalid_language_codes = ['und', 'unknown', 'undefined', 'n/a', 'none', '']
        
        # Gestione lingua indefinita: faster-whisper rileverà automaticamente
        auto_detect = False
        if whisper_language is None or whisper_language.lower().strip() in invalid_language_codes:
            whisper_language = None  # None farà rilevare automaticamente la lingua
            auto_detect = True
            logger.warning("⚠️ Codice lingua non specificato o indefinito, attivo rilevamento automatico")
        else:
            # FIX: Assicuriamo che il codice lingua sia a 2 lettere (ISO 639-1)
            # Faster-Whisper accetta sia 2 che 3 lettere, ma per sicurezza usiamo 2
            if len(whisper_language) == 3:
                 # Mappa inversa (ITA -> IT)
                 lang_map_3_to_2 = {'ita': 'it', 'eng': 'en', 'spa': 'es', 'fre': 'fr', 'deu': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja'}
                 whisper_language = lang_map_3_to_2.get(whisper_language.lower(), whisper_language)
        
        
        self.log(f"  📊 Trascrizione di {total_chunks} chunks audio...")
        self.log(f"  ⚙️ Profilo: {self.profile_name} (beam={self.beam_size}, workers={self.num_workers})")
        if auto_detect:
            self.log(f"  🎯 Lingua: AUTO-DETECT (rilevamento automatico)")
        else:
            self.log(f"  🎯 Lingua: {whisper_language}")
        self.log(f"  ⏳ Elaborazione in corso...")
        
        all_segments = []
        failed_chunks = 0
        detected_language = None
        
        progress_thresholds = {
            25: int(total_chunks * 0.25),
            50: int(total_chunks * 0.50),
            75: int(total_chunks * 0.75),
            100: total_chunks
        }
        
        logged_progress = set()
        
        for i, (chunk_path, start_time, end_time) in enumerate(audio_chunks):
            chunk_num = i + 1
            
            try:
                chunk_path_obj = Path(chunk_path)
                if not chunk_path_obj.exists():
                    logger.error(f"Chunk {chunk_num} non trovato: {chunk_path}")
                    failed_chunks += 1
                    continue
                
                chunk_path_str = str(chunk_path)
                
                
                transcribe_kwargs = dict(
                    language=whisper_language,
                    beam_size=self.beam_size,
                )
                if self.batch_size_for_transcription is not None:
                    transcribe_kwargs['batch_size'] = self.batch_manager.get_batch_size()

                if self.vad_available:
                    segments, info = self.faster_whisper_model.transcribe(
                        chunk_path_str,
                        vad_filter=True,
                        vad_parameters=dict(
                            min_silence_duration_ms=500,
                            threshold=0.5
                        ),
                        **transcribe_kwargs
                    )
                else:
                    segments, info = self.faster_whisper_model.transcribe(
                        chunk_path_str,
                        vad_filter=False,
                        word_timestamps=False,
                        **transcribe_kwargs
                    )
                
                if detected_language is None:
                    detected_language = info.language if hasattr(info, 'language') else None
                    if detected_language and auto_detect:
                        self.log(f"  🔍 Lingua rilevata automaticamente: {detected_language}")
                
                for segment in segments:
                    all_segments.append({
                        'start': segment.start + start_time,
                        'end': segment.end + start_time,
                        'text': segment.text.strip()
                    })
                
                for percentage, threshold in progress_thresholds.items():
                    if chunk_num >= threshold and percentage not in logged_progress:
                        self.log(f"  ✅ Trascrizione completata: {percentage}%")
                        logged_progress.add(percentage)
                        break
                
            except Exception as e:
                # Logga l'errore completo per diagnostica
                error_msg = f"❌ ERRORE chunk {chunk_num}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                failed_chunks += 1
                continue
        
        if failed_chunks > 0:
            self.log(f"  ⚠️ Completato con {failed_chunks} chunks falliti su {total_chunks}")
        else:
            if 100 not in logged_progress and total_chunks > 0:
                self.log(f"  ✅ Trascrizione completata: 100%")
        
        self.log(f"  📝 Totale segmenti trascritti: {len(all_segments)}")
        
        # Salva se richiesto
        if output_path and all_segments:
            save_success = save_srt_file(all_segments, Path(output_path))
            return save_success, detected_language
        
        return len(all_segments) > 0, detected_language
    
    def cleanup(self):
        """Pulizia risorse GPU"""
        try:
            if self.faster_whisper_model:
                del self.faster_whisper_model
                self.faster_whisper_model = None
            
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            
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
    """Converte segmenti in formato SRT"""
    srt_content = []
    
    for i, segment in enumerate(segments, 1):
        text = clean_html_tags(segment['text'])
        
        if not text:
            continue
        
        srt_content.append(str(i))
        
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
    """Test transcriber con profili"""
    
    print("\n" + "="*80)
    print("TEST TRANSCRIBER CON PROFILI DINAMICI")
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
        transcriber._load_profile_params()
        print(f"Profilo '{profile}': workers={transcriber.num_workers}, beam={transcriber.beam_size}")
    
    print("\n" + "="*80)
    print("✅ Test completato")
    print("="*80)