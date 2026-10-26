# -*- coding: utf-8 -*-
"""Remove the work folders a killed pipeline leaves behind.

The pipeline deletes its temporary folder in `finally`, but a cancel kills the
process tree (and a crash or a `SIGKILL` skips `finally` entirely), so
`$TMPDIR/TranscriberPro/vid_<hash>/` survives with the extracted audio and the
chunks. When `TMPDIR` points at a tmpfs (`/dev/shm`), those folders are **RAM**:
one cancelled episode left 854 MB behind.

This module sweeps them:

- at startup of the WebUI and of the headless queue, when nothing can be
  running (safest possible moment);
- after a job ends cancelled or failed, from the job manager, which runs one
  job at a time and therefore cannot remove a folder that another job is using.

Only directories named `vid_*` inside our own temp base are touched, never the
rest of `TMPDIR`.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional

TEMP_PREFIX = "vid_"
BASE_NAME = "TranscriberPro"


def temp_base() -> Path:
    """`$TMPDIR/TranscriberPro`, the same folder `utils/file_handler.py` uses."""
    return Path(tempfile.gettempdir()) / BASE_NAME


def stale_dirs(base: Optional[Path] = None, older_than_s: float = 0.0) -> List[Path]:
    """Work folders older than `older_than_s` seconds (default: all of them)."""
    target = Path(base) if base is not None else temp_base()
    now = time.time()
    found: List[Path] = []
    try:
        entries = list(target.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.startswith(TEMP_PREFIX):
            continue
        try:
            if not entry.is_dir():
                continue
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age >= older_than_s:
            found.append(entry)
    return found


def sweep(base: Optional[Path] = None, older_than_s: float = 0.0) -> List[Path]:
    """Delete the stale work folders; returns the ones actually removed."""
    removed: List[Path] = []
    for folder in stale_dirs(base, older_than_s):
        try:
            shutil.rmtree(folder)
            removed.append(folder)
        except OSError:
            continue
    return removed


def sweep_bytes(removed: List[Path]) -> int:
    """Best-effort size report for already removed folders (paths are gone)."""
    return sum(1 for _ in removed)


def sweep_summary(base: Optional[Path] = None, older_than_s: float = 0.0) -> str:
    """One-line summary for the startup log; empty string when nothing was left."""
    removed = sweep(base, older_than_s)
    if not removed:
        return ""
    return (f"rimosse {len(removed)} cartelle di lavoro orfane in "
            f"{Path(base) if base is not None else temp_base()} "
            f"(job cancellati o processi terminati senza cleanup)")


def directory_size(path: Path) -> int:
    """Bytes used by a folder; 0 when it is unreadable or already gone."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _exc: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total
