"""
GUI Package Initialization
File: gui/__init__.py

VERSIONE: v2.0 - Fixed imports con gestione dipendenze circolari

Esporta tutti i componenti GUI principali:
- MainWindow (finestra principale)
- Workers (thread di elaborazione)
- Widgets (componenti UI riutilizzabili)
- Dialogs (finestre di dialogo)
- Splash screen
"""

# Importazioni principali - sempre disponibili
from .main_window import MainWindow
from .workers import ProcessingWorker

# Importazioni opzionali - gestione graceful se mancanti
try:
    from .splash_screen import show_splash
except ImportError:
    show_splash = None

try:
    from .widgets import ResourceMonitorWidget
except ImportError:
    ResourceMonitorWidget = None

try:
    from .audio_track_selector import AudioTrackSelector
except ImportError:
    AudioTrackSelector = None

try:
    from .profile_dialog import ProfileDialog
except ImportError:
    ProfileDialog = None

try:
    from .translation_settings_dialog import TranslationSettingsDialog
except ImportError:
    TranslationSettingsDialog = None

try:
    from .translation_model_dialog import TranslationModelDialog
except ImportError:
    TranslationModelDialog = None

try:
    from .opensubtitles_settings_widget import OpenSubtitlesSettingsWidget
except ImportError:
    OpenSubtitlesSettingsWidget = None

try:
    from .library_scanner_widget import LibraryScannerWidget
except ImportError:
    LibraryScannerWidget = None


__all__ = [
    'MainWindow',
    'ProcessingWorker',
]

# Aggiungi export opzionali se disponibili
if show_splash is not None:
    __all__.append('show_splash')

if ResourceMonitorWidget is not None:
    __all__.append('ResourceMonitorWidget')

if AudioTrackSelector is not None:
    __all__.append('AudioTrackSelector')

if ProfileDialog is not None:
    __all__.append('ProfileDialog')

if TranslationSettingsDialog is not None:
    __all__.append('TranslationSettingsDialog')

if TranslationModelDialog is not None:
    __all__.append('TranslationModelDialog')

if OpenSubtitlesSettingsWidget is not None:
    __all__.append('OpenSubtitlesSettingsWidget')

if LibraryScannerWidget is not None:
    __all__.append('LibraryScannerWidget')
