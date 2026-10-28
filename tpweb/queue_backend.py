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
from core.services.file_scan import VIDEO_EXTENSIONS, iter_videos, size_text
from core.services.formatting import EN_DASH, format_elapsed, format_eta
from core.services.job_model import JobRecord, JobStatus, KIND_OCR, is_reorderable
from core.services.log_buffer import LogBuffer
from core.services.settings_service import SettingsService
from core.services.shutdown_policy import ShutdownPolicy
from core.services.tool_gate import ToolGate
from tpweb.events import EventBus
from utils import job_overrides

EMPTY, RUNNING, OK = 'empty', 'running', 'ok'     # esiti di start()


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class WebQueue(QueueListener):
    def __init__(self, bus: EventBus, engine_factory: Optional[Callable[['WebQueue'], QueueEngine]] = None,
                 history=None, shutdown_enabled: Optional[Callable[[], bool]] = None,
                 shutdown_fn: Optional[Callable[[], None]] = None, shutdown_delay_s: float = ShutdownPolicy.DELAY_MS / 1000, config=None, gate=None):
        """`history`: HistoryService su cui salvare le voci dei file completati. `shutdown_enabled`/`shutdown_fn`: la casella
        'Spegni' (letta a fine coda) e l'azione; senza `shutdown_fn` il server non spegne MAI il computer."""
        self.bus = bus
        self.config = config
        self.gate = gate if gate is not None else ToolGate()
        self.subtitle_created_hooks: List[Callable[[str], None]] = []      # chiamati a ogni file completato (notifica del Library Scanner)
        self.gate.processing = lambda: self.is_processing
        self.history = history
        self.log = LogBuffer()
        self.preview = None                       # PreviewService (impostato dal launcher)
        self._log_lock = threading.Lock()
        self.compact = True                       # «Log Sintetico»: acceso all'apertura, non persistito (come la GUI)
        self.model_name: Optional[str] = None     # tessera «Modello» durante l'elaborazione (dalla riga di log «Modello trascrizione»)
        self.errors_shown = 0                     # tessera «Errori»: la GUI la aggiorna solo a inizio coda e sugli errori del worker
        self._final_elapsed: Optional[str] = None
        self._shutdown_enabled = shutdown_enabled
        self._shutdown_fn = shutdown_fn
        self._shutdown_delay_s = shutdown_delay_s
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_cancel = False
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

    def stats(self) -> dict:
        """Le tessere della GUI: completati, in corso, in coda, errori, ETA e tempo trascorso (testi gia' formattati)."""
        c = self.counts()
        remaining = c['queued'] + c['processing']
        started = self.proc_start_time
        eta = EN_DASH
        if self.completed_count > 0 and remaining > 0 and started > 0:
            eta = format_eta(time.time() - started, self.completed_count, remaining)
        return {'completed': self.completed_count, 'in_progress': c['processing'], 'queued': c['queued'],
                'errors': self.error_count, 'eta': eta,
                'elapsed': self._final_elapsed if self._final_elapsed is not None else (
                    format_elapsed(int(time.time() - started)) if started > 0 else None)}

    def counts(self) -> Dict[str, int]:
        c = {'all': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}
        with self._rows_lock:
            for r in self._rows:
                c[r.status] = c.get(r.status, 0) + 1
        c['all'] = sum(v for k, v in c.items() if k != 'all')
        return c

    # ------------------------------------------------------------------------------------------------------ log e diagnostica
    @property
    def pipeline_open(self) -> bool:
        return SettingsService(self.config).pipeline_card_open() if self.config is not None else True

    def set_pipeline_open(self, opened: bool) -> None:
        if self.config is not None:
            SettingsService(self.config).set_pipeline_card_open(bool(opened))
        self.bus.publish('log_options', self.log_options())

    def set_compact(self, enabled: bool) -> None:
        self.compact = bool(enabled)
        self.bus.publish('log_options', self.log_options())

    def hide_progress_bars(self) -> bool:
        """Le barre escono dal log solo se la card «Pipeline in corso» e' visibile (Log Sintetico + un file in lavorazione) E aperta."""
        return self.compact and self.last_steps is not None and self.pipeline_open

    def log_options(self) -> dict:
        return {'compact': self.compact, 'pipeline_open': self.pipeline_open}

    def log_message(self, text: str) -> None:
        """Una riga di log per l'utente: stesse regole di `MainWindow.log_message` (filtro, compatta, barre sul posto, colore)."""
        from datetime import datetime
        with self._log_lock:
            res = self.log.add(text, datetime.now(), self.compact, self.hide_progress_bars())
        if res.action == 'drop_ram':
            from utils.logger import setup_logger
            setup_logger().info(res.raw)
        if res.model_name:
            self.model_name = res.model_name
            self.bus.publish('diag', self.diag())
        if res.op is not None:
            self.bus.publish('log', res.op)

    def diag(self) -> dict:
        """Le cinque tessere di diagnostica (testi gia' pronti)."""
        from utils.engine_labels import idle_model_label
        c = self.config
        return {'elapsed': self.stats()['elapsed'] or '–', 'errors': str(self.errors_shown),
                'model': self.model_name or (idle_model_label(c) if c is not None else '–'),
                'translator': c.get_translation_model() if c is not None else '–',
                'engine': SettingsService(c).engine_mode_label() if c is not None else '–'}

    def live(self) -> dict:
        return {'stats': self.stats(), 'diag': self.diag()}

    def full_state(self) -> dict:
        """Stato completo per un client che si collega (o che ha perso eventi): coda, log, diagnostica, opzioni del log."""
        with self._log_lock:
            lines = list(self.log.lines)
        return {'queue': self.state(), 'log': lines, 'diag': self.diag(), 'log_options': self.log_options()}

    def state(self) -> dict:
        return {'running': self.is_processing, 'tools': self.gate.snapshot(), 'rows': self.rows(), 'counts': self.counts(),
                'remaining': len(self.queue), 'completed': self.completed_count, 'errors': self.error_count,
                'progress': self.last_progress, 'steps': self.last_steps, 'started_at': self.proc_start_time or None,
                'stats': self.stats(),
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

    @staticmethod
    def valid_override(key: str, value) -> bool:
        return job_overrides.clean_value(key, value) is not None

    def set_overrides(self, paths: List[str], key: str, value) -> List[str]:
        from utils.job_overrides import clean_value
        if value is not None and clean_value(key, value) is None:
            return []
        changed = self.queue.set_override(paths, key, value)
        if changed:
            labels = {p: job_overrides.label(self.overrides_of(p)) for p in changed}
            with self._rows_lock:               # l'etichetta sta sulla riga IN ATTESA di quel file (le righe gia' finite con lo stesso percorso la tengono)
                for i, r in enumerate(self._rows):
                    if r.path in labels and r.status == JobStatus.QUEUED and not r.is_ocr:
                        self._rows[i] = r.with_ov(labels[r.path], self.overrides_of(r.path).get('target_language', ''))
            self.bus.publish('overrides_changed', {p: {'overrides': self.overrides_of(p), 'ov': labels[p]} for p in changed})
        return changed

    def clear(self) -> bool:
        if self.is_processing:
            return False
        self.queue.clear()
        with self._rows_lock:
            self._rows.clear()
        if self.preview is not None:
            self.preview.clear()
        self.bus.publish('jobs_cleared')
        return True

    # ------------------------------------------------------------------------------------- scansione cartelle, dimensioni
    def scan_folder(self, folder: str, exts: Optional[List[str]] = None) -> bool:
        """Enumerazione in background (rglob su SMB e' lenta). False se una scansione e' gia' in corso. Ogni video trovato segue
        le regole di `add` (nessun doppione); a fine scansione 'scan_finished' col numero di file TROVATI."""
        t = self._scan_thread
        if t is not None and t.is_alive():
            return False
        self._scan_cancel = False
        self.bus.publish('scan_started', folder)

        def work():
            found = 0
            for path, size in iter_videos(folder, list(exts) if exts is not None else list(VIDEO_EXTENSIONS),
                                          lambda: self._scan_cancel):
                found += 1
                self.add([path], {path: size})
            self.bus.publish('scan_finished', found)
        self._scan_thread = threading.Thread(target=work, name='tpweb-scan', daemon=True)
        self._scan_thread.start()
        return True

    def cancel_scan(self) -> None:
        self._scan_cancel = True

    def join_scan(self, timeout: Optional[float] = None) -> None:
        t = self._scan_thread
        if t is not None:
            t.join(timeout)

    def request_sizes(self, paths: List[str]) -> None:
        """Calcola le dimensioni in background (un file su un NAS in standby puo' metterci secondi): le righe nascono senza e la
        dimensione arriva con 'size_ready'."""
        def work():
            for p in list(paths):
                size = size_text(p)
                with self._rows_lock:
                    for i, r in enumerate(self._rows):
                        if r.path == p and not r.is_ocr:
                            self._rows[i] = dataclasses.replace(r, size=size)
                self.bus.publish('size_ready', {'path': p, 'size': size})
        threading.Thread(target=work, name='tpweb-sizes', daemon=True).start()

    # ------------------------------------------------------------------------------------------------------ avvio / arresto
    def start(self) -> str:
        """Avvio atomico rispetto agli strumenti: il controllo dei flag e la nascita del thread avvengono sotto lo stesso lucchetto."""
        with self.gate.lock:
            if self.is_processing:
                return RUNNING
            verdict = self.gate.queue_verdict(len(self.queue) > 0)
            if verdict != OK:
                return verdict
            self.completed_count = 0
            self.error_count = 0
            self.errors_shown = 0
            self.model_name = None
            self._final_elapsed = None
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
            self.errors_shown = self.error_count
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
        self.log_message(text)

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
        self.last_steps['server_time'] = time.time()          # per la barra stimata dei passi brevi (salvataggio, upload)
        self.bus.publish('steps', self.last_steps)

    def on_file_completed(self, path: str) -> None:
        self.completed_count += 1
        self._update(path, JobRecord.completed)
        self.bus.publish('file_completed', path)
        for hook in list(self.subtitle_created_hooks):
            try:
                hook(path)
            except Exception:
                pass                                  # una notifica fallita non deve fermare la coda

    def on_file_failed(self, path: str) -> None:
        self.error_count += 1
        self._update(path, JobRecord.failed)
        self.bus.publish('file_failed', path)

    def on_file_error(self, path: str, message: str) -> None:
        self.last_error = message
        self.bus.publish('file_error', {'path': path, 'message': message})

    def on_history(self, entry: dict) -> None:
        if self.history is not None:
            self.history.load()                 # rilegge: mai riscrivere il file con la sola voce nuova (o con una copia vecchia)
            self.history.append(entry)
        self.bus.publish('history', entry)

    def on_queue_updated(self, remaining: int) -> None:
        self.bus.publish('remaining', remaining)

    def on_finished(self) -> None:
        if self.proc_start_time > 0:
            self._final_elapsed = format_elapsed(int(time.time() - self.proc_start_time))      # la tessera «Tempo» si ferma a fine coda
        from utils.translations import tr
        self.log_message(tr('processing_completed'))
        self.bus.publish('finished', {'completed': self.completed_count, 'errors': self.error_count})
        # anche dopo uno Stop (i restanti restano in coda): comportamento preservato dalla GUI
        if self._shutdown_fn is not None and self._shutdown_enabled is not None and self._shutdown_enabled():
            self.bus.publish('shutdown_scheduled', self._shutdown_delay_s)
            timer = threading.Timer(self._shutdown_delay_s, self._shutdown_fn)
            timer.daemon = True
            timer.start()
