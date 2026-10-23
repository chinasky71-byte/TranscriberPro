# -*- coding: utf-8 -*-
"""Nessun nuovo letterale italiano nelle chiamate di log/emissione di core/ e utils/ (fase B).

Usa lo scanner `scripts_manutenzione/scan_i18n.py`. L'elenco ammesso e' esplicito e motivato: ogni voce nuova deve
passare da tr() invece di essere aggiunta qui."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts_manutenzione'))

import scan_i18n  # noqa: E402

# file -> numero di letterali ammessi
ALLOWED = {
    # gira nel venv dedicato `venv_glossary` (requirements-glossary.txt), che non ha le dipendenze di `utils`:
    # importare utils.translations li' farebbe fallire il processo. I messaggi vanno alla finestra del glossario.
    'core/glossary_builder_cli.py': 3,
}


def test_nessun_letterale_italiano_nei_log_oltre_all_elenco_ammesso():
    found = {}
    for d in ('core', 'utils'):
        for p in sorted((ROOT / d).rglob('*.py')):
            if '__pycache__' in p.parts or p.name.startswith(('test_', 'fix_', 'debug_')):
                continue
            r = scan_i18n.scan(p)
            if r:
                found[str(p.relative_to(ROOT)).replace('\\', '/')] = len(r)
    assert found == ALLOWED
