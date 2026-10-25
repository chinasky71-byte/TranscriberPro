"""Bridge between the thread-based EventHub and an SSE response.

The hub is written by the queue worker thread; the SSE generator runs in the
event loop. `call_soon_threadsafe` moves events across.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Dict, Optional

from core.jobs.events import EventHub


class SSEBridge:
    def __init__(self, hub: EventHub, job_id: Optional[str] = None,
                 after_seq: int = 0, heartbeat_s: float = 15.0):
        self.hub = hub
        self.job_id = job_id
        self.after_seq = max(0, int(after_seq or 0))
        self.heartbeat_s = heartbeat_s
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._closed = False
        self._unsubscribe = hub.subscribe(self._on_event)
        if job_id:
            for event in hub.history(job_id, self.after_seq):
                self._put(event)

    def _on_event(self, event: Dict) -> None:
        if self._closed:
            return
        if self.job_id and event.get("job_id") != self.job_id:
            return
        if event.get("seq", 0) <= self.after_seq:
            return
        self._put(event)

    def _put(self, event: Dict) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except (RuntimeError, asyncio.QueueFull):
            pass

    async def frames(self) -> AsyncIterator[str]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(self._queue.get(), self.heartbeat_s)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False)
                yield f"id: {event.get('seq', 0)}\ndata: {payload}\n\n"
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._unsubscribe()
            except Exception:
                pass
