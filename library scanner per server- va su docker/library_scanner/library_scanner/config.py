# -*- coding: utf-8 -*-
"""
Library Scanner - Configurazione
Gestisce configurazioni da variabili d'ambiente e valori di default.
"""
import os
import re
from pathlib import Path


class Config:
    """Configurazione centralizzata del sistema."""

    # -- Percorsi --
    BASE_DIR = Path(__file__).parent.parent  # /app
    DATA_DIR = Path(os.getenv("SCANNER_DATA_DIR", "/app/data"))
    DB_PATH = Path(os.getenv("SCANNER_DB_PATH", "/app/data/db/library_scanner.db"))
    LOG_PATH = Path(os.getenv("SCANNER_LOG_PATH", "/app/data/logs"))

    # -- Server --
    HOST = os.getenv("SCANNER_HOST", "0.0.0.0")
    PORT = int(os.getenv("SCANNER_PORT", "6680"))

    # -- Sicurezza --
    ADMIN_USER = os.getenv("SCANNER_ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("SCANNER_ADMIN_PASSWORD", "")  # Vuoto = genera automatica
    API_KEY = os.getenv("SCANNER_API_KEY", "")  # Vuoto = genera automatica
    SESSION_MAX_AGE_HOURS = int(os.getenv("SCANNER_SESSION_HOURS", "24"))
    RATE_LIMIT_ATTEMPTS = int(os.getenv("SCANNER_RATE_LIMIT", "5"))
    RATE_LIMIT_WINDOW = int(os.getenv("SCANNER_RATE_WINDOW", "300"))

    # -- Scanner --
    SCAN_INTERVAL_HOURS = int(os.getenv("SCANNER_INTERVAL_HOURS", "24"))
    MIN_FILE_SIZE_MB = int(os.getenv("SCANNER_MIN_FILE_MB", "50"))
    DAYS_THRESHOLD = int(os.getenv("SCANNER_DAYS_THRESHOLD", "1"))
    MAX_CONCURRENT_FFPROBE = int(os.getenv("SCANNER_MAX_FFPROBE", "4"))

    # -- Orari silenziosi (nessuna scansione) --
    QUIET_HOURS_START = int(os.getenv("SCANNER_QUIET_START", "-1"))
    QUIET_HOURS_END = int(os.getenv("SCANNER_QUIET_END", "-1"))

    # -- Estensioni video supportate --
    VIDEO_EXTENSIONS = {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
        ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts"
    }

    # -- Estensioni sottotitoli --
    SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ass", ".ssa", ".vtt"}

    # -- Pattern lingua italiana per sottotitoli esterni --
    ITALIAN_FILENAME_TAGS = {
        ".ita.", ".it.", "_ita.", "_it.", ".italian.", "_italian.",
        ".ita_", ".it_", "-ita.", "-it."
    }

    # Regex per individuare indicatori di lingua italiana in nomi file arbitrari.
    # Copre: [ITA], (ITA), Sub ITA, sub.ita, Sub_Ita, italiano, etc.
    # \b garantisce il word-boundary → non matcha "citation", "vitale", ecc.
    ITALIAN_FILENAME_RE = re.compile(
        r'\b(?:sub[.\s_-])?ita(?:liano|lian)?\b',
        re.IGNORECASE
    )

    # -- Codici lingua italiana per ffprobe (sottotitoli embedded) --
    ITALIAN_LANG_CODES = {"ita", "it", "italian", "italiano"}

    # -- Pattern directory da escludere --
    EXCLUDED_DIR_NAMES = {
        "sample", "samples", "extras", "extra", "bonus",
        "featurettes", "behind the scenes", "deleted scenes",
        "tmp", "temp", ".tmp", ".temp", "@eadir",
        "$recycle.bin", "system volume information"
    }

    @classmethod
    def ensure_directories(cls):
        """Crea le directory necessarie se non esistono."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.LOG_PATH.mkdir(parents=True, exist_ok=True)
