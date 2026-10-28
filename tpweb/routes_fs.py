# -*- coding: utf-8 -*-
"""Navigatore del file system (fetta 1d): sostituisce i dialoghi di file quando non c'e' il guscio nativo (8 punti della GUI).
Elenca radici (dischi Windows, root e home su Linux, cartelle montate della mappa del Library Scanner), cartelle e file.
Sola lettura. Nessun percorso relativo: serve un percorso assoluto."""
import os
import string
import sys
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from core.services.file_scan import VIDEO_EXTENSIONS, format_file_size


def list_roots(extra: Optional[List[str]] = None) -> List[dict]:
    roots: List[dict] = []
    if os.name == 'nt':
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << i):
                roots.append({'name': f'{letter}:\\', 'path': f'{letter}:\\', 'kind': 'drive'})
    else:
        roots.append({'name': '/', 'path': '/', 'kind': 'root'})
    roots.insert(0, {'name': 'Home', 'path': str(Path.home()), 'kind': 'home'})
    for p in extra or []:
        if p and all(r['path'] != p for r in roots):
            roots.append({'name': p, 'path': p, 'kind': 'mapped'})
    return roots


def list_dir(path: str, exts: Optional[List[str]] = None, show_hidden: bool = False) -> dict:
    """Cartelle (sempre) e file (con una delle estensioni, tutti se `exts` e' None), ordinati senza badare alle maiuscole."""
    p = Path(path)
    dirs, files = [], []
    with os.scandir(p) as it:
        for e in it:
            if not show_hidden and e.name.startswith('.'):
                continue
            try:
                if e.is_dir():
                    dirs.append({'name': e.name, 'path': str(Path(e.path))})
                elif e.is_file() and (exts is None or Path(e.name).suffix.lower() in exts):
                    st = e.stat()
                    files.append({'name': e.name, 'path': str(Path(e.path)), 'size': format_file_size(st.st_size),
                                  'mtime': st.st_mtime})
            except OSError:
                continue            # file sparito o non leggibile durante la lettura della cartella
    key = lambda d: d['name'].lower()           # noqa: E731
    parent = str(p.parent) if p.parent != p else None
    return {'path': str(p), 'parent': parent, 'dirs': sorted(dirs, key=key), 'files': sorted(files, key=key)}


def add_fs_routes(app: FastAPI, mapped_roots=lambda: []) -> None:
    @app.get('/api/fs/roots')
    async def roots():
        return {'roots': list_roots(mapped_roots())}

    @app.get('/api/fs/list')
    async def ls(path: str, exts: Optional[str] = Query(None, description="'.mkv,.mp4'; vuoto = tutti i file"),
                 hidden: bool = False):
        if not os.path.isabs(path) and not (os.name == 'nt' and path.startswith('\\\\')):
            return JSONResponse({'error': 'serve un percorso assoluto'}, status_code=422)
        want = [e.strip().lower() for e in exts.split(',') if e.strip()] if exts else None
        try:
            return list_dir(path, want, hidden)
        except FileNotFoundError:
            return JSONResponse({'error': 'cartella inesistente'}, status_code=404)
        except NotADirectoryError:
            return JSONResponse({'error': 'non e una cartella'}, status_code=422)
        except PermissionError:
            return JSONResponse({'error': 'accesso negato'}, status_code=403)
        except OSError as e:
            return JSONResponse({'error': str(e)}, status_code=500)

    @app.get('/api/fs/video-extensions')
    async def video_exts():
        return {'exts': VIDEO_EXTENSIONS}
