# -*- coding: utf-8 -*-
"""Regola del refactoring della coda: core/jobs (e la coda headless) NON dipendono da PyQt6 ne' dal pacchetto `gui`."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('PyQt6', 'gui')


def _imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split('.')[0]


def test_core_jobs_non_importa_qt_ne_gui():
    bad = {p.name: sorted(set(_imports(p)) & set(FORBIDDEN)) for p in (ROOT / 'core' / 'jobs').glob('*.py')}
    assert {k: v for k, v in bad.items() if v} == {}


def test_queue_runner_non_importa_qt_ne_gui():
    assert sorted(set(_imports(ROOT / 'core' / 'queue_runner.py')) & set(FORBIDDEN)) == []


def test_la_coda_headless_si_importa_senza_il_pacchetto_gui_e_senza_qt():
    """Blocca davvero gli import: con `gui` e `PyQt6` impostati a None in sys.modules, un import li farebbe fallire."""
    code = ("import sys; sys.modules['gui'] = None; sys.modules['PyQt6'] = None; sys.path.insert(0, %r);"
            "import core.queue_runner, core.jobs.file_progress, core.jobs.step_plan; print('ok')" % str(ROOT))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and 'ok' in r.stdout, r.stderr[-400:]


def test_i_nomi_vecchi_in_gui_sono_alias_degli_stessi_moduli():
    sys.path.insert(0, str(ROOT))
    import core.jobs.file_progress as a
    import core.jobs.step_plan as b
    import gui.file_progress as ga
    import gui.services.step_plan as gb
    assert ga is a and gb is b
