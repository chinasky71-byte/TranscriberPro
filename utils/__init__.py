"""
Utils Package Initialization
File: utils/__init__.py

VERSIONE: v4.0 - Complete Utils Package

Esporta tutti i componenti utility:
- Configurazione
- Gestione file
- Logging
- Resource monitoring
- TMDB client
- IMDb client
- OpenSubtitles integration
"""

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
    from .opensubtitles_client import OpenSubtitlesClient, get_opensubtitles_client
except ImportError:
    OpenSubtitlesClient = None
    get_opensubtitles_client = None

try:
    from .imdb_client import IMDbClient, get_imdb_client
except ImportError:
    IMDbClient = None
    get_imdb_client = None

try:
    from .opensubtitles_config import OpenSubtitlesConfig, get_opensubtitles_config
except ImportError:
    OpenSubtitlesConfig = None
    get_opensubtitles_config = None

try:
    from .opensubtitles_integration import OpenSubtitlesIntegration
except ImportError:
    OpenSubtitlesIntegration = None

try:
    from .subtitle_uploader_interface import (
        SubtitleUploaderInterface,
        SubtitleMetadata,
        UploaderFactory
    )
except ImportError:
    SubtitleUploaderInterface = None
    SubtitleMetadata = None
    UploaderFactory = None

try:
    from .opensubtitles_xmlrpc_uploader import OpenSubtitlesXMLRPCUploader
except ImportError:
    OpenSubtitlesXMLRPCUploader = None

try:
    from .opensubtitles_rest_uploader import OpenSubtitlesRESTUploader
except ImportError:
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
if OpenSubtitlesClient is not None:
    __all__.extend(['OpenSubtitlesClient', 'get_opensubtitles_client'])

if IMDbClient is not None:
    __all__.extend(['IMDbClient', 'get_imdb_client'])

if OpenSubtitlesConfig is not None:
    __all__.extend(['OpenSubtitlesConfig', 'get_opensubtitles_config'])

if OpenSubtitlesIntegration is not None:
    __all__.append('OpenSubtitlesIntegration')

if SubtitleUploaderInterface is not None:
    __all__.extend(['SubtitleUploaderInterface', 'SubtitleMetadata', 'UploaderFactory'])

if OpenSubtitlesXMLRPCUploader is not None:
    __all__.append('OpenSubtitlesXMLRPCUploader')

if OpenSubtitlesRESTUploader is not None:
    __all__.append('OpenSubtitlesRESTUploader')
