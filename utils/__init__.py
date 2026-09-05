"""
Utils Package Initialization
File: utils/__init__.py

VERSIONE: v4.4 - Rimossi opensubtitles_client/opensubtitles_integration/
opensubtitles_config (mai realmente usati in produzione, fuorvianti: il
secondo fingeva sempre successo senza chiamare alcuna API)

Esporta tutti i componenti utility:
- Configurazione
- Gestione file
- Logging
- Resource monitoring
- TMDB client
- IMDb client
- OpenSubtitles upload (REST/XML-RPC)
"""

import logging

# Core utilities
from .resource_monitor import ResourceMonitor
from .file_handler import FileHandler
from .logger import setup_logger
from .config import Config, get_config

# TMDB client
from .tmdb_client import TMDBClient, get_tmdb_client

# Transcription profiles
from .transcription_profiles import ProfileConfig, TranscriptionProfile

# Optional imports (possono non essere presenti)
try:
    from .imdb_client import IMDbClient, get_imdb_client
except ImportError:
    IMDbClient = None
    get_imdb_client = None

try:
    from .subtitle_uploader_interface import (
        SubtitleUploaderInterface,
        SubtitleMetadata,
        UploaderFactory,
        OPENSUBTITLES_USER_AGENT
    )
except ImportError as e:
    logging.getLogger(__name__).warning(f"subtitle_uploader_interface non disponibile: {e}")
    SubtitleUploaderInterface = None
    SubtitleMetadata = None
    UploaderFactory = None
    OPENSUBTITLES_USER_AGENT = None

try:
    from .opensubtitles_xmlrpc_uploader import OpenSubtitlesXMLRPCUploader
except ImportError as e:
    logging.getLogger(__name__).warning(f"OpenSubtitlesXMLRPCUploader non disponibile: {e}")
    OpenSubtitlesXMLRPCUploader = None

try:
    from .opensubtitles_rest_uploader import OpenSubtitlesRESTUploader
except ImportError as e:
    logging.getLogger(__name__).warning(f"OpenSubtitlesRESTUploader non disponibile: {e}")
    OpenSubtitlesRESTUploader = None


# Base exports
__all__ = [
    'ResourceMonitor',
    'FileHandler',
    'setup_logger',
    'Config',
    'get_config',
    'TMDBClient',
    'get_tmdb_client',
    'ProfileConfig',
    'TranscriptionProfile',
]

# Add optional exports if available
if IMDbClient is not None:
    __all__.extend(['IMDbClient', 'get_imdb_client'])

if SubtitleUploaderInterface is not None:
    __all__.extend(['SubtitleUploaderInterface', 'SubtitleMetadata', 'UploaderFactory', 'OPENSUBTITLES_USER_AGENT'])

if OpenSubtitlesXMLRPCUploader is not None:
    __all__.append('OpenSubtitlesXMLRPCUploader')

if OpenSubtitlesRESTUploader is not None:
    __all__.append('OpenSubtitlesRESTUploader')
