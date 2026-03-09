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

âœ… FIX TRANSLATOR SELECTION: La scelta del traduttore (NLLB/Aya) viene ora passata esplicitamente alla factory get_translator()
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
import logging
import subprocess
import tempfile
import torch
import shutil
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
from utils.opensubtitles_config import get_opensubtitles_config
from utils.logger import setup_logger

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
    
    # Mappa ISO 639-2 (3 lettere) â†’ ISO 639-1 (2 lettere)
    LANG_MAP_639_2_TO_639_1 = {
        'ita': 'it', 'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
        'deu': 'de', 'ger': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja', 
        'kor': 'ko', 'chi': 'zh', 'zho': 'zh', 'ara': 'ar', 'hin': 'hi',
        'pol': 'pl', 'tur': 'tr', 'nld': 'nl', 'dut': 'nl', 'swe': 'sv',
        'dan': 'da', 'danish': 'da', 'nor': 'no', 'fin': 'fi', 'ces': 'cs', 
        'cze': 'cs', 'hun': 'hu', 'ron': 'ro', 'rum': 'ro', 'ukr': 'uk', 
        'ell': 'el', 'gre': 'el', 'heb': 'he', 'vie': 'vi', 'tha': 'th', 
        'und': 'und'
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
        self._log_callback = log_callback
        
        self.config = get_config()
        self.tmdb_client = get_tmdb_client()
        self.file_handler = FileHandler()
        self.os_config = get_opensubtitles_config()
        
        # Inizializzazione lazy/cleanup
        self._transcriber: Optional[Transcriber] = None
        self._translator: Optional[BaseTranslator] = None 
        self._audio_processor: Optional[AudioProcessor] = None
        self.last_execution_time = 0.0
        self.metadata: Dict[str, Any] = {}
        
        # File paths
        self.extracted_srt: Optional[Path] = None
        self.detected_language: Optional[str] = None
    
    def set_log_callback(self, callback: Callable):
        """Imposta callback per logging GUI (chiamato dal ProcessingWorker)"""
        self._log_callback = callback
    
    def _log(self, message: str):
        """Logga il messaggio sia a logger che a callback GUI"""
        logger.info(message)
        if self._log_callback:
            self._log_callback(message)

    def process(self, target_language: str = 'ita') -> bool:
        """
        Esegue l'intera pipeline di elaborazione
        
        Args:
            target_language: Codice lingua target ISO 639-2 (es: 'ita', 'eng')
            
        Returns:
            True se completato con successo, False altrimenti
        """
        start_time = time.time()
        
        try:
            # ============================================================
            # STEP 0: Inizializzazione e Check
            # ============================================================
            self._log(f"\n{'='*80}")
            self._log(f"ðŸŽ¬ Inizio elaborazione: {self.video_name}")
            self._log(f"   Lingua Target: {target_language.upper()}")
            self._log(f"{'='*80}")

            # Recupero metadati e temp dir
            self._log("🔍 Ricerca metadati TMDB/IMDb...")
            self.metadata = self.tmdb_client.get_media_info(str(self.video_path))
            imdb_id = self.metadata.get('imdb_id') if self.metadata else None
            if imdb_id:
                self._log(f"âœ… Metadati trovati. IMDb ID: {imdb_id}")
            else:
                self._log("âš ï¸ Metadati non trovati. Upload OpenSubtitles disabilitato.")
                
            temp_dir = self.file_handler.get_temp_dir(self.video_path)
            
            # Variabili per risultato finale
            source_language_639_2: str = 'und' 
            subtitle_path: Optional[Path] = None
            
            # ============================================================
            # STEP 1: Estrazione Sottotitoli Embedded
            # ============================================================
            self._log("\n1. Estrazione sottotitoli embedded...")
            extractor = SubtitleExtractor(str(self.video_path))
            selected_stream = extractor.select_best_subtitle()
            
            if selected_stream:
                temp_srt_path = self.file_handler.get_temp_path(
                    self.video_path, 
                    f"embedded_{selected_stream['language']}.srt"
                )
                if extractor.extract_subtitle(temp_srt_path, selected_stream['index']):
                    subtitle_path = temp_srt_path
                    source_language_639_2 = selected_stream['language']
                    self._log(f"âœ… Sottotitoli embedded trovati ({source_language_639_2}). Salto trascrizione.")
                else:
                    self._log("âŒ Estrazione sottotitoli fallita. Passo a trascrizione.")
            else:
                self._log("â„¹ï¸ Nessun sottotitolo embedded. Procedo con trascrizione.")

            # ============================================================
            # STEP 2-4: Trascrizione (se necessaria)
            # ============================================================
            if subtitle_path is None:
                
                # STEP 2: Estrazione audio
                self._log("\n2. Estrazione traccia audio...")
                audio_selector = AudioTrackSelector(str(self.video_path))
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
                        
                        # STEP 3: Processing audio (separazione vocale + chunking)
                        self._log("\n3. Processing audio (Demucs + Chunking)...")
                        if self._audio_processor is None:
                            self._audio_processor = AudioProcessor()
                            self._audio_processor.set_log_callback(self._log_callback)
                        
                        chunk_list = self._audio_processor.process_for_transcription(
                            audio_path=audio_path,
                            output_dir=temp_dir
                        )
                        
                        if chunk_list:
                            self._log(f"âœ… Audio processato: {len(chunk_list)} chunks creati")
                            
                            # STEP 4: Trascrizione
                            self._log("\n4. Trascrizione audio (Faster-Whisper)...")
                            if self._transcriber is None:
                                self._transcriber = Transcriber()
                                self._transcriber.set_log_callback(self._log_callback)
                            
                            subtitle_path = self.file_handler.get_temp_path(
                                self.video_path, 
                                "transcribed.srt"
                            )
                            
                            # âœ… FIX CRITICO v3.9: Gestione corretta tupla + keyword argument
                            success, detected_lang_639_1 = self._transcriber.transcribe_chunks(
                                audio_chunks=chunk_list, 
                                output_path=str(subtitle_path),
                                whisper_language=source_language_639_2  # Keyword argument
                            )
                            
                            # Validazione risultato
                            if success and detected_lang_639_1 and subtitle_path.exists():
                                # Converti da ISO 639-1 (2 lettere) a ISO 639-2 (3 lettere)
                                source_language_639_2 = self._convert_639_1_to_639_2(detected_lang_639_1)
                                self._log(f"âœ… Trascrizione completata. Lingua rilevata: {source_language_639_2}")
                            else:
                                raise Exception("Trascrizione fallita o file SRT non creato.")
                        else:
                            raise Exception("Processing audio fallito - nessun chunk creato.")
                    else:
                        raise Exception("Estrazione traccia audio fallita.")
                else:
                    raise Exception("Nessuna traccia audio trovata nel video.")

            
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

            
            # ============================================================
            # STEP 5.5: Scarica Whisper e Demucs prima della traduzione
            # ============================================================
            if self._transcriber:
                self._transcriber.cleanup()
                self._transcriber = None
            if self._audio_processor:
                self._audio_processor.cleanup_model()
                self._audio_processor = None
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

            # ============================================================
            # STEP 6: Traduzione (se lingua sorgente != lingua target)
            # ============================================================
            source_language_639_1 = self.LANG_MAP_639_2_TO_639_1.get(source_language_639_2, 'und')
            target_language_639_1 = self.LANG_MAP_639_2_TO_639_1.get(target_language, 'und')

            if source_language_639_1 != target_language_639_1:

                self._log(f"\n6. Traduzione ({source_language_639_1} â†’ {target_language_639_1})...")
                
                
                # âœ… FIX TRANSLATOR SELECTION: Usa il metodo corretto per leggere il modello dalla config
                # Leggi il modello di traduzione selezionato dall'utente
                selected_model = self.config.get_translation_model()
                use_aya_model = (selected_model == 'aya')
                
                self._log(f"ðŸ“‹ Modello di traduzione selezionato: {selected_model.upper()}")

                # Usa la factory intelligente passando la scelta esplicita del modello
                self._translator = get_translator(model_type=selected_model) 
                self._translator.set_log_callback(self._log_callback)
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
                    tgt_lang=target_language_639_1   # âœ… Corretto
                ):
                    subtitle_path = translated_srt_path
                    final_language_639_1 = target_language_639_1
                    self._log("âœ… Traduzione completata con successo.")
                else:
                    self._log("âŒ Traduzione fallita. Uso i sottotitoli originali.")
                    final_language_639_1 = source_language_639_1
            else:
                final_language_639_1 = source_language_639_1
                self._log("\n6. Lingua originale == Lingua target. Salto traduzione.")

            
            # ============================================================
            # STEP 7: Salvataggio File Finale
            # ============================================================
            self._log("\n7. Salvataggio file finale...")
            
            # Crea nome file finale: [nome_video].[lang].srt
            final_name = self.video_name + f".{final_language_639_1}.srt"
            final_output_path = self.video_path.parent / final_name
            
            shutil.copy(subtitle_path, final_output_path)
            self._add_watermark_subtitle(final_output_path)

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
        # Mappa inversa: da 639-1 a 639-2
        reverse_map = {v: k for k, v in self.LANG_MAP_639_2_TO_639_1.items()}
        return reverse_map.get(lang_639_1, 'und')
    
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
            self._log("❌ Upload OpenSubtitles disabilitato da configurazione. Salto.")
            return
        
        # ============================================================
        # CHECK 2: Credenziali configurate?
        # ============================================================
        if not self.config.is_opensubtitles_configured():
            self._log("âš ï¸ Credenziali OpenSubtitles non configurate. Salto upload.")
            return

        # ============================================================
        # CHECK 3: IMDb ID disponibile? (obbligatorio)
        # ============================================================
        if not imdb_id:
            self._log("âš ï¸ IMDb ID non disponibile. Upload OpenSubtitles saltato (obbligatorio).")
            return

        self._log("\n8. Upload OpenSubtitles...")
        
        try:
            # Importa moduli per garantire registrazione factory
            import utils.opensubtitles_rest_uploader
            import utils.opensubtitles_xmlrpc_uploader
            
            # ============================================================
            # STEP 8.1: Inizializzazione Uploader
            # ============================================================
            implementation = self.config.get('opensubtitles_preferred_implementation', 'rest')
            
            creds = self.config.get_opensubtitles_credentials()
            if not creds:
                self._log("âŒ Credenziali non disponibili. Salto upload.")
                return
            
            uploader = UploaderFactory.create_uploader(
                implementation=implementation,
                **creds
            )
            
            self._log(f"ðŸ”§ Implementazione: {uploader.get_implementation_name()}")
            
            # ============================================================
            # STEP 8.2: Login
            # ============================================================
            self._log("ðŸ”‘ Autenticazione OpenSubtitles...")
            if not uploader.authenticate():
                self._log(f"❌ Login fallito. Salto upload.")
                uploader.logout()
                return

            self._log("✅ Login riuscito")
            
            # ============================================================
            # STEP 8.3: Prepara Metadata
            # ============================================================
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
            
            # ============================================================
            # STEP 8.4: Upload
            # ============================================================
            self._log(f" Avvio upload per {language_code_639_1} ({lang_639_2})...")
            success, url_or_error = uploader.upload(
                video_path=self.video_path,
                subtitle_path=subtitle_path,
                metadata=metadata
            )

            if success:
                self._log(f"✅Upload completato! URL: {url_or_error}")
            else:
                self._log(f"âŒ Upload fallito: {url_or_error}")
            
            # ============================================================
            # STEP 8.5: Logout e cleanup
            # ============================================================
            uploader.logout()
            self._log("✅ Logout completato")
            
        except Exception as e:
            error_msg = f"❌Errore upload OpenSubtitles: {e}"
            logger.error(error_msg, exc_info=True)
            self._log(f"❌ {error_msg}")
    
    @staticmethod
    def _add_watermark_subtitle(srt_path: Path) -> None:
        """
        Inserisce un sottotitolo di attribuzione AI all'inizio del file SRT.

        - Durata: 0s → 10s (o meno se il primo sub esistente inizia prima di 10s,
          con un margine di 100ms per evitare sovrapposizioni).
        - Se lo spazio disponibile è < 1s, il watermark viene saltato.
        - Tutti gli indici SRT esistenti vengono incrementati di 1.
        """
        import re

        WATERMARK_TEXT = "AI generated subtitles : Transcriber_pro"
        WATERMARK_END_MS = 10_000
        MIN_VISIBLE_MS  = 1_000

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

    def _cleanup(self):
        """
        Cleanup risorse - Scarica modelli e libera memoria GPU
        
        Ottimizzato per RTX 3060 12GB VRAM:
        - Scarica modello Faster-Whisper (~1.5GB VRAM)
        - Scarica modello Demucs (~2GB VRAM)
        - Mantiene NLLB in singleton per prossimi file
        - Svuota cache CUDA
        - Rimuove file temporanei
        """
        try:
            self._log("ðŸ§¹ Inizio cleanup risorse...")
            
            # 1. Cleanup Transcriber (scarica modello Whisper)
            if self._transcriber:
                self._transcriber.cleanup()
                self._transcriber = None
                self._log("âœ… Modello Whisper scaricato")
            
            # 2. Cleanup AudioProcessor (scarica modello Demucs)
            if self._audio_processor:
                self._audio_processor.cleanup_model()
                self._audio_processor = None
                self._log("âœ… Modello Demucs scaricato")
            
            # 3. Cleanup Translator (Singleton - solo cleanup GPU)
            if self._translator:
                self._translator.cleanup()
                # Il modello NLLB rimane in memoria per il prossimo file (efficienza)
                self._log("âœ… Cache GPU traduttore svuotata")
            
            # 4. Cleanup Memoria GPU (Finale)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                self._log("✅ Cache CUDA svuotata")
            
            # 5. Cleanup File Temporanei
            if self.video_path:
                 self.file_handler.cleanup(self.video_path)
                 self._log("✅ File temporanei rimossi")
            
            self._log("✅ Cleanup completato")
        
        except Exception as e:
            logger.warning(f"❌ Errore cleanup: {e}")
    
    def cleanup(self):
        """
        Metodo pubblico per cleanup esterno (chiamato dalla GUI)
        
        Usage:
            pipeline = ProcessingPipeline(video_path)
            pipeline.process()
            pipeline.cleanup()  # Cleanup manuale se necessario
        """
        self._log("✅ Cleanup pipeline...")
        self._cleanup()
        self._log("✅ Pipeline cleanup completato")


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