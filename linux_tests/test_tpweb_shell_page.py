# -*- coding: utf-8 -*-
"""Fase 6a: la pagina dentro il guscio nativo (finto `window.pywebview`): dialoghi nativi, trascinamento da Esplorer, richiesta di uscita."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, env, wait_rows  # noqa: E402,F401
from test_tpweb_settings_page import until  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')


def native_shell(page_script):
    return """window.__calls = []; window.pywebview = {api: {
      pick_files: async (title, exts) => { window.__calls.push(['files', title, exts]); return %s.files; },
      pick_folder: async (title) => { window.__calls.push(['folder', title]); return %s.folder; } }};""" % (page_script, page_script)


def open_native(env, files, folder):
    import json
    page = env.browser.new_page(viewport={'width': 1400, 'height': 900})
    page.add_init_script(native_shell(json.dumps({'files': files, 'folder': folder})))
    page.on('pageerror', lambda x: env.problems.append(('pageerror', str(x))))
    page.goto(env.srv.url)
    page.wait_for_selector('[data-testid=left-panel]')
    env.pages.append(page)
    return page


def test_aggiungi_file_usa_il_dialogo_nativo(env, tmp_path):
    import _queue_testkit as kit
    vids = kit.make_videos(tmp_path, 'uno.mkv', 'due.mp4')
    page = open_native(env, [str(v) for v in vids], None)
    page.click('[data-testid=add-files]')
    wait_rows(page, 2)
    assert page.locator('[data-testid=file-browser]').count() == 0                   # niente navigatore web
    kind, title, exts = page.evaluate('window.__calls[0]')
    assert kind == 'files' and '.mkv' in exts and title


def test_dialogo_nativo_annullato_non_aggiunge_nulla_e_cartella_viene_scansionata(env, tmp_path):
    import _queue_testkit as kit
    kit.make_videos(tmp_path, 'uno.mkv')
    page = open_native(env, None, [str(tmp_path)])
    page.click('[data-testid=add-files]')
    page.wait_for_timeout(300)
    assert page.locator('.file-row').count() == 0 and page.locator('[data-testid=file-browser]').count() == 0
    page.click('[data-testid=add-folder]')
    wait_rows(page, 1)
    assert page.evaluate('window.__calls.map(c => c[0])') == ['files', 'folder']


def test_trascinamento_da_esplorer_con_percorso_vero_e_senza(env, tmp_path):
    import _queue_testkit as kit
    vids = kit.make_videos(tmp_path, 'uno.mkv', 'due.mp4')
    page = env.open()
    drop = """paths => {
      const dt = new DataTransfer();
      for (const p of paths) { const f = new File(['x'], p.split('/').pop()); if (p.startsWith('/')) Object.defineProperty(f, 'pywebviewFullPath', {value: p}); dt.items.add(f); }
      const ev = new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true});
      document.querySelector('.window').dispatchEvent(ev);
      return ev.defaultPrevented;
    }"""
    assert page.evaluate(drop, ['senza_percorso.mkv']) is True                      # in un browser: ignorato ma non apre il file
    page.wait_for_timeout(200)
    assert page.locator('.file-row').count() == 0
    assert page.evaluate(drop, [str(v) for v in vids] + ['senza_percorso.mkv']) is True
    wait_rows(page, 2)


def test_richiesta_di_uscita_dal_guscio_apre_la_conferma(env):
    page = env.open()
    page.evaluate("() => window.dispatchEvent(new Event('tp-quit-request'))")
    page.wait_for_selector('.modal-confirm')
    page.click('[data-testid=confirm-no]')
    page.wait_for_selector('.modal-confirm', state='detached')
