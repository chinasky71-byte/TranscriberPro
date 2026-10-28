# -*- coding: utf-8 -*-
"""Fase 5a: la card «Library Scanner» nella pagina. Client e API finti, server e coda veri."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, Env  # noqa: E402,F401
from test_tpweb_settings_page import until, message, settle, api  # noqa: E402,F401
from test_tpweb_library import FakeClient, FakeApi, configure, clear_credentials  # noqa: E402
from utils.translations import Translations  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')
IT = Translations.TEXTS['it']


@pytest.fixture
def env(tmp_path, monkeypatch, browser):
    FakeClient.calls, FakeClient.notified, FakeClient.fail = [], [], False
    FakeApi.calls, FakeApi.reply = [], (200, '{}')
    e = Env()
    e.tmp, e.browser, e.pages, e.problems = tmp_path, browser, [], []
    e.srv, e.config = e2e.make_server(tmp_path, monkeypatch, library_deps={'client': FakeClient, 'api': FakeApi()})
    e.config.set('library_scanner_url', 'http://scanner:6680', save=False)
    e.config.set('library_scanner_api_key', 'k' * 24, save=False)
    e.config.set('library_scanner_path_map', 'V:\\=/mnt/v', save=False)
    e.srv.queue.compact = False

    def open_page():
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('console', lambda m: e.problems.append(('console', m.text)) if m.type in ('error', 'warning') else None)
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


def open_card(page):
    page.click('[data-testid=scanner-head]')
    page.wait_for_selector('[data-testid=scanner-body]')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length > 0")


def paths(page):
    return page.locator('[data-testid=scanner-table] tbody tr').evaluate_all('els => els.map(e => e.dataset.path)')


def test_card_chiusa_apertura_ricordata_stato_e_statistiche(env):
    page = env.open()
    assert page.locator('[data-testid=scanner-card]').get_attribute('data-open') == 'false'
    assert page.locator('[data-testid=scanner-body]').count() == 0
    until(page, "() => document.querySelector('[data-testid=scanner-state]').innerText === '%s'" % IT['mw_scanner_active'])    # primo caricamento dopo ~2,5 s
    assert page.locator('[data-testid=scanner-badge]').inner_text() == '6'
    open_card(page)
    assert page.locator('[data-testid=scanner-stats]').inner_text() == IT['files_stats'].format(without=6, total=100)
    assert 'on' in page.locator('[data-testid=scanner-dot]').get_attribute('class')
    assert len(paths(page)) == 6
    page.reload()
    page.wait_for_selector('[data-testid=scanner-body]')                              # l'apertura e' nella configurazione
    assert env.problems == []


def test_filtri_giorni_formato_ricerca_e_ordinamento(env):
    page = env.open()
    open_card(page)
    n = len(FakeClient.calls)
    page.fill('[data-testid=scanner-days]', '15'); page.press('[data-testid=scanner-days]', 'Tab')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 3")
    assert page.locator('[data-testid=scanner-badge]').inner_text() == '3' and len(FakeClient.calls) == n          # nessun ricaricamento
    page.fill('[data-testid=scanner-days]', '0'); page.press('[data-testid=scanner-days]', 'Tab')
    page.select_option('[data-testid=scanner-format]', 'pgs')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 2")
    assert len(FakeClient.calls) == n
    page.select_option('[data-testid=scanner-format]', 'assssa')                      # un altro endpoint: ricarica dal server
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 1")
    assert FakeClient.calls[-1][2] == 'assssa' and page.locator('[data-testid=scanner-import-all]').inner_text() == IT['ls_convert_ass']
    page.select_option('[data-testid=scanner-format]', '')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 6")
    assert FakeClient.calls[-1][2] == '' and page.locator('[data-testid=scanner-import-all]').inner_text() == IT['import_filtered']
    page.click('[data-testid=scanner-table] th >> nth=2')                              # ordina per giorni, crescente poi decrescente
    days = lambda: [int(x) for x in page.locator('.scanner-table td.c-days').all_inner_texts()]       # noqa: E731
    assert days() == sorted(days())
    page.click('[data-testid=scanner-table] th >> nth=2')
    assert days() == sorted(days(), reverse=True)
    page.select_option('[data-testid=scanner-type]', 'movie')
    page.fill('[data-testid=scanner-search]', 'film')                                  # ricerca sul server dopo 500 ms
    settle(page); settle(page); settle(page)
    assert FakeClient.calls[-1][:2] == ('film', 'movie')


def test_import_singolo_e_tutti_nella_coda_con_la_mappa_dei_percorsi(env):
    page = env.open()
    open_card(page)
    page.click('[data-testid=add-3]')
    until(page, "() => document.querySelector('[data-testid=add-3]').disabled")
    assert page.locator('[data-testid=add-3]').inner_text() == '✓' and env.srv.queue.queue.snapshot() == ['/mnt/v/film/Altro.mkv']
    page.fill('[data-testid=scanner-days]', '15'); page.press('[data-testid=scanner-days]', 'Tab')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 3")
    page.click('[data-testid=scanner-import-all]')                                     # solo le righe visibili
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] .add-btn:disabled').length === 3")
    assert sorted(env.srv.queue.queue.snapshot()) == sorted(['/mnt/v/film/Altro.mkv', '/mnt/v/film/Film.Uno.ITA.mkv', '/mnt/v/serie/Serie.S01E01.mkv', '/mnt/v/film/Pgs.Con.Testo.mkv'])
    assert any(IT['files_imported_log'].format(added=3) in l['text'] for l in env.srv.queue.log.lines)
    until(page, "() => document.querySelectorAll('.file-row').length === 4")                 # la coda della pagina segue gli eventi del server


def test_conversione_ass_dal_badge_dal_pulsante_e_filtro(env):
    page = env.open()
    open_card(page)
    page.select_option('[data-testid=scanner-format]', 'assssa')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 1")
    assert page.locator('[data-testid=badge-4]').is_disabled()                         # conversione gia' fatta
    page.click('[data-testid=scanner-import-all]')                                     # filtro ASS/SSA: converte tutti i pending
    title, text = message(page)
    assert title == IT['ls_ass_title'] and text == IT['ls_ass_started_body'].format(desc=IT['ls_all_pending'])
    assert FakeApi.calls[-1][3] == {}
    page.select_option('[data-testid=scanner-format]', '')
    until(page, "() => document.querySelectorAll('[data-testid=scanner-table] tbody tr').length === 6")
    FakeApi.reply = (500, 'boom')
    page.click('[data-testid=add-4]')                                                  # riga con ASS: il «+» converte, non accoda
    assert message(page)[1] == IT['ls_srv_err'].format(status=500, text='boom')
    assert env.srv.queue.queue.snapshot() == []


def test_notifica_del_sottotitolo_ricarica_l_elenco(env):
    page = env.open()
    open_card(page)
    n = len(FakeClient.calls)
    env.srv.queue.on_file_completed('/mnt/v/film/Altro.mkv')
    for _ in range(40):
        if len(FakeClient.calls) > n:
            break
        page.wait_for_timeout(100)
    assert len(FakeClient.calls) > n and FakeClient.notified == ['V:\\film\\Altro.mkv']


def test_senza_configurazione_e_errore_di_rete(env):
    page = env.open()
    clear_credentials(env)
    page.click('[data-testid=scanner-head]')
    page.wait_for_selector('[data-testid=scanner-body]')
    page.click('[data-testid=scanner-refresh]')
    until(page, "() => document.querySelector('[data-testid=scanner-stats]').innerText === '%s'" % IT['config_missing'])
    env.config.set('library_scanner_url', 'http://scanner:6680', save=False)
    env.config.set('library_scanner_api_key', 'k' * 24, save=False)
    FakeClient.fail = True
    page.click('[data-testid=scanner-refresh]')
    until(page, "() => document.querySelector('[data-testid=scanner-stats]').innerText === '%s'" % IT['error_status'].format(message='Server non raggiungibile: x'))
    assert 'off' in page.locator('[data-testid=scanner-dot]').get_attribute('class') and page.locator('[data-testid=scanner-state]').inner_text() == IT['web_scanner_idle']
