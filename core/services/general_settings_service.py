# -*- coding: utf-8 -*-
"""Impostazioni generali (lingua dell'interfaccia, Library Scanner), senza Qt.

Trasposizione fedele della logica di gui/general_settings_widget.py: quali chiavi di config si leggono e si scrivono, come si
normalizzano i valori e come si prova la connessione al Library Scanner. Il widget resta la vista."""
from typing import Tuple

LANGUAGES = ('auto', 'it', 'en')     # ordine delle voci della tendina


def language_index(pref: str) -> int:
    """Indice della voce per la preferenza salvata (sconosciuta -> 'auto')."""
    return LANGUAGES.index(pref) if pref in LANGUAGES else 0


def language_at(index: int) -> str:
    return LANGUAGES[index]


class GeneralSettingsService:
    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------------------------------------------------- lingua
    def language(self) -> str:
        return self._config.get('language', 'auto')

    def set_language(self, code: str) -> None:
        self._config.set('language', code)

    # --------------------------------------------------------------------------------------------------- Library Scanner
    def scanner_url(self) -> str:
        return self._config.get('library_scanner_url', '')

    def set_scanner_url(self, value: str) -> str:
        value = value.strip()
        self._config.set('library_scanner_url', value)
        return value

    def scanner_api_key(self) -> str:
        return self._config.get('library_scanner_api_key', '')

    def set_scanner_api_key(self, value: str) -> str:
        value = value.strip()
        self._config.set('library_scanner_api_key', value)
        return value

    def scanner_path_map(self) -> str:
        return self._config.get('library_scanner_path_map', '')

    def set_scanner_path_map(self, text: str) -> bool:
        """Salva solo se cambia (niente scrittura su disco inutile). True se ha scritto."""
        if text != self._config.get('library_scanner_path_map', ''):
            self._config.set('library_scanner_path_map', text)
            return True
        return False


def ping_scanner(url: str, api_key: str) -> Tuple[bool, str]:
    """Prova la connessione al Library Scanner (GET /api/stats, 4 s). (ok, messaggio)."""
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/stats", headers={'X-API-Key': api_key}, timeout=4)
        r.raise_for_status()
        return True, f"Connesso — HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)
