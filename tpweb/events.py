# -*- coding: utf-8 -*-
"""Bus di eventi del server: ogni evento ha un numero progressivo; chi si ricollega riprende da dove era arrivato
oppure, se i vecchi eventi non ci sono piu', riceve lo stato completo (piano, sezione 5). Senza Qt."""
import asyncio
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

KEEP = 5000      # eventi tenuti in memoria (il riquadro del log della GUI tiene 5.000 blocchi)


class EventBus:
    def __init__(self, keep: int = KEEP):
        self._lock = threading.Lock()
        self._events: deque = deque(maxlen=keep)
        self._seq = 0
        self._waiters: list = []                    # (loop, asyncio.Event)

    @property
    def last_seq(self) -> int:
        return self._seq

    def publish(self, kind: str, data: Any = None) -> int:
        """Pubblica un evento da qualunque thread. Ritorna il suo numero progressivo."""
        with self._lock:
            self._seq += 1
            ev = {'seq': self._seq, 'k': kind, 't': time.time(), 'd': data}
            self._events.append(ev)
            waiters = list(self._waiters)
        for loop, flag in waiters:
            try:
                loop.call_soon_threadsafe(flag.set)
            except RuntimeError:                    # loop chiuso
                pass
        return ev['seq']

    def since(self, after: int) -> tuple:
        """(eventi con seq > after, gap). gap=True se alcuni di quelli richiesti sono gia' stati scartati."""
        with self._lock:
            evs = [e for e in self._events if e['seq'] > after]
            oldest = self._events[0]['seq'] if self._events else self._seq + 1
            gap = after + 1 < oldest and self._seq > after
        return evs, gap

    def add_waiter(self, loop, flag: 'asyncio.Event') -> tuple:
        with self._lock:
            w = (loop, flag)
            self._waiters.append(w)
        return w

    def remove_waiter(self, w) -> None:
        with self._lock:
            if w in self._waiters:
                self._waiters.remove(w)
