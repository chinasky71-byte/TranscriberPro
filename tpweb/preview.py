# -*- coding: utf-8 -*-
"""Anteprima del file selezionato (fetta 2d): locandina TMDB e titolo «Nome show SxxExx». Senza Qt.

Usa `find_poster` e `TitleResolver` di core/services/metadata_service.py (gli stessi della GUI). Regole della GUI mantenute:
  - lo stesso file non ricarica la locandina (`reset_last()` forza il ricaricamento, come quando un file passa in lavorazione);
  - una ricerca ancora in corso viene annullata quando se ne chiede un'altra.
Differenza voluta: il risultato tardivo di una ricerca ANNULLATA non sovrascrive mai la locandina corrente (la GUI Qt ha questa
corsa nota, vedi gui/services/metadata_service.py: qui si evita, e' un errore e non una funzione).
La locandina e' un file della cache di TMDB: si espone con un numero (`/api/poster/<n>`), mai col percorso."""
import threading
from pathlib import Path
from typing import Callable, Optional

from core.services.metadata_service import TitleResolver, find_poster
from tpweb.events import EventBus


class PreviewService:
    def __init__(self, bus: EventBus, tmdb_client_factory: Callable[[], object]):
        self.bus = bus
        self._factory = tmdb_client_factory
        self._client = None
        self._titles: Optional[TitleResolver] = None
        self._lock = threading.Lock()
        self.last_path: Optional[str] = None
        self._token = 0                       # numero della ricerca corrente
        self._cancel = threading.Event()
        self.poster_id = 0
        self.poster_file: Optional[Path] = None
        self.status = 'none'                  # 'none' | 'loading' | 'found' | 'failed'
        self.title_text = ''

    @property
    def client(self):
        if self._client is None:
            self._client = self._factory()
        return self._client

    @property
    def titles(self) -> TitleResolver:
        if self._titles is None:
            self._titles = TitleResolver(self.client)
        return self._titles

    def state(self) -> dict:
        return {'path': self.last_path, 'status': self.status, 'poster_id': self.poster_id if self.status == 'found' else None}

    def select(self, path: str) -> bool:
        """La pagina ha selezionato un file: carica la locandina in background. False se e' lo stesso file di prima (nessun lavoro)."""
        with self._lock:
            if path == self.last_path:
                return False
            self._cancel.set()
            self._cancel = threading.Event()
            self._token += 1
            token, cancel = self._token, self._cancel
            self.last_path = path
            self.status = 'loading'
        self.bus.publish('poster_loading', {'path': path})

        def work():
            try:
                res = find_poster(path, self.client, cancel.is_set)
            except Exception:                  # rete assente, chiave mancante, risposta non valida: «nessuna anteprima»
                res = None
            with self._lock:
                if token != self._token:       # nel frattempo e' stato scelto un altro file: questo risultato non conta
                    return
                if res is not None and res.status == 'found' and res.path is not None:
                    self.poster_id += 1
                    self.poster_file = Path(res.path)
                    self.status = 'found'
                    event = ('poster_loaded', {'path': path, 'poster_id': self.poster_id})
                else:
                    self.status = 'failed'
                    event = ('poster_failed', {'path': path})
            self.bus.publish(*event)
        threading.Thread(target=work, name='tpweb-poster', daemon=True).start()
        return True

    def reset_last(self) -> None:
        with self._lock:
            self.last_path = None

    def clear(self) -> None:
        """La coda e' stata svuotata: cache dei titoli e locandina azzerate (come `clear_queue` della GUI)."""
        with self._lock:
            self._cancel.set()
            self._token += 1
            self.last_path = None
            self.status = 'none'
            self.poster_file = None
        if self._titles is not None:
            self._titles.clear()
        self.bus.publish('poster_cleared', {})

    def title_for(self, path: str, filename: str) -> str:
        return self.titles.title_for(path, filename)
