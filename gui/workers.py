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

from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from pathlib import Path
from typing import List, Optional

from core.jobs.engine import QueueEngine, QueueListener
from core.jobs.job_queue import JobQueue
from core.services.metadata_service import find_poster
from utils.logger import setup_logger

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
        """Carica poster in background (la ricerca e il download sono in core/services/metadata_service.py::find_poster)"""
        try:
            if self.is_cancelled:
                return

            video_name = Path(self.video_path).stem
            logger.debug(f"PosterLoader: Caricamento info per '{video_name}'")

            res = find_poster(self.video_path, self.tmdb_client, lambda: self.is_cancelled)
            if res.status == 'cancelled':
                return
            if res.status == 'found':
                from PyQt6.QtGui import QPixmap
                pixmap = QPixmap(str(res.path))

                if not pixmap.isNull():
                    logger.debug(f"✅ Poster caricato: {res.title}")
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


class QMutexLock:
    """Adattatore: un QMutex usato come lock di `core.jobs.job_queue.JobQueue` (`with lock:`). E' lo STESSO QMutex che le viste
    usano con QMutexLocker, quindi coda, servizio e viste si sincronizzano come prima. Non e' ricorsivo (come il QMutex)."""

    def __init__(self, mutex: QMutex):
        self.mutex = mutex

    def __enter__(self):
        self.mutex.lock()
        return self

    def __exit__(self, *exc):
        self.mutex.unlock()
        return False


class ProcessingWorker(QThread):
    """
    Worker thread per elaborazione video: adattatore Qt di `core.jobs.engine.QueueEngine`.

    Il ciclo, l'elaborazione di ogni file (sottoprocesso `core.pipeline_cli`), i contatori, l'anteprima dei passi, la cronologia e
    la pulizia delle cache a fine coda stanno nel motore (senza Qt, condiviso con la coda headless). Qui restano solo
    l'interfaccia verso la GUI, identica a prima: gli stessi 11 segnali, emessi nello stesso thread (questo QThread) e nello
    stesso ordine, e gli stessi attributi usati da QueueService.
    """

    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    file_completed = pyqtSignal(str)
    file_failed = pyqtSignal(str)          # (file_path) — emesso quando pipeline ritorna False
    file_started = pyqtSignal(str)         # (file_path)
    file_progress = pyqtSignal(str, int)   # (file_path, percent 0-100)
    file_steps = pyqtSignal(str, object)   # (file_path, PipelineSnapshot): anteprima dei passi (core/jobs/step_plan.py)
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
        self.processing_queue = processing_queue      # riferimento condiviso
        self.queue_mutex = queue_mutex                # mutex condiviso con la UI
        # La coda del motore avvolge la STESSA lista e lo STESSO mutex (nessuna copia); le eccezioni per file sono il dizionario di
        # QueueService (stesso mutex), assegnato da chi crea il worker; vuoto se il worker e' usato da solo.
        self._queue = JobQueue(lock=QMutexLock(queue_mutex), items=processing_queue, overrides={})
        self._engine = QueueEngine(self._queue, _SignalListener(self), cleanup_caches=True)

    # ------------------------------------------------------------------ compatibilita' (attributi storici)
    @property
    def job_overrides(self) -> dict:
        return self._queue.overrides

    @job_overrides.setter
    def job_overrides(self, value: dict):
        self._queue.overrides = value

    @property
    def is_cancelled(self) -> bool:
        return self._engine.is_cancelled

    @is_cancelled.setter
    def is_cancelled(self, value: bool):
        self._engine.is_cancelled = value

    @property
    def completed_files(self) -> int:
        return self._engine.completed_files

    @property
    def failed_files(self) -> int:
        return self._engine.failed_files

    @property
    def total_files_at_start(self) -> int:
        return self._engine.total_files_at_start

    def note_removed(self, n: int = 1):
        """Un file ancora in attesa e' stato tolto dalla coda mentre il worker lavora: il totale per la percentuale scende di n."""
        self._engine.note_removed(n)

    def get_total_files(self) -> int:
        """Numero file in coda, in modo thread-safe."""
        return len(self._queue)

    def get_and_remove_next_file(self) -> Optional[str]:
        """Prende E rimuove il primo file dalla coda in un'unica operazione atomica (con le sue eccezioni)."""
        item = self._queue.take_next()
        return item[0] if item else None

    def run(self):
        """Esegue la coda con supporto all'aggiunta dinamica di file (vedi QueueEngine.run)."""
        self._engine.run()

    def cancel(self):
        """Richiesta di cancellazione dal main thread: kill dell'albero del subprocess pipeline in corso."""
        self._engine.cancel()


class _SignalListener(QueueListener):
    """Ganci del motore -> segnali del ProcessingWorker (stesso thread: quello del QThread)."""

    def __init__(self, worker: ProcessingWorker):
        self._w = worker

    def on_log(self, text):
        self._w.log_message.emit(text)

    def on_progress(self, percent):
        self._w.progress.emit(percent)

    def on_file_started(self, path):
        self._w.file_started.emit(path)

    def on_file_progress(self, path, percent):
        self._w.file_progress.emit(path, percent)

    def on_file_steps(self, path, snapshot):
        self._w.file_steps.emit(path, snapshot)

    def on_file_completed(self, path):
        self._w.file_completed.emit(path)

    def on_file_failed(self, path):
        self._w.file_failed.emit(path)

    def on_history(self, entry):
        self._w.file_history_entry.emit(entry)

    def on_queue_updated(self, remaining):
        self._w.queue_updated.emit(remaining)

    def on_finished(self):
        self._w.finished.emit()
