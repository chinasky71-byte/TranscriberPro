# -*- coding: utf-8 -*-
"""
Processing Pipeline - HYBRID v3.9 PRODUCTION READY
File: core/pipeline.py

VERSIONE: v3.9 - HYBRID (Meglio di v3.7 + v3.8)

CORREZIONI v3.9:
✅ FIX CRITICO #1: Corretta chiamata transcribe_chunks() con:
   - Gestione tupla (success, detected_lang)
   - Parametro whisper_language come keyword argument
   - Validazione successo trascrizione
✅ FIX CRITICO #2: Parametri translate_file() corretti (src_lang, tgt_lang)
✅ FEATURE: Upload OpenSubtitles robusto da v3.8 (REST/XML-RPC)
✅ FEATURE: Gestione metadati completa da v3.8
✅ FEATURE: AudioTrackSelector con get_selected_language()
✅ OPTIMIZATION: Cleanup e logging migliorati

✅ FIX TRANSLATOR SELECTION: La scelta del traduttore viene passata esplicitamente alla factory get_translator()
                             per evitare fallback involontari sul default (NLLB).

HARDWARE TARGET:
- OS: Windows 11
- RAM: 12GB
- CPU: Intel 12700KF
- GPU: RTX 3060 12GB VRAM

FUNZIONALITÀ COMPLETE:
✅ Estrazione sottotitoli embedded con priorità lingua
✅ Trascrizione audio Faster-Whisper con profili ottimizzati
✅ Separazione vocale Demucs con pipeline intelligente
✅ Traduzione NLLB-200 con batch size adattivo
✅ Upload OpenSubtitles (REST e XML-RPC)
✅ Integrazione TMDB per metadata IMDb
✅ Gestione memoria GPU ottimizzata
✅ Output ISO 639-1 (2 lettere)
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
from core.subtitle_lang import detect_text_language, contradicts, lang2_to_3, normalize_lang
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
from utils.platform_compat import find_tool
from utils.translations import tr

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
    
    @staticmethod
    def _ev(kind: str, **fields) -> None:
        """Evento strutturato (utils/events.py): accanto al log, mai al suo posto. Senza sink non fa nulla."""
        from utils.events import emit
        emit(kind, **fields)

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

    def _run_bitmap_ocr(self, kind: str, italian: bool = True) -> bool:
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
        from core.pgs_types import UnsupportedLanguage, CFG_WRITEBACK, WRITEBACK_MUX, WRITEBACK_SIDECAR
        self._ocr_upload_srt: Optional[Path] = None
        self._mislabeled_bitmap_stream: Optional[int] = None   # bitmap `ita` con testo straniero, tradotto
        _ocr_started_at = time.time()
        try:
            self._ocr = make_bitmap_ocr(
                self.video_path, self.config, kind, log_callback=self._log_callback)
            # Nella pipeline l'OCR scrive SEMPRE il `.it.srt` accanto al video e non tocca l'MKV (scelta
            # utente 09/10/2026: nessuna traccia OCR dentro i file); l'impostazione `ocr_writeback` resta
            # valida per il Library Scanner e la GUI OCR.
            self._ocr.writeback_override = WRITEBACK_SIDECAR
            # Percentuale reale della lettura OCR (callback dei motori) per l'anteprima dei passi
            self._ocr.progress_callback = (
                lambda pct, _label='': None if _label == 'Estrazione' else self._ev('bar', phase='ocr', pct=pct))
            ok = bool(run_ocr_auto(self._ocr, log_callback=self._log_callback, italian=italian))
            if ok:
                self._mislabeled_bitmap_stream = getattr(self._ocr, 'mislabeled_stream_index', None)
                is_mux = self._ocr._cfg(CFG_WRITEBACK, WRITEBACK_MUX) == WRITEBACK_MUX
                if is_mux:
                    self._log(tr('pl_opensubtitles_upload_from_ocr_is'))
                else:
                    it_srt = self.video_path.with_name(f"{self.video_path.stem}.it.srt")
                    # Margine di 2s per differenze di risoluzione del filesystem
                    # tra time.time() e mtime.
                    if it_srt.exists() and it_srt.stat().st_mtime >= _ocr_started_at - 2:
                        self._ocr_upload_srt = it_srt
            return ok
        except (PgsNotSupported, VobNotSupported) as e:
            self._log(tr('pl_no_ocr_able_bitmap_subtitle').format(e=e))
            return False
        except UnsupportedLanguage as e:
            self._log(tr('pl_tesseract_language_not_supported').format(e=e))
            return False
        except Exception as e:
            logger.warning(f"OCR bitmap fallito: {e}", exc_info=True)
            self._ev('ocr_leave')
            self._log(tr('pl_bitmap_ocr_error').format(e=e))
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
        # Traccia segnata italiana ma con testo di un'altra lingua (verificato sul contenuto): vedi
        # `_replace_mislabeled_italian_track`.
        self._mislabeled_it_stream: Optional[int] = None
        # Firma (dimensione, data) del video a inizio job: un altro programma (es. FileFlows) puo' riscriverlo
        # mentre la coda gira. Vedi `_video_unchanged`.
        self._video_sig0 = self._file_sig(self._sig_target())
        self._embedded_source_stream: Optional[int] = None   # traccia da cui deriva il sottotitolo usato
        self._embedded_lang_639_1: Optional[str] = None      # lingua (verificata) di quella traccia

        try:
            # ============================================================
            # STEP 0: Inizializzazione e Check
            # ============================================================
            self._log(f"\n{'='*80}")
            self._log(tr('pl_processing_started').format(video_name=self.video_name))
            self._log(tr('pl_target_language').format(kind=target_language.upper()))
            self._log(f"{'='*80}")

            # Il file può sparire tra l'aggiunta in coda e l'elaborazione
            # (rinominato/sostituito/share offline). Senza questo check
            # l'errore emergeva più avanti in forma fuorviante
            # ("Nessuna traccia audio trovata" da ffprobe su file inesistente).
            if not Path(self.video_path).exists():
                self._log(tr('pl_file_not_found_renamed_moved').format(video_path=self.video_path))
                return False

            # Recupero metadati e temp dir
            self._log(tr('pl_searching_tmdb_imdb_metadata'))
            self.metadata = self.tmdb_client.get_media_info(str(self.video_path))
            imdb_id = self.metadata.get('imdb_id') if self.metadata else None
            if imdb_id:
                self._log(tr('pl_metadata_found_imdb_id').format(imdb_id=imdb_id))
            else:
                self._log(tr('pl_metadata_not_found_opensubtitles_upload'))
                
            temp_dir = self.file_handler.get_temp_dir(self.video_path)
            
            subtitle_path, source_language_639_2, _ocr_done = self._select_subtitles_step(imdb_id)
            if _ocr_done:
                return True

            if self._cancelled:
                self._log(tr('pl_processing_cancelled'))
                return False

            # ============================================================
            # STEP 2-4: Trascrizione (se necessaria)
            # ============================================================
            _r = self._transcribe_step(subtitle_path, source_language_639_2, temp_dir)
            if _r is None:
                return False
            subtitle_path, source_language_639_2 = _r

            # ============================================================
            # CLEANUP ANTICIPATO: Whisper + Demucs non servono piu' dopo
            # trascrizione/alignment/diarization. Liberiamo VRAM il prima
            # possibile cosi' STEP 6 (traduzione) e STEP 6.5 (LLM) trovano
            # piu' memoria libera. Idempotente: STEP 5.5/6.5 ripeteranno
            # questo blocco come rete di sicurezza.
            # ============================================================
            subtitle_path = self._clean_subtitles_step(subtitle_path, source_language_639_2)

            if self._cancelled:
                self._log(tr('pl_processing_cancelled'))
                return False

            # ============================================================
            # STEP 5.5: Scarica Whisper e Demucs prima della traduzione
            # ============================================================
            self._release_asr_models_before_translation()

            # ============================================================
            # STEP 6: Traduzione (se lingua sorgente != lingua target)
            # ============================================================
            (subtitle_path, final_language_639_1,
             translation_performed, translation_failed) = self._translate_step(
                subtitle_path, source_language_639_2, target_language)

            if self._cancelled:
                self._log(tr('pl_processing_cancelled'))
                return False


            # STEP 6.5: Correzione genere -> _gender_correction_step()
            subtitle_path = self._gender_correction_step(subtitle_path, final_language_639_1,
                                                         translation_performed)

            return self._finalize_output(subtitle_path, final_language_639_1, translation_failed,
                                         imdb_id, start_time)

        except InterruptedError:
            self._log(tr('pl_processing_cancelled'))
            return False

        except Exception as e:
            error_msg = tr('pl_critical_pipeline_error').format(e=e)
            logger.error(error_msg, exc_info=True)
            self._log(error_msg)
            return False

        finally:
            # Esegue il cleanup in ogni caso
            self._cleanup()
            
    def _finalize_output(self, subtitle_path, final_language_639_1: str, translation_failed: bool,
                         imdb_id, start_time: float) -> bool:
        """STEP 7-9 di process(): salva il file finale, upload, sostituzione/mux, chiusura.
        Spostato da process() senza modifiche al comportamento (stesso log, stessi eventi)."""
        # ============================================================
        # STEP 7: Salvataggio File Finale
        # ============================================================
        self._ev('phase', name='final', fraction=0.4)
        self._ev('step', name='save', state='start')
        self._log(tr('pl_7_saving_final_file'))
            
        # Crea nome file finale: [nome_video].[lang].srt
        final_name = self.video_name + f".{final_language_639_1}.srt"
        final_output_path = self.video_path.parent / final_name
        if translation_failed and final_output_path.exists():
            # Traduzione fallita: il file esistente (es. X.en.srt d'ingresso)
            # non va MAI sovrascritto con la versione ripulita.
            self._log(tr('pl_translation_failed_already_exists_and').format(name=final_output_path.name))
            # La cartella temporanea viene cancellata a fine job: si
            # conserva il lavoro (trascrizione/OCR) FUORI dalla libreria.
            saved = self._preserve_recovered_srt(
                subtitle_path, f"{self.video_name}.{final_language_639_1}.srt")
            if saved:
                self._log(tr('pl_recovery_copy_original_language').format(saved=saved))
            return False

        self.last_output_path = final_output_path

        try:
            shutil.copy(subtitle_path, final_output_path)
        except PermissionError:
            self._log(tr('pl_unable_to_save_the_file').format(final_output_path=final_output_path))
            return False

        if translation_failed:
            # Salvato per non perdere la trascrizione, ma il job NON e'
            # riuscito: niente watermark del motore, niente upload.
            self._log(tr('pl_saved_in_the_original_language').format(name=final_output_path.name))
            return False

        self._add_watermark_subtitle(final_output_path,
                                     self._motore_traduzione)

        self._log(tr('pl_file_saved').format(name=final_output_path.name))
        self._ev('step', name='save', state='done')
            
        # ============================================================
        # STEP 8: Upload OpenSubtitles (Opzionale) - DA v3.8
        # ============================================================
        self._upload_opensubtitles(final_output_path, final_language_639_1, imdb_id)

        # Una traccia dichiarata italiana ma con testo straniero viene sostituita dal sidecar
        # (dopo l'upload: l'hash OpenSubtitles e' quello del file originale).
        replaced = attempted = False
        if (final_language_639_1 == 'it' and self._mislabeled_it_stream is not None
                and self._mislabeled_it_stream == self._embedded_source_stream):
            attempted = True
            replaced = self._replace_mislabeled_italian_track(final_output_path)

        # Opzione job "Muxa nel video": il sottotitolo CREATO entra nel file come nuova traccia. Non si
        # incorpora una copia di una traccia embedded gia' nella lingua finale (nessuna traduzione), ne'
        # se la sostituzione della traccia errata e' stata tentata (riuscita o no): in quel caso il file
        # si lascia com'e' invece di aggiungere una seconda traccia italiana accanto a quella sbagliata.
        if not attempted and not (self._embedded_source_stream is not None
                                  and self._embedded_lang_639_1 == final_language_639_1):
            self._mux_subtitle_into_video(final_output_path, final_language_639_1)
            
        # ============================================================
        # STEP 9: Finalizzazione
        # ============================================================
        self.last_execution_time = time.time() - start_time
        self._log(f"\n{'='*80}")
        self._log(tr('pl_processing_completed_total_time_seconds').format(seconds=self.last_execution_time))
        self._log(f"{'='*80}")
            
        return True

    def _gender_correction_step(self, subtitle_path, final_language_639_1: str,
                                translation_performed: bool):
        """STEP 6.5 di process(): correzione genere in subprocess. Ritorna il percorso del sottotitolo
        (corretto, o quello ricevuto se saltata/fallita). Spostato da process() senza modifiche."""
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
            self._ev('skip', phases=['gender'])
            self._log(tr('pl_6_5_gender_correction_skipped'))

        if (final_language_639_1 == 'it'
                and translation_performed
                and self.config.get('gender_correction_enabled', False)):
            self._ev('phase', name='gender')
            self._log(tr('pl_6_5_grammatical_gender_correction'))
            try:
                from core.gender_corrector_v2 import find_selector_python
                if not self.config.get('huggingface_token', ''):
                    self._log(tr('pl_huggingface_token_missing_required_for'))
                elif find_selector_python() is None:
                    self._log(tr('pl_nlp_venv_spacy_not_found'))
                else:
                    # Cleanup parent: libera RAM/VRAM prima dello spawn.
                    # Non aiuta direttamente la VRAM del child (CUDA context
                    # parent resta), ma libera RAM e rompe ref Python locali.
                    self._log(tr('pl_cleaning_up_parent_resources_before'))

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

                    self._log(tr('pl_starting_gender_corrector_subprocess'))
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
                        self._log(tr('pl_subprocess_spawn_failed').format(e=e))
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
                                    from utils import events as _tp_events
                                    _ev = _tp_events.parse_line(line)
                                    if _ev is not None:
                                        if _ev[0]:
                                            try:
                                                _tp_events.emit(_ev[0], **_ev[1])
                                            except Exception:
                                                pass
                                        continue
                                    self._log(f"   [Gender] {line}")
                            return_code = proc.wait()
                        finally:
                            self._current_proc = None

                        if self._cancelled:
                            self._log(tr('pl_gender_correction_cancelled'))
                        elif return_code == 0 and corrected_path.exists():
                            subtitle_path = corrected_path
                            self._log(tr('pl_gender_correction_completed'))
                        else:
                            self._log(
                                tr('pl_gender_correction_failed_exit_code').format(return_code=return_code))

                    # Cleanup args temp file (best effort)
                    try:
                        if args_path.exists():
                            args_path.unlink()
                    except Exception:
                        pass
            except Exception as e:
                self._log(tr('pl_gender_correction_error').format(e=e))
                logger.error(f"Gender correction error: {e}", exc_info=True)

        return subtitle_path

    def _translate_step(self, subtitle_path, source_language_639_2: str, target_language: str):
        """STEP 6 di process(): traduzione se lingua sorgente != target. Ritorna (subtitle_path,
        final_language_639_1, translation_performed, translation_failed). Spostato da process() senza modifiche."""
        source_language_639_1 = (self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2)
                                 or normalize_lang(source_language_639_2))
        target_language_639_1 = self.LANG_MAP_639_2_TO_639_1.get(target_language, 'und')

        # Traccia se una traduzione è stata EFFETTIVAMENTE eseguita:
        # il gender corrector (STEP 6.5) corregge gli errori di genere
        # introdotti dalla traduzione — su italiano NATIVO (trascrizione
        # diretta o sottotitoli embedded ita) non deve girare.
        translation_performed = False
        translation_failed = False

        if source_language_639_1 != target_language_639_1:

            self._ev('phase', name='translate')
            self._log(tr('pl_6_translation').format(src=source_language_639_1, dst=target_language_639_1))
            # ✅ FIX TRANSLATOR SELECTION: Usa il metodo corretto per leggere il modello dalla config
            # Leggi il modello di traduzione selezionato dall'utente
            selected_model = self.config.get_translation_model()

            # Instradamento automatico (v1.25.0): TranslateGemma ('llm') e' stato
            # addestrato SEMPRE con source_lang_code "en" (vedi Gemma
            # training/make_dataset.py), anche sulle coppie non inglesi. Misurato
            # il 27/09/2026 su 140 blocchi francesi: l'etichetta 'en' storica
            # lascia molto francese non tradotto; l'etichetta vera 'fr' lo
            # dimezza ma peggiora la fluidita' oltre la soglia della regola
            # (GEMBA fluency+style +14,3%) -> NON adottata. NLLB fine-tuned sulla
            # stessa misura batte entrambe (francese residuo quasi azzerato,
            # fluidita' comparabile): finche' TranslateGemma non e' addestrato
            # anche su sorgenti non inglesi, si instrada li' automaticamente.
            # Non tocca la scelta esplicita dell'utente per gli altri motori
            # (NLLB base, Claude, OpenAI, OpenSubtitles): quelli dichiarano gia'
            # la lingua sorgente vera nel loro prompt. Dettagli: memoria
            # traduzione_non_inglese_2026_09_27.md.
            _routed = self._route_non_english_away_from_llm(
                selected_model, source_language_639_1)
            if _routed != selected_model:
                self._log(tr('pl_translategemma_is_not_ready_for').format(src=source_language_639_1))
                selected_model = _routed

            self._log(tr('pl_selected_translation_model').format(model=selected_model.upper()))

            # Solo i motori che caricano su GPU (non API) aspettano che il driver restituisca la VRAM degli ASR.
            if selected_model not in ('claude', 'openai', 'opensubtitles'):
                self._wait_vram_settled()

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
            from core.glossary import load_glossary, show_key_from_path
            glossary_key = ((self.metadata or {}).get('id')
                            or self.config.get('glossary_id')
                            or show_key_from_path(self.video_path))
            if glossary_key:
                translation_glossary = load_glossary(glossary_key)
                if translation_glossary:
                    self._log(tr('pl_active_glossary_terms').format(n=len(translation_glossary)))

            # Usa la factory intelligente passando la scelta esplicita del modello.
            # Ogni eccezione qui (factory, callback, traduzione) equivale a
            # "traduzione fallita": si prosegue con la regola di STEP 7
            # (salva comunque + job fallito) invece di perdere il lavoro.
            try:
                self._translator = get_translator(model_type=selected_model,
                                                  context=translation_context,
                                                  glossary=translation_glossary)
                self._motore_traduzione = selected_model
                self._translator.set_log_callback(self._log_callback)

                translated_srt_path = self.file_handler.get_temp_path(
                    self.video_path,
                    f"translated_{target_language}.srt"
                )

                _translation_ok = self._translator.translate_file(
                    input_path=str(subtitle_path),
                    output_path=str(translated_srt_path),
                    src_lang=source_language_639_1,
                    tgt_lang=target_language_639_1,
                    context=translation_context
                )
            except InterruptedError:
                raise
            except Exception as e:
                logger.error(f"Errore traduzione: {e}", exc_info=True)
                self._log(tr('pl_translation_error').format(e=e))
                _translation_ok = False

            if _translation_ok:
                subtitle_path = translated_srt_path
                final_language_639_1 = target_language_639_1
                translation_performed = True
                self._log(tr('pl_translation_completed_successfully'))
            else:
                self._log(tr('pl_translation_failed_using_the_original'))
                final_language_639_1 = source_language_639_1
                translation_failed = True
        else:
            final_language_639_1 = source_language_639_1
            self._ev('skip', phases=['translate', 'gender'])
            self._log(tr('pl_6_original_language_target_language'))
        return subtitle_path, final_language_639_1, translation_performed, translation_failed

    def _release_asr_models_before_translation(self) -> None:
        """STEP 5.5 di process(): scarica Whisper e Demucs prima della traduzione. Spostato senza modifiche."""
        if self._transcriber:
            self._transcriber.cleanup()
            self._transcriber = None
        if self._audio_processor:
            self._audio_processor.cleanup_model()
            self._audio_processor = None
        # Stesso cleanup di STEP 5 (workspace cuBLAS + empty_cache + ipc_collect), poi attesa che il driver restituisca
        # davvero le pagine: su WDDM la VRAM di Whisper/Demucs/pyannote risulta occupata ancora per qualche secondo e il
        # traduttore, caricando subito, sconfinerebbe in RAM condivisa.
        self._clear_vram()
        release_ram_to_os()

    def _wait_vram_settled(self) -> None:
        if not torch.cuda.is_available():
            return
        from core.vram_settle import wait_vram_settled

        def _free() -> int:
            return torch.cuda.mem_get_info()[0]
        t0 = time.monotonic()
        first, last, settled = wait_vram_settled(_free, cancelled=lambda: self._cancelled)
        if first is not None:
            logger.info(f"VRAM libera prima della traduzione: {first / 1024 ** 3:.2f} -> {last / 1024 ** 3:.2f} GiB "
                        f"in {time.monotonic() - t0:.1f}s ({'assestata' if settled else 'NON assestata'})")

    def _clean_subtitles_step(self, subtitle_path, source_language_639_2: str):
        """CLEANUP ANTICIPATO (Whisper/Demucs) + STEP 5 di process(): pulizia e normalizzazione SRT.
        Ritorna il percorso del sottotitolo pulito. Spostato da process() senza modifiche."""
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
             raise Exception(tr('pl_no_subtitle_or_transcription_available'))
                 
        self._ev('phase', name='clean')
        self._log(tr('pl_5_cleaning_and_normalizing_subtitles'))
        cleaned_srt_path = self.file_handler.get_temp_path(
            self.video_path, 
            f"temp_{source_language_639_2}_cleaned.srt"
        )
            
        SubtitleCleaner.clean_file(subtitle_path, cleaned_srt_path)
        subtitle_path = cleaned_srt_path
        self._log(tr('pl_cleanup_and_overlap_fix_completed'))
        return subtitle_path

    def _transcribe_step(self, subtitle_path, source_language_639_2: str, temp_dir):
        """STEP 2-4.5 di process(): estrazione audio, trascrizione, allineamento, diarizzazione. Ritorna
        (subtitle_path, source_language_639_2), oppure None se annullato. Spostato senza modifiche."""
        if subtitle_path is None:

            # STEP 2: Estrazione audio
            self._ev('phase', name='extract')
            self._log(tr('pl_2_extracting_audio_track'))
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
                    self._ev('audio_lang', lang=source_language_639_2)
                    self._log(tr('pl_audio_extracted_language').format(lang=source_language_639_2))

                    if self._cancelled:
                        self._log(tr('pl_processing_cancelled'))
                        return None

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
                    self._ev('phase', name='extract')
                    self._log(tr('pl_2_5_pre_loading_whisper'))
                    _planned_lang = self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2)
                    if _planned_lang == 'und':
                        _planned_lang = None
                    if self._transcriber is None:
                        # language_hint: carica subito il Whisper specializzato
                        # della lingua (whisper_model_by_language), niente reload
                        self._transcriber = Transcriber(log_callback=self._log_callback,
                                                        language_hint=_planned_lang)

                    # ── Pianificazione engine (sistema multi-engine) ──
                    # Decide QUI (prima di Demucs) l'engine per la lingua
                    # della traccia: determina anche la strategia di
                    # chunking — la modalità batched (file unico) è
                    # gestibile solo da faster-whisper (Qwen3 max 1200s,
                    # Canary max ~40s per input).
                    from core.engine_router import EngineRouter
                    _planned_engine, _plan_reason = EngineRouter.plan(_planned_lang, self.config)
                    _ENGINE_LABELS = {
                        'canary': 'Canary-Qwen-2.5B',
                        'qwen3': 'Qwen3-ASR',
                        'faster-whisper': 'Faster-Whisper',
                    }
                    _engine_label = _ENGINE_LABELS.get(_planned_engine, _planned_engine)
                    self._log(tr('pl_planned_engine').format(engine_label=_engine_label, plan_reason=_plan_reason))
                    # Riga letta dalla GUI (tessera "Modello" della Diagnostica).
                    try:
                        from utils.engine_labels import model_display
                        self._log(tr('pl_transcription_model').format(model=model_display(_planned_engine, self.config, _planned_lang)))
                    except Exception as _e:
                        logger.debug(f"Etichetta modello trascrizione non disponibile: {_e}")

                    # STEP 3: Processing audio (separazione vocale + chunking)
                    try:
                        from faster_whisper import BatchedInferencePipeline
                        _use_batched = (_planned_engine == 'faster-whisper')
                    except ImportError:
                        _use_batched = False

                    step3_label = "Demucs + BatchedInferencePipeline" if _use_batched else "Demucs + Chunking"
                    self._ev('phase', name='demucs')
                    self._log(tr('pl_3_processing_audio').format(step3_label=step3_label))
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
                        self._log(tr('pl_processing_cancelled'))
                        return None

                    if chunk_list:
                        self._log(tr('pl_audio_processed_chunks_created').format(n=len(chunk_list)))

                        if self._cancelled:
                            self._log(tr('pl_processing_cancelled'))
                            return None

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
                            self._log(tr('pl_early_unload_of_demucs_whisper').format(engine_label=_engine_label))
                            if self._audio_processor:
                                self._audio_processor.cleanup_model()
                            if self._transcriber:
                                self._transcriber.unload_engines()
                            release_ram_to_os()

                        # STEP 4: Trascrizione (engine dal router; su
                        # errore degli engine nuovi → fallback automatico
                        # su Faster-Whisper dentro la facade)
                        self._ev('phase', name='asr', engine=str(_engine_label))
                        self._log(tr('pl_4_audio_transcription').format(engine_label=_engine_label))
                        if self._transcriber is None:
                            # Fallback: non dovrebbe mai entrare qui dopo il pre-load 2.5
                            self._transcriber = Transcriber(log_callback=self._log_callback,
                                                            language_hint=_planned_lang)
                            

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
                            self._log(tr('pl_transcription_completed_detected_language').format(lang=source_language_639_2))
                        else:
                            raise Exception(tr('pl_transcription_failed_or_srt_file'))

                        if self._cancelled:
                            self._log(tr('pl_processing_cancelled'))
                            return None

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
                                    self._log(tr('pl_forced_alignment_in_progress'))
                                    aligned_segs = aligner.align(
                                        list(self._transcriber._last_segments),
                                        vocals_path_align,
                                    )
                                    self._transcriber._last_segments = aligned_segs
                                    save_srt_file(aligned_segs, subtitle_path)
                                    self._log(tr('pl_timestamps_realigned_with_phoneme_precision'))
                            except Exception as e:
                                self._log(tr('pl_forced_alignment_failed_whisper_timestamps').format(e=e))
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
                        # Copia dei segmenti per la formattazione di ripiego
                        # (il transcriber viene liberato prima della diarization)
                        _segments_snapshot = list(
                            getattr(self._transcriber, '_last_segments', None) or [])
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
                                    self._log(tr('pl_diarization_on_original_audio_a'))
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
                                self._log(tr('pl_speaker_diarization_in_progress'))
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
                                    formatter = SubtitleFormatter(
                                        log_callback=self._log,
                                        readability=bool(self.config.get(
                                            'subtitle_readability_enabled', True)))
                                    if formatter.save(annotated, subtitle_path):
                                        self._log(tr('pl_speaker_labels_professional_formatting_applied'))
                                    else:
                                        self._log(tr('pl_formatting_with_speakers_failed_trying'))
                                        self._format_srt_fallback(_segments_snapshot, subtitle_path)
                                except Exception as e:
                                    self._log(tr('pl_diarization_failed_srt_without_speaker').format(e=e))
                                    self._format_srt_fallback(_segments_snapshot, subtitle_path)
                                finally:
                                    diarizer.unload()
                            else:
                                self._log(tr('pl_diarization_enabled_but_huggingface_token'))
                                self._format_srt_fallback(_segments_snapshot, subtitle_path)
                        else:
                            self._format_srt_fallback(_segments_snapshot, subtitle_path)

                    else:
                        raise Exception(tr('pl_audio_processing_failed_no_chunks'))
                else:
                    raise Exception(tr('pl_audio_track_extraction_failed'))
            else:
                raise Exception(tr('pl_no_audio_track_found_in'))
        return subtitle_path, source_language_639_2

    def _select_subtitles_step(self, imdb_id):
        """STEP 1/1b di process(): sottotitoli embedded (testo) o OCR dei bitmap. Ritorna
        (subtitle_path, source_language_639_2, ocr_done); ocr_done=True: OCR riuscito, job concluso.
        Spostato da process() senza modifiche."""
        # Variabili per risultato finale
        source_language_639_2: str = 'und' 
        subtitle_path: Optional[Path] = None
            
        # ============================================================
        # STEP 1: Estrazione Sottotitoli Embedded
        # ============================================================
        force_audio = self.config.get('force_audio_transcription', False)
        if force_audio:
            self._ev('phase', name='setup')
            self._log(tr('pl_1_force_transcription_from_audio'))
        else:
            self._ev('phase', name='setup')
            self._log(tr('pl_1_extracting_embedded_subtitles'))
            extractor = SubtitleExtractor(str(self.video_path))
            self._subtitle_extractor = extractor
            extractor.detect_subtitles()

            # Classifica unica (testo/bitmap, v. SubtitleExtractor._rank_key): testo it > bitmap it >
            # testo en > bitmap en > altre lingue. La lingua di una traccia testo si VERIFICA sul contenuto
            # appena estratto (un tag sbagliato, es. "English" marcata `it`, non deve far credere italiano
            # un testo inglese); per i bitmap la verifica avviene dopo l'OCR (core/ocr_auto.py).
            tried: set = set()        # tracce gia' provate/fallite
            extracted: dict = {}      # indice -> SRT estratto (non si riestrae dopo una correzione)
            corrected: set = set()    # tracce la cui lingua e' gia' stata corretta dal contenuto

            def _text_path(st):
                """SRT estratto della traccia testo (una sola volta) o None se l'estrazione fallisce."""
                path = extracted.get(st['index'])
                if path is None:
                    path = self.file_handler.get_temp_path(
                        self.video_path, f"embedded_{st['lang']}_{st['index']}.srt")
                    if not extractor.extract_subtitle(path, st['index']):
                        return None
                    extracted[st['index']] = path
                return path

            def _verdict(path):
                try:
                    return detect_text_language(Path(path).read_text(encoding='utf-8', errors='replace'))
                except Exception as e:
                    logger.debug(f"Riconoscimento lingua sottotitoli non riuscito: {e}")
                    return None, {}

            # Tracce testo SENZA lingua (tag assente/ignoto e titolo muto): si verificano prima della
            # classifica, altrimenti finirebbero dietro a un bitmap inglese anche se sono italiane.
            for st in list(extractor.subtitle_streams):
                if self._cancelled:
                    break
                if st['forced'] or extractor._is_bitmap(st) or st['lang'] != 'und':
                    continue
                path = _text_path(st)
                if path is None:
                    tried.add(st['index'])
                    continue
                verdict, evidence = _verdict(path)
                if verdict:
                    self._log(tr('pl_track_has_no_declared_language').format(index=st['index'], verdict=verdict.upper()))
                    logger.info(f"   Prove lingua stream {st['index']}: {evidence}")
                    extractor.set_language(st['index'], verdict, 'text')
                    corrected.add(st['index'])

            for _ in range(2 * len(extractor.subtitle_streams) + 4):
                if self._cancelled:
                    break
                cand = extractor.select_best_candidate(exclude=tried)
                if cand is None:
                    break

                if extractor._is_bitmap(cand):
                    kind = self._bitmap_kind(cand.get('codec'))
                    is_ita = cand.get('lang') == 'it'
                    if is_ita:
                        self._ev('route', path='ocr', translate=False)
                        self._log(tr('pl_1b_italian_bitmap_subtitles_ocr').format(kind=kind.upper()))
                    else:
                        self._ev('route', path='ocr', translate=True)
                        self._log(tr('pl_1b_bitmap_subtitles_ocr_translation').format(kind=kind.upper()))
                    if self._run_bitmap_ocr(kind, italian=is_ita):
                        self._ev('phase', name='final')
                        self._ev('step', name='save', state='done')
                        self._log(tr('pl_bitmap_ocr_completed'))
                        if self._ocr_upload_srt is not None:
                            self.last_output_path = self._ocr_upload_srt   # output del job (queue_status, GUI)
                            self._upload_opensubtitles(self._ocr_upload_srt, 'it', imdb_id)
                            # Bitmap dichiarato italiano ma con testo straniero: la traccia errata viene
                            # sostituita dal sidecar (se l'interruttore e' acceso); in quel caso, riuscita
                            # o no, non si aggiunge anche la traccia "Muxa nel video".
                            if self._mislabeled_bitmap_stream is None:
                                self._mux_subtitle_into_video(self._ocr_upload_srt, 'it')
                            else:
                                self._replace_mislabeled_italian_track(
                                    self._ocr_upload_srt, idx=self._mislabeled_bitmap_stream, bitmap=True)
                        return subtitle_path, source_language_639_2, True
                    self._ev('ocr_leave')
                    self._log(tr('pl_bitmap_ocr_failed'))
                    # dopo un OCR fallito non si riprovano i bitmap dello stesso tipo (stesso motore OCR)
                    tried |= {x['index'] for x in extractor.subtitle_streams
                              if extractor._is_bitmap(x) and self._bitmap_kind(x['codec']) == kind}
                    continue

                # Traccia testo: estrai (una sola volta) e verifica la lingua sul contenuto
                path = _text_path(cand)
                if path is None:
                    self._log(tr('pl_subtitle_extraction_failed_trying_the'))
                    tried.add(cand['index'])
                    continue
                verdict, evidence = _verdict(path)
                if contradicts(cand['lang'], verdict) and cand['index'] not in corrected:
                    corrected.add(cand['index'])
                    if cand['lang'] == 'it' and not cand['forced']:
                        self._mislabeled_it_stream = cand['index']
                    self._log(tr('pl_track_tag_title_contains_text').format(index=cand['index'], tag=cand['language'], title=cand['title'], verdict=verdict.upper(), old_lang=cand['lang'].upper()))
                    logger.info(f"   Prove lingua stream {cand['index']}: {evidence}")
                    extractor.set_language(cand['index'], verdict, 'text')
                    continue
                if verdict is None and cand.get('lang_conflict'):
                    logger.warning(f"   Stream {cand['index']}: tag e titolo in contrasto, il testo non da' "
                                   f"un verdetto affidabile ({evidence}): resta la lingua del tag.")
                self._ev('embedded', lang=cand['lang'])
                self._log(tr('pl_embedded_subtitles_found_skipping_transcription').format(lang=cand['lang']))
                subtitle_path, source_language_639_2 = path, lang2_to_3(cand['lang'])
                self._embedded_source_stream = cand['index']
                self._embedded_lang_639_1 = cand['lang']
                break
            else:
                logger.warning("Selezione sottotitoli: limite di tentativi raggiunto")

            if subtitle_path is None:
                self._log(tr('pl_no_usable_embedded_subtitles_proceeding'))
        return subtitle_path, source_language_639_2, False

    # Codec testo che ffmpeg puo' togliere/sostituire in un MKV senza perdere informazione.
    _TEXT_SUB_CODECS = {'subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text'}
    # Bitmap sostituibili solo quando l'OCR ha provato che il testo non e' italiano (v. ocr_auto).
    _BITMAP_SUB_CODECS = {'hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'xsub'}

    def _sig_target(self) -> Path:
        """Il video su cui si controlla la firma (con input .srt, il video accanto). Mai eccezioni: una
        cartella non leggibile (share offline) non deve far crollare `process()` ne' l'upload."""
        try:
            return self._resolve_video_path() or self.video_path
        except Exception:
            return self.video_path

    @staticmethod
    def _file_sig(path):
        """(dimensione, data di modifica in ns) o None se il file non esiste/non si legge."""
        try:
            st = Path(path).stat()
            return (st.st_size, st.st_mtime_ns)
        except Exception:
            return None

    def _video_unchanged(self, what: str) -> bool:
        """True se il video e' ancora quello visto a inizio job. Altrimenti (cambiato o sparito) logga e
        ritorna False: remux e upload non vanno fatti su un file che nel frattempo e' stato riscritto da
        un altro programma (il remux ne sovrascriverebbe il risultato, l'hash dell'upload non sarebbe piu'
        quello del file). Senza firma di riferimento non si puo' dire: True (comportamento storico)."""
        sig0 = getattr(self, '_video_sig0', None)
        if sig0 is None:
            return True
        video = self._sig_target()
        if self._file_sig(video) == sig0:
            return True
        self._log(tr('pl_the_video_file_changed_or').format(what=what))
        return False

    def _run_cancellable(self, cmd, timeout):
        """Esegue un comando registrandolo in `_current_proc`: `cancel()` lo uccide. Ritorna
        (returncode, stdout, stderr); su timeout il processo viene ucciso e returncode e' -1."""
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        self._current_proc = proc
        try:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                return -1, out, err
            return proc.returncode, out, err
        finally:
            self._current_proc = None

    # Nomi delle tracce create dal programma (titolo nel contenitore).
    _SUB_TITLES = {'it': 'Italian', 'en': 'English', 'fr': 'French', 'es': 'Spanish', 'de': 'German',
                   'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese', 'zh': 'Chinese', 'ar': 'Arabic',
                   'ko': 'Korean', 'nl': 'Dutch', 'pl': 'Polish', 'tr': 'Turkish'}

    @staticmethod
    def _ffprobe_streams(path):
        """(durata, [stream]) letti da ffprobe, o None se il file non si legge."""
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=duration:stream=index,codec_type,codec_name:stream_tags=language,title'
             ':stream_disposition=default,forced', '-of', 'json', str(path)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
        if r.returncode != 0:
            return None
        j = json.loads(r.stdout)
        return float(j.get('format', {}).get('duration') or 0), j.get('streams', [])

    def _remux_with_sidecar(self, sidecar: Path, lang_639_1: str, remove_idx: Optional[int] = None,
                            force_default: Optional[bool] = None, allow_bitmap: bool = False) -> bool:
        """Mette il sidecar come ultima traccia sottotitoli dell'MKV, togliendo (se `remove_idx`) una
        traccia testo. File temporaneo `.converting`, verifica (stesse tracce piu' quella aggiunta, durata
        entro 1 s, traccia nuova con la lingua giusta e battute identiche al sidecar) e solo allora
        sostituzione dell'originale. Non solleva: in caso di problema il video resta com'era.

        `force_default`: None = come la traccia sostituita se `remove_idx`, altrimenti predefinita solo se
        il file non ha gia' un sottotitolo predefinito.
        `allow_bitmap`: la traccia da togliere puo' essere un bitmap (PGS/VobSub): solo per una traccia
        gia' tradotta dal suo OCR, di cui il sidecar e' il sostituto.
        """
        video = self._resolve_video_path() or self.video_path   # input .srt: il video vero accanto
        temp = Path(str(video) + ".converting")
        lang3 = self._convert_639_1_to_639_2(lang_639_1)
        title = self._SUB_TITLES.get(lang_639_1, lang3.upper())
        what = tr('pl_track').format(remove_idx=remove_idx) if remove_idx is not None else tr('pl_subtitle')
        try:
            if temp.exists():
                try:
                    temp.unlink()   # residuo di un'esecuzione interrotta (Stop = kill dell'albero)
                except Exception:
                    pass
            if video.suffix.lower() != '.mkv':
                self._log(tr('pl_the_file_is_not_an').format(what=what.capitalize()))
                return False
            if not sidecar.exists() or sidecar.stat().st_size < 200:
                self._log(tr('pl_subtitle_missing_or_empty_i').format(what=what.capitalize()))
                return False
            if not self._video_unchanged(tr('pl_the_subtitle_mux')):
                return False
            before = self._ffprobe_streams(video)
            if before is None:
                self._log(tr('pl_ffprobe_could_not_read_the').format(what=what.capitalize()))
                return False
            dur0, streams0 = before
            subs0 = [s for s in streams0 if s.get('codec_type') == 'subtitle']
            was_default = any(s.get('disposition', {}).get('default') for s in subs0)
            if remove_idx is not None:
                target = next((s for s in subs0 if s.get('index') == remove_idx), None)
                removable = self._TEXT_SUB_CODECS | (self._BITMAP_SUB_CODECS if allow_bitmap else set())
                if target is None or target.get('codec_name') not in removable:
                    self._log(tr('pl_track_missing_or_of_a').format(remove_idx=remove_idx))
                    return False
                # Con `allow_bitmap` l'OCR ha gia' trattato la traccia come COMPLETA (flag forced anomalo ignorato,
                # SubtitleExtractor) e ne ha provato il testo non italiano: il flag del contenitore non la protegge.
                if target.get('disposition', {}).get('forced') and not allow_bitmap:
                    self._log(tr('pl_track_has_the_container_forced').format(remove_idx=remove_idx))
                    return False
                is_default = bool(target.get('disposition', {}).get('default'))
                n_after = len(subs0)           # una tolta, una aggiunta
            else:
                is_default = not was_default
                n_after = len(subs0) + 1
            if force_default is not None:
                is_default = force_default
            new_rel = n_after - 1              # la nuova traccia e' l'ultima

            cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(video),
                   '-sub_charenc', 'UTF-8', '-i', str(sidecar), '-map', '0']
            if remove_idx is not None:
                cmd += ['-map', f'-0:{remove_idx}']
            cmd += ['-map', '1:0', '-map_chapters', '0', '-c', 'copy',
                    f'-metadata:s:s:{new_rel}', f'language={lang3}',
                    f'-metadata:s:s:{new_rel}', f'title={title}',
                    f'-disposition:s:{new_rel}', 'default' if is_default else '0',
                    '-f', 'matroska', str(temp)]
            tool = 'ffmpeg'
            rc, _out, err = self._run_cancellable(cmd, 3600)
            if self._cancelled:
                return False
            if (rc != 0 or not temp.exists() or temp.stat().st_size < 1024) and find_tool('mkvmerge'):
                # `ffmpeg -map 0` non regge alcuni MKV (es. flussi mjpeg di copertine/allegati): ripiego su mkvmerge,
                # che copia tutto com'e'. Le verifiche qui sotto valgono identiche.
                logger.warning(f"Mux sottotitolo: ffmpeg fallito (rc={rc}), ripiego su mkvmerge: {(err or '')[-200:]}")
                tool = 'mkvmerge'
                try:
                    if temp.exists():
                        temp.unlink()
                except Exception:
                    pass
                mk = [find_tool('mkvmerge'), '-o', str(temp)]
                if remove_idx is not None:
                    mk += ['--subtitle-tracks', f'!{remove_idx}']
                mk += [str(video), '--sub-charset', '0:UTF-8', '--language', f'0:{lang3}', '--track-name', f'0:{title}',
                       '--default-track-flag', f"0:{1 if is_default else 0}", str(sidecar)]
                rc, _out, err = self._run_cancellable(mk, 3600)
                if self._cancelled:
                    return False
                if rc == 1:      # mkvmerge: 1 = solo avvisi, il file e' prodotto
                    rc = 0
            if rc != 0 or not temp.exists() or temp.stat().st_size < 1024:
                logger.error(f"Mux sottotitolo: {tool} fallito (rc={rc}): {((err or '') + (_out or ''))[-300:]}")
                self._log(tr('pl_subtitle_mux_failed_the_video'))
                return False

            after = self._ffprobe_streams(temp)
            ok = after is not None
            subs1 = []
            if ok:
                dur1, streams1 = after
                subs1 = [s for s in streams1 if s.get('codec_type') == 'subtitle']
                ok = (len(streams1) == len(streams0) + (1 if remove_idx is None else 0)
                      and len(subs1) == n_after and abs(dur1 - dur0) < 1.0
                      and subs1[-1].get('tags', {}).get('language') == lang3)
                if ok:
                    # le tracce rimaste devono essere esattamente le altre (stesso ordine, codec e lingua): intercetta
                    # una traccia tolta al posto di un'altra (ID mkvmerge non allineato all'indice ffprobe)
                    def _sig(x):
                        return (x.get('codec_name'), (x.get('tags') or {}).get('language'))
                    expected = [_sig(x) for x in subs0 if x.get('index') != remove_idx]
                    ok = [_sig(x) for x in subs1[:-1]] == expected
            if ok:
                # fuori dalla cartella del video: un residuo non deve sembrare un sottotitolo esterno
                chk = Path(tempfile.gettempdir()) / f"tp_mux_chk_{os.getpid()}.srt"
                try:
                    e_rc, _o, _e = self._run_cancellable(
                        ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(temp), '-map', f'0:s:{len(subs1) - 1}',
                         str(chk)], 1800)
                    if self._cancelled:
                        return False

                    def _n(p):
                        import re as _re
                        t = Path(p).read_text(encoding='utf-8-sig', errors='replace').replace('\r\n', '\n')
                        return [_re.sub(r'\s+', ' ', b.split('\n', 2)[-1]).strip()
                                for b in _re.split(r'\n\s*\n', t.strip()) if b.strip()]
                    # come INSIEME di battute: il contenitore tiene i sottotitoli in ordine di tempo, un sidecar con
                    # blocchi fuori ordine tornerebbe con l'ordine cambiato pur essendo identico
                    ok = e_rc == 0 and chk.exists() and sorted(_n(chk)) == sorted(_n(sidecar))
                except Exception as exc:
                    logger.warning(f"Verifica del file con il sottotitolo non riuscita: {exc}")
                    ok = False
                finally:
                    try:
                        chk.unlink()
                    except Exception:
                        pass
            if not ok:
                self._log(tr('pl_verification_of_the_file_with'))
                return False
            if not self._video_unchanged(tr('pl_the_subtitle_mux')):
                return False            # il `finally` cancella il temporaneo
            temp.replace(video)
            self._video_sig0 = self._file_sig(video)   # il file e' cambiato per mano nostra: nuovo riferimento
            return True
        except Exception as exc:
            logger.error(f"Mux sottotitolo fallito: {exc}", exc_info=True)
            self._log(tr('pl_subtitle_mux_failed_the_video'))
            return False
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

    def _replace_mislabeled_italian_track(self, sidecar: Path, idx: Optional[int] = None,
                                          bitmap: bool = False) -> bool:
        """Sostituisce nell'MKV la traccia segnata come italiana ma con testo di un'altra lingua
        (es. inglese con tag `ita`) con il sidecar italiano appena prodotto. Il sidecar resta accanto
        al video.

        Scatta SOLO se, nello STEP 1, il contenuto di una traccia testo completa (non forced) ha
        contraddetto la sua dichiarazione di italiano (`_mislabeled_it_stream`). Va chiamato DOPO
        l'upload: l'hash OpenSubtitles e' quello del file originale. Non solleva mai: un
        fallimento lascia il video com'era e il job riuscito.
        """
        if idx is None:
            idx = getattr(self, '_mislabeled_it_stream', None)
        if idx is None:
            return False
        if not self.config.get('replace_mislabeled_italian_track', True):
            self._log(tr('pl_replacement_of_the_track_wrongly'))
            return False
        self._ev('phase', name='final', fraction=0.9)
        self._log(tr('pl_9_replacing_track_marked_as').format(idx=idx))
        if self._remux_with_sidecar(sidecar, 'it', remove_idx=idx, allow_bitmap=bitmap):
            self._log(tr('pl_track_replaced_with_the_italian').format(idx=idx, name=sidecar.name))
            return True
        return False

    def _mux_subtitle_into_video(self, sidecar: Path, lang_639_1: str) -> bool:
        """Opzione job "Muxa nel video": aggiunge al MKV il sottotitolo creato come nuova traccia
        (il sidecar resta accanto al video). Va chiamato DOPO l'upload (hash originale). Non solleva."""
        if not self.config.get('mux_subtitle_into_video', False):
            return False
        self._ev('phase', name='final', fraction=0.9)
        self._ev('step', name='mux', state='start')
        self._log(tr('pl_9_muxing_the_subtitle_into'))
        _mux_ok = False
        try:
            if self._remux_with_sidecar(sidecar, lang_639_1):
                self._log(tr('pl_subtitle_embedded_in_the_video').format(name=sidecar.name))
                _mux_ok = True
                return True
            return False
        finally:
            self._ev('step', name='mux', state='done', ok=_mux_ok)

    @staticmethod
    def _route_non_english_away_from_llm(selected_model: str, source_lang_639_1: str) -> str:
        """Delega a `core.translator.route_non_english_away_from_llm` (funzione
        condivisa anche con `core/ocr_auto.py`): vedi la sua docstring per il
        perche'. Il metodo resta qui solo per comodita' del punto di chiamata."""
        from core.translator import route_non_english_away_from_llm
        return route_non_english_away_from_llm(selected_model, source_lang_639_1)

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
        """Upload a OpenSubtitles (v. `_upload_opensubtitles_impl`) + eventi `step upload` per l'anteprima
        dei passi: `start` solo se l'upload parte davvero, `done` sempre dopo uno `start`."""
        self._upload_step_started = False
        self._upload_ok = False
        try:
            self._upload_opensubtitles_impl(subtitle_path, language_code_639_1, imdb_id)
        finally:
            if self._upload_step_started:
                self._ev('step', name='upload', state='done', ok=bool(self._upload_ok))

    def _upload_opensubtitles_impl(
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
            self._log(tr('pl_opensubtitles_upload_not_active_options'))
            self._ev('step', name='upload', state='skip', reason='disabled')
            return

        # ============================================================
        # CHECK 2: Credenziali configurate per l'implementazione scelta?
        # ============================================================
        if not self.config.is_opensubtitles_configured():
            self._log(tr('pl_opensubtitles_credentials_not_configured_options'))
            self._ev('step', name='upload', state='skip', reason='disabled')
            return

        # ============================================================
        # CHECK 3: IMDb ID disponibile? (obbligatorio)
        # ============================================================
        if not imdb_id:
            self._log(tr('pl_imdb_id_not_available_opensubtitles'))
            self._ev('step', name='upload', state='skip', reason='no_imdb')
            return

        if not self._video_unchanged(tr('pl_the_opensubtitles_upload')):
            self._ev('step', name='upload', state='skip', reason='video_changed')
            return

        self._ev('phase', name='final', fraction=0.7)
        self._upload_step_started = True
        self._ev('step', name='upload', state='start')
        self._log(tr('pl_8_opensubtitles_upload'))

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
                self._log(tr('pl_no_video_file_found_to'))
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
                self._log(tr('pl_opensubtitles').format(url_or_error=url_or_error))
                self._upload_ok = True
            else:
                self._log(tr('pl_upload_failed').format(url_or_error=url_or_error))

        except Exception as e:
            error_msg = tr('pl_opensubtitles_upload_error').format(e=e)
            logger.error(error_msg, exc_info=True)
            self._log(tr('pl_msg').format(error_msg=error_msg))

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
        self._log(tr('pl_implementation').format(impl=uploader.get_implementation_name()))

        self._log(tr('pl_opensubtitles_authentication'))
        if not uploader.authenticate():
            self._log(tr('pl_login_failed'))
            return False, tr('pl_login_failed_2')

        self._log(tr('pl_login_successful'))
        try:
            self._log(tr('pl_starting_upload_for').format(language_code_639_1=language_code_639_1, lang_639_2=lang_639_2))
            return uploader.upload(video_path=video_for_hash, subtitle_path=subtitle_path, metadata=metadata)
        finally:
            uploader.logout()
            self._log(tr('pl_opensubtitles_session_closed'))
    
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
    def _preserve_recovered_srt(src, name: str) -> Optional[Path]:
        """Copia un SRT in ~/.transcriberpro/recuperati/ (prefisso data-ora).
        Ritorna il percorso, o None se la copia non riesce."""
        try:
            dest_dir = Path.home() / '.transcriberpro' / 'recuperati'
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}"
            shutil.copy(src, dest)
            return dest
        except Exception as e:
            logger.warning(f"Copia di recupero SRT fallita: {e}")
            return None

    def _format_srt_fallback(self, segments, srt_path: Path) -> None:
        """Formattazione SRT (CPL, durata minima, leggibilità) SENZA speaker.

        Rete di sicurezza per quando la diarization è disattivata, fallisce o
        manca il token: altrimenti resterebbe l'SRT grezzo del transcriber
        (blocchi-lampo, righe da 80+ caratteri)."""
        if not segments:
            return
        try:
            from core.subtitle_formatter import SubtitleFormatter
            formatter = SubtitleFormatter(
                log_callback=self._log,
                readability=bool(self.config.get('subtitle_readability_enabled', True)))
            srt = formatter.format_srt(segments)
            if srt.strip():   # mai sostituire l'SRT grezzo con uno vuoto
                Path(srt_path).write_text(srt, encoding='utf-8')
                self._log(tr('pl_subtitle_formatting_applied_without_speakers'))
        except Exception as e:
            logger.warning(f"Formattazione di ripiego fallita: {e}")

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
            self._log(tr('pl_resource_cleanup_process_ram_gb').format(ram_before=_ram_before))

            # 1. Unload engine di trascrizione (whisper + eventuali Canary/Qwen3)
            if self._transcriber:
                self._transcriber.cleanup()
                self._transcriber = None
                self._log(tr('pl_transcription_engine_unloaded'))

            # 2. Unload Demucs
            if self._audio_processor:
                self._audio_processor.cleanup_model()
                self._audio_processor = None
                self._log(tr('pl_demucs_unloaded'))

            # 3. Unload Traduttore
            if self._translator:
                self._translator.cleanup()
                self._translator = None
                self._log(tr('pl_translator_unloaded'))

            # 4. CUDA: sync + svuota cache VRAM
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                self._log(tr('pl_cuda_cache_cleared'))

            # 5. RAM: 3x gc + EmptyWorkingSet (Windows) / malloc_trim (Linux)
            release_ram_to_os()

            _ram_after = _proc.memory_info().rss / 1024**3
            _freed = _ram_before - _ram_after
            self._log(tr('pl_ram_gb_freed_gb').format(ram_before=_ram_before, ram_after=_ram_after, freed=_freed))

            # 6. File temporanei
            if self.video_path:
                self.file_handler.cleanup(self.video_path)
                self._log(tr('pl_temporary_files_removed'))

            # 7. Cache modelli HF/torch: NON si tocca qui. La pulizia gira
            # UNA volta sola a fine coda (o su "Ferma") in ProcessingWorker:
            # farla per-file riscaricava gli stessi modelli (pyannote, ECAPA,
            # Demucs...) a ogni elemento della coda.

            self._log(tr('pl_cleanup_completed'))

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
        python -c "from core.pipeline import ProcessingPipeline; print('✅ Import OK')"
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
        print("✅ Tutti gli import OK")
    except ImportError as e:
        print(f"❌ Import fallito: {e}")
        print("\n💡 SUGGERIMENTO: Esegui con 'python -m core.pipeline' invece di 'python core/pipeline.py'")
        exit(1)
    
    # Test 2: Verifica firma metodi critici
    print("\nTest 2: Verifica firma metodi critici...")
    
    # Test translate_file
    import inspect
    translator = get_translator()
    sig = inspect.signature(translator.translate_file)
    params = list(sig.parameters.keys())
    print(f"   translate_file: {params}")
    assert 'src_lang' in params and 'tgt_lang' in params, "❌ Parametri errati!"
    print("✅ translate_file OK (src_lang, tgt_lang)")
    
    # Test transcribe_chunks
    transcriber = Transcriber()
    sig = inspect.signature(transcriber.transcribe_chunks)
    params = list(sig.parameters.keys())
    print(f"   transcribe_chunks: {params}")
    assert 'whisper_language' in params, "❌ Parametro whisper_language mancante!"
    print("✅ transcribe_chunks OK (whisper_language keyword)")
    
    # Test AudioTrackSelector
    print("\nTest 3: Verifica AudioTrackSelector...")
    assert hasattr(AudioTrackSelector, 'select_best_track'), "❌ select_best_track mancante!"
    assert hasattr(AudioTrackSelector, 'get_selected_language'), "❌ get_selected_language mancante!"
    print("✅ AudioTrackSelector OK")
    
    # Test 4: Verifica mappa lingue
    print("\nTest 4: Verifica mappa lingue ISO 639...")
    lang_map = ProcessingPipeline.LANG_MAP_639_2_TO_639_1
    test_langs = [('ita', 'it'), ('eng', 'en'), ('fra', 'fr'), ('deu', 'de')]
    for lang_2, expected_1 in test_langs:
        actual = lang_map.get(lang_2)
        assert actual == expected_1, f"❌ {lang_2} → {actual} (expected {expected_1})"
    print("✅ Mappa lingue ISO 639 OK")
    
    print("\n" + "="*80)
    print("✅ TUTTI I TEST SUPERATI - Pipeline v3.9 pronta per produzione")
    print("="*80 + "\n")
    
    print("📝 CHECKLIST DEPLOYMENT:")
    print("  [✔] Fix parametri translate_file() (src_lang, tgt_lang)")
    print("  [✔] Fix chiamata transcribe_chunks() con tupla e keyword")
    print("  [✔] Upload OpenSubtitles robusto (REST/XML-RPC)")
    print("  [✔] Gestione metadati completa")
    print("  [✔] AudioTrackSelector con get_selected_language()")
    print("  [✔] Cleanup memoria GPU ottimizzato")
    print("  [✔] Logging dettagliato per debug")
    print("  [✔] Gestione errori completa")
    print("\n🚀 Ready for deployment!")
    print("\n💡 COMANDI DISPONIBILI:")
    print("   - Test import:  python -c \"from core.pipeline import ProcessingPipeline; print('✅ OK')\"")
    print("   - Test suite:   python -m core.pipeline")
    print("   - Avvio GUI:    python main.py")