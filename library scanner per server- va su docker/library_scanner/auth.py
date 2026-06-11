# -*- coding: utf-8 -*-
"""
Library Scanner - Autenticazione e Sicurezza
Gestisce:
  - API Key per accesso programmatico (client Transcriber Pro)
  - Login username/password per dashboard web
  - Sessioni con cookie sicuro
  - Rate limiting per protezione brute force
"""
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from collections import defaultdict

from library_scanner.config import Config

logger = logging.getLogger(__name__)

# ============================================================================
# PASSWORD HASHING (senza dipendenze esterne)
# ============================================================================

def hash_password(password: str) -> str:
    """Genera hash sicuro della password con salt random."""
    salt = secrets.token_hex(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations=100000)
    return f"{salt}:{h.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica una password contro il suo hash."""
    try:
        salt, h = stored_hash.split(":", 1)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations=100000)
        return hmac.compare_digest(expected.hex(), h)
    except (ValueError, AttributeError):
        return False


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

class SessionManager:
    """Gestisce sessioni web con token sicuri e scadenza."""

    def __init__(self, max_age_hours: int = 24):
        self._sessions: dict = {}  # token -> {"created": timestamp, "username": str}
        self._max_age = max_age_hours * 3600

    def create_session(self, username: str) -> str:
        """Crea una nuova sessione e restituisce il token."""
        self._cleanup_expired()
        token = secrets.token_urlsafe(48)
        self._sessions[token] = {
            "created": time.time(),
            "username": username,
        }
        logger.info(f"Sessione creata per utente: {username}")
        return token

    def validate_session(self, token: str) -> Optional[str]:
        """Valida un token sessione. Restituisce username o None."""
        if not token or token not in self._sessions:
            return None
        session = self._sessions[token]
        if time.time() - session["created"] > self._max_age:
            del self._sessions[token]
            return None
        return session["username"]

    def destroy_session(self, token: str):
        """Distrugge una sessione."""
        self._sessions.pop(token, None)

    def _cleanup_expired(self):
        """Rimuove sessioni scadute."""
        now = time.time()
        expired = [t for t, s in self._sessions.items() if now - s["created"] > self._max_age]
        for t in expired:
            del self._sessions[t]


# ============================================================================
# RATE LIMITER (protezione brute force)
# ============================================================================

class RateLimiter:
    """Limita i tentativi di login per IP."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self._attempts: dict = defaultdict(list)  # ip -> [timestamps]
        self._max = max_attempts
        self._window = window_seconds

    def is_blocked(self, ip: str) -> bool:
        """Verifica se un IP e' bloccato."""
        self._cleanup(ip)
        return len(self._attempts[ip]) >= self._max

    def record_attempt(self, ip: str):
        """Registra un tentativo fallito."""
        self._cleanup(ip)
        self._attempts[ip].append(time.time())
        if len(self._attempts[ip]) >= self._max:
            logger.warning(f"Rate limit raggiunto per IP: {ip}")

    def reset(self, ip: str):
        """Reset contatore dopo login riuscito."""
        self._attempts.pop(ip, None)

    def _cleanup(self, ip: str):
        """Rimuove tentativi fuori dalla finestra temporale."""
        cutoff = time.time() - self._window
        self._attempts[ip] = [t for t in self._attempts[ip] if t > cutoff]


# ============================================================================
# AUTH MANAGER (singleton)
# ============================================================================

class AuthManager:
    """
    Gestore autenticazione centralizzato.

    Credenziali configurabili via environment variables:
      SCANNER_ADMIN_USER     (default: admin)
      SCANNER_ADMIN_PASSWORD (default: generata automaticamente al primo avvio)
      SCANNER_API_KEY        (default: generata automaticamente al primo avvio)
    """

    def __init__(self):
        self.sessions = SessionManager(max_age_hours=24)
        self.rate_limiter = RateLimiter(max_attempts=5, window_seconds=300)

        self._admin_user = Config.ADMIN_USER
        self._admin_password_hash: Optional[str] = None
        self._api_key: Optional[str] = None

        self._init_credentials()

    def _init_credentials(self):
        """Inizializza credenziali da env vars o genera nuove."""
        from library_scanner.database import get_db
        from library_scanner.models import SystemConfig
        from sqlalchemy import select

        # --- Admin Password ---
        env_password = Config.ADMIN_PASSWORD
        if env_password:
            # Password esplicita da environment
            self._admin_password_hash = hash_password(env_password)
            logger.info(f"Password admin impostata da variabile d'ambiente")
        else:
            # Cerca nel database o genera nuova
            try:
                with get_db() as db:
                    row = db.execute(
                        select(SystemConfig).where(SystemConfig.key == "admin_password_hash")
                    ).scalar_one_or_none()
                    if row:
                        self._admin_password_hash = row.value
                        logger.info("Password admin caricata dal database")
                    else:
                        # Genera password random
                        new_password = secrets.token_urlsafe(16)
                        self._admin_password_hash = hash_password(new_password)
                        db.add(SystemConfig(key="admin_password_hash", value=self._admin_password_hash))
                        logger.info("=" * 60)
                        logger.info("  PASSWORD ADMIN GENERATA AUTOMATICAMENTE")
                        logger.info(f"  Username: {self._admin_user}")
                        logger.info(f"  Password: {new_password}")
                        logger.info("  Cambiala dalla dashboard o imposta SCANNER_ADMIN_PASSWORD")
                        logger.info("=" * 60)
            except Exception as e:
                # Database non ancora pronto, genera temporanea
                new_password = secrets.token_urlsafe(16)
                self._admin_password_hash = hash_password(new_password)
                logger.warning(f"Database non pronto, password temporanea: {new_password}")

        # --- API Key ---
        env_api_key = Config.API_KEY
        if env_api_key:
            self._api_key = env_api_key
            logger.info("API key impostata da variabile d'ambiente")
        else:
            try:
                with get_db() as db:
                    row = db.execute(
                        select(SystemConfig).where(SystemConfig.key == "api_key")
                    ).scalar_one_or_none()
                    if row:
                        self._api_key = row.value
                        logger.info("API key caricata dal database")
                    else:
                        self._api_key = secrets.token_urlsafe(32)
                        db.add(SystemConfig(key="api_key", value=self._api_key))
                        logger.info("=" * 60)
                        logger.info("  API KEY GENERATA AUTOMATICAMENTE")
                        logger.info(f"  API Key: {self._api_key}")
                        logger.info("  Usala nel client Transcriber Pro")
                        logger.info("  Oppure imposta SCANNER_API_KEY")
                        logger.info("=" * 60)
            except Exception:
                self._api_key = secrets.token_urlsafe(32)
                logger.warning(f"Database non pronto, API key temporanea: {self._api_key}")

    def verify_login(self, username: str, password: str, client_ip: str) -> Optional[str]:
        """
        Verifica credenziali login web.
        Returns: session token se OK, None se fallito.
        """
        if self.rate_limiter.is_blocked(client_ip):
            logger.warning(f"Login bloccato per rate limit: {client_ip}")
            return None

        if username == self._admin_user and verify_password(password, self._admin_password_hash):
            self.rate_limiter.reset(client_ip)
            token = self.sessions.create_session(username)
            return token

        self.rate_limiter.record_attempt(client_ip)
        logger.warning(f"Login fallito per utente '{username}' da {client_ip}")
        return None

    def verify_api_key(self, key: str) -> bool:
        """Verifica API key per accesso programmatico."""
        if not key or not self._api_key:
            return False
        return hmac.compare_digest(key, self._api_key)

    def verify_session(self, token: str) -> Optional[str]:
        """Verifica sessione web. Returns username o None."""
        return self.sessions.validate_session(token)

    def logout(self, token: str):
        """Distrugge sessione."""
        self.sessions.destroy_session(token)

    def get_api_key(self) -> str:
        """Restituisce l'API key corrente (per visualizzazione in dashboard)."""
        return self._api_key or ""

    def change_password(self, current_password: str, new_password: str) -> bool:
        """Cambia la password admin."""
        if not verify_password(current_password, self._admin_password_hash):
            return False

        self._admin_password_hash = hash_password(new_password)

        # Salva nel database
        try:
            from library_scanner.database import get_db
            from library_scanner.models import SystemConfig
            from sqlalchemy import select

            with get_db() as db:
                row = db.execute(
                    select(SystemConfig).where(SystemConfig.key == "admin_password_hash")
                ).scalar_one_or_none()
                if row:
                    row.value = self._admin_password_hash
                else:
                    db.add(SystemConfig(key="admin_password_hash", value=self._admin_password_hash))
            logger.info("Password admin aggiornata")
        except Exception as e:
            logger.error(f"Errore salvando nuova password: {e}")

        return True

    def regenerate_api_key(self) -> str:
        """Rigenera l'API key."""
        self._api_key = secrets.token_urlsafe(32)

        try:
            from library_scanner.database import get_db
            from library_scanner.models import SystemConfig
            from sqlalchemy import select

            with get_db() as db:
                row = db.execute(
                    select(SystemConfig).where(SystemConfig.key == "api_key")
                ).scalar_one_or_none()
                if row:
                    row.value = self._api_key
                else:
                    db.add(SystemConfig(key="api_key", value=self._api_key))
            logger.info("API key rigenerata")
        except Exception as e:
            logger.error(f"Errore salvando nuova API key: {e}")

        return self._api_key


# Singleton
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Restituisce l'istanza singleton dell'AuthManager."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
