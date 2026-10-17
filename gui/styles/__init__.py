"""Template QSS dei dialoghi (gui/styles/<nome>.qss.tpl), resi con i token di design.

    from gui.styles import load_qss
    widget.setStyleSheet(load_qss('library_scanner'))
    widget.setStyleSheet(load_qss('ocr_review', accent=T.accent))   # {{nome}} extra locali

I segnaposto {{token}} sono gli attributi di gui.design_tokens.T; `extra` aggiunge/sovrascrive
segnaposto locali. Il file e' letto in UTF-8 senza conversione dei fine riga.
"""
from __future__ import annotations

import re
from pathlib import Path

from gui.design_tokens import token_map

_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r'\{\{(\w+)\}\}')


def load_qss(name: str, **extra) -> str:
    text = (_DIR / f'{name}.qss.tpl').read_bytes().decode('utf-8')
    tokens = token_map()
    tokens.update({k: str(v) for k, v in extra.items()})

    def _sub(m):
        key = m.group(1)
        if key not in tokens:
            raise KeyError(f"token QSS sconosciuto: {{{{{key}}}}} in {name}.qss.tpl")
        return tokens[key]

    return _PLACEHOLDER.sub(_sub, text)
