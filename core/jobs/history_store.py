# -*- coding: utf-8 -*-
"""Cronologia dei file elaborati (~/.transcriberpro/history.json), senza Qt: stesso file e stesso formato che
`gui/history_widget.py::HistoryWidget` legge e scrive (lista JSON di voci, indent 2), cosi' le voci aggiunte dalla coda headless
compaiono nella scheda Cronologia della GUI alla prossima apertura. La GUI e la coda headless non girano insieme."""
from pathlib import Path
from typing import Optional


def history_path() -> Path:
    return Path.home() / '.transcriberpro' / 'history.json'


def append_entry(entry: dict, path: Optional[Path] = None) -> bool:
    """Aggiunge una voce. Come la GUI: un file illeggibile si considera vuoto. Scrittura atomica. False se non riesce.
    L'implementazione e' di core/services/history_service.py (la stessa che usa la scheda Cronologia della GUI)."""
    from core.services.history_service import HistoryService
    svc = HistoryService(Path(path) if path else history_path())
    svc.load()
    return svc.append(entry)
