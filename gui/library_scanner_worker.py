# -*- coding: utf-8 -*-
"""
Library Scanner Worker - Chiamate API in background al server Library Scanner
File: gui/library_scanner_worker.py
"""

from PyQt6.QtCore import QThread, pyqtSignal
import requests
import logging

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
                 parent=None):
        super().__init__(parent)
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.request_type = request_type
        self.search = search
        self.media_type = media_type
        self.timeout = 5
        self.max_retries = 1

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Esegue GET HTTP con retry"""
        headers = {'X-API-Key': self.api_key}
        url = f"{self.server_url}{endpoint}"

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.ConnectionError:
                last_error = f"Server non raggiungibile: {self.server_url}"
            except requests.exceptions.Timeout:
                last_error = f"Timeout connessione ({self.timeout}s)"
            except requests.exceptions.HTTPError as e:
                last_error = f"Errore HTTP: {e.response.status_code}"
                break
            except Exception as e:
                last_error = f"Errore: {str(e)}"

        raise ConnectionError(last_error)

    def run(self):
        """Esegue le richieste API"""
        try:
            if self.request_type in (self.REQUEST_STATS, self.REQUEST_BOTH):
                stats = self._make_request('/api/stats')
                self.stats_loaded.emit(stats)

            if self.request_type in (self.REQUEST_VIDEOS, self.REQUEST_BOTH):
                params = {
                    'no_subs_only': 'true',
                    'limit': 500,
                    'offset': 0,
                    'sort_by': 'first_seen',
                    'sort_order': 'desc',
                }
                if self.search:
                    params['search'] = self.search
                if self.media_type:
                    params['media_type'] = self.media_type

                data = self._make_request('/api/videos', params)
                self.data_loaded.emit(data)

            self.connection_status.emit(True)

        except Exception as e:
            logger.error(f"LibraryScannerWorker error: {e}")
            self.connection_status.emit(False)
            self.error.emit(str(e))
