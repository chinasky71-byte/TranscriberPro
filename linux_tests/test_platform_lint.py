# -*- coding: utf-8 -*-
"""
Rete di sicurezza della compatibilita' Linux (F0): impedisce NUOVO codice con dipendenze Windows cablate.

I punti gia' noti sono fotografati in BASELINE (file -> pattern -> occorrenze) e verranno spostati su
utils/platform_compat.py nelle fasi successive. Il test fallisce se un pattern compare in un file nuovo o piu' volte del
previsto (debito nuovo) e anche se ne compare MENO volte (si e' pagato debito: aggiornare BASELINE, cosi' resta esatta).

Esecuzione (dalla radice):  venv\\Scripts\\python.exe -m pytest ui_bench\\tests\\test_platform_lint.py -q
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCAN = ('core', 'utils', 'gui', 'glossary_engine', 'main.py')
HELPER = 'utils/platform_compat.py'          # l'unico posto dove questi pattern sono ammessi

PATTERNS = {
    'venv_Scripts': re.compile(r"""['"]Scripts['"]|Scripts[/\\]+python"""),
    'python_exe': re.compile(r"python\.exe"),
    'taskkill': re.compile(r"taskkill"),
    'create_no_window_hex': re.compile(r"0x08000000"),
    'windll': re.compile(r"\bwindll\b"),
    'startfile': re.compile(r"os\.startfile"),
}

BASELINE = {
    'core/gender_selector_cli.py': {'python_exe': 1},
    'core/glossary_builder_cli.py': {'venv_Scripts': 1},
    'glossary_engine/build_glossary_candidates.py': {'venv_Scripts': 2},
    'glossary_engine/glossary_align.py': {'windll': 1},
    'glossary_engine/glossary_qwen_gpu_cli.py': {'venv_Scripts': 1},
    'utils/resource_monitor.py': {'windll': 1},
}


def _scan():
    found = {}
    files = []
    for entry in SCAN:
        p = ROOT / entry
        files += [p] if p.is_file() else sorted(p.rglob('*.py'))
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if rel == HELPER or '__pycache__' in rel:
            continue
        for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.lstrip().startswith('#'):
                continue
            for name, rx in PATTERNS.items():
                n = len(rx.findall(line))
                if n:
                    found.setdefault(rel, {}).setdefault(name, 0)
                    found[rel][name] += n
    return found


def test_nessun_nuovo_codice_windows_cablato():
    found = _scan()
    diffs = []
    for rel in sorted(set(found) | set(BASELINE)):
        for name in sorted(set(found.get(rel, {})) | set(BASELINE.get(rel, {}))):
            got, exp = found.get(rel, {}).get(name, 0), BASELINE.get(rel, {}).get(name, 0)
            if got != exp:
                diffs.append(f"{rel} [{name}]: trovate {got}, attese {exp}")
    assert not diffs, (
        "Pattern dipendenti da Windows fuori da utils/platform_compat.py. Nuovo codice: usa venv_python(), "
        "no_window_flags(), kill_tree(). Se hai tolto debito, aggiorna BASELINE.\n  " + "\n  ".join(diffs))


def test_il_lint_riconosce_i_pattern():
    assert PATTERNS['venv_Scripts'].search("root / 'venv_nlp' / 'Scripts' / 'python.exe'")
    assert PATTERNS['venv_Scripts'].search("venv_canary/Scripts/python.exe")
    assert PATTERNS['taskkill'].search('["taskkill", "/F"]')
    assert PATTERNS['create_no_window_hex'].search("_CREATE_NO_WINDOW = 0x08000000")
    assert not PATTERNS['venv_Scripts'].search("bin/python")
