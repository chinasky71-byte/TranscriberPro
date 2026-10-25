"""In-process event hub for job updates.

Subscribers receive plain dictionaries. The hub keeps a small per-job history
so a browser that reconnects can replay the tail (SSE `Last-Event-ID`).

Thread-safe: the queue runs in a worker thread, the web server in another.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List

Subscriber = Callable[[Dict[str, Any]], None]


class EventHub:
    def __init__(self, history_size: int = 500):
        self.history_size = history_size
        self._lock = threading.RLock()
        self._subscribers: List[Subscriber] = []
        self._history: Dict[str, Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=history_size))
        self._seq = 0

    def publish(self, job_id: str, kind: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "job_id": job_id, "kind": kind,
                     "ts": time.time(), **fields}
            self._history[job_id].append(event)
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # A broken subscriber must never stop the queue.
                pass
        return event

    def log(self, job_id: str, line: str) -> None:
        self.publish(job_id, "log", line=line)

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def history(self, job_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            return [event for event in self._history.get(job_id, ())
                    if event["seq"] > after_seq]

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._history.pop(job_id, None)
