# -*- coding: utf-8 -*-
"""Regola di tpweb: nessun modulo importa PyQt6 ne' `gui` (ne' torch/ctranslate2 nel server); importabile senza Qt."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'PyQt6', 'gui', 'torch', 'ctranslate2'}


def _imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split('.')[0]


def test_tpweb_non_importa_qt_gui_ne_ml():
    bad = {str(p.relative_to(ROOT)): sorted(set(_imports(p)) & FORBIDDEN)
           for p in (ROOT / 'tpweb').rglob('*.py') if 'proto' not in p.parts}
    assert {k: v for k, v in bad.items() if v} == {}


def test_il_server_si_importa_e_risponde_senza_qt():
    code = ("import sys; sys.modules['gui'] = None; sys.modules['PyQt6'] = None; sys.path.insert(0, %r);"
            "from tpweb.runner import ServerThread; import httpx;"
            "s = ServerThread().start();"
            "r = httpx.get(f'http://127.0.0.1:{s.port}/api/i18n/it', headers={'X-TP-Token': s.token}); s.stop();"
            "print(r.status_code)" % str(ROOT))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and r.stdout.strip().endswith('200'), r.stderr[-500:]
