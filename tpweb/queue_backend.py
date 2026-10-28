# -*- coding: utf-8 -*-
"""WebQueue: la coda di elaborazione per la web UI (fetta 1b). Senza Qt.

E' l'equivalente di `gui.services.queue_service.QueueService` + `ProcessingWorker`: possiede la `JobQueue` (core/jobs), le righe
(`JobRecord`: la verita' dello stato di ogni file), il motore `QueueEngine` in un thread, i contatori; e pubblica ogni
cambiamento sul bus di eventi (che il browser legge via SSE). Regole prese dalla GUI:
  - nessun doppione: un file e' rifiutato se c'e' gia' una riga con lo stesso percorso in attesa o in lavorazione (non OCR);
  - Stop uccide il file in corso, i restanti restano in coda; la coda non si svuota mentre lavora;
  - togliere un file in attesa mentre lavora abbassa il totale del motore (`note_removed`);
  - i job OCR compaiono nell'elenco ma non entrano nella coda del motore.
Ordine dei lock: mai prendere il lock della JobQueue tenendo `_rows_lock` (le callback di `accept` fanno il contrario: ok)."""
import dataclasses
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.jobs.engine import QueueEngine, QueueListener
from core.jobs.job_queue import JobQueue
from core.services.job_model import JobRecord, JobStatus, KIND_OCR, is_reorderable
from tpweb.events import EventBus

EMPTY, RUNNING, OK = 'empty', 'running', 'ok'     # esiti di start()


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class WebQueue(QueueListener):
    def __init__(self, bus: EventBus, engine_factory: Optional[Callable[['WebQueue'], QueueEngine]] = None):
        self.bus = bus
        self.queue = JobQueue()
        self._rows_lock = threading.RLock()
        self._rows: List[JobRecord] = []
        self._engine_factory = engine_factory or (lambda wq: QueueEngine(wq.queue, wq))
        self._engine: Optional[QueueEngine] = None
        self._thread: Optional[threading.Thread] = None
        self.completed_count = 0
        self.error_count = 0
        self.proc_start_time = 0.0
        self.last_error = ''
        self.last_steps: Optional[dict] = None
        self.last_progress = 0

    # ----------------------------------------------------------------------------------------------------------- lettura
    @property
    def is_processing(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def rows(self) -> List[dict]:
        with self._rows_lock:
            return [r.to_item_data() for r in self._rows]

    def counts(self) -> Dict[str, int]:
        c = {'all': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}
        with self._rows_lock:
            for r in self._rows:
                c[r.status] = c.get(r.status, 0) + 1
        c['all'] = sum(v for k, v in c.items() if k != 'all')
        return c

    def state(self) -> dict:
        return {'running': self.is_processing, 'rows': self.rows(), 'counts': self.counts(),
                'remaining': len(self.queue), 'completed': self.completed_count, 'errors': self.error_count,
                'progress': self.last_progress, 'steps': self.last_steps, 'started_at': self.proc_start_time or None,
                'overrides': {p: o for p, o in self._overrides().items()}}

    def _overrides(self) -> dict:
        with self.queue.lock:
            return {p: dict(o) for p, o in self.queue.overrides.items()}

    def overrides_of(self, path: str) -> dict:
        return self.queue.overrides_of(path)

    def is_active(self, path: str) -> bool:
        key = _key(path)
        with self._rows_lock:
            return any(r.kind != KIND_OCR and _key(r.path) == key and r.status in (JobStatus.QUEUED, JobStatus.PROCESSING)
                       for r in self._rows)

    # --------------------------------------------------------------------------------------------------------- scrittura
    def add(self, paths, sizes: Optional[Dict[str, str]] = None, only_files: bool = False) -> List[str]:
        sizes = sizes or {}
        added: List[str] = []
        for f in paths:
            if only_files and not Path(f).is_file():
                continue
            rec = JobRecord.new(f, sizes.get(f, ''))
            if self.queue.add(f, accept=lambda p: not self.is_active(p)):
                with self._rows_lock:
                    self._rows.append(rec)
                added.append(f)
                self.bus.publish('job_added', rec.to_item_data())
        if added:
            self.bus.publish('remaining', len(self.queue))
        return added

    def add_ocr_job(self, path: str, kind_label: str) -> bool:
        """Compare nell'elenco ma NON entra nella coda del motore (Avvia lo ignora)."""
        rec = JobRecord.new_ocr(path, kind_label)
        with self._rows_lock:
            self._rows.append(rec)
        self.bus.publish('job_added', rec.to_item_data())
        return True

    def remove(self, path: str) -> bool:
        if not self.queue.remove(path):
            return False
        eng = self._engine
        if eng is not None and self.is_processing:
            eng.note_removed()
        with self._rows_lock:
            for i, r in enumerate(self._rows):
                if r.path == path and r.status == JobStatus.QUEUED and not r.is_ocr:
                    del self._rows[i]
                    break
        self.bus.publish('job_removed', path)
        self.bus.publish('remaining', len(self.queue))
        return True

    def reorder(self, ordered_paths: list, moved_path: Optional[str]) -> bool:
        if not self.queue.reorder(ordered_paths, moved_path):
            return False
        order = self.queue.snapshot()
        with self._rows_lock:        # le righe in attesa si riassegnano agli stessi posti: le altre restano dove sono
            slots = [i for i, r in enumerate(self._rows) if is_reorderable(r.status, r.kind)]
            waiting = {self._rows[i].path: self._rows[i] for i in slots}
            fresh = [waiting[p] for p in order if p in waiting]
            for i, r in zip(slots, fresh):
                self._rows[i] = r
        self.bus.publish('queue_reordered', order)
        return True

    def set_overrides(self, paths: List[str], key: str, value) -> List[str]:
        from utils.job_overrides import clean_value
        if value is not None and clean_value(key, value) is None:
            return []
        changed = self.queue.set_override(paths, key, value)
        if changed:
            self.bus.publish('overrides_changed', {p: self.overrides_of(p) for p in changed})
        return changed

    def clear(self) -> bool:
        if self.is_processing:
            return False
        self.queue.clear()
        with self._rows_lock:
            self._rows.clear()
        self.bus.publish('jobs_cleared')
        return True

    # ------------------------------------------------------------------------------------------------------ avvio / arresto
    def start(self) -> str:
        if self.is_processing:
            return RUNNING
        if len(self.queue) == 0:
            return EMPTY
        self.completed_count = 0
        self.error_count = 0
        self.last_error = ''
        self.last_steps = None
        self.last_progress = 0
        self.proc_start_time = time.time()
        self._engine = self._engine_factory(self)
        self.bus.publish('processing_started', self.counts()['all'])
        self._thread = threading.Thread(target=self._run, name='tpweb-queue', daemon=True)
        self._thread.start()
        return OK

    def _run(self) -> None:
        try:
            self._engine.run()
        except Exception as e:                      # il motore non dovrebbe sollevare: se succede lo si dice e si chiude
            self.error_count += 1
            self.last_error = str(e)
            self.bus.publish('worker_error', str(e))
            self.on_finished()

    def stop(self) -> bool:
        eng = self._engine
        if eng is None or not self.is_processing:
            return False
        eng.cancel()
        return True

    def join(self, timeout: Optional[float] = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    # ----------------------------------------------------------------------------------------------- ganci del motore
    def _update(self, path: str, fn) -> None:
        with self._rows_lock:
            for i, r in enumerate(self._rows):
                if r.path == path and not r.is_ocr and r.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                    self._rows[i] = fn(r)
                    return

    def on_log(self, text: str) -> None:
        self.bus.publish('log', text)

    def on_progress(self, percent: int) -> None:
        self.last_progress = percent
        self.bus.publish('progress', percent)

    def on_file_started(self, path: str) -> None:
        self._update(path, JobRecord.started)
        self.bus.publish('file_started', path)

    def on_file_progress(self, path: str, percent: int) -> None:
        self._update(path, lambda r: r.with_progress(percent))
        self.bus.publish('file_progress', {'path': path, 'percent': percent})

    def on_file_steps(self, path: str, snapshot) -> None:
        self.last_steps = dataclasses.asdict(snapshot)
        self.bus.publish('steps', self.last_steps)

    def on_file_completed(self, path: str) -> None:
        self.completed_count += 1
        self._update(path, JobRecord.completed)
        self.bus.publish('file_completed', path)

    def on_file_failed(self, path: str) -> None:
        self.error_count += 1
        self._update(path, JobRecord.failed)
        self.bus.publish('file_failed', path)

    def on_file_error(self, path: str, message: str) -> None:
        self.last_error = message
        self.bus.publish('file_error', {'path': path, 'message': message})

    def on_history(self, entry: dict) -> None:
        self.bus.publish('history', entry)

    def on_queue_updated(self, remaining: int) -> None:
        self.bus.publish('remaining', remaining)

    def on_finished(self) -> None:
        self.bus.publish('finished', {'completed': self.completed_count, 'errors': self.error_count})
