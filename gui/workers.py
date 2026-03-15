# -*- coding: utf-8 -*-
"""
Processing Worker - FIX SINCRONIZZAZIONE CODA
File: gui/workers.py

VERSIONE: v3.5 - FIX CRITICO SINCRONIZZAZIONE CODA

CORREZIONI v3.5:
âœ… FIX CRITICO: Worker rimuove file dalla coda PRIMA di continuare il loop
âœ… Elimina race condition tra worker e UI
âœ… Garantisce elaborazione sequenziale corretta
âœ… Mutex condiviso tra worker e UI

NOVITÃ€ RISPETTO A v3.4:
âœ… Worker rimuove file completato dalla coda in modo sincrono
âœ… Segnale file_completed serve solo per aggiornare UI
âœ… Nessuna dipendenza dall'UI per gestione coda
âœ… Elaborazione robusta e prevedibile

FUNZIONALITÃ€ MANTENUTE:
âœ… Coda condivisa thread-safe con MainWindow
âœ… Supporto aggiunta file DURANTE elaborazione
âœ… Gestione errori robusta
âœ… Cleanup corretto dopo ogni file
âœ… Segnale per file completato
âœ… Cancellazione pulita
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from pathlib import Path
from typing import List, Optional

from core.pipeline import ProcessingPipeline
from utils.logger import setup_logger
from utils.translations import tr

logger = setup_logger()


class PosterLoaderWorker(QThread):
    """
    Worker thread per caricamento asincrono locandine TMDB
    Evita blocchi della GUI durante download poster
    """
    
    poster_loaded = pyqtSignal(object)  # Emette QPixmap o None
    poster_failed = pyqtSignal()
    
    def __init__(self, video_path: str, tmdb_client):
        """
        Args:
            video_path: Path completo del video
            tmdb_client: Istanza TMDBClient per API calls
        """
        super().__init__()
        self.video_path = video_path
        self.tmdb_client = tmdb_client
        self.is_cancelled = False
    
    def run(self):
        """Carica poster in background"""
        try:
            if self.is_cancelled:
                return
            
            video_name = Path(self.video_path).stem
            logger.debug(f"PosterLoader: Caricamento info per '{video_name}'")
            
            # API call TMDB (1-2 sec)
            media_info = self.tmdb_client.get_media_info(video_name)
            
            if self.is_cancelled:
                return
            
            if media_info and 'poster_path' in media_info and media_info['poster_path']:
                poster_path = media_info['poster_path']
                
                # Download poster (1-3 sec)
                poster_local_path = self.tmdb_client.download_poster(
                    poster_path, 
                    media_info['title']
                )
                
                if self.is_cancelled:
                    return
                
                if poster_local_path and poster_local_path.exists():
                    from PyQt6.QtGui import QPixmap
                    pixmap = QPixmap(str(poster_local_path))
                    
                    if not pixmap.isNull():
                        logger.debug(f"✅ Poster caricato: {media_info['title']}")
                        self.poster_loaded.emit(pixmap)
                        return
            
            # Nessun poster trovato
            logger.debug(f"⚠️ Nessun poster disponibile per '{video_name}'")
            self.poster_failed.emit()
            
        except Exception as e:
            logger.error(f"❌ Errore caricamento poster: {e}")
            self.poster_failed.emit()
    
    def cancel(self):
        """Cancella caricamento in corso"""
        self.is_cancelled = True


class ProcessingWorker(QThread):
    """
    Worker thread per elaborazione video
    Con supporto per aggiunta dinamica file e sincronizzazione corretta coda
    """
    
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    file_completed = pyqtSignal(str)  # Emesso dopo ogni file completato (per aggiornare UI)
    error = pyqtSignal(str)  # Emesso in caso di errore critico
    queue_updated = pyqtSignal(int)  # Emesso quando coda cambia (nuovo total)
    
    def __init__(self, processing_queue: List[str], queue_mutex: QMutex):
        """
        Args:
            processing_queue: RIFERIMENTO alla lista condivisa (non copia!)
            queue_mutex: Mutex condiviso con MainWindow per thread-safety
        """
        super().__init__()
        
        # ========================================
        # v3.5: Coda CONDIVISA con mutex condiviso
        # ========================================
        self.processing_queue = processing_queue  # âœ… Riferimento condiviso
        self.queue_mutex = queue_mutex  # âœ… Mutex condiviso con UI
        
        self.is_cancelled = False
        self.pipeline = None
        
        # Contatori per statistiche
        self.completed_files = 0
        self.failed_files = 0
        self.total_files_at_start = 0
    
    def get_total_files(self) -> int:
        """
        Ottiene totale file in coda in modo thread-safe
        
        Returns:
            Numero file in coda
        """
        with QMutexLocker(self.queue_mutex):
            return len(self.processing_queue)
    
    def get_and_remove_next_file(self) -> Optional[str]:
        """
        âœ… v3.5: Ottiene E RIMUOVE primo file dalla coda in modo atomico thread-safe
        
        IMPORTANTE: Questa operazione Ã¨ atomica - prende E rimuove in un'unica operazione
        protetta dal mutex, eliminando race conditions.
        
        Returns:
            Path del prossimo file, o None se coda vuota
        """
        with QMutexLocker(self.queue_mutex):
            if len(self.processing_queue) > 0:
                # âœ… ATOMICO: Prendi E rimuovi in una sola operazione
                file_path = self.processing_queue[0]
                self.processing_queue.pop(0)
                return file_path
            return None
    
    def run(self):
        """
        Esegue elaborazione con supporto aggiunta dinamica file
        
        CARATTERISTICHE v3.5:
        - Prende E rimuove atomicamente il primo elemento dalla coda
        - Elimina race condition con UI
        - Continua finchè coda non Ã¨ vuota
        - Thread-safe con QMutex condiviso
        """
        # Salva il totale iniziale per statistiche
        self.total_files_at_start = self.get_total_files()
        self.log_message.emit(tr('worker_start').format(n=self.total_files_at_start))
        
        # ========================================
        # LOOP DINAMICO v3.5: Prende e rimuove atomicamente
        # ========================================
        while not self.is_cancelled:
            # âœ… OPERAZIONE ATOMICA: Prendi E rimuovi file dalla coda
            video_path = self.get_and_remove_next_file()
            
            # Se non ci sono più file, termina
            if video_path is None:
                break
            
            filename = Path(video_path).name
            files_processed = self.completed_files + self.failed_files
            
            # Log progresso
            self.log_message.emit(
                f"\n{'='*70}\n"
                f"{tr('worker_file_header').format(current=files_processed+1, total=self.total_files_at_start, filename=filename)}\n"
                f"{'='*70}"
            )
            
            # Elabora file
            success = self._process_single_file(video_path)
            
            if success:
                self.completed_files += 1
                # Emetti segnale per aggiornare UI (file giÃ  rimosso dalla coda)
                self.file_completed.emit(video_path)
            else:
                self.failed_files += 1
            
            # Calcola progresso basato su file elaborati vs totale iniziale
            files_processed = self.completed_files + self.failed_files
            progress_percentage = int((files_processed / self.total_files_at_start) * 100)
            self.progress.emit(progress_percentage)
            
            # Emetti aggiornamento coda (per UI)
            remaining = self.get_total_files()
            self.queue_updated.emit(remaining)
        
        # Log finale
        if self.is_cancelled:
            self.log_message.emit(tr('worker_cancelled_user'))
        else:
            self.log_message.emit(
                f"\n{'='*70}\n"
                f"{tr('worker_done_header')}\n"
                f"{tr('worker_stats_completed').format(n=self.completed_files)}\n"
                f"{tr('worker_stats_failed').format(n=self.failed_files)}\n"
                f"{tr('worker_stats_total').format(n=self.completed_files + self.failed_files)}\n"
                f"{'='*70}"
            )
        
        self.finished.emit()
    
    def _process_single_file(self, video_path: str) -> bool:
        """
        Elabora singolo file video
        
        Args:
            video_path: Path del file da elaborare
            
        Returns:
            True se successo, False altrimenti
        """
        filename = Path(video_path).name
        
        try:
            # Check cancellazione prima di iniziare
            if self.is_cancelled:
                return False
            
            # Crea pipeline
            self.pipeline = ProcessingPipeline(video_path)
            
            # Log callback
            def log_callback(msg):
                if not self.is_cancelled:
                    self.log_message.emit(msg)
            
            self.pipeline.set_log_callback(log_callback)
            
            # Elabora (SINGOLO TENTATIVO - NO RETRY)
            self.log_message.emit(tr('worker_start_single'))
            from utils.config import get_config
            target_language = get_config().get_target_language()
            success = self.pipeline.process(target_language=target_language)
            
            # Gestisci risultato
            if success and not self.is_cancelled:
                self.log_message.emit(tr('worker_completed').format(filename=filename))
                return True
            
            elif self.is_cancelled:
                self.log_message.emit(tr('worker_cancelled_file').format(filename=filename))
                return False
            
            else:
                self.log_message.emit(tr('worker_failed').format(filename=filename))
                self.log_message.emit(tr('worker_hint'))
                return False
            
        except Exception as e:
            # Errore critico
            error_msg = tr('worker_critical_error').format(filename=filename, error=str(e))
            self.log_message.emit(error_msg)
            logger.error(f"Critical error processing {video_path}: {e}", exc_info=True)
            
            # Emetti segnale errore
            self.error.emit(error_msg)
            
            return False
        
        finally:
            # CLEANUP OBBLIGATORIO dopo ogni file
            self._cleanup_pipeline()
    
    def _cleanup_pipeline(self):
        """
        Cleanup pipeline e risorse
        CHIAMATO SEMPRE dopo ogni file
        """
        try:
            if self.pipeline:
                logger.info("ðŸ§¹ Cleanup pipeline...")
                self.pipeline.cleanup()
                self.pipeline = None
                
                # Garbage collection esplicito
                import gc
                gc.collect()
                
                logger.info("âœ… Pipeline cleanup completato")
        except Exception as e:
            logger.error(f"❌ Errore durante cleanup: {e}")
