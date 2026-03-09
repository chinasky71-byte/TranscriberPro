"""
File __init__.py - Crea questi file nelle rispettive cartelle
"""

# ============================================================================
# FILE: gui/__init__.py
# ============================================================================
"""GUI package initialization"""
from .main_window import MainWindow
from .splash_screen import show_splash
from .widgets import ResourceMonitorWidget
from .workers import ProcessingWorker

__all__ = ['MainWindow', 'show_splash', 'ResourceMonitorWidget', 'ProcessingWorker']


# ============================================================================
# FILE: core/__init__.py
# ============================================================================
"""Core processing modules"""
from .pipeline import ProcessingPipeline
from .audio_processor import AudioProcessor
from .transcriber import Transcriber
from .translator import Translator

__all__ = ['ProcessingPipeline', 'AudioProcessor', 'Transcriber', 'Translator']


# ============================================================================
# FILE: utils/__init__.py
# ============================================================================
"""Utility modules"""
from .resource_monitor import ResourceMonitor
from .file_handler import FileHandler
from .logger import setup_logger
from .tmdb_client import TMDBClient

__all__ = ['ResourceMonitor', 'FileHandler', 'setup_logger', 'TMDBClient']
