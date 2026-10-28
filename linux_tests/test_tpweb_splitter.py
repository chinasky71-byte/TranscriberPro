# -*- coding: utf-8 -*-
"""Fase 6: le maniglie tra i tre pannelli (QSplitter): trascinamento con minimo 200 px, misure salvate e ripristinate."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, env  # noqa: E402,F401
from test_tpweb_settings_page import until, api  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')


def widths(page):
    return page.evaluate("() => [...document.querySelectorAll('.splitter > .panel')].map(p => Math.round(p.getBoundingClientRect().width))")


def drag(page, handle, dx):
    box = page.locator(f'[data-testid=split-handle-{handle}]').bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + 200
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx / 2, y, steps=3)
    page.mouse.move(x + dx, y, steps=3)
    page.mouse.up()


def test_misure_predefinite_trascinamento_minimo_e_ripristino(env):
    page = env.open()
    w0 = widths(page)
    assert w0[0] < w0[1] and abs(w0[1] - w0[2]) <= 1                       # 2:3:3
    drag(page, 0, 100)
    w1 = widths(page)
    assert abs((w1[0] - w0[0]) - 100) <= 2 and abs((w0[1] - w1[1]) - 100) <= 2 and w1[2] == w0[2]
    page.wait_for_timeout(300)
    saved = api(page, '/api/settings/splitter')['sizes']
    assert saved is not None and len(saved) == 3
    drag(page, 1, -2000)                                                    # oltre il minimo: il centro si ferma a 200 px
    w2 = widths(page)
    assert w2[1] == 200
    page.reload()
    page.wait_for_selector('[data-testid=left-panel]')
    page.wait_for_timeout(300)
    assert widths(page) == w2                                               # misure ripristinate dal server


def test_dimensioni_non_valide_rifiutate_e_lette_come_la_gui(env):
    page = env.open()
    r = page.evaluate("() => fetch('/api/settings/splitter', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({sizes: [100, 0, 100]})}).then(r => r.status)")
    assert r == 422
    r = page.evaluate("() => fetch('/api/settings/splitter', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({sizes: [100, 100]})}).then(r => r.status)")
    assert r == 422
    assert api(page, '/api/settings/splitter')['sizes'] is None


def center_heights(page):
    return page.evaluate("() => { const k = [...document.querySelector('.center-split').children]; return [k[0], k[2]].map(e => Math.round(e.getBoundingClientRect().height)); }")


def test_maniglia_tra_anteprima_e_monitor(env):
    page = env.open()
    h0 = center_heights(page)
    assert h0[1] == 217                                                     # predefinito: monitor alto 217 px come nella finestra Qt di riferimento
    box = page.locator('[data-testid=split-handle-center]').bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x, y - 40, steps=4); page.mouse.up()
    h1 = center_heights(page)
    assert abs((h0[0] - h1[0]) - 40) <= 2 and abs((h1[1] - h0[1]) - 40) <= 2
    page.wait_for_timeout(300)
    saved = api(page, '/api/settings/center_split')['sizes']
    assert saved is not None and abs(saved[1] - h1[1]) <= 1
    box = page.locator('[data-testid=split-handle-center]').bounding_box()
    page.mouse.move(box['x'] + 5, box['y'] + 3); page.mouse.down(); page.mouse.move(box['x'] + 5, box['y'] - 2000, steps=4); page.mouse.up()
    assert center_heights(page)[0] == 120                                   # minimo 120 px per l'anteprima
    page.reload()
    page.wait_for_selector('[data-testid=left-panel]')
    page.wait_for_timeout(300)
    assert center_heights(page)[0] == 120


def test_misure_del_centro_non_valide(env):
    page = env.open()
    put = "(b) => fetch('/api/settings/center_split', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)}).then(r => r.status)"
    assert page.evaluate(put, {'sizes': [100, 0]}) == 422 and page.evaluate(put, {'sizes': [1, 2, 3]}) == 422
    assert api(page, '/api/settings/center_split')['sizes'] is None
