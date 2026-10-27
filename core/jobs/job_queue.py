# -*- coding: utf-8 -*-
"""JobQueue: la coda dei file da elaborare, senza Qt e senza GUI.

Possiede la lista dei percorsi in attesa e le eccezioni per file (`utils/job_overrides.py`) e le protegge con UN lock. E' la
trasposizione fedele dell'invariante v3.5 che prima viveva fra gui/services/queue_service.py e gui/workers.py:
  - la lista (`items`) e il dizionario (`overrides`) nascono qui e NON si riassegnano mai; ogni modifica e' sul posto
    (`items[:] = ...`), cosi' chi ne tiene un riferimento (la GUI, le viste) vede sempre la stessa lista;
  - mutazioni e letture che decidono qualcosa stanno sotto lock; chi chiama emette i suoi segnali/eventi DOPO il rilascio;
  - il prelievo del file, la sua rimozione dalla coda e il prelievo delle sue eccezioni sono UN'unica operazione (`take_next`).

Il lock e' iniettabile: di default un `threading.RLock`; la GUI passa un adattatore sullo stesso `QMutex` che le sue viste
gia' usano con `QMutexLocker`. I metodi di questa classe NON annidano mai il lock (un QMutex non e' ricorsivo).
"""
import threading
from typing import Callable, Dict, List, Optional, Tuple


class JobQueue:
    def __init__(self, lock=None, items: Optional[List[str]] = None, overrides: Optional[Dict[str, dict]] = None):
        self.lock = lock if lock is not None else threading.RLock()
        self.items: List[str] = items if items is not None else []
        self.overrides: Dict[str, dict] = overrides if overrides is not None else {}

    # ------------------------------------------------------------------------------------------------------------ lettura
    def __len__(self) -> int:
        with self.lock:
            return len(self.items)

    def contains(self, path: str) -> bool:
        with self.lock:
            return path in self.items

    def snapshot(self) -> List[str]:
        """Copia dei percorsi in attesa, nell'ordine di esecuzione."""
        with self.lock:
            return list(self.items)

    def overrides_of(self, path: str) -> dict:
        with self.lock:
            return dict(self.overrides.get(path, {}))

    # ---------------------------------------------------------------------------------------------------------- scrittura
    def add(self, path: str, accept: Optional[Callable[[str], bool]] = None) -> bool:
        """Accoda `path` se non c'e' gia' (e se `accept(path)`, valutata sotto lock, lo consente). Le eccezioni di un file
        riaccodato ripartono vuote. False se non e' stato aggiunto."""
        with self.lock:
            if path in self.items or (accept is not None and not accept(path)):
                return False
            self.items.append(path)
            self.overrides.pop(path, None)
            return True

    def take_next(self) -> Optional[Tuple[str, dict]]:
        """Prende E rimuove il primo file e le sue eccezioni in un'unica operazione atomica. None se la coda e' vuota."""
        with self.lock:
            if not self.items:
                return None
            path = self.items.pop(0)
            return path, dict(self.overrides.pop(path, None) or {})

    def remove(self, path: str) -> bool:
        """Toglie UN file ancora in attesa (e le sue eccezioni). False se non e' in coda (gia' preso, finito, non della coda)."""
        with self.lock:
            if path not in self.items:
                return False
            self.items.remove(path)
            self.overrides.pop(path, None)
            return True

    def reorder(self, ordered_paths: list, moved_path: Optional[str]) -> bool:
        """Riscrive la coda secondo l'ordine dato (sul posto). False se la riga spostata e' gia' stata presa: spostamento
        annullato. I percorsi non citati restano in fondo, nel loro ordine."""
        with self.lock:
            if moved_path not in self.items:
                return False
            in_queue = set(self.items)
            ordered = [p for p in ordered_paths if p in in_queue]
            seen = set(ordered)
            ordered += [p for p in self.items if p not in seen]
            self.items[:] = ordered
            return True

    def set_override(self, paths: List[str], key: str, value) -> List[str]:
        """Imposta (value) o toglie (value None) UNA eccezione sui file ancora in attesa. Ritorna i percorsi modificati; quelli
        non in coda sono saltati. Sotto lock: il prelievo non puo' avvenire a meta'. La validazione del valore e' di chi chiama."""
        changed: List[str] = []
        with self.lock:
            for p in paths:
                if p not in self.items:
                    continue
                cur = dict(self.overrides.get(p, {}))
                if value is None:
                    cur.pop(key, None)
                else:
                    cur[key] = value
                if cur:
                    self.overrides[p] = cur
                else:
                    self.overrides.pop(p, None)
                changed.append(p)
        return changed

    def clear(self) -> None:
        with self.lock:
            self.items.clear()
            self.overrides.clear()
