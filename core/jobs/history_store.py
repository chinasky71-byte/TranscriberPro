# -*- coding: utf-8 -*-
"""Cronologia dei file elaborati (~/.transcriberpro/history.json), senza Qt: stesso file e stesso formato che
`gui/history_widget.py::HistoryWidget` legge e scrive (lista JSON di voci, indent 2), cosi' le voci aggiunte dalla coda headless
compaiono nella scheda Cronologia della GUI alla prossima apertura. La GUI e la coda headless non girano insieme."""
import json
import os
from pathlib import Path
from typing import Optional


def history_path() -> Path:
    return Path.home() / '.transcriberpro' / 'history.json'


def append_entry(entry: dict, path: Optional[Path] = None) -> bool:
    """Aggiunge una voce. Come la GUI: un file illeggibile si considera vuoto. Scrittura atomica. False se non riesce."""
    p = Path(path) if path else history_path()
    try:
        entries = []
        if p.exists():
            try:
                loaded = json.loads(p.read_text(encoding='utf-8'))
                entries = loaded if isinstance(loaded, list) else []
            except Exception:
                entries = []
        entries.append(entry)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(p)
        return True
    except Exception:
        return False
