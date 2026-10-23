# -*- coding: utf-8 -*-
"""Cerca stringhe italiane scritte nel codice e mostrate a schermo (gui/ e messaggi di log della pipeline). Solo lettura.
Uso: python ui_bench/tools/scan_i18n.py [cartella ...]"""
import ast, re, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
IT_WORDS = set("il lo la le gli un una uno di del della dei delle degli da dal dalla in nel nella su sul per con tra fra che non sono è e o ma se già solo più come quando mentre dopo prima senza anche ancora tutti tutto file video sottotitoli sottotitolo traduzione trascrizione elaborazione completato errore avvio ferma salta salvato salvata caricamento modello lingua nessun nessuna impossibile usa uso scelto scelta attivo attiva spento abilita disabilita apri chiudi annulla conferma riprova trovato trovati mancante mancano".split())
ACC = re.compile(r"[àèéìòù]")
UI_CALLS = {'setText', 'setToolTip', 'setWindowTitle', 'setPlaceholderText', 'setTitle', 'setStatusTip', 'addAction', 'addMenu', 'addTab',
            'setTabText', 'setSummary', 'setLabelText', 'setInformativeText', 'setDetailedText', 'addItem', 'setHeaderLabels',
            'information', 'warning', 'critical', 'question', 'getOpenFileName', 'getExistingDirectory', 'getSaveFileName',
            'QLabel', 'QPushButton', 'QCheckBox', 'QRadioButton', 'QGroupBox', 'QAction', 'QToolButton',
            'log_message', '_log', 'log', 'emit_log', 'append_log', '_emit'}

def strings_in(node):
    """Parti costanti di una stringa/f-string/concatenazione."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out

def looks_italian(s):
    if len(s.strip()) < 4: return False
    words = re.findall(r"[A-Za-zÀ-ù']+", s.lower())
    hits = sum(1 for w in words if w in IT_WORDS)
    return (hits >= 2) or (hits >= 1 and ACC.search(s) is not None) or (len(words) >= 3 and ACC.search(s) is not None and hits >= 1)

def scan(path):
    try:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return []
    found = []
    parent = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parent[c] = p
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')
        if name not in UI_CALLS:
            continue
        # logger.xxx(...) e simili non sono a schermo
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ('logger', 'logging', 'print'):
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            # tr('chiave') e' gia' tradotto: salta gli argomenti che sono chiamate a tr/get_text
            if isinstance(arg, ast.Call) and isinstance(arg.func, (ast.Name, ast.Attribute)) and getattr(arg.func, 'id', getattr(arg.func, 'attr', '')) in ('tr', 'get_text'):
                continue
            # .format(...) su tr(...) e' tradotto
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == 'format' and isinstance(arg.func.value, ast.Call):
                inner = arg.func.value
                if getattr(inner.func, 'id', getattr(inner.func, 'attr', '')) in ('tr', 'get_text'):
                    continue
            for s in strings_in(arg):
                if looks_italian(s):
                    found.append((node.lineno, name, s.strip().replace('\n', ' ')[:90]))
    return found

LIMIT = 99


def main(dirs):
    total = 0
    per_file = defaultdict(list)
    for d in dirs:
        for p in sorted((ROOT / d).rglob('*.py')):
            if 'venv' in p.parts or '__pycache__' in p.parts or p.name.startswith(('test_', 'fix_', 'debug_')):
                continue
            r = scan(p)
            if r:
                per_file[str(p.relative_to(ROOT))] = r
                total += len(r)
    for f, items in sorted(per_file.items(), key=lambda kv: -len(kv[1])):
        print(f"{f}: {len(items)}")
        for ln, name, s in items[:LIMIT]:
            print(f"    {ln:5d} {name}: {s}")
    print(f"\nTOTALE: {total} stringhe in {len(per_file)} file")

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(sys.argv[1:] or ['gui', 'core', 'utils'])
