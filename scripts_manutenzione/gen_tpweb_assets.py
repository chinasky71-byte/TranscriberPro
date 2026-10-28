# -*- coding: utf-8 -*-
"""Genera i file di tema della web UI dalle FONTI della GUI Qt (una sola fonte di verita'):
   tpweb/static/tokens.css  <- gui/design_tokens.py (T)      variabili CSS `--nome-con-trattini`
   tpweb/static/js/icons.js <- gui/icons.py (_SVG_CONTENT)   le stesse icone SVG (viewBox 24, tratto 1.5)
Uso:  python scripts_manutenzione/gen_tpweb_assets.py          (riscrive i file)
Il test linux_tests/test_tpweb_assets.py verifica che i file committati coincidano con questa uscita."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

STATIC = ROOT / 'tpweb' / 'static'


def tokens_css() -> str:
    from gui.design_tokens import T
    lines = ['/* GENERATO da scripts_manutenzione/gen_tpweb_assets.py da gui/design_tokens.py: non modificare a mano. */', ':root {']
    for k, v in vars(T).items():
        if k.startswith('_') or k in ('STATUS_COLORS', 'LOG_COLORS', 'rgba') or not isinstance(v, (str, int, float)) or isinstance(v, bool):
            continue
        name = k.replace('_', '-').lower()
        if isinstance(v, str):
            val = v
        else:
            val = f'{v}px' if k.startswith(('SP_', 'R_', 'FS_')) and k != 'FS_BASE_PT' else str(v)
        lines.append(f'  --{name}: {val};')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def icons_js() -> str:
    from gui.icons import _SVG_CONTENT
    body = json.dumps(_SVG_CONTENT, ensure_ascii=False, indent=1, sort_keys=True)
    return ('// GENERATO da scripts_manutenzione/gen_tpweb_assets.py da gui/icons.py: non modificare a mano.\n'
            '// Stesso disegno della GUI Qt: viewBox 24, tratto 1.5, estremi e giunzioni arrotondati.\n'
            f'export const ICONS = {body};\n')


def main() -> None:
    (STATIC / 'js').mkdir(parents=True, exist_ok=True)
    (STATIC / 'tokens.css').write_text(tokens_css(), encoding='utf-8', newline='\n')
    (STATIC / 'js' / 'icons.js').write_text(icons_js(), encoding='utf-8', newline='\n')
    print('scritti tokens.css e js/icons.js')


if __name__ == '__main__':
    main()
