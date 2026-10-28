# -*- coding: utf-8 -*-
"""Scansione di cartelle e dimensioni dei file, senza Qt (estratto da gui/workers.py e gui/services/queue_service.py).

Il comportamento e' quello di prima: `iter_videos` enumera ricorsivamente (rglob) i file con le estensioni date, nell'ordine di
`Path.rglob`, e si ferma se `cancelled()` e' vero; un errore di lettura interrompe l'enumerazione senza sollevare. La dimensione si
scrive con `format_file_size` («500 B», «2 KB», «1.5 TB»; stringa vuota se negativa o illeggibile)."""
import logging
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']


def format_file_size(nbytes: float) -> str:
    """500 → '500 B', 1536 → '2 KB', ... Stringa vuota per valori negativi."""
    if nbytes < 0:
        return ''
    s = float(nbytes)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if s < 1024:
            return f'{s:.0f} {unit}'
        s /= 1024
    return f'{s:.1f} TB'


def size_text(path: str) -> str:
    """Dimensione leggibile di un file; vuota se non si riesce a leggerla (share non raggiungibile, file sparito)."""
    try:
        return format_file_size(Path(path).stat().st_size)
    except Exception:
        return ''


def iter_videos(folder: str, extensions: List[str], cancelled: Optional[Callable[[], bool]] = None) -> Iterator[Tuple[str, str]]:
    """(percorso, dimensione leggibile) di ogni file con una delle estensioni, in tutta la cartella."""
    exts = [e.lower() for e in extensions]
    try:
        for f_path in Path(folder).rglob('*'):
            if cancelled is not None and cancelled():
                break
            if f_path.suffix.lower() not in exts:
                continue
            try:
                size = format_file_size(f_path.stat().st_size)
            except Exception:
                size = ''
            yield str(f_path), size
    except Exception as e:
        logger.warning(f"iter_videos: errore scansione: {e}")
