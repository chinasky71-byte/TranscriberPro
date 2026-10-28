# -*- coding: utf-8 -*-
"""
Library Scanner Worker - Chiamate API in background al server Library Scanner
File: gui/library_scanner_worker.py

Adattatore Qt sul client senza Qt `core/services/library_scanner_client.py` (`LibraryScannerClient`): resta un QThread con gli
stessi segnali, nello stesso ordine di prima. Richieste, messaggi d'errore e normalizzazione dell'endpoint ASS/SSA vivono nel client.
"""

from PyQt6.QtCore import QThread, pyqtSignal
import logging

from core.services.library_scanner_client import LibraryScannerClient

logger = logging.getLogger(__name__)


class LibraryScannerWorker(QThread):
    """
    Worker thread per chiamate API al server Library Scanner.
    Creato per ogni richiesta, esegue una volta e termina.
    """

    # Segnali
    data_loaded = pyqtSignal(dict)
    stats_loaded = pyqtSignal(dict)
    error = pyqtSignal(str)
    connection_status = pyqtSignal(bool)

    # Tipi richiesta
    REQUEST_VIDEOS = 'videos'
    REQUEST_STATS = 'stats'
    REQUEST_BOTH = 'both'

    def __init__(self, server_url: str, api_key: str,
                 request_type: str = 'both',
                 search: str = '',
                 media_type: str = '',
                 format_filter: str = '',
                 parent=None):
        super().__init__(parent)
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.request_type = request_type
        self.search = search
        self.media_type = media_type
        self.format_filter = format_filter
        self.timeout = 4
        self.max_retries = 0

    def _client(self) -> LibraryScannerClient:
        # Gli attributi (timeout, max_retries, ...) si leggono a ogni richiesta: chi li cambia prima di start() vale ancora.
        return LibraryScannerClient(self.server_url, self.api_key, self.timeout, self.max_retries)

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Esegue GET HTTP con retry"""
        return self._client().get(endpoint, params)

    def run(self):
        """Esegue le richieste API"""
        try:
            client = self._client()
            if self.request_type in (self.REQUEST_STATS, self.REQUEST_BOTH):
                stats = client.stats()
                self.stats_loaded.emit(stats)

            if self.request_type in (self.REQUEST_VIDEOS, self.REQUEST_BOTH):
                data = client.videos(self.search, self.media_type, self.format_filter)
                self.data_loaded.emit(data)

            self.connection_status.emit(True)

        except Exception as e:
            logger.error(f"LibraryScannerWorker error: {e}")
            self.connection_status.emit(False)
            self.error.emit(str(e))
