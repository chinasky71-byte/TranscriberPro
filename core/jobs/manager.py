"""Shared job manager: one queue, one GPU-heavy job at a time.

Used by the headless CLI today and by the WebUI later. It owns the job list,
spawns one ``core.pipeline_cli`` subprocess per file and publishes events.
No Qt, no GPU code.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .events import EventHub
from .models import (
    CANCELLED, DONE, FAILED, INTERRUPTED, LEGACY_STATUS, QUEUED, RUNNING, Job,
)
from .persistence import load_jobs, save_jobs
from .process_runner import ProcessRunner
from .progress import FileProgress


class JobManager:
    def __init__(self, target_language: str = "ita",
                 persist_path: Optional[Path] = None,
                 log_dir: Optional[Path] = None,
                 runner: Optional[Any] = None,
                 progress_factory: Callable[[str], Any] = FileProgress,
                 hub: Optional[EventHub] = None,
                 load_persisted: bool = True,
                 keep_alive: bool = False,
                 preflight: Optional[Callable[[Job], tuple]] = None):
        self.target_language = target_language
        self.persist_path = Path(persist_path) if persist_path else None
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner or ProcessRunner()
        self.progress_factory = progress_factory
        self.hub = hub or EventHub()
        self._jobs: List[Job] = []
        self._by_id: Dict[str, Job] = {}
        self._lock = threading.RLock()
        self._cancel: Dict[str, threading.Event] = {}
        self._worker: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._keep_alive = keep_alive
        # preflight(job) -> (ok, message): deciso PRIMA di lanciare il processo.
        # Un job GPU su un venv senza backend funzionante deve fallire in un
        # secondo, non dopo mezz'ora di CPU (v. docs/adr/ADR-007).
        self.preflight = preflight
        self._state = "finished"
        self.started = time.time()

        if self.persist_path and load_persisted:
            for job in load_jobs(self.persist_path):
                self._jobs.append(job)
                self._by_id[job.id] = job
            self._save()

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------
    def add(self, path: str | Path, overrides: Optional[Dict[str, Any]] = None,
            target_language: Optional[str] = None) -> Job:
        job = Job(path=str(path), overrides=dict(overrides or {}))
        if target_language:
            job.overrides.setdefault("target_language", target_language)
        with self._lock:
            self._jobs.append(job)
            self._by_id[job.id] = job
        self.hub.publish(job.id, "created", job=job.to_dict())
        self._wake.set()
        self._save()
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._by_id.get(job_id)
            if job is None or job.status != QUEUED:
                return False
            self._jobs.remove(job)
            self._by_id.pop(job_id, None)
        self.hub.publish(job_id, "removed")
        self._save()
        return True

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._by_id.get(job_id)
            if job is None:
                return False
            if job.status == QUEUED:
                job.status = CANCELLED
                job.finished_at = time.time()
                event = self._cancel.get(job_id)
                if event:
                    event.set()
                changed = True
            elif job.status == RUNNING:
                event = self._cancel.get(job_id)
                if event is None:
                    return False
                event.set()
                changed = True
            else:
                return False
        self.hub.publish(job_id, "status", status=job.status, job=job.to_dict())
        self._save()
        return changed

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stopping.clear()
            self._wake.clear()
            self._state = "running"
            self._worker = threading.Thread(target=self._run, name="tp-jobs", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        with self._lock:
            running = [job for job in self._jobs if job.status == RUNNING]
            queued = [job for job in self._jobs if job.status == QUEUED]
        for job in running:
            self.cancel(job.id)
        for job in queued:
            self.cancel(job.id)
        if self._worker is not None:
            self._worker.join(timeout=30)
        self._state = "cancelled"

    def wait(self) -> None:
        if self._worker is not None:
            self._worker.join()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [job.to_dict() for job in self._jobs]

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._by_id.get(job_id)
            return job.to_dict() if job else None

    @property
    def state(self) -> str:
        return self._state

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        return self.hub.subscribe(callback)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _next_queued(self) -> Optional[Job]:
        with self._lock:
            for job in self._jobs:
                if job.status == QUEUED:
                    return job
        return None

    def _run(self) -> None:
        while not self._stopping.is_set():
            job = self._next_queued()
            if job is None:
                if not self._keep_alive:
                    break
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            self._run_one(job)
        with self._lock:
            if not self._keep_alive and self._state != "cancelled":
                self._state = "finished"

    def _run_one(self, job: Job) -> None:
        if self.preflight is not None:
            try:
                allowed, reason = self.preflight(job)
            except Exception as exc:                      # il preflight non deve fermare la coda
                allowed, reason = True, f"preflight non eseguibile: {exc}"
            if not allowed:
                with self._lock:
                    self._cancel.pop(job.id, None)
                    job.status = FAILED
                    job.error = reason
                    job.finished_at = time.time()
                self.hub.log(job.id, reason)
                self.hub.publish(job.id, "status", status=job.status, job=job.to_dict())
                self._save()
                return
        overrides = dict(job.overrides)
        target = overrides.get("target_language") or self.target_language
        cancel_event = threading.Event()
        with self._lock:
            self._cancel[job.id] = cancel_event
            if job.status == CANCELLED:
                self._cancel.pop(job.id, None)
                return
            job.status = RUNNING
            job.started_at = time.time()
            job.percent = 0
            job.phase = "setup"
        self.hub.publish(job.id, "status", status=job.status, job=job.to_dict())

        progress = self.progress_factory(target)
        log_path = (self.log_dir / f"{job.id}.log") if self.log_dir else None

        def _progress(percent: int | None, phase: str | None) -> None:
            if percent is None and not phase:
                return
            with self._lock:
                if percent is not None and percent > job.percent:
                    job.percent = min(99, percent)
                if phase:
                    job.phase = phase
                snapshot = job.to_dict()
            self.hub.publish(job.id, "progress", percent=job.percent,
                             phase=job.phase, job=snapshot)

        def _on_line(line: str) -> None:
            self.hub.log(job.id, line)
            _progress(progress.feed(line), progress.phase)

        def _on_event(kind: str, fields: Dict[str, Any]) -> None:
            self.hub.publish(job.id, "event", event_kind=kind, fields=fields)
            _progress(progress.feed_event(kind, fields), progress.phase)

        try:
            result = self.runner.run(
                Path(job.path), target, 0, log_path,
                on_line=_on_line, on_event=_on_event, cancel_event=cancel_event,
            )
        except Exception as exc:  # a runner failure must not kill the queue
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                      "cancelled": cancel_event.is_set(), "output": None}

        with self._lock:
            self._cancel.pop(job.id, None)
            job.finished_at = time.time()
            if result.get("cancelled") or cancel_event.is_set():
                job.status = CANCELLED
                job.error = "cancelled"
            elif result.get("ok"):
                job.status = DONE
                job.percent = 100
                job.phase = ""
                job.output = result.get("output")
            else:
                job.status = FAILED
                job.error = result.get("error") or "failed"
        self.hub.publish(job.id, "status", status=job.status, job=job.to_dict())
        self._save()

    # ------------------------------------------------------------------
    # Persistence and legacy status
    # ------------------------------------------------------------------
    def _save(self) -> None:
        if not self.persist_path:
            return
        with self._lock:
            jobs = list(self._jobs)
        try:
            save_jobs(self.persist_path, jobs)
        except Exception:
            pass

    def legacy_snapshot(self) -> Dict[str, Any]:
        """Status file compatible with the historical headless queue."""
        with self._lock:
            jobs = list(self._jobs)
            current_index = next((i for i, job in enumerate(jobs)
                                  if job.status == RUNNING), None)
        by = lambda status: [job for job in jobs if job.status == status]  # noqa: E731
        done, failed, queued = by(DONE), by(FAILED), by(QUEUED)
        current = jobs[current_index] if current_index is not None else None
        elapsed = (time.time() - current.started_at) if current and current.started_at else 0.0
        eta_file = _eta_seconds(current.percent, elapsed) if current else None
        eta_queue = None
        durations = [job.seconds for job in done if job.seconds]
        if durations:
            average = sum(durations) / len(durations)
            if current is None:
                rest = 0.0
            elif eta_file is not None:
                rest = eta_file
            elif current.percent >= 99:
                rest = 0.0
            else:
                rest = max(average - elapsed, 0.0)
            eta_queue = int(rest + average * len(queued))
        return {
            "version": 1,
            "state": self._state,
            "pid": __import__("os").getpid(),
            "started": _iso(self.started),
            "updated": _iso(),
            "total": len(jobs),
            "completed": len(done),
            "failed": len(failed) + len(by(INTERRUPTED)),
            "cancelled": len(by(CANCELLED)),
            "queued": len(queued),
            "current": ({"index": current_index + 1, "name": current.name,
                         "phase": current.phase, "percent": current.percent,
                         "eta_seconds": eta_file} if current else None),
            "eta_queue_seconds": eta_queue,
            "files": [{
                "name": job.name, "path": job.path,
                "status": LEGACY_STATUS.get(job.status, job.status),
                "percent": job.percent, "phase": job.phase,
                "seconds": job.seconds, "output": job.output, "error": job.error,
            } for job in jobs],
        }


def _iso(timestamp: float | None = None) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(timestamp if timestamp is not None else time.time()).isoformat(timespec="seconds")


def _eta_seconds(percent: int, elapsed: float) -> Optional[int]:
    if percent < 3 or percent >= 99 or elapsed < 20:
        return None
    return int(elapsed * (100 - percent) / percent)
