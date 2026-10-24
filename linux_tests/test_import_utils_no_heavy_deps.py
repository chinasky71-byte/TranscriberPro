# -*- coding: utf-8 -*-
"""`import utils` non deve caricare PyQt6, torch, onnxruntime (ne' llama_cpp).

Regressione v1.34.30: utils.translations importava PyQt6.QtCore a livello di chiamata senza QApplication; su Windows
PyQt6 caricato prima di onnxruntime fa fallire `import onnxruntime` in main.py ("DLL load failed ...
onnxruntime_pybind11_state"). Su Linux il problema non si manifesta, quindi lo si impedisce con due controlli:

1. dinamico: sottoprocesso pulito, `import utils`, poi si guarda sys.modules;
2. statico (AST): nessun modulo raggiungibile da utils/__init__.py con import a livello di modulo (anche dentro
   try/if, non dentro funzioni/classi) importa un pacchetto proibito.

Regola di progetto: onnxruntime prima di PyQt6; llama_cpp primo import nei processi che lo usano."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = ('PyQt6', 'PyQt5', 'PySide6', 'torch', 'torchaudio', 'onnxruntime', 'llama_cpp')


def _banned(name):
    return name.split('.')[0] in BANNED


def _module_level_imports(tree):
    """(lineno, nome assoluto o ('rel', livello, modulo, nomi)) degli import eseguiti all'import del modulo."""
    out, stack = [], list(tree.body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Import):
            out += [(n.lineno, a.name, 0, []) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append((n.lineno, n.module or '', n.level, [a.name for a in n.names]))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        else:
            for f in ('body', 'orelse', 'finalbody', 'handlers'):
                stack.extend(getattr(n, f, None) or [])
    return out


def _resolve(importer, name, level, names):
    """File locali (utils/, core/) caricati da un import; per `from pkg import x` anche x se e' un modulo."""
    base = importer.parent.relative_to(ROOT).parts
    if level:
        base = base[:len(base) - (level - 1)]
        parts = list(base) + (name.split('.') if name else [])
    else:
        parts = name.split('.') if name else []
    if not parts or parts[0] not in ('utils', 'core'):
        return []
    found = []
    for cand in [parts] + [parts + [x] for x in names]:
        f = ROOT.joinpath(*cand)
        if f.with_suffix('.py').is_file():
            found.append(f.with_suffix('.py'))
        elif (f / '__init__.py').is_file():
            found.append(f / '__init__.py')
    return found


def violations_from(entry):
    seen, todo, bad = set(), [entry], []
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        tree = ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
        for lineno, name, level, names in _module_level_imports(tree):
            if not level and _banned(name):
                bad.append(f'{p.relative_to(ROOT)}:{lineno} importa {name}')
            todo.extend(_resolve(p, name, level, names))
    return sorted(bad), seen


def test_statico_utils_init_non_raggiunge_pacchetti_pesanti():
    bad, seen = violations_from(ROOT / 'utils' / '__init__.py')
    assert len(seen) > 5, 'il risolutore di import non segue i moduli (test vacuo)'
    assert not bad, 'import a livello di modulo vietati (vedi docstring):\n' + '\n'.join(bad)


def test_statico_rileva_import_vietato_anche_in_try(tmp_path):
    tree = ast.parse('try:\n    import torch\nexcept ImportError:\n    pass\ndef f():\n    import PyQt6\n')
    found = [n for _, n, _, _ in _module_level_imports(tree)]
    assert found == ['torch']


def _stub_pacchetti_pesanti(tmp_path):
    """Pacchetti finti: su Linux/CI PyQt6 & co. non sono installati, e un import nascosto fallirebbe in silenzio
    (try/except ImportError) senza far emergere la regressione. Con lo stub l'import riesce e finisce in sys.modules."""
    for name in BANNED:
        d = tmp_path / 'stub' / name
        d.mkdir(parents=True)
        (d / '__init__.py').write_text('')
    (tmp_path / 'stub' / 'PyQt6' / 'QtCore.py').write_text(
        'class QLocale:\n    @staticmethod\n    def system():\n        raise RuntimeError("stub")\n')
    return str(tmp_path / 'stub')


def test_dinamico_import_utils_in_sottoprocesso_pulito(tmp_path):
    code = (
        'import sys; sys.path.insert(0, %r); sys.path.append(%r)\n'
        'import utils\n'
        'import utils.translations as t\n'
        'print("MODS=" + ",".join(sorted(m for m in sys.modules if m.split(".")[0] in %r)))\n'
    ) % (str(ROOT), _stub_pacchetti_pesanti(tmp_path), BANNED)
    r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-2000:]
    line = next(l for l in r.stdout.splitlines() if l.startswith('MODS='))
    assert line == 'MODS=', f'dopo `import utils` sono in sys.modules: {line[5:]}'


def test_dinamico_rilevamento_lingua_senza_qapplication_non_carica_pyqt6(tmp_path):
    code = (
        'import sys; sys.path.insert(0, %r); sys.path.append(%r)\n'
        'import utils.translations as t\n'
        'getattr(t, "init_language_headless", lambda: None)()\n'
        'print("PYQT=" + str(any(m.split(".")[0] == "PyQt6" for m in sys.modules)))\n'
    ) % (str(ROOT), _stub_pacchetti_pesanti(tmp_path))
    r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'PYQT=False' in r.stdout, r.stdout
