# -*- coding: utf-8 -*-
"""Quale interfaccia avviare (`--ui qt|web`). Modulo minimo, solo libreria standard: main.py lo importa prima di PyQt6."""
from typing import Callable, List, Optional


def ui_from_args(argv: List[str]) -> Optional[str]:
    """'qt' o 'web' se c'e' `--ui X` / `--ui=X` (l'ultimo no: vale il primo); None se manca. Valore non valido -> ValueError."""
    for i, a in enumerate(argv):
        if a == '--ui' or a.startswith('--ui='):
            v = a.split('=', 1)[1] if a.startswith('--ui=') else (argv[i + 1] if i + 1 < len(argv) else None)
            if v not in ('qt', 'web'):
                raise ValueError(f"--ui: valore non valido {v!r} (qt|web)")
            return v
    return None


def requested_ui(argv: List[str], config_get: Optional[Callable] = None) -> str:
    """'qt' o 'web': `--ui` vince sulla chiave `ui` del config, che vale 'qt' se manca, non e' valida o non si legge."""
    v = ui_from_args(argv)
    if v is not None:
        return v
    try:
        v = config_get('ui', 'qt') if config_get else 'qt'
    except Exception:
        v = 'qt'
    return v if v in ('qt', 'web') else 'qt'
