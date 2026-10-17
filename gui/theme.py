"""Tema di Transcriber Pro: genera gui/theme.qss da gui/theme.qss.tpl + design tokens.

    build_qss()        -> str  QSS completo (template con {{token}} sostituiti)
    set_role(w, role)  -> imposta la proprieta' dinamica `role` (e `tone`) e ripulisce lo stile
    render(text)       -> sostituisce {{token}} in una stringa QSS arbitraria

Da riga di comando (dalla radice del progetto):
    python -m gui.theme --check    # exit 1 se theme.qss su disco != build_qss()
    python -m gui.theme --write    # rigenera theme.qss

theme.qss e' un file GENERATO: si modifica theme.qss.tpl (o i token) e si rigenera.
Newline e codifica sono conservati byte per byte (UTF-8, nessuna conversione di fine riga).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from gui.design_tokens import T, token_map

_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = _DIR / 'theme.qss.tpl'
QSS_PATH = _DIR / 'theme.qss'

_PLACEHOLDER = re.compile(r'\{\{(\w+)\}\}')


def render(text: str) -> str:
    """Sostituisce ogni {{token}} con il valore in design_tokens.T (KeyError se sconosciuto)."""
    tokens = token_map()

    def _sub(m):
        name = m.group(1)
        if name not in tokens:
            raise KeyError(f"token QSS sconosciuto: {{{{{name}}}}}")
        return tokens[name]

    return _PLACEHOLDER.sub(_sub, text)


def build_qss() -> str:
    """Rende theme.qss.tpl con i token. Non altera i fine riga del template."""
    with open(TEMPLATE_PATH, 'rb') as f:
        return render(f.read().decode('utf-8'))


def set_flat(widget):
    """Contenitore "trasparente": prende lo sfondo della card/riga che lo ospita invece del fondo finestra.
    Attiva la regola QWidget[flat="true"] di theme.qss.tpl. Ritorna il widget (comodo inline)."""
    widget.setProperty('flat', True)
    return widget


def set_role(widget, role: str, tone: str | None = None) -> None:
    """Imposta role (e opzionalmente tone) come proprieta' dinamiche e ri-applica lo stile.

    Esempi: set_role(lbl, 'muted'); set_role(lbl, 'h2', tone='success');
            set_role(frame, 'card'); set_role(badge, 'badge', tone='warn')
    role=None/'' rimuove la proprieta'.
    """
    widget.setProperty('role', role or None)
    widget.setProperty('tone', tone or None)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _read_disk() -> bytes:
    return QSS_PATH.read_bytes() if QSS_PATH.exists() else b''


def _main(argv) -> int:
    built = build_qss().encode('utf-8')
    if '--write' in argv:
        QSS_PATH.write_bytes(built)
        print(f"scritto {QSS_PATH.name}: {len(built)} byte")
        return 0
    if '--check' in argv:
        if _read_disk() == built:
            print("OK: theme.qss e' identico a build_qss()")
            return 0
        print("DIFFERENTE: theme.qss non coincide con build_qss() (usa --write)")
        return 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
