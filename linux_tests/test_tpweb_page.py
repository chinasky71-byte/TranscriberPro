# -*- coding: utf-8 -*-
"""La pagina Coda nel browser (Chromium del cloud, server vero, finto pipeline_cli): righe, filtri, selezione, aggiunta con il
navigatore dei file, scansione cartella, Avvia/Stop con conferma, Svuota, spegnimento, cronologia, lingua, nessun errore di console."""
import json
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
import _queue_testkit as kit  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')


@pytest.fixture(scope='module')
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=e2e.CHROME, args=['--no-sandbox'])
        yield b
        b.close()


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch, browser):
    e = Env()
    e.tmp, e.browser = tmp_path, browser
    e.srv, e.config = e2e.make_server(tmp_path, monkeypatch)
    e.wq = e.srv.queue
    e.pages = []
    e.problems = []

    def open_page(width=1400, height=900):
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.on('console', lambda m: e.problems.append(('console', m.type, m.text)) if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda x: e.problems.append(('pageerror', str(x))))
        page.on('requestfailed', lambda r: e.problems.append(('requestfailed', r.url)))
        page.on('response', lambda r: e.problems.append(('http', r.status, r.url)) if r.status >= 400 else None)
        page.goto(e.srv.url)
        page.wait_for_selector('[data-testid=left-panel]')
        e.pages.append(page)
        return page
    e.open = open_page
    yield e
    e.wq.stop()
    e.wq.join(20)
    for p in e.pages:
        p.close()
    e.srv.stop()


def rows(page):
    return page.locator('.file-row').evaluate_all("els => els.map(e => ({path: e.dataset.path, status: e.dataset.status, text: e.innerText}))")


def wait_rows(page, n, timeout=10000):
    page.wait_for_function('n => document.querySelectorAll(".file-row").length === n', arg=n, timeout=timeout)


def test_pagina_senza_errori_e_con_i_testi_in_italiano(env):
    page = env.open()
    assert page.title() == 'Transcriber Pro - Trascrizione Video AI'
    assert page.locator('[data-testid=add-files]').inner_text().strip() == 'Aggiungi File'
    assert page.locator('[data-testid=start]').inner_text().strip() == 'Avvia'
    assert page.locator('[data-testid=tabbar] .tab.selected').inner_text().strip().startswith('Coda di processamento (0)')
    time.sleep(1.2)
    assert env.problems == []


def test_pagina_in_inglese_con_la_lingua_scelta(env):
    env.config.set('language', 'en', save=False)
    page = env.open()
    assert page.title() == 'Transcriber Pro - AI Video Transcription'
    assert page.locator('[data-testid=add-folder]').inner_text().strip() == 'Add Folder'
    assert page.locator('[data-filter=queued]').inner_text().strip() == 'Queue (0)'


def test_lingua_auto_segue_il_browser(env, browser):
    env.config.set('language', 'auto', save=False)
    ctx = browser.new_context(locale='it-IT')
    page = ctx.new_page()
    page.goto(env.srv.url)
    page.wait_for_selector('[data-testid=left-panel]')
    assert page.locator('[data-testid=start]').inner_text().strip() == 'Avvia'
    ctx.close()
    ctx = browser.new_context(locale='en-US')
    page = ctx.new_page()
    page.goto(env.srv.url)
    page.wait_for_selector('[data-testid=left-panel]')
    assert page.locator('[data-testid=start]').inner_text().strip() == 'Start'
    ctx.close()


def test_righe_stati_filtri_e_contatori(env):
    paths = e2e.seed_rows(env.wq)
    page = env.open()
    wait_rows(page, 3)
    r = rows(page)
    assert [x['status'] for x in r] == ['completed', 'processing', 'queued']
    assert 'Film Uno.mkv' in r[0]['text'] and '1.5 GB' in r[0]['text'] and 'completato' in r[0]['text']
    assert '45%' in r[1]['text'] and 'ENG · mux' in r[1]['text'] and 'elaborazione' in r[1]['text']
    assert '…' in r[1]['text'] and r[1]['text'].startswith('Serie Due') and r[1]['text'].split('\n')[0].endswith('.mkv')   # ElideMiddle
    assert page.locator('[data-filter=all]').inner_text() == 'Tutti (3)'
    assert page.locator('[data-filter=processing]').inner_text() == 'Attivi (1)'
    page.click('[data-filter=queued]')
    assert [x['path'] for x in rows(page)] == [paths[2]]
    page.click('[data-filter=completed]')
    assert [x['path'] for x in rows(page)] == [paths[0]]
    page.click('[data-filter=all]')
    assert len(rows(page)) == 3
    assert page.locator('[data-filter=all]').evaluate('e => e.classList.contains("checked")')
    assert page.locator('.file-row.status-processing .row-bar-fill').evaluate('e => e.style.width') == '45%'


def test_selezione_con_clic_ctrl_e_maiusc_e_rimozione_con_canc_solo_dei_file_in_attesa(env):
    env.wq.add(['/a.mkv', '/b.mkv', '/c.mkv', '/d.mkv'])
    env.wq.queue.take_next()
    env.wq.on_file_started('/a.mkv')
    page = env.open()
    removed = []
    page.on('request', lambda r: removed.append(json.loads(r.post_data)['path']) if r.url.endswith('/api/queue/remove') else None)
    wait_rows(page, 4)
    sel = lambda: page.locator('.file-row.selected').evaluate_all('els => els.map(e => e.dataset.path)')      # noqa: E731
    page.click('.file-row[data-path="/b.mkv"]')
    assert sel() == ['/b.mkv']
    page.click('.file-row[data-path="/d.mkv"]', modifiers=['Shift'])
    assert sel() == ['/b.mkv', '/c.mkv', '/d.mkv']
    page.click('.file-row[data-path="/c.mkv"]', modifiers=['Control'])
    assert sel() == ['/b.mkv', '/d.mkv']
    page.click('.file-row[data-path="/a.mkv"]', modifiers=['Control'])           # il file in lavorazione e' selezionabile ma non rimovibile
    assert sel() == ['/a.mkv', '/b.mkv', '/d.mkv']      # nell'ordine della lista
    page.keyboard.press('Delete')
    wait_rows(page, 2)
    assert [x['path'] for x in rows(page)] == ['/a.mkv', '/c.mkv']
    assert env.wq.queue.snapshot() == ['/c.mkv']
    assert sorted(removed) == ['/b.mkv', '/d.mkv']                       # per il file in lavorazione non parte nemmeno la richiesta


def test_avanzamento_e_tessere_si_aggiornano_dal_vivo(env):
    paths = e2e.seed_rows(env.wq)
    env.wq._thread = type('T', (), {'is_alive': lambda self: True})()      # la coda risulta al lavoro (senza lanciare nulla)
    env.wq.proc_start_time = time.time() - 5
    page = env.open()
    wait_rows(page, 3)
    assert '45%' in rows(page)[1]['text']
    env.wq.on_file_progress(paths[1], 70)                                 # evento dal server, senza ricaricare
    page.wait_for_function('() => document.querySelector(".status-processing .row-bar-fill").style.width === "70%"')
    assert '70%' in rows(page)[1]['text']
    env.wq.completed_count = 5                                            # nessun evento: solo l'interrogazione periodica lo porta alla pagina
    page.wait_for_function('() => document.querySelector("[data-testid=stat-completed] .stat-value").innerText === "5"', timeout=5000)
    assert re.fullmatch(r'\d+', page.locator('[data-testid=stat-queued] .stat-value').inner_text())
    env.wq._thread = None


def test_stesso_file_finito_e_riaccodato_compare_due_volte(env):
    env.wq.add(['/r.mkv'])
    env.wq.queue.take_next()
    env.wq.on_file_started('/r.mkv')
    env.wq.on_file_completed('/r.mkv')
    env.wq.add(['/r.mkv'])
    page = env.open()
    wait_rows(page, 2)
    assert [x['status'] for x in rows(page)] == ['completed', 'queued']
    env.wq.queue.take_next()
    env.wq.on_file_started('/r.mkv')
    page.wait_for_function('() => document.querySelectorAll(".file-row")[1].dataset.status === "processing"')
    env.wq.on_file_progress('/r.mkv', 33)                                  # l'avanzamento va alla riga attiva, non a quella finita
    page.wait_for_function('() => document.querySelectorAll(".file-row")[1].innerText.includes("33%")')
    assert '33%' not in rows(page)[0]['text'] and not [p for p in env.problems if p[0] != 'console' or 'key' in str(p).lower()]


def test_aggiungi_file_con_il_navigatore(env):
    d = env.tmp / 'media'
    (d / 'sub').mkdir(parents=True)
    vids = kit.make_videos(d, 'uno.mkv', 'due.mp4')
    (d / 'nota.txt').write_text('x')
    env.config.set('last_input_folder', str(d), save=False)
    page = env.open()
    page.click('[data-testid=add-files]')
    page.wait_for_selector('[data-testid=file-browser]')
    assert page.locator('[data-testid=fs-path]').inner_text() == str(d)
    names = page.locator('.fs-row .fs-name').all_inner_texts()
    assert names == ['sub', 'due.mp4', 'uno.mkv']                      # cartelle prima, nessun .txt (filtro video), ordine alfabetico
    assert page.locator('[data-testid=fs-ok]').is_disabled()
    page.click('.fs-file[data-path$="uno.mkv"]')
    page.click('.fs-file[data-path$="due.mp4"]', modifiers=['Control'])
    assert 'Aggiungi (2)' in page.locator('[data-testid=fs-ok]').inner_text()
    page.click('[data-testid=fs-ok]')
    wait_rows(page, 2)
    assert sorted(x['path'] for x in rows(page)) == sorted(vids)
    assert env.wq.queue.snapshot() == [str(Path(v)) for v in vids] or sorted(env.wq.queue.snapshot()) == sorted(vids)
    assert page.locator('[data-testid=file-browser]').count() == 0
    # la cartella resta quella dell'ultima aggiunta
    assert env.config.get('last_input_folder') == str(d)


def test_navigatore_cartelle_su_e_giu_annulla_e_errore(env):
    d = env.tmp / 'media'
    (d / 'sub').mkdir(parents=True)
    env.config.set('last_input_folder', str(d), save=False)
    page = env.open()
    page.click('[data-testid=add-files]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click('.fs-dir')
    page.wait_for_function('p => document.querySelector("[data-testid=fs-path]").innerText === p', arg=str(d / 'sub'))
    assert page.locator('.fs-empty').inner_text() == 'Cartella vuota'
    page.click('.fs-up')
    page.wait_for_function('p => document.querySelector("[data-testid=fs-path]").innerText === p', arg=str(d))
    page.keyboard.press('Escape')
    assert page.locator('[data-testid=file-browser]').count() == 0 and rows(page) == []
    page.click('[data-testid=add-files]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click('[data-testid=fs-cancel]')
    assert page.locator('[data-testid=file-browser]').count() == 0


def test_aggiungi_cartella_scansiona_e_aggiunge(env):
    d = env.tmp / 'lib'
    (d / 's').mkdir(parents=True)
    kit.make_videos(d, 'a.mkv')
    kit.make_videos(d / 's', 'b.mp4')
    (d / 's' / 'x.txt').write_text('x')
    env.config.set('last_input_folder', str(env.tmp), save=False)
    page = env.open()
    page.click('[data-testid=add-folder]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click('.fs-dir:has-text("lib")')
    page.wait_for_function('p => document.querySelector("[data-testid=fs-path]").innerText === p', arg=str(d))
    assert page.locator('.fs-file').count() == 0                         # in modalita' cartella i file non si scelgono
    page.click('[data-testid=fs-ok]')
    wait_rows(page, 2)
    assert sorted(Path(x['path']).name for x in rows(page)) == ['a.mkv', 'b.mp4']
    assert env.config.get('last_input_folder') == str(d)


def test_avvia_elabora_con_il_finto_pipeline_e_mostra_tessere_e_avanzamento(env):
    vids = kit.make_videos(env.tmp, 'a.mkv', 'b.mkv')
    env.wq.add(vids)
    page = env.open()
    wait_rows(page, 2)
    assert page.locator('[data-testid=stop]').is_disabled() and page.locator('[data-testid=start]').is_enabled()
    page.click('[data-testid=start]')
    page.wait_for_function('() => [...document.querySelectorAll(".file-row")].every(r => r.dataset.status === "completed")', timeout=60000)
    assert page.locator('[data-testid=start]').is_enabled() and page.locator('[data-testid=stop]').is_disabled()
    assert page.locator('[data-testid=clear]').is_enabled()
    page.wait_for_function('() => document.querySelector("[data-testid=stat-completed] .stat-value").innerText === "2"', timeout=10000)
    assert page.locator('[data-testid=progress-fill], .progress-fill').first.evaluate('e => e.style.width') == '100%'
    assert page.locator('[data-testid=left-panel] .progress-pct').inner_text() == '100%'
    assert page.locator('[data-filter=completed]').inner_text() == 'Completati (2)'


def test_avvia_con_coda_vuota_non_fa_nulla(env):
    page = env.open()
    assert page.locator('[data-testid=start]').is_disabled()


def test_stop_chiede_conferma_no_non_ferma_si_ferma(env):
    vids = kit.make_videos(env.tmp, 'slow.mkv', 'b.mkv')
    env.wq.add(vids)
    page = env.open()
    wait_rows(page, 2)
    page.click('[data-testid=start]')
    page.wait_for_selector('.file-row[data-status=processing]', timeout=30000)
    assert page.locator('[data-testid=start]').is_disabled() and page.locator('[data-testid=clear]').is_disabled()
    page.click('[data-testid=stop]')
    assert page.locator('.modal-confirm .modal-title').inner_text() == 'Conferma interruzione'
    assert page.locator('.modal-confirm .modal-text').inner_text().startswith('Interrompere l')
    page.click('[data-testid=confirm-no]')
    assert page.locator('.modal-confirm').count() == 0 and env.wq.is_processing
    page.click('[data-testid=stop]')
    page.keyboard.press('Escape')                                         # Esc = No
    assert page.locator('.modal-confirm').count() == 0 and env.wq.is_processing
    page.click('[data-testid=stop]')
    page.click('[data-testid=confirm-yes]')
    page.wait_for_function('() => document.querySelector("[data-testid=start]").disabled === false', timeout=30000)
    assert [x['status'] for x in rows(page)] == ['failed', 'queued']
    assert env.wq.queue.snapshot() == [vids[1]]


def test_svuota_e_riga_aggiunta_dal_server_compare_senza_ricaricare(env):
    page = env.open()
    env.wq.add(['/x.mkv', '/y.mkv'])                                     # evento dal server: la pagina non ricarica
    wait_rows(page, 2)
    assert page.locator('[data-testid=tabbar] .tab.selected').inner_text().strip().endswith('(2)')
    page.click('[data-testid=clear]')
    wait_rows(page, 0)
    assert env.wq.rows() == []


def test_casella_spegni_salva_nel_config(env):
    page = env.open()
    assert page.locator('[data-testid=shutdown]').is_checked() is False
    page.click('[data-testid=shutdown] + .box')
    page.wait_for_function('() => document.querySelector("[data-testid=shutdown]").checked === true')
    time.sleep(0.3)
    assert json.loads(env.config.CONFIG_FILE.read_text(encoding='utf-8'))['shutdown_after_processing'] is True
    page.reload()
    page.wait_for_selector('[data-testid=left-panel]')
    page.wait_for_function('() => document.querySelector("[data-testid=shutdown]").checked === true')
    assert page.locator('.defaults-summary').inner_text().startswith('Predefiniti:')


def test_cronologia_tabella_ricerca_e_azioni(env):
    from core.services.history_service import HistoryService
    h = env.srv.queue.history
    h.entries = [{'name': 'Film Uno', 'date_iso': '2026-10-27T21:05:09', 'src_lang': 'eng', 'dst_lang': 'ita', 'duration_seconds': 3725,
                  'size_bytes': 1536, 'srt_path': '/v/uno.srt', 'video_path': '/v/uno.mkv'},
                 {'name': 'Serie Due', 'date_iso': '2026-10-28T08:00:00', 'src_lang': 'auto', 'dst_lang': '', 'duration_seconds': 65, 'size_bytes': 5 * 1024 ** 3}]
    h.save()
    opened = []
    env.srv.app.state.opener = opened.append
    page = env.open()
    page.wait_for_function('() => document.querySelector("[data-tab=history]").innerText.includes("(2)")')
    page.click('[data-tab=history]')
    page.wait_for_selector('[data-testid=history] tbody tr')
    assert page.locator('[data-testid=history] tbody tr').count() == 2
    first = page.locator('[data-testid=history] tbody tr').first.inner_text()
    assert 'Film Uno' in first and '2026-10-27 21:05' in first and 'eng→ita' in first and '1h 02m 05s' in first and '2 KB' in first
    page.fill('[data-testid=hist-search]', 'serie')
    page.wait_for_function('() => document.querySelectorAll("[data-testid=history] tbody tr").length === 1')
    page.fill('[data-testid=hist-search]', '')
    page.wait_for_function('() => document.querySelectorAll("[data-testid=history] tbody tr").length === 2')
    page.locator('[data-testid=history] tbody tr').first.locator('button').first.click()
    page.wait_for_function('() => true')
    deadline = time.time() + 5
    while not opened and time.time() < deadline:
        time.sleep(0.05)
    assert opened == [str(Path('/v/uno.srt'))]
    assert page.locator('[data-testid=history] tbody tr').nth(1).locator('button').first.is_disabled()
    page.click('[data-tab=queue]')
    page.wait_for_selector('[data-testid=left-panel]')


def test_uscita_senza_coda_e_con_coda_al_lavoro(env):
    import threading
    ev = threading.Event()
    from tpweb.routes_lifecycle import add_lifecycle_routes
    # il server di prova non ha il percorso /api/quit (lo aggiunge il launcher): si prova con quello del launcher
    from tpweb.launcher import build
    env.srv.stop()
    from utils import config as cfg
    s2 = build(cfg.get_config(), history_path=env.tmp / 'h2.json', project_root=ROOT, shutdown_fn=lambda: None, quit_event=ev).start()
    env.srv = s2
    env.wq = s2.queue
    vids = kit.make_videos(env.tmp, 'slow.mkv')
    env.wq.add(vids)
    page = env.open()
    page.click('[data-testid=start]')
    page.wait_for_selector('.file-row[data-status=processing]', timeout=30000)
    page.click('[data-testid=quit]')
    assert 'La coda è al lavoro' in page.locator('.modal-confirm .modal-text').inner_text() and not ev.is_set()
    page.click('[data-testid=confirm-no]')
    page.click('[data-testid=quit]')
    page.click('[data-testid=confirm-yes]')
    deadline = time.time() + 10
    while not ev.is_set() and time.time() < deadline:
        time.sleep(0.05)
    assert ev.is_set()


def test_monitor_risorse_mostra_i_valori_del_server(env):
    page = env.open()
    page.wait_for_function('() => document.querySelector("[data-testid=m-cpu] .metric-value").innerText.endsWith("%")', timeout=10000)
    assert re.fullmatch(r'\d+\.\d%', page.locator('[data-testid=m-cpu] .metric-value').inner_text())
    assert re.fullmatch(r'\d+\.\d%', page.locator('[data-testid=m-ram] .metric-value').inner_text())
    assert page.locator('[data-testid=m-down] .net-value').inner_text().endswith('/s')
    assert page.locator('[data-testid=m-gpu]').count() == 0                # nessuna GPU NVML nel cloud: le barre GPU non ci sono


def test_ripresa_dopo_la_caduta_del_flusso(env):
    """Il server perde gli eventi (buffer corto): la pagina, ricollegandosi, riceve lo stato completo e si riallinea."""
    page = env.open()
    env.wq.add(['/p.mkv'])
    wait_rows(page, 1)
    page.evaluate("() => { window.__es_closed = true; }")
    for i in range(6000):                                                # piu' degli eventi tenuti dal bus: la ripresa avra' un buco
        env.wq.bus.publish('noise', i)
    env.wq.add(['/q.mkv'])
    wait_rows(page, 2, timeout=15000)
    assert [Path(x['path']).name for x in rows(page)] == ['p.mkv', 'q.mkv']


# ------------------------------------------------------------------------- confronto di geometria con la finestra Qt vera (Linux)
QT_REF = ROOT / 'tpweb' / 'proto' / 'results' / 'p2_qt_linux' / '1.0'


def qt_widgets(state):
    g = json.loads((QT_REF / f'{state}.json').read_text(encoding='utf-8'))
    out = {}
    for k, v in g['widgets'].items():
        out.setdefault(k.split('#')[0], []).append(v)
    return out, g


def dom_box(page, selector, index=0):
    b = page.locator(selector).nth(index).bounding_box()
    return [round(b['x']), round(b['y']), round(b['width']), round(b['height'])]


def close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_geometria_come_la_finestra_qt_vera_stato_righe(env):
    """Regressione di LAYOUT (non di pixel): le scatole della pagina a 1400x900 coincidono con quelle di Qt entro 2 px. Il riferimento e'
    la cattura Qt su Linux (p2_qt_capture.py); il confronto vero, a 100/125/150% su Windows, e' della sessione locale (C-010)."""
    e2e.seed_rows(env.wq)
    page = env.open(1400, 900)
    wait_rows(page, 3)
    time.sleep(0.5)
    qt, g = qt_widgets('righe')
    checks = [
        ('titlebar', '[data-testid=titlebar]', qt['miniTitleBar'][0], 0),
        ('tabbar', '[data-testid=tabbar]', qt['mainTabBar'][0], 0),
        ('pannello sinistro', '[data-testid=left-panel]', qt['leftPanel'][0], 1),
        ('pannello centrale', '[data-testid=center-panel]', qt['centerPanel'][0], 1),
        ('pannello destro', '[data-testid=right-panel]', qt['rightPanel'][0], 1),
        ('lista', '[data-testid=file-list]', qt['fileList'][0], 1),
        ('Avvia', '[data-testid=start]', qt['startButton'][0], 1),
        ('Ferma', '[data-testid=stop]', qt['stopButton'][0], 1),
        ('barra', '[data-testid=progress]', qt['modernProgress'][0], 1),
    ]
    bad = []
    for name, sel, ref, tol in checks:
        got = dom_box(page, sel)
        if not close(got, ref, 2 + tol):
            bad.append((name, got, ref))
    for i, ref in enumerate(sorted(qt['primaryButton'])):
        sel = ['[data-testid=add-files]', '[data-testid=add-folder]', '[data-testid=clear]'][i]
        got = dom_box(page, sel)
        if not close(got, ref, 3):
            bad.append((sel, got, ref))
    for i, ref in enumerate(sorted(qt['segmentFilterBtn'])):
        got = dom_box(page, '.seg-btn', i)
        if not close(got, ref, 12):                                     # larghezze dipendono dal testo (Qt e Chromium misurano i glifi in modo diverso): tolleranza larga
            bad.append(('filtro %d' % i, got, ref))
    for i, row in enumerate(g['rows']):
        got = dom_box(page, '.file-row', i)
        if not close(got, row['rect'], 2):
            bad.append(('riga %d' % i, got, row['rect']))
    assert bad == []


def test_geometria_a_pagina_vuota(env):
    page = env.open(1400, 900)
    time.sleep(0.4)
    qt, _ = qt_widgets('vuota')
    assert close(dom_box(page, '[data-testid=file-list]'), qt['fileList'][0], 2)
    assert close(dom_box(page, '[data-testid=start]'), qt['startButton'][0], 2)


# ------------------------------------------------------------------------------------------ 2c: menu contestuale e riordino
def menu_labels(page):
    page.wait_for_selector('[data-testid=context-menu]')
    return page.locator('[data-testid=context-menu] > .ctx-item').evaluate_all('els => els.map(e => e.dataset.label + (e.classList.contains("disabled") ? " [x]" : ""))')


def test_menu_contestuale_voci_e_applicazione_delle_eccezioni(env):
    env.wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    page = env.open()
    wait_rows(page, 3)
    page.click('.file-row[data-path="/a.mkv"]', button='right')
    page.wait_for_selector('[data-testid=context-menu]')
    assert menu_labels(page) == ['Lingua sottotitoli', 'Motore di traduzione', 'Forza trascrizione da audio', 'Correzione del genere',
                                 'Muxa nel video', 'Upload su OpenSubtitles', 'Ripristina i predefiniti [x]', 'Rimuovi dalla coda']
    assert page.locator('.file-row.selected').count() == 1                 # il clic destro seleziona la riga come in Qt
    page.hover('.ctx-item[data-label="Lingua sottotitoli"]')
    langs = page.locator('.ctx-sub .ctx-label').all_inner_texts()
    assert langs[:3] == ['Predefinito', 'Italiano', 'Inglese'] and len(langs) == 15
    assert page.locator('.ctx-sub .ctx-item[data-label="Predefinito"] .ctx-check').inner_text() == '✓'
    page.click('.ctx-sub .ctx-item[data-label="Inglese"]')
    page.wait_for_function('() => document.querySelector(".file-row .meta-ov")')
    assert env.wq.overrides_of('/a.mkv') == {'target_language': 'eng'}
    assert page.locator('.file-row[data-path="/a.mkv"] .meta-ov').inner_text() == 'ENG'
    # seconda eccezione, poi la voce spuntata e il ripristino
    page.click('.file-row[data-path="/a.mkv"]', button='right')
    page.hover('.ctx-item[data-label="Muxa nel video"]')
    page.click('.ctx-sub .ctx-item[data-label="Sì"]')
    page.wait_for_function('() => document.querySelector(".file-row .meta-ov").innerText.includes("mux")')
    assert page.locator('.file-row[data-path="/a.mkv"] .meta-ov').inner_text() == 'ENG · mux'
    page.click('.file-row[data-path="/a.mkv"]', button='right')
    page.hover('.ctx-item[data-label="Lingua sottotitoli"]')
    assert page.locator('.ctx-sub .ctx-item[data-label="Inglese"] .ctx-check').inner_text() == '✓'
    page.keyboard.press('Escape')
    assert page.locator('[data-testid=context-menu]').count() == 0
    page.click('.file-row[data-path="/a.mkv"]', button='right')
    page.click('.ctx-item[data-label="Ripristina i predefiniti"]')
    page.wait_for_function('() => !document.querySelector(".file-row .meta-ov")')
    assert env.wq.overrides_of('/a.mkv') == {}


def test_menu_su_piu_righe_voce_comune_e_mista(env):
    env.wq.add(['/a.mkv', '/b.mkv'])
    env.wq.set_overrides(['/a.mkv'], 'mux_subtitle_into_video', True)
    page = env.open()
    wait_rows(page, 2)
    page.click('.file-row[data-path="/a.mkv"]')
    page.click('.file-row[data-path="/b.mkv"]', modifiers=['Control'])
    page.click('.file-row[data-path="/b.mkv"]', button='right')
    assert page.locator('.file-row.selected').count() == 2                 # il clic destro su una riga gia' selezionata mantiene la selezione
    page.hover('.ctx-item[data-label="Muxa nel video"]')
    assert page.locator('.ctx-sub .ctx-check').all_inner_texts() == ['', '', '']       # valori diversi: nessuna voce spuntata
    page.click('.ctx-sub .ctx-item[data-label="No"]')
    page.wait_for_function('() => document.querySelectorAll(".file-row .meta-ov").length === 2')
    assert env.wq.overrides_of('/a.mkv') == env.wq.overrides_of('/b.mkv') == {'mux_subtitle_into_video': False}


def test_menu_file_in_lavorazione_senza_eccezioni_e_area_vuota_con_rimuovi_disattivato(env):
    paths = e2e.seed_rows(env.wq)
    page = env.open()
    wait_rows(page, 3)
    page.click('.file-row[data-path="%s"]' % paths[1], button='right')              # in lavorazione: niente eccezioni, niente rimozione
    assert menu_labels(page) == ['Rimuovi dalla coda [x]']
    page.keyboard.press('Escape')
    page.click('[data-testid=file-list]', button='right', position={'x': 100, 'y': 400})
    assert menu_labels(page) == ['Rimuovi dalla coda [x]']
    page.keyboard.press('Escape')
    page.click('.file-row[data-path="%s"]' % paths[2], button='right')
    page.click('.ctx-item[data-label="Rimuovi dalla coda"]')
    wait_rows(page, 2)
    assert env.wq.queue.snapshot() == []


def test_eccezione_su_file_gia_preso_dal_motore_avvisa_nel_log(env):
    env.wq.add(['/a.mkv'])
    page = env.open()
    wait_rows(page, 1)
    page.click('.file-row[data-path="/a.mkv"]', button='right')
    page.wait_for_selector('[data-testid=context-menu]')
    env.wq.queue.take_next()                                                # il motore prende il file mentre il menu e' aperto
    env.wq.on_file_started('/a.mkv')
    page.hover('.ctx-item[data-label="Correzione del genere"]')
    page.click('.ctx-sub .ctx-item[data-label="Sì"]')
    deadline = time.time() + 5
    while time.time() < deadline and not [e for e in env.wq.bus.since(0)[0] if e['k'] == 'log']:
        time.sleep(0.05)
    logs = [e['d'] for e in env.wq.bus.since(0)[0] if e['k'] == 'log']
    assert logs == ['⚠️ 1 file non modificati: già in elaborazione, finiti o non più in coda.']


def drag(page, src, dst, after=False):
    s = page.locator(f'.file-row[data-path="{src}"]')
    d = page.locator(f'.file-row[data-path="{dst}"]')
    box = d.bounding_box()
    s.drag_to(d, target_position={'x': 40, 'y': box['height'] * (0.8 if after else 0.2)})


def test_riordino_con_il_trascinamento(env):
    env.wq.add(['/a.mkv', '/b.mkv', '/c.mkv', '/d.mkv'])
    page = env.open()
    wait_rows(page, 4)
    drag(page, '/d.mkv', '/b.mkv')                                          # sopra b
    page.wait_for_function('() => document.querySelectorAll(".file-row")[1].dataset.path === "/d.mkv"')
    assert env.wq.queue.snapshot() == ['/a.mkv', '/d.mkv', '/b.mkv', '/c.mkv']
    drag(page, '/a.mkv', '/c.mkv', after=True)                              # sotto c
    page.wait_for_function('() => document.querySelectorAll(".file-row")[3].dataset.path === "/a.mkv"')
    assert env.wq.queue.snapshot() == ['/d.mkv', '/b.mkv', '/c.mkv', '/a.mkv']
    assert [Path(x['path']).name for x in rows(page)] == ['d.mkv', 'b.mkv', 'c.mkv', 'a.mkv']
    drag(page, '/b.mkv', '/c.mkv')                                          # rilascio che non cambia l'ordine: nessuna richiesta
    time.sleep(0.4)
    assert env.wq.queue.snapshot() == ['/d.mkv', '/b.mkv', '/c.mkv', '/a.mkv']


def test_riordino_non_vale_per_righe_non_in_attesa_ne_con_selezione_multipla(env):
    env.wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    env.wq.queue.take_next()
    env.wq.on_file_started('/a.mkv')
    page = env.open()
    wait_rows(page, 3)
    assert page.locator('.file-row[data-path="/a.mkv"]').get_attribute('draggable') == 'false'
    assert page.locator('.file-row[data-path="/b.mkv"]').get_attribute('draggable') == 'true'
    drag(page, '/a.mkv', '/c.mkv', after=True)
    time.sleep(0.4)
    assert env.wq.queue.snapshot() == ['/b.mkv', '/c.mkv']
    page.click('.file-row[data-path="/b.mkv"]')
    page.click('.file-row[data-path="/c.mkv"]', modifiers=['Control'])      # due selezionate: il trascinamento di una riga non parte
    drag(page, '/b.mkv', '/c.mkv', after=True)
    time.sleep(0.4)
    assert env.wq.queue.snapshot() == ['/b.mkv', '/c.mkv']


def test_riordino_annullato_se_la_riga_e_gia_stata_presa(env):
    env.wq.add(['/a.mkv', '/b.mkv', '/c.mkv'])
    page = env.open()
    wait_rows(page, 3)
    from tpweb import queue_backend
    env.wq.queue.take_next()                                                # il motore prende a mentre l'utente trascina a
    env.wq.on_file_started('/a.mkv')
    r = env.srv.app  # noqa: F841
    import httpx
    res = httpx.post(f'http://127.0.0.1:{env.srv.port}/api/queue/reorder', json={'order': ['/b.mkv', '/a.mkv', '/c.mkv'], 'moved': '/a.mkv'},
                     headers={'X-TP-Token': env.srv.token})
    assert res.json() == {'ok': False} and env.wq.queue.snapshot() == ['/b.mkv', '/c.mkv']
