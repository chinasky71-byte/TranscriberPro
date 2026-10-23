# -*- coding: utf-8 -*-
"""Elenca i letterali di testo passati direttamente ai widget in gui/ (senza tr()). Solo lettura.
Usato anche da ui_bench/tests/test_i18n.py: nessun letterale nuovo deve comparire fuori dall'elenco ammesso."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = {'setText', 'setToolTip', 'setWindowTitle', 'setPlaceholderText', 'setTitle', 'addAction', 'addMenu', 'addTab', 'setTabText', 'setSummary',
      'information', 'warning', 'critical', 'question', 'QLabel', 'QPushButton', 'QCheckBox', 'QRadioButton', 'QGroupBox', 'QAction',
      'QToolButton', 'addItem', 'setHeaderLabels', 'setLabelText', 'ElideLabel', 'CollapsibleCard', 'setStatusTip',
      'log_message', '_log'}
LOGGERS = {'logger', 'logging', 'log'}


def find_literals(base='gui'):
    """[(file relativo, riga, chiamata, testo)] dei letterali non tradotti passati ai widget o ai log a schermo."""
    out = []
    for p in sorted((ROOT / base).rglob('*.py')):
        if '__pycache__' in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')
            if name not in UI:
                continue
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in LOGGERS:
                continue                      # logger.warning(...) non e' a schermo
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, ast.Call) and getattr(arg.func, 'id', getattr(arg.func, 'attr', '')) in ('tr', 'get_text'):
                    continue
                if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == 'format'
                        and isinstance(arg.func.value, ast.Call)
                        and getattr(arg.func.value.func, 'id', getattr(arg.func.value.func, 'attr', '')) in ('tr', 'get_text')):
                    continue
                for c in ast.walk(arg):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        s = c.value.strip()
                        if len(re.findall(r'[A-Za-zÀ-ù]', s)) >= 3 and not re.fullmatch(r"[a-z_\.#:/\-]+", s) \
                                and not s.startswith(('<', '#', 'color', 'QLabel')):
                            out.append((str(p.relative_to(ROOT)), node.lineno, name, s.replace('\n', ' ')))
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    rows = find_literals(*(sys.argv[1:2] or ['gui']))
    cur = None
    for f, ln, name, s in rows:
        if f != cur:
            print(f); cur = f
        print(f"   {ln:5d} {name}: {s[:80]}")
    print('TOTALE', len(rows))
