# -*- coding: utf-8 -*-
"""Traduzioni IT/EN: parita' delle chiavi, stessi segnaposto, chiavi usate dal codice, lingua nel processo figlio.

Esecuzione (dalla radice):  python -m pytest linux_tests/test_i18n_texts.py -q
"""
import ast
import os
import string
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import translations as T  # noqa: E402

EN, IT = T.Translations.TEXTS['en'], T.Translations.TEXTS['it']


def _fields(text):
    out = []
    for _, name, spec, _ in string.Formatter().parse(text):
        if name is not None:
            out.append((name, spec))
    return sorted(out)


def test_stesse_chiavi_in_en_e_it():
    assert sorted(set(EN) - set(IT)) == [] and sorted(set(IT) - set(EN)) == []


def test_stessi_segnaposto_in_en_e_it():
    bad = [k for k in EN if k in IT and _fields(EN[k]) != _fields(IT[k])]
    assert bad == []


def test_valori_formattabili():
    """Ogni valore deve poter passare da str.format con segnaposto con nome (niente apostrofi/graffe rotti)."""
    for table in (EN, IT):
        for k, v in table.items():
            names = {n for n, _ in _fields(v) if n}
            assert all(n.isidentifier() for n in names), k
            v.format(**{n: 1 for n in names})


def _tr_literals(dirs):
    found = []
    for d in dirs:
        for path in (ROOT / d).rglob('*.py'):
            try:
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            except Exception:
                continue
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('tr', 'get_text')
                        and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                    found.append((str(path.relative_to(ROOT)), n.lineno, n.args[0].value))
    return found


@pytest.mark.parametrize('folder', ['core', 'utils', 'gui'])
def test_ogni_chiave_tr_letterale_esiste_in_en(folder):
    missing = [f for f in _tr_literals([folder]) if f[2] not in EN]
    assert missing == []


def test_all_texts_ritorna_entrambe_le_lingue():
    assert T.all_texts('logm_bar_translation') == ('Traduzione: [', 'Translation: [')
    assert T.all_texts('chiave_inesistente') == ()


def test_lingua_del_figlio_forzata_da_tp_lang():
    """Il figlio (python -m core.*_cli) applica la lingua senza Qt: TP_LANG vince, poi la config."""
    code = ("from utils.translations import init_language_headless, get_translations;"
            "init_language_headless();print(get_translations().current_language)")
    for lang in ('it', 'en'):
        env = dict(os.environ, TP_LANG=lang)
        out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
        assert out.stdout.strip().splitlines()[-1] == lang, out.stderr


def test_lingua_del_figlio_segue_la_config():
    class Cfg:
        def __init__(self, v): self.v = v
        def get(self, k, d=None): return self.v if k == 'language' else d
    prev = T.get_translations().current_language
    try:
        for pref, expected in (('it', 'it'), ('en', 'en')):
            T.init_language(Cfg(pref))
            assert T.get_translations().current_language == expected
    finally:
        T.get_translations().current_language = prev
