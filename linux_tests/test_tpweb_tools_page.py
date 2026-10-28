# -*- coding: utf-8 -*-
"""Fase 4b: il dialogo «Glossario per show» nel browser. Motore vero con un finto CLI, cartella di lavoro e home isolate, ricerca TMDB finta."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, Env  # noqa: E402,F401
from test_tpweb_settings_page import until, tick, message, settle, api  # noqa: E402,F401
from test_tpweb_tools import stub_engine  # noqa: E402
from utils.translations import Translations  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')
IT = Translations.TEXTS['it']


@pytest.fixture
def env(tmp_path, monkeypatch, browser):
    from core.services import glossary_service as GS
    monkeypatch.setattr(GS, 'PROJECT_ROOT', tmp_path / 'proj')
    monkeypatch.setattr(GS, 'resolve_tmdb', lambda names: ({'id': 321, 'title': names[0]}, names[0]) if names and names[0] != 'Sconosciuto' else (None, None))
    e = Env()
    e.tmp, e.browser, e.pages, e.problems = tmp_path, browser, [], []
    e.srv, e.config = e2e.make_server_with_tools(tmp_path, monkeypatch, {'glossary': stub_engine})
    e.show = tmp_path / 'media' / 'Mio Show' / 'Season 1'
    e.show.mkdir(parents=True)
    (e.show / 'Mio.Show.S01E01.mkv').write_text('x')

    def open_page():
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('console', lambda m: e.problems.append(('console', m.text)) if m.type in ('error', 'warning') and '409' not in m.text and '422' not in m.text else None)
        page.on('pageerror', lambda x: e.problems.append(('pageerror', str(x))))
        page.goto(e.srv.url)
        page.wait_for_selector('[data-testid=left-panel]')
        e.pages.append(page)
        return page
    e.open = open_page
    yield e
    e.srv.queue.stop(); e.srv.queue.join(20)
    for p in e.pages:
        p.close()
    e.srv.stop()


def open_glossary(page):
    page.click('[data-testid=tools-menu]')
    page.click('.ctx-item[data-label="%s"]' % IT['tools_glossary'])
    page.wait_for_selector('[data-testid=glossary-dialog]')


def pick_folder(page, folder):
    page.click('[data-testid=gl-browse]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.evaluate("p => fetch('/api/fs/last', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder: p})})", str(folder))
    page.click('[data-testid=fs-cancel]')
    page.fill('[data-testid=gl-folder]', str(folder))


def test_apertura_blocchi_come_la_gui(env):
    page = env.open()
    env.srv.queue.gate.sync_active = True
    page.click('[data-testid=tools-menu]'); page.click('.ctx-item[data-label="%s"]' % IT['tools_glossary'])
    assert message(page) == (IT['tools_glossary'], IT['glossary_blocked_sync'])
    assert page.locator('[data-testid=glossary-dialog]').count() == 0
    env.srv.queue.gate.sync_active = False
    env.srv.queue.add(['/a.mkv'])
    assert env.srv.queue.start() == 'ok'
    until(page, "() => document.querySelector('[data-testid=tools-menu]').disabled")       # a coda in lavoro la voce e' disattivata come nella GUI
    env.srv.queue.stop(); env.srv.queue.join(20)


def test_cartella_nome_tmdb_e_conferma_senza_id(env):
    page = env.open()
    open_glossary(page)
    page.click('[data-testid=gl-run]')
    assert message(page) == (IT['glossary_dialog_title'], IT['glossary_error_no_folder'])
    page.click('[data-testid=gl-browse]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click('[data-testid=fs-cancel]')
    # selezione vera dal navigatore: si naviga fino alla cartella e si conferma «qui»
    r = page.evaluate("p => fetch('/api/fs/list?path=' + encodeURIComponent(p) + '&dirs_only=true').then(r => r.json())", str(env.show))
    assert r['path'] == str(env.show)
    page.fill('[data-testid=gl-folder]', str(env.show))
    page.fill('[data-testid=gl-name]', 'Sconosciuto')
    page.click('[data-testid=gl-resolve]')
    until(page, "() => document.querySelector('[data-testid=gl-tmdb]').innerText.length > 0")
    settle(page)
    assert page.locator('[data-testid=gl-tmdb]').inner_text() == IT['glossary_tmdb_not_found']
    page.click('[data-testid=gl-run]')                                         # senza id: chiede conferma, «No» non parte
    page.wait_for_selector('.modal-confirm')
    assert page.locator('.modal-confirm .modal-text').inner_text() == IT['glossary_confirm_no_tmdb']
    page.keyboard.press('Escape')
    assert api(page, '/api/tools/glossary')['status'] == 'idle'
    page.fill('[data-testid=gl-name]', 'Il Mio Show')
    page.click('[data-testid=gl-resolve]')
    until(page, "() => document.querySelector('[data-testid=gl-tmdb]').innerText.startsWith('TMDB #321')")
    assert page.locator('[data-testid=gl-tmdb]').inner_text() == 'TMDB #321 — Il Mio Show'


def run_ok(page, env, name='ok'):
    page.fill('[data-testid=gl-folder]', str(env.show))
    page.fill('[data-testid=gl-name]', name)
    page.click('[data-testid=gl-resolve]')
    until(page, "() => document.querySelector('[data-testid=gl-tmdb]').innerText.startsWith('TMDB #')")
    page.click('[data-testid=gl-run]')
    until(page, "() => document.querySelector('[data-testid=gl-cards]').children.length > 0")


def test_run_schede_candidato_modifica_resa_e_salvataggio(env):
    page = env.open()
    open_glossary(page)
    run_ok(page, env, 'ok')
    assert page.locator('[data-testid=gl-status]').inner_text() == IT['glossary_status_done'].format(n=2)
    assert 'fine' in page.locator('[data-testid=gl-log]').inner_text()
    cards = page.locator('.term-card')
    assert cards.count() == 2 and cards.nth(0).get_attribute('data-term') == 'Winterfell'
    assert page.locator('[data-testid=gl-ok-Raven]').is_checked() is False         # «review»: aperta e non approvata
    assert page.locator('.term-card[data-term=Winterfell] .term-body').count() == 0   # «auto»: chiusa
    page.click('.term-card[data-term=Winterfell] .term-head')
    assert page.locator('[data-testid=gl-ok-Winterfell]').is_checked() is True
    assert page.locator('[data-testid=gl-rend-Winterfell]').input_value() == 'Grande Inverno'
    assert page.locator('[data-testid=gl-info-Winterfell]').inner_text().startswith(f"{IT['glossary_occurrences']}: 12 · ")
    page.fill('[data-testid=gl-rend-Winterfell]', 'Grande Inverno 2')
    tick(page, 'gl-ok-Raven')
    page.click('[data-testid=gl-save]')
    title, text = message(page)
    assert title == IT['glossary_dialog_title'] and text.startswith('2 ') and 'tmdb_321.json' in text.replace('\\', '/')
    saved = (env.tmp / 'home' / '.transcriberpro' / 'glossary' / 'tmdb_321.json').read_text(encoding='utf-8')
    assert 'Grande Inverno 2' in saved and 'Corvo' in saved
    assert env.problems == []


def test_ricaricare_la_pagina_non_annulla_chiudere_il_dialogo_si(env):
    page = env.open()
    open_glossary(page)
    page.fill('[data-testid=gl-folder]', str(env.show))
    page.fill('[data-testid=gl-name]', 'slow')
    page.click('[data-testid=gl-resolve]')
    until(page, "() => document.querySelector('[data-testid=gl-tmdb]').innerText.startsWith('TMDB #')")
    page.click('[data-testid=gl-run]')
    until(page, "() => document.querySelector('[data-testid=gl-cancel]') && !document.querySelector('[data-testid=gl-cancel]').disabled")
    page.reload()                                                              # il run e' sul server: la scheda si ricarica e non lo ferma
    page.wait_for_selector('[data-testid=left-panel]')
    assert api(page, '/api/tools/glossary')['status'] == 'running'
    page.click('[data-testid=tools-menu]')
    assert page.locator('[data-testid=tools-menu]').is_enabled()
    # la coda e' libera, ma il glossario e' attivo: la sincronizzazione resterebbe bloccata (4c); qui si riapre il dialogo e lo stato e' quello vero
    page.keyboard.press('Escape')
    page.click('[data-testid=tools-menu]'); page.click('.ctx-item[data-label="%s"]' % IT['tools_glossary'])
    page.wait_for_selector('[data-testid=glossary-dialog]')
    assert page.locator('[data-testid=gl-run]').is_disabled() and page.locator('[data-testid=gl-name]').input_value().startswith('slow')
    page.click('[data-testid=glossary-close]')                                 # chiudere annulla e azzera
    page.wait_for_selector('[data-testid=glossary-dialog]', state='detached')
    assert api(page, '/api/tools/glossary')['status'] == 'idle'
    assert env.srv.queue.gate.snapshot()['glossary'] is False
