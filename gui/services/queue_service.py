# -*- coding: utf-8 -*-
"""
QueueService: la coda di elaborazione senza widget.

Possiede
  - `processing_queue` (lista di path) e `queue_mutex`, passati PER RIFERIMENTO al ProcessingWorker.
    INVARIANTE v3.5 (gui/workers.py): la lista e il mutex nascono qui e NON vengono mai riassegnati/ricreati
    (niente `processing_queue = [...]`, niente QMutex() per run); il riordino scrive IN PLACE (`[:] = ...`);
    mutazioni e letture decisionali stanno sotto QMutexLocker, i segnali si emettono DOPO aver rilasciato il lock.
  - avvio/arresto del ProcessingWorker e inoltro dei suoi segnali alla vista
  - contatori e statistiche (completati, errori, ETA, tempo trascorso)
  - FileSizeWorker / FolderScanWorker
  - spegnimento a fine coda

NON possiede lo stato delle righe: la verita' resta nel dict in UserRole di ogni riga della lista (lo leggono
delegato, banco visivo e LibraryScannerWidget, che aggiunge righe anche senza passare di qui). Il servizio lo
legge attraverso `jobs_provider` (impostato dalla vista) e comunica le variazioni con segnali: e' la vista
a scriverle nella lista.

Va chiamato SOLO dal thread GUI. Nessun import di QtWidgets.
"""
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import (QCoreApplication, QMutex, QMutexLocker, QObject, QThread, QTimer,
                          pyqtSignal)

from gui.services.formatting import EN_DASH, format_elapsed, format_eta
from gui.services.job_model import JobRecord, JobStatus, is_reorderable
from gui.workers import FileSizeWorker, FolderScanWorker, ProcessingWorker
from utils.logger import setup_logger

logger = setup_logger()

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']


class StartVerdict(Enum):
    OK = 'ok'
    EMPTY = 'empty'            # niente in coda: il pulsante Avvia non fa nulla (nessun avviso)
    OCR = 'ocr'                # conversione OCR in corso
    GLOSSARY = 'glossary'      # strumento Glossario in esecuzione
    SYNC = 'sync'              # sincronizzazione SRT in esecuzione


@dataclass(frozen=True)
class QueueStats:
    completed: int
    in_progress: int
    queued: int
    errors: int
    eta: str                   # gia' formattata; EN_DASH se non calcolabile


class ShutdownPolicy:
    """Spegnimento del PC a fine coda (casella 'Spegni'): comando per sistema e ritardo."""
    DELAY_MS = 5000

    @staticmethod
    def command() -> List[str]:
        return ['shutdown', '/s', '/t', '60'] if os.name == 'nt' else ['shutdown', '-h', '+1']


class QueueService(QObject):
    # --- verso la vista ---
    job_added = pyqtSignal(object)                 # JobRecord: la vista crea e accoda la riga
    jobs_cleared = pyqtSignal()                    # la vista svuota la lista
    job_changed = pyqtSignal(str, object)          # (path, JobRecord con stato/avanzamento nuovi): job OCR
    job_size_ready = pyqtSignal(str, str)          # (path, dimensione leggibile)
    queue_reordered = pyqtSignal()
    remaining_changed = pyqtSignal(int)            # la vista ricalcola l'etichetta dei rimanenti
    processing_started = pyqtSignal(int)           # numero di righe in lista (per la tessera 'In coda')
    processing_finished = pyqtSignal()
    # eventi del file corrente (inoltro dei segnali del worker; il contatore e' gia' aggiornato)
    file_started = pyqtSignal(str)
    file_progress = pyqtSignal(str, int)
    file_completed = pyqtSignal(str)
    file_failed = pyqtSignal(str)
    progress_changed = pyqtSignal(int)
    log_line = pyqtSignal(str)
    history_entry = pyqtSignal(dict)
    worker_error = pyqtSignal(str)
    scan_started = pyqtSignal(str)
    scan_finished = pyqtSignal(int)

    def __init__(self, worker_factory: Callable = ProcessingWorker, parent=None):
        super().__init__(parent)
        self.worker_factory = worker_factory
        # INVARIANTE v3.5: creati una volta sola, mai riassegnati
        self.processing_queue: List[str] = []
        self.queue_mutex = QMutex()
        self.is_processing = False
        self.glossary_active = False
        self.sync_active = False
        self.worker = None
        self.completed_count = 0
        self.error_count = 0
        self.proc_start_time = 0.0
        self.io_workers: list = []             # FileSizeWorker/FolderScanWorker attivi
        self.folder_scan_worker = None
        # callable() -> list[dict]: i dict in UserRole delle righe, nell'ordine della lista (impostato dalla vista)
        self.jobs_provider: Callable[[], List[dict]] = lambda: []

    # ------------------------------------------------------------------ utilita'
    def _check_thread(self):
        """Il servizio e' chiamato solo dal thread GUI: se non e' cosi' lo si segnala nel log (non si blocca)."""
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            logger.warning("QueueService chiamato fuori dal thread GUI")

    # ------------------------------------------------------------------ lettura righe
    def _records(self) -> List[JobRecord]:
        return [JobRecord.from_item_data(d) for d in self.jobs_provider()]

    def find(self, path: str) -> Optional[JobRecord]:
        """La riga con quel path (esatto: sempre preferito), altrimenti la prima con lo stesso nome file."""
        name = Path(path).name
        fallback = None
        for rec in self._records():
            if rec.path == path:
                return rec
            if fallback is None and rec.filename == name:
                fallback = rec
        return fallback

    def counts(self) -> Dict[str, int]:
        counts = {'all': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}
        for d in self.jobs_provider():
            s = (d or {}).get('status', JobStatus.QUEUED)
            counts[s] = counts.get(s, 0) + 1
        counts['all'] = sum(v for k, v in counts.items() if k != 'all')
        return counts

    def remaining(self) -> int:
        with QMutexLocker(self.queue_mutex):
            return len(self.processing_queue)

    @staticmethod
    def can_reorder(record: JobRecord) -> bool:
        return is_reorderable(record.status, record.kind)

    # ------------------------------------------------------------------ aggiunta
    def enqueue(self, paths, sizes: Optional[Dict[str, str]] = None, only_files: bool = False) -> List[str]:
        """Accoda i path non gia' in coda (nessun doppione, nemmeno nella stessa chiamata).
        Restituisce quelli aggiunti, nell'ordine."""
        self._check_thread()
        sizes = sizes or {}
        added: List[str] = []
        records: List[JobRecord] = []
        with QMutexLocker(self.queue_mutex):
            for f in paths:
                if only_files and not Path(f).is_file():
                    continue
                if f not in self.processing_queue:
                    self.processing_queue.append(f)
                    records.append(JobRecord.new(f, sizes.get(f, '')))
                    added.append(f)
        for rec in records:
            self.job_added.emit(rec)
        self.remaining_changed.emit(self.remaining())
        return added

    def enqueue_scanned(self, path: str, size: str = '') -> bool:
        """Un file trovato dalla scansione di una cartella (stessa regola: niente doppioni)."""
        self._check_thread()
        with QMutexLocker(self.queue_mutex):
            if path in self.processing_queue:
                return False
            self.processing_queue.append(path)
            rec = JobRecord.new(path, size)
        self.job_added.emit(rec)
        self.remaining_changed.emit(self.remaining())
        return True

    def add_ocr_job(self, path: str, kind_label: str) -> bool:
        """Job OCR: compare in lista ma NON entra in processing_queue (Avvia lo ignora)."""
        self._check_thread()
        if self.find(path) is not None:
            return False
        self.job_added.emit(JobRecord.new_ocr(path, kind_label))
        return True

    def set_ocr_status(self, path: str, status: str, progress: int = 0) -> bool:
        """Stato/avanzamento di un job OCR. False se la riga non esiste o non e' un job OCR."""
        self._check_thread()
        rec = self.find(path)
        if rec is None or not rec.is_ocr:
            return False
        self.job_changed.emit(path, rec.with_status(status, progress))
        return True

    # ------------------------------------------------------------------ I/O asincrono
    def request_size_load(self, paths: list):
        """Dimensioni dei file in background (Path.stat() sul thread GUI bloccava con share SMB in standby)."""
        if not paths:
            return
        worker = FileSizeWorker(paths)
        worker.size_ready.connect(self.on_size_ready)
        worker.finished.connect(lambda w=worker: self._untrack_io_worker(w))
        self.io_workers.append(worker)
        worker.start()

    def on_size_ready(self, path: str, size: str):
        if self.find(path) is not None:
            self.job_size_ready.emit(path, size)

    def scan_folder(self, folder: str, exts: Optional[List[str]] = None) -> bool:
        """Enumerazione in background (rglob su SMB bloccava il thread GUI). False se una scansione e' in corso."""
        self._check_thread()
        if self.folder_scan_worker and self.folder_scan_worker.isRunning():
            return False
        self.scan_started.emit(folder)
        worker = FolderScanWorker(folder, list(exts) if exts is not None else list(VIDEO_EXTENSIONS))
        worker.file_found.connect(self.enqueue_scanned)
        worker.scan_done.connect(self.on_scan_done)
        worker.finished.connect(lambda w=worker: self._untrack_io_worker(w))
        self.folder_scan_worker = worker
        self.io_workers.append(worker)
        worker.start()
        return True

    def on_scan_done(self, count: int):
        self.folder_scan_worker = None
        self.scan_finished.emit(count)

    def _untrack_io_worker(self, worker):
        try:
            self.io_workers.remove(worker)
        except ValueError:
            pass

    # ------------------------------------------------------------------ riordino / svuotamento
    def reorder(self, ordered_paths: list, moved_path: Optional[str]) -> bool:
        """Riscrive processing_queue secondo l'ordine dato. False se la riga trascinata e' gia' stata presa
        dal worker (spostamento annullato). I path non citati restano in fondo, nel loro ordine."""
        self._check_thread()
        with QMutexLocker(self.queue_mutex):
            if moved_path not in self.processing_queue:
                return False
            in_queue = set(self.processing_queue)
            ordered = [p for p in ordered_paths if p in in_queue]
            seen = set(ordered)
            ordered += [p for p in self.processing_queue if p not in seen]
            # in place: il worker tiene un riferimento alla stessa lista
            self.processing_queue[:] = ordered
        self.queue_reordered.emit()
        return True

    def clear(self) -> bool:
        """Svuota coda e lista. Rifiutato (False) se l'elaborazione e' in corso."""
        self._check_thread()
        if self.is_processing:
            return False
        with QMutexLocker(self.queue_mutex):
            self.processing_queue.clear()
        self.jobs_cleared.emit()
        return True

    # ------------------------------------------------------------------ avvio / arresto
    def can_start(self, ocr_running: bool = False, glossary_active: Optional[bool] = None,
                  sync_active: Optional[bool] = None) -> StartVerdict:
        """Precedenza: coda vuota (silenziosa) > OCR > Glossario > Sincronizzazione."""
        if glossary_active is None:
            glossary_active = self.glossary_active
        if sync_active is None:
            sync_active = self.sync_active
        if not self.processing_queue:
            return StartVerdict.EMPTY
        if ocr_running:
            return StartVerdict.OCR
        if glossary_active:
            return StartVerdict.GLOSSARY
        if sync_active:
            return StartVerdict.SYNC
        return StartVerdict.OK

    def start(self):
        """Crea il worker sulla STESSA lista e sullo STESSO mutex, collega i segnali e lo avvia.
        La vista aggiorna pulsanti/tessere in risposta a `processing_started` (prima di worker.start())."""
        self._check_thread()
        self.is_processing = True
        w = self.worker_factory(self.processing_queue, self.queue_mutex)
        self.worker = w
        w.progress.connect(self.progress_changed)
        w.log_message.connect(self.log_line)
        w.finished.connect(self.worker_finished)
        w.file_completed.connect(self.on_file_completed)
        w.file_failed.connect(self.on_file_failed)
        w.file_started.connect(self.file_started)
        w.file_progress.connect(self.file_progress)
        w.file_history_entry.connect(self.history_entry)
        w.queue_updated.connect(self.remaining_changed)
        self.completed_count = 0
        self.error_count = 0
        self.proc_start_time = time.time()
        self.processing_started.emit(len(self.jobs_provider()))
        w.error.connect(self.on_worker_error)
        w.start()

    def stop(self):
        """Richiesta di arresto (la conferma all'utente e' della vista). cancel() uccide l'albero del subprocess
        e attende fino a 5 s sul thread GUI; il file corrente emette file_failed, i restanti restano in coda."""
        self._check_thread()
        if self.worker:
            self.worker.cancel()

    # ------------------------------------------------------------------ eventi del worker
    def on_file_completed(self, path: str):
        self.completed_count += 1
        self.file_completed.emit(path)

    def on_file_failed(self, path: str):
        self.error_count += 1
        self.file_failed.emit(path)

    def on_worker_error(self, msg: str):
        self.error_count += 1
        self.worker_error.emit(msg)

    def worker_finished(self):
        self.is_processing = False
        self.processing_finished.emit()

    # ------------------------------------------------------------------ statistiche
    def stats(self) -> QueueStats:
        counts = self.counts()
        in_prog, queued = counts['processing'], counts['queued']
        remaining = queued + in_prog
        if self.completed_count > 0 and remaining > 0 and self.proc_start_time > 0:
            eta = format_eta(time.time() - self.proc_start_time, self.completed_count, remaining)
        else:
            eta = EN_DASH
        return QueueStats(self.completed_count, in_prog, queued, self.error_count, eta)

    def elapsed_text(self) -> Optional[str]:
        """Tempo trascorso dall'avvio ('MM:SS' / 'HH:MM:SS'), None se la coda non e' mai partita."""
        if self.proc_start_time > 0:
            return format_elapsed(int(time.time() - self.proc_start_time))
        return None

    # ------------------------------------------------------------------ spegnimento
    def shutdown_system(self):
        subprocess.run(ShutdownPolicy.command())

    def schedule_shutdown(self, callback: Callable, enabled: bool, delay_ms: int = ShutdownPolicy.DELAY_MS):
        """A fine coda, se la casella e' spuntata, chiama `callback` (la vista passa il suo shutdown_system)
        dopo `delay_ms`. Vale anche dopo uno Stop (comportamento preservato)."""
        if enabled:
            QTimer.singleShot(delay_ms, callback)
