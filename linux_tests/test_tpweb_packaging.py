# -*- coding: utf-8 -*-
"""Fase 6: il pacchetto PyInstaller della web UI. PyInstaller non si esegue qui (serve Windows): si legge lo spec con un finto PyInstaller e si
controlla che tutto cio' che elenca esista e che i file che la pagina serve a runtime siano coperti. Piu' le dipendenze e gli script di avvio."""
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_spec():
    seen = {}

    class Rec:
        def __init__(self, *a, **k):
            self.a, self.k = a, k
            self.pure, self.scripts, self.binaries, self.datas = [], [], [], []

    def collect_submodules(name):
        return [name]
    ns = {'Analysis': lambda *a, **k: seen.setdefault('analysis', Rec(*a, **k)), 'PYZ': lambda *a, **k: Rec(*a, **k),
          'EXE': lambda *a, **k: seen.setdefault('exe', Rec(*a, **k))}
    hooks = types.ModuleType('PyInstaller.utils.hooks')
    hooks.collect_submodules = collect_submodules
    mods = {'PyInstaller': types.ModuleType('PyInstaller'), 'PyInstaller.utils': types.ModuleType('PyInstaller.utils'), 'PyInstaller.utils.hooks': hooks}
    old = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        exec(compile((ROOT / 'TranscriberProWeb.spec').read_text(encoding='utf-8'), 'TranscriberProWeb.spec', 'exec'), ns)
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return seen['analysis'], seen['exe']


def test_lo_spec_elenca_solo_cio_che_esiste_e_copre_la_pagina():
    a, exe = load_spec()
    assert a.a[0] == ['main.py'] and (ROOT / 'main.py').is_file()
    datas = {src: dst for src, dst in a.k['datas']}
    assert all((ROOT / src).exists() for src in datas)
    assert datas['tpweb/static'] == 'tpweb/static' and datas['assets'] == 'assets'
    hidden = set(a.k['hiddenimports'])
    assert {'uvicorn', 'starlette', 'fastapi', 'anyio', 'h11'} <= hidden
    assert exe.k['name'] == 'TranscriberProWeb' and exe.k['console'] is False and (ROOT / exe.k['icon']).is_file()
    assert 'PyQt6' not in hidden


def test_i_file_serviti_a_runtime_sono_sotto_le_cartelle_impacchettate():
    """La pagina serve /static/* da tpweb/static e /assets/* da assets: nessun altro percorso di dati letto dal server."""
    src = (ROOT / 'tpweb' / 'app.py').read_text(encoding='utf-8')
    assert "STATIC = " in src and "'static'" in src
    for f in ('index.html', 'app.css', 'tokens.css'):
        assert (ROOT / 'tpweb' / 'static' / f).is_file()
    assert (ROOT / 'assets' / 'fonts').is_dir() and (ROOT / 'assets' / 'icons').is_dir()


def test_dipendenze_della_web_ui_dichiarate():
    req = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    web = (ROOT / 'requirements-web.txt').read_text(encoding='utf-8')
    for pkg in ('fastapi==', 'uvicorn=='):
        assert pkg in req
    assert re.search(r'^pywebview==\d+\.\d+', web, re.M)
    assert 'pywebview' in (ROOT / 'NOTICE.md').read_text(encoding='utf-8')


def test_script_di_avvio_senza_percorsi_personali():
    for name in ('Lancia Transcriptor Web.bat', 'Lancia Transcriptor Web.vbs', 'run_web.sh'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert '--ui web' in text, name
        assert not re.search(r'[A-Za-z]:\\Users\\', text), name              # repository pubblico: nessun dato personale
    assert (ROOT / 'run_web.sh').stat().st_mode & 0o111
