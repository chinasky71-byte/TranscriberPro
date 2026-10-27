# -*- coding: utf-8 -*-
"""Client HTTP del server Library Scanner, senza Qt e senza GUI.

Trasposizione fedele dei tre worker di gui/library_scanner_worker.py e gui/library_scanner_widget.py (`LibraryScannerWorker`,
`_NotifyWorker`, `_ApiCallWorker`): stesse richieste (metodo, percorso, parametri, intestazione `X-API-Key`), stessi messaggi d'errore,
stessa normalizzazione dell'endpoint ASS/SSA. I worker restano gli adattatori Qt (thread e segnali)."""
import logging
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 4
FORMAT_ASS = 'assssa'


class LibraryScannerClient:
    def __init__(self, server_url: str, api_key: str, timeout=DEFAULT_TIMEOUT, max_retries: int = 0):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------------------------------------------------------ GET
    def get(self, endpoint: str, params: dict = None) -> dict:
        """GET HTTP con retry (solo sugli errori di rete: un errore HTTP interrompe subito). Solleva ConnectionError con un messaggio
        leggibile."""
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

    def stats(self) -> dict:
        return self.get('/api/stats')

    def videos(self, search: str = '', media_type: str = '', format_filter: str = '') -> dict:
        """Elenco dei video senza sottotitoli (o, con il filtro ASS/SSA, di quelli convertibili)."""
        if format_filter == FORMAT_ASS:
            # Endpoint dedicato: restituisce TUTTI i file con ASS/SSA,
            # inclusi quelli con has_any_italian_sub=True (non visibili in /api/videos).
            params = {'issue_type': 'convertible', 'limit': 500, 'offset': 0}
            data = self.get('/api/subtitles/list', params)
            # Normalizza campi assenti nell'endpoint subtitle
            for v in data.get('videos', []):
                v.setdefault('days_without_subs', 0)
                v.setdefault('has_any_italian_sub', True)
                v.setdefault('first_seen', None)
            return data
        params = {
            'no_subs_only': 'true',
            'limit': 500,
            'offset': 0,
            'sort_by': 'first_seen',
            'sort_order': 'desc',
        }
        if search:
            params['search'] = search
        if media_type:
            params['media_type'] = media_type
        return self.get('/api/videos', params)

    # ----------------------------------------------------------------------------------------------------------------- POST
    def notify_subtitle(self, windows_path: str) -> bool:
        """POST /api/videos/notify-subtitle (fire-and-forget). True solo con HTTP 200; qualsiasi eccezione -> False."""
        try:
            resp = requests.post(
                f"{self.server_url}/api/videos/notify-subtitle",
                json={"windows_path": windows_path},
                headers={"X-API-Key": self.api_key},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False


def call_api(method: str, url: str, api_key: str, json_body=None, params=None, timeout: int = 10) -> Tuple[int, str]:
    """Chiamata generica (conversione ASS, elenco Superpower). (status, corpo); (0, messaggio) se la connessione fallisce."""
    try:
        r = requests.request(
            method, url,
            json=json_body, params=params,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)
