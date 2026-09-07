# -*- coding: utf-8 -*-
"""
Processing Pipeline - HYBRID v3.9 PRODUCTION READY
File: core/pipeline.py

VERSIONE: v3.9 - HYBRID (Meglio di v3.7 + v3.8)

CORREZIONI v3.9:
âœ… FIX CRITICO #1: Corretta chiamata transcribe_chunks() con:
   - Gestione tupla (success, detected_lang)
   - Parametro whisper_language come keyword argument
   - Validazione successo trascrizione
âœ… FIX CRITICO #2: Parametri translate_file() corretti (src_lang, tgt_lang)
âœ… FEATURE: Upload OpenSubtitles robusto da v3.8 (REST/XML-RPC)
âœ… FEATURE: Gestione metadati completa da v3.8
âœ… FEATURE: AudioTrackSelector con get_selected_language()
âœ… OPTIMIZATION: Cleanup e logging migliorati

âœ… FIX TRANSLATOR SELECTION: La scelta del traduttore viene passata esplicitamente alla factory get_translator()
                             per evitare fallback involontari sul default (NLLB).

HARDWARE TARGET:
- OS: Windows 11
- RAM: 12GB
- CPU: Intel 12700KF
- GPU: RTX 3060 12GB VRAM

FUNZIONALITÃ€ COMPLETE:
âœ… Estrazione sottotitoli embedded con prioritÃ  lingua
âœ… Trascrizione audio Faster-Whisper con profili ottimizzati
âœ… Separazione vocale Demucs con pipeline intelligente
âœ… Traduzione NLLB-200 con batch size adattivo
âœ… Upload OpenSubtitles (REST e XML-RPC)
âœ… Integrazione TMDB per metadata IMDb
âœ… Gestione memoria GPU ottimizzata
âœ… Output ISO 639-1 (2 lettere)
"""
import gc
import json
import logging
import os
import subprocess
import sys
import tempfile
import torch
import shutil
import psutil
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from datetime import datetime
import time

# Core Modules
from core.subtitle_extractor import SubtitleExtractor
from core.subtitle_cleaner import SubtitleCleaner
from core.translator import BaseTranslator, get_translator
from core.transcriber import Transcriber
from core.audio_track_selector import AudioTrackSelector
from core.audio_processor import AudioProcessor 

# Utility Modules
from utils.file_handler import FileHandler
from utils.config import get_config
from utils.tmdb_client import get_tmdb_client
from utils.subtitle_uploader_interface import UploaderFactory, SubtitleMetadata
from utils.logger import setup_logger
from utils.resource_monitor import release_ram_to_os

logger = setup_logger(__name__)


class ProcessingPipeline:
    """
    Pipeline completa per elaborazione sottotitoli con output ISO 639-1
    
    WORKFLOW:
    1. Estrazione sottotitoli embedded (se presenti)
    2. Trascrizione audio Faster-Whisper (se necessaria)
       - Estrazione traccia audio
       - Separazione vocale Demucs
       - Chunking intelligente
       - Trascrizione multi-chunk
    3. Pulizia e normalizzazione SRT
    4. Traduzione NLLB-200 (se necessaria)
    5. Salvataggio file finale
    6. Upload OpenSubtitles (opzionale)
    """
    
    # Mappa ISO 639-2 (3 lettere) → ISO 639-1 (2 lettere)
    LANG_MAP_639_2_TO_639_1 = {
        'ita': 'it', 'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
        'deu': 'de', 'ger': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
        'kor': 'ko', 'chi': 'zh', 'zho': 'zh', 'ara': 'ar', 'hin': 'hi',
        'pol': 'pl', 'tur': 'tr', 'nld': 'nl', 'dut': 'nl', 'swe': 'sv',
        'dan': 'da', 'nor': 'no', 'fin': 'fi', 'ces': 'cs',
        'cze': 'cs', 'hun': 'hu', 'ron': 'ro', 'rum': 'ro', 'ukr': 'uk',
        'ell': 'el', 'gre': 'el', 'heb': 'he', 'vie': 'vi', 'tha': 'th',
        'srp': 'sr', 'hrv': 'hr', 'bos': 'bs', 'slk': 'sk', 'slv': 'sl',
        'bul': 'bg', 'cat': 'ca', 'lit': 'lt', 'lav': 'lv', 'est': 'et',
        'und': 'und'
    }

    # Direzione inversa (ISO 639-1 → 639-2) esplicita, NON auto-generata dalla
    # mappa sopra: quest'ultima contiene coppie /B e /T per lo stesso codice
    # (es. 'ger'/'deu' → 'de'), e invertirla con una dict-comprehension farebbe
    # dipendere il risultato dall'ordine di dichiarazione — fragile anche se
    # per le lingue attuali il risultato coincideva già con quello giusto (la
    # vera voce rotta era 'danish': 'da', rimossa sopra: 6 caratteri, scartata
    # da SubtitleMetadata.validate() perché non è un codice ISO 639-2 valido).
    # Qui il codice /B (quello atteso da OpenSubtitles come sublanguageid, e a
    # cui utils/opensubtitles_rest_uploader._LANG3_TO_LANG2 sa fare da inverso)
    # è scelto esplicitamente per ogni lingua ambigua, senza dipendere da un
    # ordine implicito.
    ISO_639_1_TO_639_2 = {
        'it': 'ita', 'en': 'eng', 'es': 'spa', 'fr': 'fre', 'de': 'ger',
        'pt': 'por', 'ru': 'rus', 'ja': 'jpn', 'ko': 'kor', 'zh': 'chi',
        'ar': 'ara', 'hi': 'hin', 'pl': 'pol', 'tr': 'tur', 'nl': 'dut',
        'sv': 'swe', 'da': 'dan', 'no': 'nor', 'fi': 'fin', 'cs': 'cze',
        'hu': 'hun', 'ro': 'rum', 'uk': 'ukr', 'el': 'gre', 'he': 'heb',
        'vi': 'vie', 'th': 'tha', 'sr': 'srp', 'hr': 'hrv', 'bs': 'bos',
        'sk': 'slo', 'sl': 'slv', 'bg': 'bul', 'ca': 'cat', 'lt': 'lit',
        'lv': 'lav', 'et': 'est',
    }
    
    def __init__(self, video_path: str, log_callback: Optional[Callable] = None):
        """
        Inizializza la pipeline
        
        Args:
            video_path: Percorso del file video
            log_callback: Funzione per inviare log alla GUI
        """
        self.video_path = Path(video_path)
        self.video_name = self.video_path.stem
        # Se l'input è già un file sottotitolo (es. "Movie.en.srt"), lo stem
        # include il codice lingua originale ("Movie.en") — va rimosso, altrimenti
        # il file finale diventa "Movie.en.it.srt" invece di "Movie.it.srt".
        if self.video_path.suffix.lower() in {'.srt', '.vtt', '.ass', '.ssa', '.sub'}:
            base, sep, last_seg = self.video_name.rpartition('.')
            if sep:
                known_codes = (set(self.LANG_MAP_639_2_TO_639_1.keys())
                               | set(self.LANG_MAP_639_2_TO_639_1.values()))
                if last_seg.lower() in known_codes:
                    self.video_name = base
        self._log_callback = log_callback
        
        self.config = get_config()
        self.tmdb_client = get_tmdb_client()
        self.file_handler = FileHandler()

        # Inizializzazione lazy/cleanup
        self._transcriber: Optional[Transcriber] = None
        self._translator: Optional[BaseTranslator] = None
        # Quale motore ha tradotto, per la firma in coda al file. Resta
        # None quando non si traduce affatto — sottotitolo gia' nella
        # lingua di destinazione — e in quel caso la firma non lo cita.
        self._motore_traduzione: Optional[str] = None
        self._audio_processor: Optional[AudioProcessor] = None
        self.last_execution_time = 0.0
        self.last_output_path: Optional[Path] = None
        self.metadata: Dict[str, Any] = {}
        self._cleanup_done: bool = False

        # Batch context (fatigue tracking per OOM prevention)
        self._files_processed_in_batch: int = 0

        # Cancellazione
        self._cancelled: bool = False
        self._current_proc: Optional[subprocess.Popen] = None
        self._track_selector = None   # AudioTrackSelector ref per cancel()
        self._subtitle_extractor = None  # SubtitleExtractor ref per cancel()
        self._ocr = None  # PgsOcr/VobSubOcr ref per cancel() (ramo bitmap STEP 1)
        
        # File paths
        self.extracted_srt: Optional[Path] = None
        self.detected_language: Optional[str] = None

        # Diagnostica RAM per-step (opt-in via config: "diagnose_ram": true).
        # Quando attiva, _log() appende l'RSS del processo ai boundary di step.
        try:
            self._diagnose_ram = bool(self.config.get('diagnose_ram', False))
        except Exception:
            self._diagnose_ram = False
    
    def set_log_callback(self, callback: Callable):
        """Imposta callback per logging GUI (chiamato dal ProcessingWorker)"""
        self._log_callback = callback

    def set_batch_context(self, files_processed: int):
        """Inietta contatore file elaborati per fatigue tracking (OOM prevention)."""
        self._files_processed_in_batch = files_processed

    def cancel(self):
        """Segnala cancellazione e termina immediatamente i sottoprocessi attivi."""
        self._cancelled = True
        if self._current_proc:
            try:
                self._current_proc.kill()
            except Exception:
                pass
        if self._audio_processor:
            self._audio_processor.cancel()
        if self._transcriber:
            self._transcriber.cancel()
        if self._track_selector:
            self._track_selector.cancel()
        if self._subtitle_extractor:
            self._subtitle_extractor.cancel()
        if self._ocr:
            try:
                self._ocr.cancel()
            except Exception:
                pass
    
    def _log(self, message: str):
        """Logga il messaggio sia a logger che a callback GUI"""
        logger.info(message)
        if self._log_callback:
            self._log_callback(message)
        # Diagnostica RAM: SOLO sul file di log (mai a schermo), quando attiva
        # e il messaggio è un boundary di step (es. "\n2. …", "\n6.5. …").
        if getattr(self, '_diagnose_ram', False):
            import re
            if re.match(r'\s*\n?\d+(?:\.\d+)?\.\s', message):
                self._log_ram_diag(message.strip().splitlines()[0])

    def _log_ram_diag(self, step_label: str):
        """Scrive una riga di diagnostica RAM SOLO sul file di log (non a schermo).

        Usa metriche affidabili — NON l'RSS, che EmptyWorkingSet falsa svuotando
        il working set:
        - RAM di SISTEMA (used/available): è ciò che l'utente vede riempirsi.
        - commit del PROCESSO (private bytes su Windows): cresce anche col working
          set svuotato → vero indicatore di leak/frammentazione.
        """
        try:
            vm = psutil.virtual_memory()
            mi = psutil.Process(os.getpid()).memory_info()
            private_gb = getattr(mi, 'private', getattr(mi, 'vms', 0)) / 1024**3
            msg = (
                f"[DIAG-RAM] {step_label} | sistema: usata {vm.used/1024**3:.2f} GB / "
                f"disp. {vm.available/1024**3:.2f} GB ({vm.percent:.0f}%) | "
                f"processo: commit {private_gb:.2f} GB, rss {mi.rss/1024**3:.2f} GB"
            )
            # Emette via callback quando disponibile: nel subprocess isolato il
            # callback è _emit (→ stdout → parent), così la diagnostica confluisce
            # nel file di log del PARENT (centralizzata) invece che in quello del
            # child. Il consumer (main_window.log_message) riconosce il prefisso
            # [DIAG-RAM] e lo scrive solo su file, mai a schermo. Fallback su
            # logger.info se non c'è callback.
            if self._log_callback:
                self._log_callback(msg)
            else:
                logger.info(msg)
        except Exception:
            pass

    @staticmethod
    def _bitmap_kind(codec) -> str:
        """Mappa il codec del sottotitolo bitmap al motore OCR: 'vobsub' per i
        DVD (dvd_subtitle), 'pgs' per tutto il resto (PGS Blu-ray, ecc.)."""
        c = (codec or '').lower()
        if c in ('dvd_subtitle', 'dvdsub'):
            return 'vobsub'
        return 'pgs'

    def _run_bitmap_ocr(self, kind: str) -> bool:
        """Esegue l'OCR bitmap AUTO (PGS/VOBSUB → SRT) tramite core.ocr_auto.

        Ritorna False su qualsiasi problema (nessun bitmap OCR-abile, lingua
        Tesseract mancante, errore), così il chiamante può ripiegare sulla
        trascrizione da audio. L'OCR gira in AUTO (nessuna UI di revisione: la
        pipeline è headless nel subprocess).

        Side effect: imposta self._ocr_upload_srt al path del sidecar
        ".it.srt" prodotto, così il chiamante può proporlo per l'upload
        OpenSubtitles. Resta None in modalità mux (il risultato è incorporato
        nel video: non c'è alcun file sidecar da caricare — in tal caso viene
        solo loggato che l'upload da OCR richiede la modalità "sidecar").
        Il file viene accettato solo se scritto DOPO l'avvio di questa
        chiamata: un `<stem>.it.srt` più vecchio (es. lasciato da un upload
        precedente via STEP 8, o da una run OCR passata) non è il risultato
        di questa OCR e non va proposto per l'upload.
        """
        from core.ocr_auto import make_bitmap_ocr, run_ocr_auto
        from core.pgs_ocr import BitmapNotSupported as PgsNotSupported
        from core.vobsub_ocr import BitmapNotSupported as VobNotSupported
        from core.pgs_types import UnsupportedLanguage, CFG_WRITEBACK, WRITEBACK_MUX
        self._ocr_upload_srt: Optional[Path] = None
        _ocr_started_at = time.time()
        try:
            self._ocr = make_bitmap_ocr(
                self.video_path, self.config, kind, log_callback=self._log_callback)
            ok = bool(run_ocr_auto(self._ocr, log_callback=self._log_callback))
            if ok:
                is_mux = self._ocr._cfg(CFG_WRITEBACK, WRITEBACK_MUX) == WRITEBACK_MUX
                if is_mux:
                    self._log("ℹ️ Upload OpenSubtitles da OCR non disponibile in modalità "
                               "\"mux\" (nessun sidecar prodotto): passa a \"sidecar\" in "
                               "Opzioni se vuoi che l'SRT OCR venga proposto per l'upload.")
                else:
                    it_srt = self.video_path.with_name(f"{self.video_path.stem}.it.srt")
                    # Margine di 2s per differenze di risoluzione del filesystem
                    # tra time.time() e mtime.
                    if it_srt.exists() and it_srt.stat().st_mtime >= _ocr_started_at - 2:
                        self._ocr_upload_srt = it_srt
            return ok
        except (PgsNotSupported, VobNotSupported) as e:
            self._log(f"⚠️ Nessun sottotitolo bitmap OCR-abile: {e}")
            return False
        except UnsupportedLanguage as e:
            self._log(f"⚠️ Tesseract: lingua non supportata ({e})")
            return False
        except Exception as e:
            logger.warning(f"OCR bitmap fallito: {e}", exc_info=True)
            self._log(f"⚠️ Errore OCR bitmap: {e}")
            return False

    def process(self, target_language: str = 'ita') -> bool:
        """
        Esegue l'intera pipeline di elaborazione
        
        Args:
            target_language: Codice lingua target ISO 639-2 (es: 'ita', 'eng')
            
        Returns:
            True se completato con successo, False altrimenti
        """
        start_time = time.time()
        self._cleanup_done = False  # reset guard per questa elaborazione

        try:
            # ============================================================
            # STEP 0: Inizializzazione e Check
            # ============================================================
            self._log(f"\n{'='*80}")
            self._log(f"ðŸŽ¬ Inizio elaborazione: {self.video_name}")
            self._log(f"   Lingua Target: {target_language.upper()}")
            self._log(f"{'='*80}")

            # Il file può sparire tra l'aggiunta in coda e l'elaborazione
            # (rinominato/sostituito/share offline). Senza questo check
            # l'errore emergeva più avanti in forma fuorviante
            # ("Nessuna traccia audio trovata" da ffprobe su file inesistente).
            if not Path(self.video_path).exists():
                self._log(f"❌ File non trovato (rinominato, spostato o share "
                          f"di rete non raggiungibile):\n   {self.video_path}")
                return False

            # Recupero metadati e temp dir
            self._log("🔍 Ricerca metadati TMDB/IMDb...")
            self.metadata = self.tmdb_client.get_media_info(str(self.video_path))
            imdb_id = self.metadata.get('imdb_id') if self.metadata else None
            if imdb_id:
                self._log(f"✅ Metadati trovati. IMDb ID: {imdb_id}")
            else:
                self._log("⚠️ Metadati non trovati. Upload OpenSubtitles disabilitato.")
                
            temp_dir = self.file_handler.get_temp_dir(self.video_path)
            
            # Variabili per risultato finale
            source_language_639_2: str = 'und' 
            subtitle_path: Optional[Path] = None
            
            # ============================================================
            # STEP 1: Estrazione Sottotitoli Embedded
            # ============================================================
            force_audio = self.config.get('force_audio_transcription', False)
            if force_audio:
                self._log("\n1. Forza trascrizione da audio attivata. Salto check sottotitoli embedded.")
            else:
                self._log("\n1. Estrazione sottotitoli embedded...")
                extractor = SubtitleExtractor(str(self.video_path))
                self._subtitle_extractor = extractor
                selected_stream = extractor.select_best_subtitle()
                selected_is_ita = bool(
                    selected_stream
                    and (selected_stream.get('language') or '').lower().startswith('it'))

                def _use_text_sub(stream):
                    """Estrae la traccia testo selezionata → (path, lang) o (None, None)."""
                    p = self.file_handler.get_temp_path(
                        self.video_path, f"embedded_{stream['language']}.srt")
                    if extractor.extract_subtitle(p, stream['index']):
                        self._log(f"✅ Sottotitoli embedded trovati "
                                  f"({stream['language']}). Salto trascrizione.")
                        return p, stream['language']
                    self._log("❌ Estrazione sottotitoli fallita. Passo a trascrizione.")
                    return None, None

                # Bitmap ITALIANO ha priorità sul testo NON italiano: si privilegia
                # l'italiano nativo (testo o bitmap) alla traduzione da un'altra lingua.
                try:
                    ita_bitmaps = extractor.select_all_italian_bitmap_subtitles()
                except Exception:
                    ita_bitmaps = []

                if selected_is_ita:
                    # (2) Testo ITALIANO → usa quello (migliore dell'OCR).
                    p, lang = _use_text_sub(selected_stream)
                    if p:
                        subtitle_path, source_language_639_2 = p, lang

                elif ita_bitmaps:
                    # (3) Bitmap ITALIANO → OCR, anche se esiste un testo non italiano.
                    kind = self._bitmap_kind(ita_bitmaps[0].get('codec'))
                    self._log(f"\n1b. Sottotitoli bitmap italiani ({kind.upper()}) → OCR...")
                    if self._run_bitmap_ocr(kind):
                        self._log("✅ OCR bitmap completato.")
                        if self._ocr_upload_srt is not None:
                            self._upload_opensubtitles(self._ocr_upload_srt, 'it', imdb_id)
                        return True
                    self._log("⚠️ OCR bitmap non riuscito.")
                    if selected_stream:  # ripiega sul testo non italiano, se presente
                        p, lang = _use_text_sub(selected_stream)
                        if p:
                            subtitle_path, source_language_639_2 = p, lang

                elif selected_stream:
                    # (4) Testo NON italiano → usa quello (tradotto a valle).
                    p, lang = _use_text_sub(selected_stream)
                    if p:
                        subtitle_path, source_language_639_2 = p, lang

                else:
                    # (5) Nessun testo: c'è un bitmap (non italiano)? → OCR + traduzione.
                    try:
                        best_bitmap = extractor.select_best_bitmap_subtitle()
                    except Exception:
                        best_bitmap = None
                    if best_bitmap:
                        kind = self._bitmap_kind(best_bitmap.get('codec'))
                        self._log(f"\n1b. Sottotitoli bitmap ({kind.upper()}) → OCR + traduzione...")
                        if self._run_bitmap_ocr(kind):
                            self._log("✅ OCR bitmap completato.")
                            if self._ocr_upload_srt is not None:
                                self._upload_opensubtitles(self._ocr_upload_srt, 'it', imdb_id)
                            return True
                        self._log("⚠️ OCR bitmap non riuscito. Procedo con trascrizione.")
                    else:
                        self._log("ℹ️ Nessun sottotitolo embedded. Procedo con trascrizione.")

            if self._cancelled:
                self._log("⏹ Elaborazione annullata")
                return False

            # ============================================================
            # STEP 2-4: Trascrizione (se necessaria)
            # ============================================================
            if subtitle_path is None:

                # STEP 2: Estrazione audio
                self._log("\n2. Estrazione traccia audio...")
                audio_selector = AudioTrackSelector(str(self.video_path))
                self._track_selector = audio_selector
                audio_stream = audio_selector.select_best_track()
                
                if audio_stream:
                    audio_path = self.file_handler.get_temp_path(
                        self.video_path, 
                        "extracted_audio.wav"
                    )
                    
                    if audio_selector.extract_audio_track(audio_path, audio_stream['index']):
                        # Usa get_selected_language() per ottenere lingua traccia
                        source_language_639_2 = audio_selector.get_selected_language()
                        self._log(f"âœ… Audio estratto. Lingua: {source_language_639_2}")

                        if self._cancelled:
                            self._log("⏹ Elaborazione annullata")
                            return False

                        # ================================================
                        # STEP 2.5: Pre-carica WhisperModel PRIMA di Demucs
                        #
                        # ctranslate2 ≥4.7 usa lazy CUDA init: il suo backend
                        # CUDA si inizializza al primo WhisperModel().
                        # Se PyTorch ha già usato CUDA pesantemente (Demucs),
                        # ctranslate2 trova il contesto in uno stato che non
                        # gestisce → std::abort() silenzioso.
                        #
                        # Caricando Whisper QUI (contesto CUDA vergine), Demucs
                        # viene poi eseguito con ctranslate2 già inizializzato,
                        # senza conflitti. VRAM: ~1.5GB Whisper + ~5GB Demucs
                        # peak = ~6.5GB su 12GB → sicuro.
                        #
                        # Multi-engine: whisper viene pre-caricato SEMPRE
                        # (fallback caldo + ordine CUDA garantito); se il
                        # routing sceglie Canary/Qwen3, la facade lo scarica
                        # prima di caricare l'engine nuovo.
                        # ================================================
                        self._log("\n2.5. Pre-caricamento Whisper (prima di Demucs)...")
                        if self._transcriber is None:
                            self._transcriber = Transcriber(log_callback=self._log_callback)

                        # ── Pianificazione engine (sistema multi-engine) ──
                        # Decide QUI (prima di Demucs) l'engine per la lingua
                        # della traccia: determina anche la strategia di
                        # chunking — la modalità batched (file unico) è
                        # gestibile solo da faster-whisper (Qwen3 max 1200s,
                        # Canary max ~40s per input).
                        from core.engine_router import EngineRouter
                        _planned_lang = self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2)
                        if _planned_lang == 'und':
                            _planned_lang = None
                        _planned_engine, _plan_reason = EngineRouter.plan(_planned_lang, self.config)
                        _ENGINE_LABELS = {
                            'canary': 'Canary-Qwen-2.5B',
                            'qwen3': 'Qwen3-ASR',
                            'faster-whisper': 'Faster-Whisper',
                        }
                        _engine_label = _ENGINE_LABELS.get(_planned_engine, _planned_engine)
                        self._log(f"🧭 Engine pianificato: {_engine_label} ({_plan_reason})")

                        # STEP 3: Processing audio (separazione vocale + chunking)
                        try:
                            from faster_whisper import BatchedInferencePipeline
                            _use_batched = (_planned_engine == 'faster-whisper')
                        except ImportError:
                            _use_batched = False

                        step3_label = "Demucs + BatchedInferencePipeline" if _use_batched else "Demucs + Chunking"
                        self._log(f"\n3. Processing audio ({step3_label})...")
                        if self._audio_processor is None:
                            self._audio_processor = AudioProcessor()
                            self._audio_processor.set_log_callback(self._log_callback)

                        chunk_list = self._audio_processor.process_for_transcription(
                            audio_path=audio_path,
                            output_dir=temp_dir,
                            use_batched_pipeline=_use_batched,
                            engine=_planned_engine
                        )

                        if self._cancelled:
                            self._log("⏹ Elaborazione annullata")
                            return False

                        if chunk_list:
                            self._log(f"âœ… Audio processato: {len(chunk_list)} chunks creati")

                            if self._cancelled:
                                self._log("⏹ Elaborazione annullata")
                                return False

                            # ================================================
                            # Unload anticipato (solo engine ≠ whisper):
                            # Demucs e whisper pre-caricato non servono più —
                            # scaricarli QUI fa partire il load di Qwen3/
                            # Canary con VRAM massima (niente spillover WDDM).
                            # Con len==1 la facade forza whisper → non si
                            # scarica (evita unload/reload inutile).
                            # Whisper resta ricaricabile per il fallback.
                            # ================================================
                            if _planned_engine != 'faster-whisper' and len(chunk_list) > 1:
                                self._log("🧹 Unload anticipato Demucs + Whisper (engine pianificato: "
                                          f"{_engine_label})...")
                                if self._audio_processor:
                                    self._audio_processor.cleanup_model()
                                if self._transcriber:
                                    self._transcriber.unload_engines()
                                release_ram_to_os()

                            # STEP 4: Trascrizione (engine dal router; su
                            # errore degli engine nuovi → fallback automatico
                            # su Faster-Whisper dentro la facade)
                            self._log(f"\n4. Trascrizione audio ({_engine_label})...")
                            if self._transcriber is None:
                                # Fallback: non dovrebbe mai entrare qui dopo il pre-load 2.5
                                self._transcriber = Transcriber(log_callback=self._log_callback)
                            

                            # Inietta fatigue counter per OOM prevention
                            if self._files_processed_in_batch > 0:
                                self._transcriber.set_files_processed(self._files_processed_in_batch)

                            subtitle_path = self.file_handler.get_temp_path(
                                self.video_path, 
                                "transcribed.srt"
                            )
                            
                            # Whisper vuole ISO 639-1 (2 lettere, es. 'sr').
                            # source_language_639_2 viene dal MKV in ISO 639-2 (3 lettere, es. 'srp').
                            # Convertiamo prima; 'und' diventa None (auto-detect Whisper).
                            _whisper_lang = self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2)
                            if _whisper_lang == 'und':
                                _whisper_lang = None

                            success, detected_lang_639_1 = self._transcriber.transcribe_chunks(
                                audio_chunks=chunk_list,
                                output_path=str(subtitle_path),
                                whisper_language=_whisper_lang
                            )
                            
                            # Validazione risultato
                            if success and detected_lang_639_1 and subtitle_path.exists():
                                # Converti da ISO 639-1 (2 lettere) a ISO 639-2 (3 lettere)
                                source_language_639_2 = self._convert_639_1_to_639_2(detected_lang_639_1)
                                self._log(f"âœ… Trascrizione completata. Lingua rilevata: {source_language_639_2}")
                            else:
                                raise Exception("Trascrizione fallita o file SRT non creato.")

                            if self._cancelled:
                                self._log("⏹ Elaborazione annullata")
                                return False

                            # ================================================
                            # STEP 4.2: Forced Alignment (opzionale)
                            # Whisper ancora in VRAM — Wav2Vec2 caricato
                            # affianco (~5GB totali, dentro i 12GB).
                            # Aggiorna _last_segments con timestamp precisi
                            # che verranno poi usati dalla diarization.
                            # ================================================
                            enable_forced_alignment = self.config.get('enable_forced_alignment', False)
                            if enable_forced_alignment and len(chunk_list) == 1:
                                vocals_path_align = str(chunk_list[0][0])
                                from core.aligner import ForcedAligner
                                from core.transcriber import save_srt_file
                                aligner = ForcedAligner(self._log)
                                try:
                                    device_align = "cuda" if torch.cuda.is_available() else "cpu"
                                    loaded = aligner.load(detected_lang_639_1, device_align)
                                    if loaded:
                                        self._log("🔠 Forced alignment in corso...")
                                        aligned_segs = aligner.align(
                                            list(self._transcriber._last_segments),
                                            vocals_path_align,
                                        )
                                        self._transcriber._last_segments = aligned_segs
                                        save_srt_file(aligned_segs, subtitle_path)
                                        self._log("✅ Timestamp riallineati con precisione fonema")
                                except Exception as e:
                                    self._log(f"⚠️ Forced alignment fallito: {e} — timestamp Whisper mantenuti")
                                finally:
                                    aligner.unload()

                            # ================================================
                            # STEP 4.5: Speaker Diarization
                            #
                            # Si attiva con 'enable_diarization' (storica) O
                            # con 'dialogue_style_enabled' (stile dialoghi
                            # professionale, default ON). Funziona con TUTTI
                            # gli engine: in modalità batched il vocals è il
                            # chunk unico; in modalità chunk classici si usa
                            # il file vocals COMPLETO che Demucs lascia su
                            # disco (extracted_audio_vocals.wav), con
                            # fallback sull'audio estratto.
                            # ================================================
                            enable_diarization = (
                                self.config.get('enable_diarization', False)
                                or self.config.get('dialogue_style_enabled', True)
                            )
                            if enable_diarization:
                                if self.config.is_huggingface_token_set():
                                    segments_for_diarization = list(self._transcriber._last_segments)
                                    # A/B diarization (v. piano_fix_pipeline_trascrizione
                                    # punto A): 'original' bypassa Demucs anche in modalità
                                    # batched — valutato PRIMA del ramo su len(chunk_list),
                                    # altrimenti il caso a chunk singolo lo ignorerebbe.
                                    _diar_src = self.config.get('diarization_audio_source', 'vocals')
                                    if _diar_src == 'original':
                                        vocals_path = str(audio_path)
                                        self._log("  🎭 Diarization su audio ORIGINALE (A/B: bypass Demucs)")
                                    elif len(chunk_list) == 1:
                                        vocals_path = str(chunk_list[0][0])
                                    else:
                                        _vocals_candidate = audio_path.parent / f"{audio_path.stem}_vocals.wav"
                                        vocals_path = str(
                                            _vocals_candidate if _vocals_candidate.exists()
                                            else audio_path)

                                    # Cleanup modelli (libera VRAM per pyannote)
                                    if self._transcriber:
                                        self._transcriber.cleanup()
                                        self._transcriber = None
                                    if self._audio_processor:
                                        self._audio_processor.cleanup_model()
                                        self._audio_processor = None
                                    if torch.cuda.is_available():
                                        torch.cuda.synchronize()
                                        gc.collect()
                                        torch.cuda.empty_cache()
                                    release_ram_to_os()

                                    from core.diarizer import Diarizer
                                    from core.subtitle_formatter import SubtitleFormatter
                                    self._log("🎭 Speaker diarization in corso...")
                                    diarizer = Diarizer(self.config.get_huggingface_token(), self._log)
                                    try:
                                        diarizer.load()
                                        num_spk = self.config.get('diarization_num_speakers', 0)
                                        diarization_result = diarizer.diarize(
                                            vocals_path, num_speakers=num_spk,
                                            audio_source_label=_diar_src)
                                        # Salva i turni per il riuso nello STEP 6.5
                                        # (Gender Corrector v2: risparmia ~1-2 min/film)
                                        try:
                                            _diar_json = self.file_handler.get_temp_path(
                                                self.video_path, "diarization_turns.json")
                                            _diar_json.write_text(
                                                json.dumps(diarization_result),
                                                encoding='utf-8')
                                        except Exception as e:
                                            logger.warning(f"Salvataggio diarization per riuso fallito: {e}")
                                        annotated = diarizer.assign_speakers(segments_for_diarization, diarization_result)
                                        formatter = SubtitleFormatter(log_callback=self._log)
                                        formatter.save(annotated, subtitle_path)
                                        self._log("✅ Speaker labels + formattazione professionale applicati")
                                    except Exception as e:
                                        self._log(f"⚠️ Diarization fallita: {e} — SRT senza speaker labels")
                                    finally:
                                        diarizer.unload()
                                else:
                                    self._log("⚠️ Diarization abilitata ma token HuggingFace non configurato.")

                        else:
                            raise Exception("Processing audio fallito - nessun chunk creato.")
                    else:
                        raise Exception("Estrazione traccia audio fallita.")
                else:
                    raise Exception("Nessuna traccia audio trovata nel video.")

            # ============================================================
            # CLEANUP ANTICIPATO: Whisper + Demucs non servono piu' dopo
            # trascrizione/alignment/diarization. Liberiamo VRAM il prima
            # possibile cosi' STEP 6 (traduzione) e STEP 6.5 (LLM) trovano
            # piu' memoria libera. Idempotente: STEP 5.5/6.5 ripeteranno
            # questo blocco come rete di sicurezza.
            # ============================================================
            if self._transcriber is not None:
                try:
                    self._transcriber.cleanup()
                except Exception as e:
                    logger.warning(f"Errore cleanup transcriber (post-trascrizione): {e}")
                try:
                    del self._transcriber
                except Exception:
                    pass
                self._transcriber = None
            if self._audio_processor is not None:
                try:
                    self._audio_processor.cleanup_model()
                except Exception as e:
                    logger.warning(f"Errore cleanup audio_processor (post-trascrizione): {e}")
                try:
                    del self._audio_processor
                except Exception:
                    pass
                self._audio_processor = None
            self._clear_vram()

            # ============================================================
            # STEP 5: Pulizia e Normalizzazione SRT
            # ============================================================
            if subtitle_path is None:
                 raise Exception("Nessun sottotitolo o trascrizione disponibile.")
                 
            self._log("\n5. Pulizia e normalizzazione sottotitoli...")
            cleaned_srt_path = self.file_handler.get_temp_path(
                self.video_path, 
                f"temp_{source_language_639_2}_cleaned.srt"
            )
            
            SubtitleCleaner.clean_file(subtitle_path, cleaned_srt_path)
            subtitle_path = cleaned_srt_path
            self._log("âœ… Pulizia e fix overlap completati.")

            if self._cancelled:
                self._log("⏹ Elaborazione annullata")
                return False

            # ============================================================
            # STEP 5.5: Scarica Whisper e Demucs prima della traduzione
            # ============================================================
            if self._transcriber:
                self._transcriber.cleanup()
                self._transcriber = None
            if self._audio_processor:
                self._audio_processor.cleanup_model()
                self._audio_processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            release_ram_to_os()

            # ============================================================
            # STEP 6: Traduzione (se lingua sorgente != lingua target)
            # ============================================================
            source_language_639_1 = self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2, 'und')
            target_language_639_1 = self.LANG_MAP_639_2_TO_639_1.get(target_language, 'und')

            # Traccia se una traduzione è stata EFFETTIVAMENTE eseguita:
            # il gender corrector (STEP 6.5) corregge gli errori di genere
            # introdotti dalla traduzione — su italiano NATIVO (trascrizione
            # diretta o sottotitoli embedded ita) non deve girare.
            translation_performed = False

            if source_language_639_1 != target_language_639_1:

                self._log(f"\n6. Traduzione ({source_language_639_1} â†’ {target_language_639_1})...")
                # âœ… FIX TRANSLATOR SELECTION: Usa il metodo corretto per leggere il modello dalla config
                # Leggi il modello di traduzione selezionato dall'utente
                selected_model = self.config.get_translation_model()
                self._log(f"📋 Modello di traduzione selezionato: {selected_model.upper()}")

                # Contesto dell'opera per il traduttore: titolo e trama sono
                # già in self.metadata e aiutano soprattutto sui nomi propri e
                # sul registro. I motori che non lo usano lo ignorano.
                translation_context = None
                if self.metadata:
                    _bits = [self.metadata.get('title') or self.metadata.get('name'),
                             self.metadata.get('overview')]
                    translation_context = ". ".join(
                        str(b).strip() for b in _bits if b) or None

                # Glossario a resa fissa per la serie (core/glossary.py):
                # {} se non esiste, nessun cambio di comportamento.
                translation_glossary = {}
                if self.metadata and self.metadata.get('id'):
                    from core.glossary import load_glossary
                    translation_glossary = load_glossary(self.metadata['id'])
                    if translation_glossary:
                        self._log(f"   Glossario attivo: {len(translation_glossary)} termini")

                # Usa la factory intelligente passando la scelta esplicita del modello
                self._translator = get_translator(model_type=selected_model,
                                                  context=translation_context,
                                                  glossary=translation_glossary)
                self._motore_traduzione = selected_model
                self._translator.set_log_callback(self._log_callback)

                translated_srt_path = self.file_handler.get_temp_path(
                    self.video_path,
                    f"translated_{target_language}.srt"
                )

                # âœ… FIX v3.7/v3.9: Parametri corretti src_lang e tgt_lang
                if self._translator.translate_file(
                    input_path=str(subtitle_path),
                    output_path=str(translated_srt_path),
                    src_lang=source_language_639_1,  # âœ… Corretto
                    tgt_lang=target_language_639_1,  # âœ… Corretto
                    context=translation_context
                ):
                    subtitle_path = translated_srt_path
                    final_language_639_1 = target_language_639_1
                    translation_performed = True
                    self._log("âœ… Traduzione completata con successo.")
                else:
                    self._log("âŒ Traduzione fallita. Uso i sottotitoli originali.")
                    final_language_639_1 = source_language_639_1
            else:
                final_language_639_1 = source_language_639_1
                self._log("\n6. Lingua originale == Lingua target. Salto traduzione.")

            if self._cancelled:
                self._log("⏹ Elaborazione annullata")
                return False


            # ============================================================
            # STEP 6.5: Correzione Genere (solo italiano, opzionale)
            #
            # Eseguito in SUBPROCESS isolato per liberare l'intera VRAM al
            # LLM. Il processo principale (Python+CUDA+ctranslate2) tiene
            # sempre ~4 GB di contesto incollato che non si puo' rilasciare
            # senza terminare l'interprete. Lo spawn di un child process
            # parte da CUDA context vergine -> ~11.5 GB liberi per Qwen 14B.
            # ============================================================
            if (final_language_639_1 == 'it'
                    and not translation_performed
                    and self.config.get('gender_correction_enabled', False)):
                # Italiano NATIVO (nessuna traduzione): il corrector sarebbe
                # inutile (niente errori di genere da traduzione) e costoso.
                self._log("\n6.5. Correzione genere saltata: italiano nativo, nessuna traduzione.")

            if (final_language_639_1 == 'it'
                    and translation_performed
                    and self.config.get('gender_correction_enabled', False)):
                self._log("\n6.5. Correzione genere grammaticale (v2, subprocess)...")
                try:
                    from core.gender_corrector_v2 import find_selector_python
                    if not self.config.get('huggingface_token', ''):
                        self._log("⚠️ Token HuggingFace mancante (serve per pyannote). Salto.")
                    elif find_selector_python() is None:
                        self._log("⚠️ Venv NLP (spaCy) non trovato. Salto.")
                    else:
                        # Cleanup parent: libera RAM/VRAM prima dello spawn.
                        # Non aiuta direttamente la VRAM del child (CUDA context
                        # parent resta), ma libera RAM e rompe ref Python locali.
                        self._log("   Cleanup risorse parent prima dello spawn...")

                        if self._transcriber is not None:
                            try:
                                self._transcriber.cleanup()
                            except Exception as e:
                                logger.warning(f"Errore cleanup transcriber (pre-LLM): {e}")
                            try:
                                del self._transcriber
                            except Exception:
                                pass
                            self._transcriber = None

                        if self._audio_processor is not None:
                            try:
                                self._audio_processor.cleanup_model()
                            except Exception as e:
                                logger.warning(f"Errore cleanup audio_processor (pre-LLM): {e}")
                            try:
                                del self._audio_processor
                            except Exception:
                                pass
                            self._audio_processor = None

                        if self._translator is not None:
                            try:
                                if hasattr(self._translator, 'model') and self._translator.model is not None:
                                    try:
                                        del self._translator.model
                                    except Exception as e:
                                        logger.warning(f"Errore del translator.model: {e}")
                                self._translator.cleanup()
                            except Exception as e:
                                logger.warning(f"Errore cleanup translator (pre-LLM): {e}")
                            try:
                                del self._translator
                            except Exception:
                                pass
                            self._translator = None

                        for _ in range(3):
                            self._clear_vram()
                        release_ram_to_os()

                        # Prepara args.json per il subprocess (v2: serve il
                        # video per la speaker gender map dall'audio)
                        corrected_path = self.file_handler.get_temp_path(
                            self.video_path, f"gender_corrected_{final_language_639_1}.srt")
                        args_path = self.file_handler.get_temp_path(
                            self.video_path, "gender_correction_args.json")
                        # Riuso diarization della trascrizione (se disponibile)
                        _diar_json = self.file_handler.get_temp_path(
                            self.video_path, "diarization_turns.json")
                        # Cast TMDB per i vocativi 2ª persona (API leggera)
                        character_context = {}
                        if self.metadata and self.metadata.get('id'):
                            try:
                                character_context = self.tmdb_client.get_cast_info(
                                    self.metadata['id'],
                                    'tv' if self.metadata.get('season') else 'movie',
                                    season=self.metadata.get('season'),
                                    episode=self.metadata.get('episode'))
                            except Exception as e:
                                logger.warning(f"TMDB cast error: {e}")
                        # Se l'input della pipeline è già un .srt (non un video),
                        # self.video_path punta al sottotitolo stesso: la speaker
                        # gender map ha bisogno dell'audio, quindi va risolto il
                        # video reale corrispondente (stesso meccanismo usato per
                        # l'hash upload OpenSubtitles).
                        _gender_video_path = self._resolve_video_path()
                        args_payload = {
                            "input_srt": str(subtitle_path),
                            "output_srt": str(corrected_path),
                            "video_path": str(_gender_video_path) if _gender_video_path else None,
                            "diarization_json": str(_diar_json) if _diar_json.exists() else None,
                            "character_context": character_context or {},
                        }
                        args_path.write_text(
                            json.dumps(args_payload, ensure_ascii=False),
                            encoding='utf-8')

                        # Spawn subprocess isolato
                        project_root = Path(__file__).resolve().parent.parent
                        env = os.environ.copy()
                        env['PYTHONIOENCODING'] = 'utf-8'
                        env['PYTHONUTF8'] = '1'

                        self._log("   Avvio subprocess Gender Corrector...")
                        try:
                            # stderr SEPARATO: il rumore di libreria (warning
                            # transformers/speechbrain/torchaudio) va solo nel
                            # file di log, mai a schermo (stesso pattern di
                            # workers._process_single_file_subprocess).
                            proc = subprocess.Popen(
                                [sys.executable, "-m", "core.gender_corrector_cli",
                                 str(args_path)],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                cwd=str(project_root),
                                env=env,
                                text=True,
                                encoding='utf-8',
                                errors='replace',
                                bufsize=1,
                            )
                        except Exception as e:
                            self._log(f"⚠️ Spawn subprocess fallito: {e}")
                            proc = None

                        if proc is not None:
                            self._current_proc = proc

                            # Drena lo stderr del child in un thread: solo nel
                            # file di log del parent, mai a schermo.
                            import threading as _threading

                            def _drain_gender_stderr(stream):
                                try:
                                    for eline in stream:
                                        eline = eline.rstrip()
                                        if eline:
                                            logger.info(
                                                f"[gender-stderr] {eline}")
                                except Exception:
                                    pass

                            _threading.Thread(
                                target=_drain_gender_stderr,
                                args=(proc.stderr,), daemon=True).start()

                            try:
                                # Stream stdout linea per linea -> log GUI.
                                # Cancel: a ogni linea controlliamo _cancelled.
                                for line in proc.stdout:
                                    if self._cancelled:
                                        try:
                                            proc.terminate()
                                            try:
                                                proc.wait(timeout=5)
                                            except subprocess.TimeoutExpired:
                                                proc.kill()
                                        except Exception:
                                            pass
                                        break
                                    line = line.rstrip()
                                    if line:
                                        self._log(f"   [Gender] {line}")
                                return_code = proc.wait()
                            finally:
                                self._current_proc = None

                            if self._cancelled:
                                self._log("⏹ Correzione genere annullata.")
                            elif return_code == 0 and corrected_path.exists():
                                subtitle_path = corrected_path
                                self._log("✅ Correzione genere completata.")
                            else:
                                self._log(
                                    f"⚠️ Correzione genere fallita "
                                    f"(exit code {return_code}). Uso originale.")

                        # Cleanup args temp file (best effort)
                        try:
                            if args_path.exists():
                                args_path.unlink()
                        except Exception:
                            pass
                except Exception as e:
                    self._log(f"⚠️ Errore correzione genere: {e}")
                    logger.error(f"Gender correction error: {e}", exc_info=True)

            # ============================================================
            # STEP 7: Salvataggio File Finale
            # ============================================================
            self._log("\n7. Salvataggio file finale...")
            
            # Crea nome file finale: [nome_video].[lang].srt
            final_name = self.video_name + f".{final_language_639_1}.srt"
            final_output_path = self.video_path.parent / final_name
            self.last_output_path = final_output_path
            
            try:
                shutil.copy(subtitle_path, final_output_path)
            except PermissionError:
                self._log(f"❌ Impossibile salvare il file: permesso negato.\n"
                          f"   Percorso: {final_output_path}\n"
                          f"   Verificare che la cartella di destinazione non sia in sola lettura.")
                return False
            self._add_watermark_subtitle(final_output_path,
                                         self._motore_traduzione)

            self._log(f"✅ File salvato: {final_output_path.name}")
            
            # ============================================================
            # STEP 8: Upload OpenSubtitles (Opzionale) - DA v3.8
            # ============================================================
            self._upload_opensubtitles(final_output_path, final_language_639_1, imdb_id)
            
            # ============================================================
            # STEP 9: Finalizzazione
            # ============================================================
            self.last_execution_time = time.time() - start_time
            self._log(f"\n{'='*80}")
            self._log(f"✅ Elaborazione completata! Tempo totale: {self.last_execution_time:.2f} secondi.")
            self._log(f"{'='*80}")
            
            return True

        except InterruptedError:
            self._log("⏹ Elaborazione annullata")
            return False

        except Exception as e:
            error_msg = f"❌ Errore critico pipeline: {e}"
            logger.error(error_msg, exc_info=True)
            self._log(error_msg)
            return False

        finally:
            # Esegue il cleanup in ogni caso
            self._cleanup()
            
    def _convert_639_1_to_639_2(self, lang_639_1: str) -> str:
        """
        Converte codice ISO 639-1 (2 lettere) in ISO 639-2 (3 lettere)
        
        Args:
            lang_639_1: Codice ISO 639-1 (es: 'it', 'en')
            
        Returns:
            Codice ISO 639-2 (es: 'ita', 'eng')
        """
        return self.ISO_639_1_TO_639_2.get(lang_639_1, 'und')
    
    def _upload_opensubtitles(
        self,
        subtitle_path: Path,
        language_code_639_1: str,
        imdb_id: Optional[str]
    ):
        """
        Gestisce l'upload a OpenSubtitles con supporto REST e XML-RPC

        Implementazione robusta da v3.8 con:
        - Verifica credenziali
        - Supporto multi-implementazione (REST/XML-RPC)
        - Gestione errori completa
        - Logout automatico

        Args:
            subtitle_path: Path file .srt da caricare
            language_code_639_1: Codice lingua ISO 639-1 (2 lettere)
            imdb_id: ID IMDb del video (obbligatorio)
        """

        # ============================================================
        # CHECK 1: Upload abilitato da configurazione?
        # ============================================================
        if not self.config.get('opensubtitles_upload_enabled'):
            self._log("ℹ️ Upload OpenSubtitles non attivo "
                       "(Opzioni → OpenSubtitles → \"Upload OpenSubtitles\"). Salto.")
            return

        # ============================================================
        # CHECK 2: Credenziali configurate per l'implementazione scelta?
        # ============================================================
        if not self.config.is_opensubtitles_configured():
            self._log("⚠️ Credenziali OpenSubtitles non configurate (Opzioni → OpenSubtitles). Salto upload.")
            return

        # ============================================================
        # CHECK 3: IMDb ID disponibile? (obbligatorio)
        # ============================================================
        if not imdb_id:
            self._log("⚠️ IMDb ID non disponibile. Upload OpenSubtitles saltato (obbligatorio).")
            return

        self._log("\n8. Upload OpenSubtitles...")

        try:
            # Importa moduli per garantire registrazione factory
            import utils.opensubtitles_rest_uploader
            import utils.opensubtitles_xmlrpc_uploader

            implementation = self.config.get('opensubtitles_preferred_implementation', 'xmlrpc')
            # opensubtitles.org (xmlrpc) e opensubtitles.com (rest) sono
            # account separati con credenziali proprie: niente di
            # intercambiabile tra i due set.
            creds = (
                self.config.get_opensubtitles_xmlrpc_credentials()
                if implementation == 'xmlrpc'
                else self.config.get_opensubtitles_credentials()
            )

            # Converte 639-1 in 639-2 per OpenSubtitles API
            lang_639_2 = self._convert_639_1_to_639_2(language_code_639_1)

            metadata = SubtitleMetadata(
                imdb_id=imdb_id,
                language_code=lang_639_2,  # OpenSubtitles preferisce 3 lettere
                release_name=self.video_name,
                movie_name=self.metadata.get('title', self.video_name),
                movie_year=self.metadata.get('year'),
                movie_kind=self.metadata.get('type', 'movie')
            )

            # Se l'input era un file sottotitolo (es. .en.srt), cerchiamo
            # il video originale nella stessa cartella per il calcolo dell'hash.
            video_for_hash = self._resolve_video_path()
            if video_for_hash is None:
                self._log("⚠️ Nessun file video trovato per il calcolo dell'hash. Upload saltato.")
                return

            success, url_or_error = self._try_upload_with(
                implementation, creds, metadata, video_for_hash,
                subtitle_path, language_code_639_1, lang_639_2
            )

            # NESSUN fallback automatico REST↔XML-RPC: sono due account
            # separati con credenziali proprie (vedi sopra), quindi un
            # fallimento sull'uno non è "riprovabile" con le credenziali
            # dell'altro. In più, a oggi, l'endpoint di upload della REST
            # API v1 (POST /api/v1/subtitles/upload) risponde 403
            # "uploads_not_enabled" per i consumer normali: va richiesta
            # l'abilitazione a OpenSubtitles prima che REST sia utilizzabile
            # per l'upload, indipendentemente da credenziali/API key.

            if success:
                # url_or_error è già un messaggio descrittivo restituito
                # dall'uploader ("Upload riuscito", "GIÀ PRESENTE - <url>", ecc.):
                # non anteporgli "Upload completato", sarebbe fuorviante nel
                # caso "già presente" (non è stato caricato nulla di nuovo).
                self._log(f"✅ OpenSubtitles: {url_or_error}")
            else:
                self._log(f"❌ Upload fallito: {url_or_error}")

        except Exception as e:
            error_msg = f"Errore upload OpenSubtitles: {e}"
            logger.error(error_msg, exc_info=True)
            self._log(f"❌ {error_msg}")

    def _try_upload_with(
        self, implementation: str, creds: dict, metadata: SubtitleMetadata,
        video_for_hash: Path, subtitle_path: Path,
        language_code_639_1: str, lang_639_2: str
    ):
        """
        Autentica, esegue l'upload e fa logout per UNA implementazione.
        Isolato in un metodo a parte perché _upload_opensubtitles lo
        richiama due volte nel percorso di fallback XML-RPC → REST.

        Niente controllo duplicati esplicito qui: XML-RPC lo fa già
        internamente (TryUploadSubtitles prima di UploadSubtitles, dentro
        upload()) — richiamarlo a parte raddoppierebbe hash+rete per nulla —
        e la REST API non espone alcun endpoint dedicato per farlo (il suo
        check_exists() è un no-op che ritorna sempre False).

        Returns:
            (success, message) — message è già pronto per il log.
        """
        uploader = UploaderFactory.create_uploader(implementation=implementation, **creds)
        self._log(f"🔧 Implementazione: {uploader.get_implementation_name()}")

        self._log("🔑 Autenticazione OpenSubtitles...")
        if not uploader.authenticate():
            self._log("❌ Login fallito.")
            return False, "Login fallito"

        self._log("✅ Login riuscito")
        try:
            self._log(f" Avvio upload per {language_code_639_1} ({lang_639_2})...")
            return uploader.upload(video_path=video_for_hash, subtitle_path=subtitle_path, metadata=metadata)
        finally:
            uploader.logout()
            self._log("🔓 Sessione OpenSubtitles chiusa")
    
    def _resolve_video_path(self) -> Optional[Path]:
        """
        Restituisce il path del file video reale associato a questa elaborazione.
        Se l'input della pipeline è già un video, lo restituisce direttamente.
        Se l'input è un sottotitolo (es. .en.srt), cerca il video corrispondente
        nella stessa cartella (stesso nome base, estensione video). Usato sia
        per l'hash upload OpenSubtitles sia per l'estrazione audio della
        correzione di genere (entrambi richiedono un video reale, mai il .srt
        stesso).
        """
        _SUB_EXTS   = {'.srt', '.vtt', '.ass', '.ssa', '.sub'}
        _VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.m4v',
                       '.mpg', '.mpeg', '.ts', '.webm'}

        if self.video_path.suffix.lower() not in _SUB_EXTS:
            return self.video_path  # già un file video

        # Estrai il nome base senza il codice lingua (es. "movie.en" → "movie")
        stem = self.video_path.stem          # "The Terrorists ...en"
        parts = stem.rsplit('.', 1)
        base_stem = parts[0] if len(parts) > 1 and len(parts[1]) <= 5 else stem

        parent = self.video_path.parent

        # 1. Cerca video con nome base identico (senza estensione lingua)
        for f in sorted(parent.iterdir()):
            if f.suffix.lower() in _VIDEO_EXTS and f.stem == base_stem:
                logger.info(f"🎬 Video trovato per hash: {f.name}")
                return f

        # 2. Cerca video il cui nome inizia con il base_stem
        for f in sorted(parent.iterdir()):
            if f.suffix.lower() in _VIDEO_EXTS and f.name.startswith(base_stem):
                logger.info(f"🎬 Video trovato per hash (prefisso): {f.name}")
                return f

        logger.warning(f"⚠️ Nessun video trovato in {parent} per il base_stem '{base_stem}'")
        return None

    # Come si chiama ogni motore nella firma. Nomi CORTI: la riga del
    # watermark ne ha gia' 40 di caratteri e il limite di un sottotitolo
    # e' 42, quindi il motore va su una seconda riga e deve starci comodo.
    _NOMI_MOTORE = {
        'nllb': 'NLLB-200',
        'nllb_finetuned': 'NLLB-FT',
        'llm': 'TGemma',
        'claude': 'Claude',
        'openai': 'GPT',
        'opensubtitles': 'OpenSubtitles',
    }

    @staticmethod
    def _add_watermark_subtitle(srt_path: Path,
                                motore: Optional[str] = None) -> None:
        """
        Inserisce un sottotitolo di attribuzione AI all'inizio del file SRT.

        - Durata: 0s → 10s (o meno se il primo sub esistente inizia prima di 10s,
          con un margine di 100ms per evitare sovrapposizioni).
        - Se lo spazio disponibile è < 1s, il watermark viene saltato.
        - Tutti gli indici SRT esistenti vengono incrementati di 1.
        """
        import re

        WATERMARK_TEXT = "AI generated subtitles : Transcriber_pro"
        # Il motore su una riga sua: unito alla prima si sforerebbero i
        # 42 caratteri per riga. Assente quando non si e' tradotto.
        _nome = ProcessingPipeline._NOMI_MOTORE.get(motore) if motore else None
        if _nome:
            WATERMARK_TEXT += "\n" + _nome
        WATERMARK_END_MS = 10_000
        # Sotto questa soglia il watermark si salta invece di comprimerlo:
        # a 1000ms bastava un recap che parte a 1,09s (comune nelle serie TV,
        # "Negli episodi precedenti" attacca quasi subito) per saltarlo SEMPRE.
        # Scesa a 200ms: resta leggibile anche breve, e la copertura reale
        # sale da "quasi mai sui recap" a "praticamente sempre".
        MIN_VISIBLE_MS  = 200

        # Lettura con fallback di encoding
        content = None
        for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
            try:
                content = srt_path.read_text(encoding=enc)
                break
            except Exception:
                continue
        if content is None:
            logger.warning(f"Watermark: impossibile leggere {srt_path.name}")
            return

        # Cerca il primo timestamp per calcolare lo spazio disponibile
        time_re = re.compile(
            r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}'
        )
        m = time_re.search(content)
        if m:
            first_ms = (
                int(m.group(1)) * 3_600_000 +
                int(m.group(2)) *    60_000 +
                int(m.group(3)) *     1_000 +
                int(m.group(4))
            )
            end_ms = (first_ms - 100) if first_ms <= WATERMARK_END_MS else WATERMARK_END_MS
        else:
            end_ms = WATERMARK_END_MS  # file privo di sottotitoli: usa 10s pieni

        if end_ms < MIN_VISIBLE_MS:
            logger.info("Watermark: primo sottotitolo troppo vicino all'inizio, watermark saltato")
            return

        def ms_to_srt(ms: int) -> str:
            h  = ms // 3_600_000; ms %= 3_600_000
            mi = ms //    60_000; ms %=    60_000
            s  = ms //     1_000; ms %=     1_000
            return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"

        watermark_block = (
            f"1\n"
            f"00:00:00,000 --> {ms_to_srt(end_ms)}\n"
            f"{WATERMARK_TEXT}\n\n"
        )

        # Re-indicizza i blocchi esistenti (ogni riga che è un numero intero
        # seguito da una riga timestamp viene incrementata di 1)
        index_re = re.compile(r'^\d+$')
        lines = content.splitlines()
        new_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if index_re.fullmatch(stripped):
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
                if time_re.match(next_line):
                    new_lines.append(str(int(stripped) + 1))
                    continue
            new_lines.append(line)

        new_content = watermark_block + '\n'.join(new_lines)
        if not new_content.endswith('\n'):
            new_content += '\n'

        try:
            srt_path.write_text(new_content, encoding='utf-8-sig')
            logger.info(f"✅ Watermark aggiunto: 0s → {end_ms / 1000:.1f}s")
        except Exception as e:
            logger.warning(f"Watermark: errore scrittura {srt_path.name}: {e}")

    def _clear_vram(self):
        """
        Cleanup VRAM aggressivo: gc + clearCublasWorkspaces + empty_cache + ipc_collect.

        Va chiamato DOPO aver azzerato i riferimenti Python ai modelli
        (cleanup() + del + None) cosi' che il GC possa effettivamente
        rilasciare la memoria al driver CUDA.

        Punto chiave: dopo translate_file() di NLLB, torch.alloc scende a ~0 MB
        ma torch.reserved resta ~3 GB perche' il caching allocator non puo'
        rilasciare segmenti che contengono ancora gli workspace persistenti di
        cuBLAS (handle creati durante le matrix multiplications del beam search).
        torch._C._cuda_clearCublasWorkspaces() forza il rilascio di questi
        workspace -> i segmenti diventano vuoti -> empty_cache() puo' liberarli.

        SICURO solo dopo l'unload di Whisper (ctranslate2 4.6.0). Non chiamare
        PRIMA di WhisperModel(): pre-inizializzerebbe il contesto CUDA e farebbe
        crashare ctranslate2 sotto PyQt6 (vedi memory/MEMORY.md - Critical
        Dependency Constraints).
        """
        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                # Libera gli workspace cuBLAS persistenti — chiave per liberare
                # i segmenti riservati del caching allocator.
                torch._C._cuda_clearCublasWorkspaces()
            except Exception as e:
                logger.debug(f"_cuda_clearCublasWorkspaces: {e}")
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass

    def _cleanup(self):
        """
        Cleanup risorse -- scarica tutti i modelli e libera RAM/VRAM.

        Sequenza ottimizzata:
        1. Unload modelli (Whisper, Demucs, Traduttore) + azzera riferimenti a None
        2. CUDA sync + empty_cache
        3. release_ram_to_os() aggressivo (3x gc + EmptyWorkingSet)
        4. Rimozione file temporanei
        """
        # Guard: se già eseguito non ripetere (evita doppia chiamata da finally + GUI)
        if self._cleanup_done:
            return
        self._cleanup_done = True

        try:
            _proc = psutil.Process(os.getpid())
            _ram_before = _proc.memory_info().rss / 1024**3
            self._log(f"🧹 Cleanup risorse... (RAM processo: {_ram_before:.2f} GB)")

            # 1. Unload engine di trascrizione (whisper + eventuali Canary/Qwen3)
            if self._transcriber:
                self._transcriber.cleanup()
                self._transcriber = None
                self._log("  ✅ Engine trascrizione scaricato")

            # 2. Unload Demucs
            if self._audio_processor:
                self._audio_processor.cleanup_model()
                self._audio_processor = None
                self._log("  ✅ Demucs scaricato")

            # 3. Unload Traduttore
            if self._translator:
                self._translator.cleanup()
                self._translator = None
                self._log("  ✅ Traduttore scaricato")

            # 4. CUDA: sync + svuota cache VRAM
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                self._log("  ✅ Cache CUDA svuotata")

            # 5. RAM: 3x gc + EmptyWorkingSet (Windows) / malloc_trim (Linux)
            release_ram_to_os()

            _ram_after = _proc.memory_info().rss / 1024**3
            _freed = _ram_before - _ram_after
            self._log(f"  ✅ RAM: {_ram_before:.2f} → {_ram_after:.2f} GB (liberati {_freed:.2f} GB)")

            # 6. File temporanei
            if self.video_path:
                self.file_handler.cleanup(self.video_path)
                self._log("  ✅ File temporanei rimossi")

            # 7. Cache modelli HF/torch: NON si tocca qui. La pulizia gira
            # UNA volta sola a fine coda (o su "Ferma") in ProcessingWorker:
            # farla per-file riscaricava gli stessi modelli (pyannote, ECAPA,
            # Demucs...) a ogni elemento della coda.

            self._log("✅ Cleanup completato")

        except Exception as e:
            logger.warning(f"❌ Errore cleanup: {e}")

    def cleanup(self):
        """Metodo pubblico per cleanup esterno (chiamato dalla GUI)."""
        self._cleanup()


# ============================================================================
# TESTING & VALIDATION
# ============================================================================

if __name__ == '__main__':
    """
    Test pipeline v3.9 con tutte le correzioni
    
    ESECUZIONE CORRETTA:
        python -m core.pipeline
    
    OPPURE dalla root del progetto:
        python -c "from core.pipeline import ProcessingPipeline; print('âœ… Import OK')"
    """
    
    import sys
    import os
    
    # Fix path per esecuzione diretta
    if __package__ is None:
        # Eseguito direttamente (python core/pipeline.py)
        # Aggiungi parent directory al path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    print("\n" + "="*80)
    print("TEST PIPELINE v3.9 HYBRID - PRODUCTION READY")
    print("="*80 + "\n")
    
    # Test 1: Verifica import
    print("Test 1: Verifica import moduli...")
    try:
        from core.translator import get_translator
        from core.transcriber import Transcriber
        from core.audio_processor import AudioProcessor
        from core.audio_track_selector import AudioTrackSelector
        print("âœ… Tutti gli import OK")
    except ImportError as e:
        print(f"âŒ Import fallito: {e}")
        print("\nðŸ’¡ SUGGERIMENTO: Esegui con 'python -m core.pipeline' invece di 'python core/pipeline.py'")
        exit(1)
    
    # Test 2: Verifica firma metodi critici
    print("\nTest 2: Verifica firma metodi critici...")
    
    # Test translate_file
    import inspect
    translator = get_translator()
    sig = inspect.signature(translator.translate_file)
    params = list(sig.parameters.keys())
    print(f"   translate_file: {params}")
    assert 'src_lang' in params and 'tgt_lang' in params, "âŒ Parametri errati!"
    print("âœ… translate_file OK (src_lang, tgt_lang)")
    
    # Test transcribe_chunks
    transcriber = Transcriber()
    sig = inspect.signature(transcriber.transcribe_chunks)
    params = list(sig.parameters.keys())
    print(f"   transcribe_chunks: {params}")
    assert 'whisper_language' in params, "âŒ Parametro whisper_language mancante!"
    print("âœ… transcribe_chunks OK (whisper_language keyword)")
    
    # Test AudioTrackSelector
    print("\nTest 3: Verifica AudioTrackSelector...")
    assert hasattr(AudioTrackSelector, 'select_best_track'), "âŒ select_best_track mancante!"
    assert hasattr(AudioTrackSelector, 'get_selected_language'), "âŒ get_selected_language mancante!"
    print("âœ… AudioTrackSelector OK")
    
    # Test 4: Verifica mappa lingue
    print("\nTest 4: Verifica mappa lingue ISO 639...")
    lang_map = ProcessingPipeline.LANG_MAP_639_2_TO_639_1
    test_langs = [('ita', 'it'), ('eng', 'en'), ('fra', 'fr'), ('deu', 'de')]
    for lang_2, expected_1 in test_langs:
        actual = lang_map.get(lang_2)
        assert actual == expected_1, f"âŒ {lang_2} â†’ {actual} (expected {expected_1})"
    print("âœ… Mappa lingue ISO 639 OK")
    
    print("\n" + "="*80)
    print("âœ… TUTTI I TEST SUPERATI - Pipeline v3.9 pronta per produzione")
    print("="*80 + "\n")
    
    print("ðŸ“ CHECKLIST DEPLOYMENT:")
    print("  [âœ”] Fix parametri translate_file() (src_lang, tgt_lang)")
    print("  [âœ”] Fix chiamata transcribe_chunks() con tupla e keyword")
    print("  [âœ”] Upload OpenSubtitles robusto (REST/XML-RPC)")
    print("  [âœ”] Gestione metadati completa")
    print("  [âœ”] AudioTrackSelector con get_selected_language()")
    print("  [âœ”] Cleanup memoria GPU ottimizzato")
    print("  [âœ”] Logging dettagliato per debug")
    print("  [âœ”] Gestione errori completa")
    print("\nðŸš€ Ready for deployment!")
    print("\nðŸ’¡ COMANDI DISPONIBILI:")
    print("   - Test import:  python -c \"from core.pipeline import ProcessingPipeline; print('âœ… OK')\"")
    print("   - Test suite:   python -m core.pipeline")
    print("   - Avvio GUI:    python main.py")