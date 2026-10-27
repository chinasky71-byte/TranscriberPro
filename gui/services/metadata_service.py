# -*- coding: utf-8 -*-
"""
MetadataService: locandina TMDB (caricamento asincrono) e titolo mostrato sotto la locandina.

Estratto da MainWindow SENZA cambiare semantica:
  - guardia `last_loaded_file`: lo stesso file non ricarica (la vista la azzera per forzare il reload)
  - un worker ancora in corso viene annullato e atteso (wait 500 ms) prima di crearne uno nuovo
  - i segnali del worker PRECEDENTE restano collegati (race nota: un risultato tardivo puo' sovrascrivere
    la locandina corrente). NON correggere qui: e' un limite noto, fuori dallo scopo del refactoring.
  - il titolo "Nome show SxxExx" e' calcolato una volta per file e messo in cache; quello provvisorio
    (anime senza stagione risolta) e' rivalutato al massimo ogni 5 s.

Niente QtWidgets: la vista (MainWindow) riceve i segnali e scrive nelle etichette.
"""
from PyQt6.QtCore import QObject, pyqtSignal

from core.services.metadata_service import TitleResolver
from gui.workers import PosterLoaderWorker


class MetadataService(QObject):
    poster_loading = pyqtSignal(str)   # emesso PRIMA di creare il worker (la vista mostra "caricamento...")
    poster_loaded = pyqtSignal(object)  # QPixmap
    poster_failed = pyqtSignal()

    def __init__(self, tmdb_client, parent=None):
        super().__init__(parent)
        self._titles = TitleResolver(tmdb_client)     # logica del titolo: core/services/metadata_service.py (senza Qt)
        self.last_loaded_file = None
        self.poster_worker = None

    # letto a ogni chiamata (mai copiato): chi lo sostituisce a runtime (test) viene rispettato
    @property
    def tmdb_client(self):
        return self._titles.tmdb_client

    @tmdb_client.setter
    def tmdb_client(self, value):
        self._titles.tmdb_client = value

    @property
    def overlay_title_cache(self) -> dict:
        return self._titles.cache

    @property
    def overlay_title_provisional(self) -> dict:
        return self._titles.provisional

    # ------------------------------------------------------------------ locandina
    def load_poster(self, video_path: str):
        if video_path == self.last_loaded_file: return
        if self.poster_worker and self.poster_worker.isRunning():
            self.poster_worker.cancel()
            self.poster_worker.wait(500)
        self.last_loaded_file = video_path
        self.poster_loading.emit(video_path)
        self.poster_worker = PosterLoaderWorker(video_path, self.tmdb_client)
        self.poster_worker.poster_loaded.connect(self._on_worker_loaded)
        self.poster_worker.poster_failed.connect(self._on_worker_failed)
        self.poster_worker.start()

    def reset_last_loaded(self):
        """Azzera la guardia: il prossimo load_poster ricarica anche lo stesso file."""
        self.last_loaded_file = None

    def _on_worker_loaded(self, pixmap):
        self.poster_loaded.emit(pixmap)

    def _on_worker_failed(self):
        self.poster_failed.emit()

    # ------------------------------------------------------------------ titolo
    def clear_title_caches(self):
        self._titles.clear()

    def overlay_title_for(self, path: str, filename: str) -> str:
        """'Nome show SxxExx' per le serie; per i film solo il titolo (logica in core/services/metadata_service.py)."""
        return self._titles.title_for(path, filename)
