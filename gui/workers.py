# -*- coding: utf-8 -*-
"""
Processing Worker - FIX SINCRONIZZAZIONE CODA
File: gui/workers.py

VERSIONE: v3.5 - FIX CRITICO SINCRONIZZAZIONE CODA

CORREZIONI v3.5:
✅ FIX CRITICO: Worker rimuove file dalla coda PRIMA di continuare il loop
✅ Elimina race condition tra worker e UI
✅ Garantisce elaborazione sequenziale corretta
✅ Mutex condiviso tra worker e UI

NOVITÀ RISPETTO A v3.4:
✅ Worker rimuove file completato dalla coda in modo sincrono
✅ Segnale file_completed serve solo per aggiornare UI
✅ Nessuna dipendenza dall'UI per gestione coda
✅ Elaborazione robusta e prevedibile

FUNZIONALITÀ MANTENUTE:
✅ Coda condivisa thread-safe con MainWindow
✅ Supporto aggiunta file DURANTE elaborazione
✅ Gestione errori robusta
✅ Cleanup corretto dopo ogni file
✅ Segnale per file completato
✅ Cancellazione pulita
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import re

from core.jobs.file_runner import FileHooks, FileRunner, kill_tree
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
            # nome COMPLETO (con estensione): parse_filename fa gia' .stem, un secondo .stem toglierebbe
            # il suffisso finale ('.E26' in 'Titolo.E26') e il nome verrebbe cercato come film
            media_info = self.tmdb_client.get_media_info(Path(self.video_path).name)
            
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


def format_file_size(nbytes: float) -> str:
    """500 → '500 B', 1536 → '2 KB', ... Stringa vuota per valori negativi."""
    if nbytes < 0:
        return ''
    s = float(nbytes)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if s < 1024:
            return f'{s:.0f} {unit}'
        s /= 1024
    return f'{s:.1f} TB'


class FileSizeWorker(QThread):
    """Calcola le dimensioni file in background.

    Path.stat() sul thread GUI blocca l'interfaccia per secondi quando i
    file stanno su share SMB con dischi NAS in standby (spin-up 5-15s):
    gli item vengono creati subito senza size, che arriva appena pronta.
    """

    size_ready = pyqtSignal(str, str)   # (path, size leggibile es. "2 GB")

    def __init__(self, paths: List[str], parent=None):
        super().__init__(parent)
        self._paths = list(paths)

    def run(self):
        for p in self._paths:
            try:
                size = format_file_size(Path(p).stat().st_size)
            except Exception:
                size = ''
            self.size_ready.emit(p, size)


class FolderScanWorker(QThread):
    """Enumera ricorsivamente i video di una cartella in background.

    rglob() sul thread GUI congela l'interfaccia per l'intera scansione
    dell'albero SMB. Emette un file alla volta (path + size già calcolata
    qui, siamo già fuori dal thread GUI) e il totale a fine scansione.
    """

    file_found = pyqtSignal(str, str)   # (path, size leggibile)
    scan_done = pyqtSignal(int)         # file trovati in totale

    def __init__(self, folder: str, extensions: List[str], parent=None):
        super().__init__(parent)
        self._folder = folder
        self._exts = [e.lower() for e in extensions]
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        found = 0
        try:
            for f_path in Path(self._folder).rglob('*'):
                if self._cancelled:
                    break
                if f_path.suffix.lower() not in self._exts:
                    continue
                try:
                    size = format_file_size(f_path.stat().st_size)
                except Exception:
                    size = ''
                found += 1
                self.file_found.emit(str(f_path), size)
        except Exception as e:
            logger.warning(f"FolderScanWorker: errore scansione: {e}")
        self.scan_done.emit(found)


class ProcessingWorker(QThread):
    """
    Worker thread per elaborazione video
    Con supporto per aggiunta dinamica file e sincronizzazione corretta coda
    """
    
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    file_completed = pyqtSignal(str)
    file_failed = pyqtSignal(str)          # (file_path) — emesso quando pipeline ritorna False
    file_started = pyqtSignal(str)         # (file_path)
    file_progress = pyqtSignal(str, int)   # (file_path, percent 0-100)
    file_steps = pyqtSignal(str, object)   # (file_path, PipelineSnapshot): anteprima dei passi (gui/services/step_plan.py)
    file_history_entry = pyqtSignal(dict)  # emesso dopo ogni file completato con successo
    error = pyqtSignal(str)
    queue_updated = pyqtSignal(int)
    
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
        self.processing_queue = processing_queue  # ✅ Riferimento condiviso
        self.queue_mutex = queue_mutex  # ✅ Mutex condiviso con UI
        
        self.is_cancelled = False
        self._current_proc = None     # subprocess pipeline_cli in corso (isolamento)
        self.job_overrides = {}       # {path: eccezioni}: dizionario di QueueService (stesso mutex); vuoto se il worker e' usato da solo
        self._current_overrides = {}  # eccezioni del file in lavorazione, prese insieme al file

        # Contatori per statistiche
        self.completed_files = 0
        self.failed_files = 0
        self.total_files_at_start = 0
    
    def note_removed(self, n: int = 1):
        """Un file ancora in attesa e' stato tolto dalla coda mentre il worker lavora: il totale usato per la percentuale e per
        l'intestazione 'File N/totale' scende di n (altrimenti la barra non arriva piu' al 100%)."""
        self.total_files_at_start = max(1, self.total_files_at_start - n)

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
        ✅ v3.5: Ottiene E RIMUOVE primo file dalla coda in modo atomico thread-safe
        
        IMPORTANTE: Questa operazione è atomica - prende E rimuove in un'unica operazione
        protetta dal mutex, eliminando race conditions.
        
        Returns:
            Path del prossimo file, o None se coda vuota
        """
        with QMutexLocker(self.queue_mutex):
            if len(self.processing_queue) > 0:
                # ✅ ATOMICO: Prendi E rimuovi in una sola operazione
                file_path = self.processing_queue[0]
                self.processing_queue.pop(0)
                self._current_overrides = dict(self.job_overrides.pop(file_path, None) or {})   # nello stesso lock: nessuna modifica a meta'
                return file_path
            return None
    
    def run(self):
        """
        Esegue elaborazione con supporto aggiunta dinamica file
        
        CARATTERISTICHE v3.5:
        - Prende E rimuove atomicamente il primo elemento dalla coda
        - Elimina race condition con UI
        - Continua finchè coda non è vuota
        - Thread-safe con QMutex condiviso
        """
        # Salva il totale iniziale per statistiche
        self.total_files_at_start = self.get_total_files()
        self.log_message.emit(tr('worker_start').format(n=self.total_files_at_start))
        
        # ========================================
        # LOOP DINAMICO v3.5: Prende e rimuove atomicamente
        # ========================================
        while not self.is_cancelled:
            # ✅ OPERAZIONE ATOMICA: Prendi E rimuovi file dalla coda
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
            
            # Notifica UI: file iniziato
            self.file_started.emit(video_path)

            # Elabora file
            success = self._process_single_file(video_path)
            
            if success:
                self.completed_files += 1
                # Emetti segnale per aggiornare UI (file già rimosso dalla coda)
                self.file_completed.emit(video_path)
            else:
                self.failed_files += 1
                self.file_failed.emit(video_path)

            # Calcola progresso basato su file elaborati vs totale iniziale
            files_processed = self.completed_files + self.failed_files
            progress_percentage = min(100, int((files_processed / self.total_files_at_start) * 100))
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

        # Cache modelli HF/torch: pulizia UNA volta sola qui, a coda conclusa
        # (fine naturale o "Ferma"). Prima stava in pipeline._cleanup() e
        # girava a ogni file, riscaricando gli stessi modelli decine di volte.
        # cache_cleaner importa solo shutil/pathlib (e in modo lazy config/engine
        # dell'LLM, senza torch): nessun costo ML nel processo GUI.
        try:
            from utils.cache_cleaner import cleanup_non_italian_caches

            def _cache_log(m):
                self.log_message.emit(m)   # log a schermo
                logger.info(m)             # e nel file di log

            res = cleanup_non_italian_caches(log_callback=_cache_log)
            if res['removed']:
                _cache_log(
                    f"🗑️ Cache modelli liberata a fine coda: "
                    f"{len(res['removed'])} elementi")
            if res['failed']:
                logger.warning(
                    f"Cache cleanup parziale: {len(res['failed'])} "
                    f"elementi non rimossi")
        except Exception as e:
            logger.warning(f"Errore cache cleanup a fine coda: {e}")

        self.finished.emit()
    
    def _process_single_file(self, video_path: str) -> bool:
        """
        Elabora un file in subprocess ISOLATO (core.pipeline_cli).

        L'isolamento evita l'accumulo di RAM su code lunghe (ogni film gira
        in un processo che muore a fine elaborazione) e tiene torch fuori
        dal processo GUI. Il vecchio percorso legacy in-process (flag
        'pipeline_subprocess_isolation') è stato ritirato: caricava lo stack
        ML nel processo GUI.
        """
        return self._process_single_file_subprocess(video_path)

    def _process_single_file_subprocess(self, video_path: str) -> bool:
        """Elabora il film in un subprocess isolato (core.pipeline_cli). Lo spawn, la lettura dell'output, l'esito e la pulizia
        sono in core/jobs/file_runner.py (unica copia, usata anche dalla coda headless): qui restano i segnali verso la GUI."""
        filename = Path(video_path).name

        from utils.config import get_config
        from utils.job_overrides import clean as _clean_ov
        overrides = _clean_ov(getattr(self, '_current_overrides', None))
        target_language = overrides.get('target_language') or get_config().get_target_language()
        # Avanzamento del file: fasi pesate per durata reale + barra interna di fase (core/jobs/file_progress.py).
        from core.jobs.file_progress import FileProgress
        _file_progress = FileProgress(target_language)
        # Anteprima dei passi (Log Sintetico): gira SEMPRE, cosi' spuntando la casella a meta' file lo stato e' gia' vero.
        from core.jobs.step_plan import StepTracker, PlanOptions
        try:
            _steps = StepTracker(video_path, PlanOptions.from_config(get_config(), target_language, overrides))
            self.file_steps.emit(video_path, _steps.snapshot())
        except Exception:
            _steps = None

        def _steps_emit(changed=True):
            if _steps is not None and changed:
                try:
                    self.file_steps.emit(video_path, _steps.snapshot())
                except Exception:
                    pass
        files_done = self.completed_files + self.failed_files

        worker = self

        class _Hooks(FileHooks):
            def on_spawn(self, proc):
                worker._current_proc = proc

            def on_text(self, line):
                worker.log_message.emit(line)

            def on_noise(self, line):
                # rumore che alcune librerie scrivono su STDOUT bypassando il logging (torch.hub): solo nel file di log
                logger.info(f"[child-stdout] {line}")

            def on_event(self, kind, fields):
                # evento strutturato: muove l'anteprima dei passi (la barra del file l'ha gia' mossa il runner)
                if _steps is not None:
                    try:
                        _steps_emit(_steps.feed_event(kind, fields))
                    except Exception:
                        pass

            def on_progress(self, value, phase, changed):
                if changed:
                    worker.file_progress.emit(video_path, value)

            def on_stderr(self, line):
                # stderr del figlio (tqdm, warning di librerie): SOLO nel file di log, MAI a schermo
                logger.info(f"[child-stderr] {line}")

        self.log_message.emit(tr('worker_start_single'))
        try:
            result = FileRunner().run(
                video_path, target_language, files_done, progress=_file_progress, hooks=_Hooks(), overrides=overrides,
                is_cancelled=lambda: self.is_cancelled, ipc_prefix="tp_pipe_", feed_diag_progress=False,
                converting_cleanup='cancelled', raise_on_spawn_error=False)
        finally:
            self._current_proc = None

        if result.spawn_error is not None:
            self.log_message.emit(
                tr('worker_critical_error').format(filename=filename, error=result.spawn_error))
            logger.error(f"Spawn pipeline_cli fallito: {result.spawn_error}")
            if _steps is not None:
                _steps.mark_failed()
                _steps_emit()
            return False

        if result.cancelled:
            if _steps is not None:
                _steps.mark_stopped()
                _steps_emit()
            self.log_message.emit(tr('worker_cancelled_file').format(filename=filename))
            return False

        success = result.success
        last_output_path = result.output or ''
        _duration = result.duration

        if _steps is not None:
            (_steps.mark_completed if success else _steps.mark_failed)()
            _steps_emit()

        if success:
            self.log_message.emit(tr('worker_completed').format(filename=filename))
            try:
                self.file_history_entry.emit({
                    'name': Path(video_path).name,
                    'date_iso': datetime.now().isoformat(timespec='seconds'),
                    'src_lang': 'auto',
                    'dst_lang': target_language,
                    'duration_seconds': round(_duration),
                    'size_bytes': Path(video_path).stat().st_size,
                    'srt_path': last_output_path,
                    'video_path': video_path,
                })
            except Exception:
                pass
            return True

        self.log_message.emit(tr('worker_failed').format(filename=filename))
        self.log_message.emit(tr('worker_hint'))
        return False

    def _kill_proc_tree(self, proc):
        """Uccide il subprocess e TUTTI i discendenti (ffmpeg, gender_corrector_cli). Copia unica in core/jobs/file_runner.py."""
        kill_tree(proc)

    def cancel(self):
        """Richiesta di cancellazione dal main thread: kill dell'albero del
        subprocess pipeline in corso."""
        self.is_cancelled = True
        proc = self._current_proc
        if proc is not None:
            self._kill_proc_tree(proc)
