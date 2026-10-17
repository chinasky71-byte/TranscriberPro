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
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from gui.workers import PosterLoaderWorker


class MetadataService(QObject):
    poster_loading = pyqtSignal(str)   # emesso PRIMA di creare il worker (la vista mostra "caricamento...")
    poster_loaded = pyqtSignal(object)  # QPixmap
    poster_failed = pyqtSignal()

    def __init__(self, tmdb_client, parent=None):
        super().__init__(parent)
        # letto a ogni chiamata (mai copiato): chi lo sostituisce a runtime (test) viene rispettato
        self.tmdb_client = tmdb_client
        self.last_loaded_file = None
        self.poster_worker = None
        self.overlay_title_cache = {}
        # chiave -> (etichetta provvisoria, istante): rivalutata ogni pochi secondi
        self.overlay_title_provisional = {}

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
        self.overlay_title_cache.clear()
        self.overlay_title_provisional.clear()

    def overlay_title_for(self, path: str, filename: str) -> str:
        """'Nome show SxxExx' per le serie; per i film solo il titolo. Calcolato una volta per file
        (parse_filename scrive righe di debug: non va chiamato a ogni tick di avanzamento).
        Anime con solo il numero assoluto ("Titolo.E01"): SxxExx appena la ricerca TMDB ha risolto la
        stagione (resolved_episode); fino ad allora "Titolo E01" e il risultato NON viene messo in cache."""
        key = path or filename
        cached = self.overlay_title_cache.get(key)
        if cached is not None:
            return cached
        # Titolo provvisorio (stagione non ancora risolta da TMDB): si rivaluta al massimo ogni 5 s, non a ogni
        # aggiornamento della barra (fino a ~99 per file), cosi' parse_filename non scrive debug a raffica.
        prov = self.overlay_title_provisional.get(key)
        now = time.monotonic()
        if prov is not None and (now - prov[1]) < 5.0:
            return prov[0]
        label = Path(filename or path).stem
        final = True
        try:
            parsed = self.tmdb_client.parse_filename(filename or Path(path).name)
            title = (parsed.get('title') or '').strip()
            if title:
                season, episode = parsed.get('season'), parsed.get('episode')
                absolute = parsed.get('absolute')
                # season < 100: 'The.Corporation.720x480' non e' una stagione 720
                if parsed.get('type') == 'tv' and season is not None and episode is not None and int(season) < 100:
                    label = f"{title} S{int(season):02d}E{int(episode):02d}"
                elif parsed.get('type') == 'tv' and absolute is not None:
                    resolved = self.tmdb_client.resolved_episode(title, absolute, parsed.get('year'))
                    if resolved:
                        label = f"{title} S{int(resolved[0]):02d}E{int(resolved[1]):02d}"
                    else:
                        label = f"{title} E{int(absolute):02d}"
                        final = False
                else:
                    label = title
            elif parsed.get('type') == 'movie':
                # titolo vuoto (es. '1917.2019.1080p'): stessa pulizia usata per la ricerca, non il nome grezzo
                label = (self.tmdb_client._clean_title(self.tmdb_client._pre_clean_title(label)) or label)
        except Exception:
            pass
        if final:
            self.overlay_title_cache[key] = label
            self.overlay_title_provisional.pop(key, None)
        else:
            self.overlay_title_provisional[key] = (label, now)
        return label
