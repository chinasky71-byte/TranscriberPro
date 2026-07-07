"""
Logging configuration - FIXED for Windows UTF-8
File: utils/logger.py
"""
import logging
import os
import sys
import io
import unicodedata
from pathlib import Path
from datetime import datetime


# File handler condiviso tra tutti i logger dell'app: creato una sola volta,
# così ogni modulo (anche con nome diverso, es. "core.pipeline") scrive nello
# STESSO file invece di generarne uno separato per nome.
_shared_file_handler = None
_shared_log_file = None
_stdout_reconfigured = False


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
    Setup application logger with Windows UTF-8 fix.

    Tutti i logger dell'app condividono UN unico file di log per sessione
    (handler condiviso), a prescindere dal `name` passato: così i moduli con
    nome distinto (es. "core.pipeline") non generano file separati.
    """
    global _shared_file_handler, _shared_log_file, _stdout_reconfigured

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
    # FILE HANDLER - UTF-8, CONDIVISO tra tutti i logger
    # ========================================
    # Creato una sola volta: il primo setup_logger() della sessione crea il
    # file, tutti i successivi riusano lo stesso handler → un unico file.
    if _shared_file_handler is None:
        _shared_log_file = log_dir / f'transcriber_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        _shared_file_handler = logging.FileHandler(_shared_log_file, encoding='utf-8')
        _shared_file_handler.setLevel(logging.DEBUG)
        _shared_file_handler.setFormatter(detailed_formatter)
    logger.addHandler(_shared_file_handler)

    # ========================================
    # CONSOLE HANDLER - FIX UTF-8 per Windows
    # ========================================
    try:
        # Riconfigura stdout per UTF-8 una sola volta (evita di re-wrappare
        # ad ogni chiamata di setup_logger).
        if sys.platform == 'win32' and not _stdout_reconfigured:
            # Wrap stdout con UTF-8 encoding
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding='utf-8',
                errors='replace',  # Sostituisci caratteri problematici
                line_buffering=True
            )
            _stdout_reconfigured = True
    except Exception as e:
        # Se fallisce, continua senza UTF-8 nel console
        pass

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

    # Console: solo WARNING ed ERROR (INFO/DEBUG già nel file di log e nella GUI).
    # Nei subprocess isolati (TP_SUBPROCESS) NON aggiungiamo il console handler:
    # lì sys.stdout è la pipe catturata dal worker e deve restare pulita (solo
    # i messaggi _emit della pipeline), altrimenti i logger.warning delle
    # librerie finirebbero a schermo nel QTextEdit del parent.
    if not os.environ.get('TP_SUBPROCESS'):
        safe_console = SafeStreamHandler(sys.stdout)
        safe_console.setLevel(logging.WARNING)
        safe_console.setFormatter(simple_formatter)
        logger.addHandler(safe_console)
    
    logger.info(f"Logger initialized. Log file: {_shared_log_file}")
    
    return logger
