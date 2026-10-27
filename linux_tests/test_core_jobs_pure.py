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


def test_core_utils_e_glossary_engine_non_importano_gui_nemmeno_dentro_le_funzioni():
    """Regola F4: nessun modulo fuori da gui/ dipende dal pacchetto `gui` (altrimenti gui/ non si potrebbe togliere)."""
    bad = {}
    for d in ('core', 'utils', 'glossary_engine'):
        for p in (ROOT / d).rglob('*.py'):
            if 'vendor' in p.parts:
                continue
            hit = {m for m in _imports(p) if m == 'gui'}
            if hit:
                bad[str(p.relative_to(ROOT))] = sorted(hit)
    assert bad == {}


def test_coda_headless_completa_senza_pacchetto_gui_e_senza_qt(tmp_path):
    """Una coda vera (motore, runner, cronologia, stato JSON) con `gui` e `PyQt6` bloccati: se un import li toccasse fallirebbe."""
    code = r'''
import json, subprocess, sys
sys.modules['gui'] = None
sys.modules['PyQt6'] = None
sys.path.insert(0, %(root)r); sys.path.insert(0, %(tests)r)
import _queue_testkit as kit
subprocess.Popen = kit.PopenSpy()
import os
os.environ['HOME'] = os.environ['USERPROFILE'] = %(home)r
from utils import config as cfg
from pathlib import Path
cfg.Config.CONFIG_DIR = Path(%(home)r) / '.transcriberpro'
cfg.Config.CONFIG_FILE = cfg.Config.CONFIG_DIR / 'config.json'
cfg.reset_config()
import utils.cache_cleaner as cc
cc.cleanup_non_italian_caches = lambda log_callback=None: {'removed': [], 'failed': []}
import core.queue_runner as qr
qr._HOME = Path(%(home)r) / '.transcriberpro'
qr._gui_running = lambda: False
v = kit.make_videos(Path(%(vd)r), 'a_ok.mkv', 'b_fail.mkv')
rc = qr.main([%(vd)r, '--status', %(st)r, '--log-dir', %(logs)r])
st = json.loads(Path(%(st)r).read_text(encoding='utf-8'))
print('RESULT', rc, st['completed'], st['failed'], 'gui' in [m for m, x in sys.modules.items() if x is not None])
'''
    vd = tmp_path / 'vid'
    vd.mkdir()
    src = code % dict(root=str(ROOT), tests=str(ROOT / 'linux_tests'), home=str(tmp_path / 'home'), vd=str(vd),
                      st=str(tmp_path / 'st.json'), logs=str(tmp_path / 'logs'))
    r = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True, cwd=str(ROOT))
    assert 'RESULT 2 1 1 False' in r.stdout, (r.stdout[-600:], r.stderr[-800:])
    assert (tmp_path / 'home' / '.transcriberpro' / 'history.json').exists()
