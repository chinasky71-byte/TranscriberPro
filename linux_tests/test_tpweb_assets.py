# -*- coding: utf-8 -*-
"""File statici della web UI: tokens.css e icons.js coincidono con la GUI Qt (generati), nessuna risorsa esterna, niente traversal,
tipi MIME fissi, chiavi di traduzione dei JS presenti in italiano e in inglese."""
import os
import re
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts_manutenzione'))
STATIC = ROOT / 'tpweb' / 'static'


def test_tokens_e_icone_coincidono_con_la_gui():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import gen_tpweb_assets as g
    assert (STATIC / 'tokens.css').read_text(encoding='utf-8') == g.tokens_css(), 'rigenera: python scripts_manutenzione/gen_tpweb_assets.py'
    assert (STATIC / 'js' / 'icons.js').read_text(encoding='utf-8') == g.icons_js(), 'rigenera: python scripts_manutenzione/gen_tpweb_assets.py'


def test_ogni_token_della_gui_e_una_variabile_css():
    from gui.design_tokens import T
    css = (STATIC / 'tokens.css').read_text(encoding='utf-8')
    for name in ('bg_0', 'fg_row', 'accent', 'accent_a45', 'white_a03', 'danger_deep', 'purple_a35', 'rad_card', 'FONT_SANS', 'FS_BODY', 'SP_LG'):
        assert f'--{name.replace("_", "-").lower()}: {getattr(T, name)}' in css or f'--{name.replace("_", "-").lower()}: {getattr(T, name)}px' in css, name


def test_nessuna_risorsa_esterna_nei_file_della_pagina():
    """L'app funziona offline: nessun URL assoluto nei file nostri (nel codice vendorizzato resta solo il nome di spazio SVG)."""
    ext = re.compile(r'(?<![\w.])(?:https?:)?//(?!www\.w3\.org/2000/svg)[A-Za-z0-9.-]+\.[a-z]{2,}', re.I)
    bad = {}
    for p in STATIC.rglob('*'):
        if p.is_file() and p.suffix in ('.html', '.js', '.css') and 'LICENSE' not in p.name:
            hits = ext.findall(p.read_text(encoding='utf-8'))
            if hits:
                bad[str(p.relative_to(STATIC))] = hits[:3]
    assert bad == {}


def test_il_codice_vendorizzato_ha_la_licenza_e_la_versione_fissata():
    v = STATIC / 'vendor'
    assert (v / 'LICENSE-htm.txt').read_text(encoding='utf-8').lstrip().startswith('Apache License')
    assert 'MIT License' in (v / 'LICENSE-preact.txt').read_text(encoding='utf-8')
    notice = (ROOT / 'NOTICE.md').read_text(encoding='utf-8')
    assert 'htm' in notice and 'preact' in notice.lower() and '3.1.1' in notice


def code_of(p):
    """Il sorgente senza commenti (// e /* */): gli esempi nei commenti non sono chiavi ne' testi."""
    s = p.read_text(encoding='utf-8')
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    return re.sub(r'(?m)(^|\s)//.*$', '', s)


def js_keys():
    keys = {}
    for p in (STATIC / 'js').glob('*.js'):
        if p.name == 'icons.js':
            continue
        for m in re.finditer(r"""\bt\(\s*(['"])([A-Za-z0-9_]+)\1\s*[,)]""", code_of(p)):
            keys.setdefault(m.group(2), p.name)
        for m in re.finditer(r"""\[\s*'[a-z]+'\s*,\s*'([a-z_]+)'\s*\]""", code_of(p)):   # tabelle [chiave, etichetta]
            if m.group(1).startswith(('seg_', 'dl_')):
                keys.setdefault(m.group(1), p.name)
    return keys


def test_nomi_delle_lingue_dei_sottotitoli_in_italiano_e_in_inglese():
    from utils import job_overrides as JO
    from utils.translations import Translations
    for lang in ('it', 'en'):
        assert [c for c in JO.LANGUAGES if f'lang_name_{c}' not in Translations.TEXTS[lang]] == []


def test_ogni_chiave_di_traduzione_dei_js_esiste_in_italiano_e_in_inglese():
    from utils.translations import Translations
    keys = js_keys()
    assert len(keys) > 40
    missing = {k: f for k, f in keys.items() if k not in Translations.TEXTS['it'] or k not in Translations.TEXTS['en']}
    assert missing == {}
    for lang in ('it', 'en'):          # i segnaposto delle due lingue coincidono
        pass
    ph = lambda s: sorted(re.findall(r'\{(\w+)\}', s))      # noqa: E731
    assert {k for k in keys if ph(Translations.TEXTS['it'][k]) != ph(Translations.TEXTS['en'][k])} == set()


def test_nessun_testo_italiano_o_inglese_scritto_a_mano_nei_js():
    """Ogni testo visibile passa da t(): niente stringhe di prosa dentro html`...` (solo nomi propri, simboli e attributi tecnici)."""
    allowed = {'Transcriber Pro', 'Library Scanner'}
    bad = []
    for p in (STATIC / 'js').glob('*.js'):
        if p.name in ('icons.js',):
            continue
        for m in re.finditer(r">([^<>`${}()=;\n]{3,})<", code_of(p)):
            txt = m.group(1).strip()
            if txt and txt not in allowed and re.search(r'[A-Za-zÀ-ÿ]{3,}', txt):
                bad.append((p.name, txt))
    assert bad == []


@pytest.fixture(scope='module')
def web():
    from tpweb.runner import ServerThread
    s = ServerThread().start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=10, headers={'X-TP-Token': s.token})
    yield c, s
    c.close()
    s.stop()


def test_file_serviti_con_il_tipo_giusto(web):
    c, _ = web
    for path, ctype in (('/', 'text/html'), ('/static/app.css', 'text/css'), ('/static/js/main.js', 'text/javascript'),
                        ('/static/tokens.css', 'text/css'), ('/assets/icons/check.svg', 'image/svg+xml'),
                        ('/assets/fonts/InterTight%5Bwght%5D.ttf', 'font/ttf')):
        r = c.get(path)
        assert r.status_code == 200 and r.headers['content-type'].split(';')[0] == ctype, (path, r.status_code, r.headers.get('content-type'))


@pytest.mark.parametrize('path', ['/static/../app.py', '/static/%2e%2e/app.py', '/static/..%2fapp.py', '/assets/fonts/../../main.py',
                                  '/assets/fonts/%2e%2e/%2e%2e/main.py', '/static/js/../../runner.py', '/assets/../main.py'])
def test_nessun_traversal(web, path):
    c, _ = web
    r = c.get(path)
    assert r.status_code in (400, 404) and b'import' not in r.content[:200]


def test_senza_token_nemmeno_i_file_statici(web):
    _, s = web
    assert httpx.get(f'http://127.0.0.1:{s.port}/static/app.css').status_code == 401
