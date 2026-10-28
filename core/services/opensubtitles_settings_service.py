# -*- coding: utf-8 -*-
"""Impostazioni di OpenSubtitles (upload, due serie di credenziali, metodo API, test di connessione), senza Qt.

Trasposizione fedele di gui/opensubtitles_settings_widget.py. opensubtitles.org (XML-RPC) e opensubtitles.com (REST) sono due
account separati con credenziali proprie. Il widget resta la vista: mostra i dialoghi e i testi tr() in base agli esiti."""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

IMPLEMENTATIONS = ('xmlrpc', 'rest')     # ordine delle voci della tendina


@dataclass(frozen=True)
class OsStatus:
    configured: bool
    implementation: str
    username: str            # dell'account rilevante per il metodo scelto


@dataclass(frozen=True)
class ConnectionTest:
    kind: str                # 'missing_creds' | 'ok' | 'fail' | 'error'
    implementation: str = ''
    error: str = ''


class OpenSubtitlesSettingsService:
    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------------------------------------------------- lettura
    def implementation(self) -> str:
        return self._config.get('opensubtitles_preferred_implementation', 'xmlrpc')

    def status(self) -> OsStatus:
        c = self._config
        impl = self.implementation()
        username = c.get('opensubtitles_xmlrpc_username', '') if impl == 'xmlrpc' else c.get('opensubtitles_username', '')
        return OsStatus(c.is_opensubtitles_configured(), impl, username)

    def upload_enabled(self) -> bool:
        return self._config.get('opensubtitles_upload_enabled', True)

    def credentials_com(self) -> dict:
        return self._config.get_opensubtitles_credentials()

    def credentials_org(self) -> dict:
        return self._config.get_opensubtitles_xmlrpc_credentials()

    # ----------------------------------------------------------------------------------------------------------- scrittura
    def normalize_implementation(self) -> str:
        """Un valore sconosciuto in config viene riscritto 'xmlrpc' (la GUI non deve mentire sullo stato reale)."""
        impl = self.implementation()
        if impl not in IMPLEMENTATIONS:
            self._config.set('opensubtitles_preferred_implementation', 'xmlrpc')
            return 'xmlrpc'
        return impl

    def set_implementation(self, impl) -> None:
        self._config.set('opensubtitles_preferred_implementation', impl)

    def set_upload_enabled(self, enabled: bool) -> None:
        self._config.set('opensubtitles_upload_enabled', enabled)

    def save_com(self, username: str, password: str, api_key: str) -> bool:
        """Credenziali .com (REST + traduttore AI). False, senza scrivere, se username o password sono vuoti."""
        username, password, api_key = username.strip(), password.strip(), api_key.strip()
        if not username or not password:
            return False
        self._config.set_opensubtitles_credentials(username=username, password=password, api_key=api_key)
        return True

    def save_org(self, username: str, password: str) -> bool:
        """Credenziali .org (XML-RPC). False, senza scrivere, se username o password sono vuoti."""
        username, password = username.strip(), password.strip()
        if not username or not password:
            return False
        self._config.set_opensubtitles_xmlrpc_credentials(username=username, password=password)
        return True

    # ------------------------------------------------------------------------------------------------------------- test
    def test_connection(self, on_start: Optional[Callable[[], None]] = None) -> ConnectionTest:
        """Autentica col metodo scelto. `on_start` e' chiamata dopo aver creato l'uploader e prima di autenticare."""
        impl = ''
        try:
            impl = self.implementation()
            creds = self.credentials_org() if impl == 'xmlrpc' else self.credentials_com()
            if not creds.get('username') or not creds.get('password'):
                return ConnectionTest('missing_creds', impl)

            from utils.subtitle_uploader_interface import UploaderFactory
            import utils.opensubtitles_rest_uploader  # noqa: F401  (registra l'implementazione)
            import utils.opensubtitles_xmlrpc_uploader  # noqa: F401

            uploader = UploaderFactory.create_uploader(impl, **creds)
            if on_start is not None:
                on_start()
            if uploader.authenticate():
                uploader.logout()
                return ConnectionTest('ok', impl)
            return ConnectionTest('fail', impl)
        except Exception as e:
            logger.error(f"Errore test connessione: {e}", exc_info=True)
            return ConnectionTest('error', impl, str(e))
