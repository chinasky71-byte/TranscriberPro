"""
Logging configuration - FIXED for Windows UTF-8
File: utils/logger.py
"""
import logging
import sys
import io
import unicodedata
from pathlib import Path
from datetime import datetime


def _strip_emoji(text: str) -> str:
    """Rimuove emoji e simboli grafici dal testo per output console DOS Windows."""
    result = []
    for c in text:
        cp = ord(c)
        # Caratteri nel Supplementary Plane (U+10000+): quasi tutte le emoji moderne
        if cp > 0xFFFF:
            continue
        # Simboli "Other" (categoria So): emoji BMP come checkmark, stelle, ecc.
        if unicodedata.category(c) == 'So':
            continue
        result.append(c)
    return ''.join(result)

def setup_logger(name='TranscriberPro', log_dir=None):
    """
    Setup application logger with Windows UTF-8 fix
    """
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create log directory
    if log_dir is None:
        log_dir = Path.home() / '.transcriberpro' / 'logs'
    else:
        log_dir = Path(log_dir)
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    
    # ========================================
    # FILE HANDLER - UTF-8 (già OK)
    # ========================================
    log_file = log_dir / f'transcriber_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)
    
    # ========================================
    # CONSOLE HANDLER - FIX UTF-8 per Windows
    # ========================================
    try:
        # Prova a riconfigurare stdout per UTF-8
        if sys.platform == 'win32':
            # Wrap stdout con UTF-8 encoding
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding='utf-8',
                errors='replace',  # Sostituisci caratteri problematici
                line_buffering=True
            )
    except Exception as e:
        # Se fallisce, continua senza UTF-8 nel console
        pass
    
    # Console handler con gestione errori
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # Gestione errori di encoding
    class SafeStreamHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                msg_safe = _strip_emoji(msg)
                self.stream.write(msg_safe + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)
    
    # Usa SafeStreamHandler invece di StreamHandler normale
    safe_console = SafeStreamHandler(sys.stdout)
    safe_console.setLevel(logging.INFO)
    safe_console.setFormatter(simple_formatter)
    logger.addHandler(safe_console)
    
    logger.info(f"Logger initialized. Log file: {log_file}")
    
    return logger
