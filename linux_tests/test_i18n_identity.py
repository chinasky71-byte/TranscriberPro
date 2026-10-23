# -*- coding: utf-8 -*-
"""L'italiano delle chiavi convertite (fase B) deve restare IDENTICO al letterale originale del sorgente.

`i18n_it_originals.json` e' generato da scripts_manutenzione/i18n_convert.py al momento della conversione, dal
letterale originale (modello `{segnaposto}`). La prova indipendente sul codice e'
`scripts_manutenzione/verify_i18n_identity.py <rif-base> <file>` (valuta vecchio e nuovo con valori finti)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.translations import Translations  # noqa: E402

ORIG = json.loads((Path(__file__).with_name('i18n_it_originals.json')).read_text(encoding='utf-8'))


def test_italiano_identico_agli_originali():
    it = Translations.TEXTS['it']
    diff = [k for k, v in ORIG.items() if it.get(k) != v]
    assert diff == []


def test_manifest_non_vuoto():
    assert len(ORIG) > 100
