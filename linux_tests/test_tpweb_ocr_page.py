# -*- coding: utf-8 -*-
"""Fase 5b: OCR dal Library Scanner e revisione mirata nella pagina. Motore OCR, client e API finti; server, coda e browser veri."""
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, Env  # noqa: E402,F401
from test_tpweb_settings_page import until, message, settle, api  # noqa: E402,F401
from test_tpweb_library import FakeClient, FakeApi  # noqa: E402
from test_tpweb_ocr import FakeEngine  # noqa: E402
from utils.translations import Translations  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')
IT = Translations.TEXTS['it']


@pytest.fixture
def env(tmp_path, monkeypatch, browser):
    FakeClient.calls, FakeClient.notified, FakeClient.fail = [], [], False
    FakeApi.calls, FakeApi.reply = [], (200, '{}')
    FakeEngine.made, FakeEngine.writeback_ok, FakeEngine.gate = [], True, None
    e = Env()
    e.tmp, e.browser, e.pages, e.problems = tmp_path, browser, [], []
    e.srv, e.config = e2e.make_server(tmp_path, monkeypatch, library_deps={'client': FakeClient, 'api': FakeApi()}, ocr_engine=FakeEngine)
    e.config.set('library_scanner_url', 'http://scanner:6680', save=False)
    e.config.set('library_scanner_api_key', 'k' * 24, save=False)
    e.config.set('library_scanner_path_map', 'V:\\=/mnt/v', save=False)
    e.srv.queue.compact = False

    def open_page():
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('console', lambda m: e.problems.append(('console', m.text)) if m.type in ('error', 'warning') and '409' not in m.text else None)
        page.on('pageerror', lambda x: e.problems.append(('pageerror', str(x))))
        page.goto(e.srv.url)
        page.wait_for_selector('[data-testid=left-panel]')
        e.pages.append(page)
        return page
    e.open = open_page
    yield e
    if FakeEngine.gate is not None:
        FakeEngine.gate.set()
    e.srv.queue.stop(); e.srv.queue.join(20)
    for p in e.pages:
        p.close()
    e.srv.stop()


def open_card(page):
    page.click('[data-testid=scanner-head]')
    page.wait_for_selector('[data-testid=scanner-body]')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length > 0")


def test_badge_avvia_l_ocr_riga_nella_coda_avanzamento_e_messaggio(env):
    page = env.open()
    open_card(page)
    FakeEngine.gate = threading.Event()
    path = 'V:\\film\\Altro.mkv'                        # nel finto client il badge del film 3 e' MIX (-> pgs)
    page.click('[data-testid=badge-3]')
    page.wait_for_selector(f'.file-row[data-status=processing]')
    until(page, "() => document.querySelector('[data-testid=scanner-stats]').innerText.includes('Altro.mkv')")        # avanzamento al posto delle statistiche
    assert page.locator('.file-row[data-status=processing] .row-bar-fill').evaluate('e => e.style.width') == '30%'
    page.click('[data-testid=badge-1]')                                       # un altro OCR mentre uno gira
    assert message(page) == (IT['ocr_section_title'], IT['ls_ocr_other_running'])
    FakeEngine.gate.set()
    title, text = message(page)
    assert title == IT['ocr_section_title'] and text == IT['ls_conv_done'].format(name='Altro.mkv')
    until(page, "() => document.querySelectorAll('.file-row[data-status=completed]').length === 1")
    assert page.locator('[data-testid=scanner-stats]').inner_text() == IT['files_stats'].format(without=6, total=100)
    assert FakeEngine.made[0].args['kind'] == 'pgs' and env.problems == []


def start_review(page, env):
    open_card(page)
    page.click('[data-testid=badge-2]')                                       # nel finto client il film 2 (VOB) -> vobsub: usa il nome 'Serie'
    page.wait_for_selector('[data-testid=ocr-review]')


def test_revisione_dialogo_lista_filtro_tasti_corsivo_e_scrittura(env):
    from test_tpweb_library import VIDEOS
    VIDEOS[1]['filename'], VIDEOS[1]['windows_path'] = 'review.mkv', 'V:\\serie\\review.mkv'
    try:
        page = env.open()
        start_review(page, env)
        assert page.locator('.review-item').count() == 4 and page.locator('.review-item.selected').get_attribute('data-i') == '1'     # primo dubbio
        assert page.locator('[data-testid=rv-counter]').inner_text() == IT['ocr_counter'].format(total=4, flagged=2)
        assert page.locator('[data-testid=rv-text]').input_value() == 'Dubb1o'
        assert '#2' in page.locator('.review-item.selected').inner_text() and 'Dubb1o' in page.locator('.review-item.selected').inner_text()
        until(page, "() => { const i = document.querySelector('[data-testid=rv-image]'); return i && i.complete && i.naturalWidth > 0; }")
        # Invio: salva e passa al prossimo dubbio (Maiusc+Invio = riga nuova)
        page.fill('[data-testid=rv-text]', 'Dubbio')
        page.press('[data-testid=rv-text]', 'Shift+Enter')
        assert page.locator('[data-testid=rv-text]').input_value() == 'Dubbio\n'
        page.fill('[data-testid=rv-text]', 'Dubbio')
        page.press('[data-testid=rv-text]', 'Enter')
        until(page, "() => document.querySelector('.review-item.selected').dataset.i === '3'")
        assert page.locator('[data-testid=rv-text]').input_value() == 'Altro dubbio'
        assert 'Dubbio' in page.locator('.review-item[data-i="1"]').inner_text()        # etichetta aggiornata dal server
        # corsivo sull'intera riga e su una selezione
        text_is = lambda v: until(page, "() => document.querySelector('[data-testid=rv-text]').value === %r" % v)      # noqa: E731
        page.click('[data-testid=rv-italic]')
        text_is('<i>Altro dubbio</i>')
        page.click('[data-testid=rv-italic]')
        text_is('Altro dubbio')
        page.locator('[data-testid=rv-text]').evaluate('e => { e.focus(); e.setSelectionRange(0, 5); }')
        page.click('[data-testid=rv-italic]')
        text_is('<i>Altro</i> dubbio')
        # verificato: sparisce dai dubbi; con il filtro «solo dubbi» la lista si restringe
        page.click('[data-testid=rv-verify]')
        until(page, "() => document.querySelector('[data-testid=rv-counter]').innerText.includes('1')")
        page.locator('[data-testid=rv-flagged]').locator('xpath=..').click()
        until(page, "() => document.querySelectorAll('.review-item').length === 1")
        page.locator('[data-testid=rv-flagged]').locator('xpath=..').click()
        until(page, "() => document.querySelectorAll('.review-item').length === 4")
        page.click('.review-item[data-i="0"]')
        until(page, "() => document.querySelector('.review-item.selected').dataset.i === '0'")
        assert page.locator('[data-testid=rv-prev]').is_disabled() and page.locator('[data-testid=rv-next]').is_enabled()
        page.click('[data-testid=rv-next]')
        until(page, "() => document.querySelector('.review-item.selected').dataset.i === '1'")
        assert page.locator('[data-testid=rv-noimage]').count() == 0
        page.click('.review-item[data-i="2"]')
        until(page, "() => document.querySelector('[data-testid=rv-noimage]')")
        page.fill('[data-testid=rv-text]', 'Fine!')                                    # modifica non ancora salvata: «Fatto» la salva
        page.click('[data-testid=rv-done]')
        title, text = message(page)
        assert text == IT['ls_srt_written'].format(name='review.mkv')
        wb = FakeEngine.made[-1].args
        assert wb['mode'] == 'writeback' and 'Dubbio' in wb['srt_text'] and '<i>Altro</i> dubbio' in wb['srt_text'] and 'Fine!' in wb['srt_text']
        assert page.locator('[data-testid=ocr-review]').count() == 0 and env.problems == []
    finally:
        VIDEOS[1]['filename'], VIDEOS[1]['windows_path'] = 'Serie.S01E01.mkv', 'V:\\serie\\Serie.S01E01.mkv'


def test_chiudere_la_revisione_annulla(env):
    from test_tpweb_library import VIDEOS
    VIDEOS[1]['filename'], VIDEOS[1]['windows_path'] = 'review.mkv', 'V:\\serie\\review.mkv'
    try:
        page = env.open()
        start_review(page, env)
        page.keyboard.press('Escape')
        page.wait_for_selector('[data-testid=ocr-review]', state='detached')
        until(page, "() => document.querySelectorAll('.file-row[data-status=failed]').length === 1")
        assert env.srv.queue.gate.ocr_running is False and [e.args['mode'] for e in FakeEngine.made] == ['ocr']
    finally:
        VIDEOS[1]['filename'], VIDEOS[1]['windows_path'] = 'Serie.S01E01.mkv', 'V:\\serie\\Serie.S01E01.mkv'


def test_menu_dei_job_ocr_differiti(env, monkeypatch):
    from tpweb.queue_backend import WebQueue
    monkeypatch.setattr(WebQueue, 'is_processing', property(lambda self: True))
    page = env.open()
    open_card(page)
    page.click('[data-testid=badge-3]')
    page.wait_for_selector('.file-row[data-status=queued]')
    assert FakeEngine.made == [] and env.srv.app.state.ocr.state()['deferred'] == ['V:\\film\\Altro.mkv']
    page.click('.file-row[data-status=queued]')
    page.click('.file-row[data-status=queued]', button='right')
    page.click('.ctx-item[data-label="%s"]' % IT['job_ov_ocr_review'])
    page.click('.ctx-item[data-label="%s"]' % IT['job_ov_ocr_targeted'])
    until(page, "() => document.querySelector('.file-row[data-status=queued]').innerText.includes('%s')" % IT['job_ov_ocr_targeted_short'])
    assert env.srv.app.state.ocr.mode_override == {'V:\\film\\Altro.mkv': 'review'}
    page.click('.file-row[data-status=queued]', button='right')                  # «Predefinita» toglie l'etichetta
    page.click('.ctx-item[data-label="%s"]' % IT['job_ov_ocr_review'])
    page.click('.ctx-item[data-label="%s"]' % IT['job_ov_default'])
    until(page, "() => !document.querySelector('.file-row[data-status=queued]').innerText.includes('%s')" % IT['job_ov_ocr_targeted_short'])
    assert env.srv.app.state.ocr.mode_override == {}


def test_superpower_conferma_elenco_e_batch(env):
    import json
    env.srv.app.state.library._api = FakeApi()
    FakeApi.reply = (200, json.dumps({'videos': [{'windows_path': 'V:\\auto_ok1.mkv', 'bitmap_format': 'pgs'}, {'windows_path': 'V:\\auto_ok2.mkv', 'bitmap_format': 'vobsub'}]}))
    page = env.open()
    open_card(page)
    page.click('[data-testid=scanner-superpower]')
    page.wait_for_selector('.modal-confirm')
    assert page.locator('.modal-confirm .modal-title').inner_text() == IT['web_superpower_confirm_title']
    assert page.locator('.modal-confirm .modal-text').inner_text() == IT['ls_sp_confirm']
    page.click('[data-testid=confirm-no]')                                     # «No»: non parte nulla
    settle(page)
    assert FakeEngine.made == [] and FakeApi.calls == []
    page.click('[data-testid=scanner-superpower]')
    page.click('[data-testid=confirm-yes]')
    assert message(page) == (IT['ocr_section_title'], IT['ls_batch_done'].format(ok=2, fail=0, total=2))
    until(page, "() => document.querySelectorAll('.file-row[data-status=completed]').length === 2")
    assert [e.args['strategy'] for e in FakeEngine.made] == ['auto', 'auto']
    FakeApi.reply = (200, json.dumps({'videos': []}))
    page.click('[data-testid=scanner-superpower]'); page.click('[data-testid=confirm-yes]')
    assert message(page) == (IT['web_superpower_title'], IT['ls_sp_none'])


def test_superpower_senza_configurazione_avvisa_e_non_chiede_conferma(env):
    page = env.open()
    open_card(page)
    env.config.set('library_scanner_url', '', save=False)
    page.click('[data-testid=scanner-superpower]')
    assert message(page) == (IT['web_superpower_title'], IT['ls_not_configured'])
    assert page.locator('.modal-confirm').count() == 0
