# -*- coding: utf-8 -*-
"""Fase 4c: il dialogo «Sincronizzazione» nel browser. Singola con un finto SubtitleSynchronizer, coda con il finto `core.sync_cli`."""
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, Env  # noqa: E402,F401
from test_tpweb_settings_page import until, tick, message, settle, api  # noqa: E402,F401
from test_tpweb_sync import FakeSync, single_engine, batch_engine, make_tree  # noqa: E402
from utils.translations import Translations  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')
IT = Translations.TEXTS['it']


@pytest.fixture
def env(tmp_path, monkeypatch, browser):
    mod = types.ModuleType('core.subtitle_synchronizer')
    mod.SubtitleSynchronizer = FakeSync
    monkeypatch.setitem(sys.modules, 'core.subtitle_synchronizer', mod)
    FakeSync.made, FakeSync.behaviour = [], staticmethod(lambda s: True)
    e = Env()
    e.tmp, e.browser, e.pages, e.problems = tmp_path, browser, [], []
    e.srv, e.config = e2e.make_server_with_tools(tmp_path, monkeypatch, {'sync_single': single_engine, 'sync_batch': batch_engine})

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


def open_sync(page):
    page.click('[data-testid=open-sync]')
    page.wait_for_selector('[data-testid=sync-dialog]')


def set_last(page, folder):
    page.evaluate("p => fetch('/api/fs/last', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder: p})})", str(folder))


def pick_folder(page, browse_testid, folder):
    set_last(page, folder)
    page.click(f'[data-testid={browse_testid}]')
    page.wait_for_selector('[data-testid=file-browser]')
    until(page, "() => document.querySelector('[data-testid=fs-path]').innerText.length > 0")
    page.click('[data-testid=fs-ok]')
    page.wait_for_selector('[data-testid=file-browser]', state='detached')


def pick_file(page, browse_testid, folder, path):
    set_last(page, folder)
    page.click(f'[data-testid={browse_testid}]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click(f'.fs-file[data-path="{path}"]')
    page.click('[data-testid=fs-ok]')
    page.wait_for_selector('[data-testid=file-browser]', state='detached')


def test_singola_campi_mancanti_scelta_file_esito_e_log(env):
    page = env.open()
    d = env.tmp / 'm'; d.mkdir()
    (d / 'Film.mkv').write_text('x'); (d / 'Film.it.srt').write_text('x'); (d / 'nota.txt').write_text('x')
    open_sync(page)
    page.click('[data-testid=sy-start]')
    assert message(page) == (IT['warning'], IT['sync_missing_video'])
    pick_file(page, 'sy-video-browse', d, str(d / 'Film.mkv'))
    assert page.locator('[data-testid=sy-video]').input_value() == str(d / 'Film.mkv')
    page.click('[data-testid=sy-start]')
    assert message(page) == (IT['warning'], IT['sync_missing_srt'])
    set_last(page, d); page.click('[data-testid=sy-srt-browse]'); page.wait_for_selector('.fs-file')
    assert page.locator('.fs-row .fs-name').all_inner_texts() == ['Film.it.srt']          # filtro .srt
    page.click('[data-testid=fs-cancel]')

    def beh(s):
        s.log('1. Estrazione audio'); s.prog(40)
        return True
    FakeSync.behaviour = staticmethod(beh)
    pick_file(page, 'sy-srt-browse', d, str(d / 'Film.it.srt'))
    page.click('[data-testid=sy-start]')
    title, text = message(page)
    assert title == IT['sync_done_title'] and text == IT['sync_done_msg'].format(output='/out/Film.it.synced.it.srt')
    assert page.locator('[data-testid=sy-log]').inner_text() == '1. Estrazione audio'
    assert page.locator('[data-testid=sy-progress] .progress-text').inner_text() == '100%'
    assert page.locator('[data-testid=sy-start]').is_enabled() and page.locator('[data-testid=sy-cancel]').is_disabled()
    assert env.problems == []


def test_errore_della_singola_e_chiusura_con_esc(env):
    page = env.open()
    FakeSync.behaviour = staticmethod(lambda s: False)
    open_sync(page)
    page.evaluate("() => 0")
    d = env.tmp / 'm'; d.mkdir()
    (d / 'Film.mkv').write_text('x'); (d / 'Film.it.srt').write_text('x')
    pick_file(page, 'sy-video-browse', d, str(d / 'Film.mkv'))
    pick_file(page, 'sy-srt-browse', d, str(d / 'Film.it.srt'))
    page.click('[data-testid=sy-start]')
    title, text = message(page)
    assert title == IT['error'] and 'fallita' in text
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=sync-dialog]', state='detached')
    assert api(page, '/api/tools/sync')['status'] == 'idle'


def test_coda_di_coppie_abbina_scegli_conferma_ed_esegui(env):
    page = env.open()
    v, s = make_tree(env.tmp, ('Show.S01E01', 'Show.S01E02'))
    open_sync(page)
    page.click('[data-tab=batch]')
    page.click('[data-testid=sy-pair]')
    assert message(page) == (IT['warning'], IT['sync_batch_nothing'])
    pick_folder(page, 'sy-vdir-browse', v)
    pick_folder(page, 'sy-sdir-browse', s)
    page.click('[data-testid=sy-pair]')
    page.wait_for_selector('[data-testid=sy-table] tbody tr')
    assert page.locator('[data-testid=sy-table] tbody tr').count() == 2
    assert page.locator('[data-testid=sy-state-0]').inner_text() == IT['sync_batch_state_ready']
    assert page.locator('[data-testid=sy-summary]').inner_text() == IT['sync_batch_summary'].format(ready=2, check=0, nosrt=0, left=0)
    page.uncheck('[data-testid=sy-inc-1]')
    until(page, "() => document.querySelector('[data-testid=sy-summary]').innerText.includes('1')")
    page.click('[data-testid=sy-start]')
    page.wait_for_selector('.modal-confirm')
    assert page.locator('.modal-confirm .modal-text').inner_text() == IT['sync_batch_confirm'].format(n=1)
    page.click('[data-testid=confirm-yes]')
    title, text = message(page)
    assert title == IT['sync_done_title'] and text == IT['sync_batch_done'].format(ok=1, fail=0, skipped=0)
    assert page.locator('[data-testid=sy-state-0]').inner_text() == IT['sync_batch_state_ok']
    assert page.locator('[data-testid=sy-state-1]').inner_text() == ''
    assert IT['sync_batch_done'].format(ok=1, fail=0, skipped=0) in page.locator('[data-testid=sy-log]').inner_text()
    assert env.problems == []


def test_annulla_ricarica_non_ferma_chiudere_si(env):
    page = env.open()
    started = threading.Event()
    FakeSync.behaviour = staticmethod(lambda s: (started.set(), s.cancelled.wait(20), False)[2])
    d = env.tmp / 'm'; d.mkdir()
    (d / 'Film.mkv').write_text('x'); (d / 'Film.it.srt').write_text('x')
    open_sync(page)
    pick_file(page, 'sy-video-browse', d, str(d / 'Film.mkv'))
    pick_file(page, 'sy-srt-browse', d, str(d / 'Film.it.srt'))
    page.click('[data-testid=sy-start]')
    assert started.wait(10)
    until(page, "() => document.querySelector('[data-testid=sy-cancel]') && !document.querySelector('[data-testid=sy-cancel]').disabled")
    assert page.locator('[data-tab=batch]').is_disabled()                              # schede bloccate col run in corso
    page.reload()                                                                      # il run e' sul server
    page.wait_for_selector('[data-testid=left-panel]')
    assert api(page, '/api/tools/sync')['status'] == 'running'
    assert page.locator('[data-testid=open-sync]').is_enabled()
    page.click('[data-testid=open-sync]')
    page.wait_for_selector('[data-testid=sync-dialog]')
    assert page.locator('[data-testid=sy-start]').is_disabled() and page.locator('[data-testid=sy-cancel]').is_enabled()
    page.click('[data-testid=sync-close]')                                             # chiudere annulla, attende e azzera
    page.wait_for_selector('[data-testid=sync-dialog]', state='detached')
    assert api(page, '/api/tools/sync')['status'] == 'idle' and FakeSync.made[0].cancelled.is_set()
    assert env.srv.queue.gate.snapshot()['sync'] is False


def test_apertura_bloccata_a_coda_in_lavoro_o_con_il_glossario(env):
    page = env.open()
    env.srv.queue.gate.glossary_active = True
    page.click('[data-testid=open-sync]')
    assert message(page) == (IT['sync_dialog_title'], IT['sync_blocked_glossary'])
    env.srv.queue.gate.glossary_active = False
    env.srv.queue.add(['/a.mkv'])
    assert env.srv.queue.start() == 'ok'
    until(page, "() => document.querySelector('[data-testid=open-sync]').disabled")
    env.srv.queue.stop(); env.srv.queue.join(20)
