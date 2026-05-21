"""
Main Application Entry Point
File: main.py
"""
# pythonw.exe non ha console: sys.stdout/stderr sono None.
# Demucs, tqdm e altre librerie scrivono su di essi → crash immediato.
# stdout → devnull (output non utile); stderr → file di log (cattura eccezioni Qt).
import sys, os  # noqa: E401
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    import pathlib
    _stderr_log = pathlib.Path.home() / '.transcriberpro' / 'pythonw_stderr.log'
    _stderr_log.parent.mkdir(exist_ok=True)
    sys.stderr = open(str(_stderr_log), 'w', buffering=1, encoding='utf-8')

# Cache bootstrap: redireziona HF_HOME, TORCH_HOME nella cartella progetto.
# DEVE stare prima di qualsiasi import che tocchi torch/transformers/HF/onnxruntime.
import utils.cache_bootstrap  # noqa: F401

import sys
import warnings
import logging
from pathlib import Path

warnings.filterwarnings("ignore", message="In 2.9, this function's implementation")

# onnxruntime deve essere importato PRIMA di PyQt6.
# Qt6 carica DLL che confliggono con onnxruntime_pybind11_state se importato dopo.
import onnxruntime as _ort  # noqa: F401 (usato da faster-whisper VAD)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont

from utils.logger import setup_logger
from utils.translations import init_language, tr


# ── Versione applicazione — unica fonte di verità ─────────────────────────────
APP_VERSION = "1.3.8"

PROJECT_ROOT      = Path(__file__).resolve().parent
ASSETS_FONTS_DIR  = PROJECT_ROOT / 'assets' / 'fonts'
THEME_QSS_PATH    = PROJECT_ROOT / 'gui' / 'theme.qss'


# ── Helper di avvio ───────────────────────────────────────────────────────────

def _load_application_fonts(logger):
    """Carica i font UI dal repository (Inter Tight + JetBrains Mono)."""
    if not ASSETS_FONTS_DIR.exists():
        logger.warning(f"Cartella font non trovata: {ASSETS_FONTS_DIR}")
        return
    loaded = 0
    for ttf in ASSETS_FONTS_DIR.glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid < 0:
            logger.warning(f"Font NON caricato: {ttf.name}")
        else:
            loaded += 1
    logger.info(f"Font applicazione caricati: {loaded}")


def _apply_global_stylesheet(app, logger):
    """Carica e applica il QSS globale (gui/theme.qss)."""
    if not THEME_QSS_PATH.exists():
        logger.warning(f"theme.qss non trovato: {THEME_QSS_PATH}")
        return
    try:
        qss = THEME_QSS_PATH.read_text(encoding='utf-8')
        app.setStyleSheet(qss)
        logger.info(f"Tema applicato: {THEME_QSS_PATH.name} ({len(qss)} char)")
    except Exception as e:
        logger.error(f"Errore caricamento theme.qss: {e}")


def _check_gpu(logger):
    """Rileva GPU disponibile e logga nome e VRAM."""
    try:
        import torch
        if torch.cuda.is_available():
            name   = torch.cuda.get_device_name(0)
            vram   = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            logger.info(f"GPU: {name} — {vram:.1f} GB VRAM")
        else:
            logger.info("CUDA non disponibile — elaborazione su CPU")
    except ImportError:
        logger.info("PyTorch non importabile durante check GPU")


def _verify_model_paths(config, logger):
    """Verifica esistenza dei percorsi modello configurati (solo Path.exists, no loading)."""
    checks = {
        'Whisper':          config.get('whisper_model_path', ''),
        'Gender corrector': config.get('gender_correction_model_path', ''),
    }
    for name, path in checks.items():
        if not path:
            logger.info(f"  {name}: non configurato")
        elif Path(path).exists():
            logger.info(f"  {name}: ✓ trovato")
        else:
            logger.warning(f"  {name}: ✗ non trovato — {path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info(f"Transcriber Pro v{APP_VERSION} — Avvio")
    logger.info("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("Transcriber Pro")
    app.setOrganizationName("TranscriberPro")
    app.setStyle("Fusion")

    # Config e lingua caricati prima dello splash (< 20 ms, impercettibili)
    from utils.config import get_config
    config = get_config()
    init_language(config)

    # ── Splash: prima cosa visibile all'utente ────────────────────────────────
    from gui.splash_screen import SplashScreen
    splash = SplashScreen(version=APP_VERSION)
    splash.show()
    app.processEvents()

    # Step 1 — Font
    splash.update_progress(15, tr('splash_loading_fonts'))
    _load_application_fonts(logger)
    app.setFont(QFont("Inter Tight", 10))

    # Step 2 — Tema
    splash.update_progress(30, tr('splash_loading_theme'))
    _apply_global_stylesheet(app, logger)

    # Step 3 — GPU
    splash.update_progress(50, tr('checking_gpu'))
    _check_gpu(logger)

    # Step 4 — Percorsi modelli
    splash.update_progress(65, tr('splash_checking_models'))
    _verify_model_paths(config, logger)

    # Step 5 — MainWindow
    splash.update_progress(85, tr('splash_loading_window'))
    from gui.main_window import MainWindow
    main_window = MainWindow()

    # Done
    splash.update_progress(100, tr('ready'))
    app.processEvents()

    # Chiude splash e mostra la finestra principale
    splash.finish(main_window)
    main_window.show()

    logger.info("Interfaccia grafica inizializzata")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
