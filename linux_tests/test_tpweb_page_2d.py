# -*- coding: utf-8 -*-
"""Pagina Coda, fase 2d: log, card «Pipeline in corso», diagnostica, anteprima (locandina e titolo), badge GPU, stato in barra."""
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
from test_tpweb_page import browser, env, rows, wait_rows  # noqa: E402,F401

pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')

BAR = lambda name, pct: f'{name}: [{"#" * (pct // 10)}{"-" * (10 - pct // 10)}] {pct}%'      # noqa: E731


def log_lines(page):
    return page.locator('[data-testid=log] .log-line').evaluate_all('els => els.map(e => [e.innerText, e.className.replace("log-line kind-", "")])')


def wait_log(page, n):
    page.wait_for_function('n => document.querySelectorAll("[data-testid=log] .log-line").length === n', arg=n, timeout=10000)


def snapshot(path='C:/Video/Serie Due S01E02.mkv', pct=40, est=False):
    from core.jobs.step_plan import StepTracker, PlanOptions
    tr = StepTracker(path, PlanOptions(), clock=lambda: 1000.0)
    tr.feed_event('phase', {'name': 'extract'})
    tr.feed_event('phase', {'name': 'asr', 'engine': 'qwen3'})
    tr.feed_event('bar', {'phase': 'asr', 'pct': pct})
    return tr.snapshot()


# ------------------------------------------------------------------------------------------------------------------------- log
def test_log_iniziale_come_la_gui_e_colori(env):
    page = env.open()
    wait_log(page, 3)
    l = log_lines(page)
    assert [x[1] for x in l] == ['info', 'success', 'info']                  # la riga TMDB contiene ✅ (stessa regola della GUI)
    assert re.match(r'\[\d\d:\d\d:\d\d\] 🎬 Transcriber Pro avviato', l[0][0]) and 'TMDB Client: ✅ Attivo' in l[1][0] and 'Motore di trascrizione: Auto' in l[2][0]
    env.wq.log_message('✅ ok'); env.wq.log_message('❌ male'); env.wq.log_message('🎉 tutto'); env.wq.log_message('⚙️ passo')
    wait_log(page, 7)
    assert [x[1] for x in log_lines(page)][3:] == ['success', 'danger', 'success', 'info']


def test_barre_riscritte_sul_posto_e_spostate_in_fondo(env):
    page = env.open()
    wait_log(page, 3)
    env.wq.set_compact(False)
    env.wq.log_message(BAR('Trascrizione', 10))
    env.wq.log_message(BAR('Trascrizione', 40))                              # stessa riga
    wait_log(page, 4)
    assert '40%' in log_lines(page)[3][0]
    env.wq.log_message('⚠️ avviso')
    env.wq.log_message(BAR('Trascrizione', 60))                              # tolta e riscritta in fondo
    wait_log(page, 5)
    t = [x[0] for x in log_lines(page)]
    assert 'avviso' in t[3] and '60%' in t[4] and not any('40%' in x for x in t)


def test_log_sintetico_filtra_e_si_ricorda_sul_server(env):
    page = env.open()
    wait_log(page, 3)
    assert page.locator('[data-testid=compact]').is_checked()                # acceso all'apertura (come la GUI)
    env.wq.log_message('riga senza marcatori')                               # in modalita' compatta non passa
    time.sleep(0.4)
    assert len(log_lines(page)) == 3
    page.click('[data-testid=compact] + .box')
    page.wait_for_function('() => !document.querySelector("[data-testid=compact]").checked')
    assert env.wq.compact is False
    env.wq.log_message('riga senza marcatori 2')
    wait_log(page, 4)
    page2 = env.open()                                                       # un'altra scheda vede lo stesso stato e lo stesso log
    wait_log(page2, 4)
    assert not page2.locator('[data-testid=compact]').is_checked()


def test_log_ripreso_dopo_la_perdita_di_eventi(env):
    page = env.open()
    wait_log(page, 3)
    env.wq.set_compact(False)
    for i in range(6000):                                                   # piu' degli eventi tenuti dal bus: serve lo stato completo
        env.wq.bus.publish('noise', i)
    env.wq.log_message('dopo il buco')
    page.wait_for_function('() => [...document.querySelectorAll("[data-testid=log] .log-line")].some(l => l.innerText.includes("dopo il buco"))', timeout=15000)
    assert [x[0].split('] ', 1)[1] for x in log_lines(page)][-1] == 'dopo il buco'


def test_log_massimo_5000_righe_nella_pagina(env):
    env.wq.set_compact(False)
    for i in range(5100):
        env.wq.log_message(f'riga {i}')
    page = env.open()
    page.wait_for_function('() => document.querySelectorAll("[data-testid=log] .log-line").length === 5000', timeout=15000)
    assert page.locator('[data-testid=log] .log-line').last.inner_text().endswith('riga 5099')


def test_il_log_scorre_in_fondo(env):
    env.wq.set_compact(False)
    for i in range(80):
        env.wq.log_message(f'riga {i}')
    page = env.open()
    page.wait_for_function('() => document.querySelectorAll("[data-testid=log] .log-line").length >= 80')
    assert page.locator('[data-testid=log]').evaluate('e => e.scrollTop + e.clientHeight >= e.scrollHeight - 2')
    env.wq.log_message('ultima')
    page.wait_for_function('() => document.querySelector("[data-testid=log] .log-line:last-child").innerText.includes("ultima")')
    assert page.locator('[data-testid=log]').evaluate('e => e.scrollTop + e.clientHeight >= e.scrollHeight - 2')


# ---------------------------------------------------------------------------------------------------------- card Pipeline in corso
def test_card_pipeline_passi_percentuali_e_testi(env):
    page = env.open()
    assert page.locator('[data-testid=pipeline-card]').count() == 0          # nessun file in lavorazione: nascosta
    env.wq.on_file_steps('C:/Video/Serie Due S01E02.mkv', snapshot())
    page.wait_for_selector('[data-testid=pipeline-card]')
    assert page.locator('.pipeline-title').inner_text().lower() == 'pipeline in corso'
    assert page.locator('.pipeline-pill').inner_text() == '1/5' and page.locator('.pipeline-file').inner_text() == 'Serie Due S01E02.mkv'
    st = lambda: page.locator('.prow').evaluate_all('els => els.map(e => [e.dataset.step, e.dataset.status, e.querySelector(".prow-label").innerText])')    # noqa: E731
    got = st()
    assert got[0] == ['extract', 'done', 'Estrazione audio'] and got[1][1] == 'not_needed' and got[2] == ['asr', 'active', 'Trascrizione']
    assert [g[1] for g in got[3:]] == ['pending', 'pending', 'disabled', 'pending', 'disabled']      # diarize, translate, gender, save, upload
    assert page.locator('.prow-extract, [data-step=extract] .prow-right').inner_text() == 'fatto'
    assert page.locator('[data-step=asr] .prow-pct').inner_text() == '40%'
    assert page.locator('[data-step=asr] .prow-fill').evaluate('e => e.style.width') == '40%'
    assert page.locator('[data-step=demucs] .prow-right').inner_text() == 'non necessario'
    assert page.locator('[data-step=gender] .prow-right').inner_text() == 'disattivato'
    assert page.locator('[data-step=diarize] .pc-pending').inner_text() == '3' and page.locator('[data-step=translate] .pc-pending').inner_text() == '4'
    env.wq.on_file_steps('C:/Video/Serie Due S01E02.mkv', snapshot(pct=75))
    page.wait_for_function('() => document.querySelector("[data-step=asr] .prow-pct").innerText === "75%"')


def test_card_si_chiude_e_si_apre_e_il_server_ricorda(env):
    env.wq.on_file_steps('C:/Video/a.mkv', snapshot('C:/Video/a.mkv'))
    page = env.open()
    page.wait_for_selector('[data-testid=pipeline-card]')
    assert page.locator('.prow').count() == 8 and page.locator('[data-testid=pipeline-card]').get_attribute('data-open') == 'true'
    page.click('[data-testid=pipeline-head]')
    page.wait_for_function('() => document.querySelector("[data-testid=pipeline-card]").dataset.open === "false"')
    assert page.locator('.prow').count() == 0 and env.wq.pipeline_open is False
    assert json.loads(env.config.CONFIG_FILE.read_text(encoding='utf-8'))['ui_pipeline_card_open'] is False
    page.reload()
    page.wait_for_selector('[data-testid=pipeline-card][data-open=false]')
    page.click('[data-testid=pipeline-head]')
    page.wait_for_selector('.prow')


def test_card_visibile_solo_con_log_sintetico(env):
    env.wq.on_file_steps('C:/Video/a.mkv', snapshot('C:/Video/a.mkv'))
    page = env.open()
    page.wait_for_selector('[data-testid=pipeline-card]')
    page.click('[data-testid=compact] + .box')
    page.wait_for_function('() => !document.querySelector("[data-testid=pipeline-card]")')
    page.click('[data-testid=compact] + .box')
    page.wait_for_selector('[data-testid=pipeline-card]')


def test_con_la_card_aperta_le_barre_con_percentuale_escono_dal_log(env):
    env.wq.on_file_steps('C:/Video/a.mkv', snapshot('C:/Video/a.mkv'))
    page = env.open()
    page.wait_for_selector('[data-testid=pipeline-card]')
    wait_log(page, 3)
    env.wq.log_message(BAR('Trascrizione', 50))                              # la card le mostra gia': non si accodano
    env.wq.log_message('⚙️ OCR in corso')                                    # senza % restano
    wait_log(page, 4)
    assert '⚙️ OCR' in log_lines(page)[3][0]
    page.click('[data-testid=pipeline-head]')                                # card chiusa: le barre tornano nel log
    page.wait_for_function('() => !document.querySelector(".prow")')
    env.wq.log_message(BAR('Trascrizione', 60))
    wait_log(page, 5)
    assert '60%' in log_lines(page)[4][0]


def test_barra_stimata_dei_passi_brevi_si_anima(env):
    from core.jobs.step_plan import StepTracker, PlanOptions
    path = 'C:/Video/a.mkv'
    tr = StepTracker(path, PlanOptions(), clock=time.time)
    for n in ('extract', 'asr', 'translate'):
        tr.feed_event('phase', {'name': n})
    tr.feed_event('step', {'name': 'save', 'state': 'start'})
    snap = tr.snapshot()
    env.wq.on_file_steps(path, snap)
    page = env.open()
    page.wait_for_selector('[data-step=save][data-status=active]')
    first = int(page.locator('[data-step=save] .prow-pct').inner_text().rstrip('%'))
    time.sleep(1.2)
    later = int(page.locator('[data-step=save] .prow-pct').inner_text().rstrip('%'))
    assert 0 <= first < later <= 95


def test_passo_senza_misura_ha_la_barra_indeterminata(env):
    from core.jobs.step_plan import StepTracker, PlanOptions
    tr = StepTracker('C:/Video/a.mkv', PlanOptions(), clock=time.time)
    tr.feed_event('phase', {'name': 'extract'})
    env.wq.on_file_steps('C:/Video/a.mkv', tr.snapshot())
    page = env.open()
    page.wait_for_selector('[data-step=extract][data-status=active]')
    assert page.locator('[data-step=extract] .prow-fill.indeterminate').count() == 1 and page.locator('[data-step=extract] .prow-pct').count() == 0


# ------------------------------------------------------------------------------------------------------------------- diagnostica
def test_diagnostica_valori_a_riposo_e_durante_la_coda(env):
    page = env.open()
    wait_log(page, 3)
    t = lambda k: page.locator(f'[data-testid=diag-{k}] .diag-value').inner_text()      # noqa: E731
    assert (t('elapsed'), t('errors'), t('model'), t('engine')) == ('–', '0', 'Auto (per lingua)', 'Auto') and t('translator')
    env.wq.log_message('Modello trascrizione: whisper-large-v3')
    page.wait_for_function('() => document.querySelector("[data-testid=diag-model] .diag-value").innerText === "whisper-large-v3"')
    vids = kit.make_videos(env.tmp, 'slow.mkv')
    env.wq.add(vids)
    page.click('[data-testid=start]')
    page.wait_for_selector('.file-row[data-status=processing]', timeout=20000)
    page.wait_for_function('() => /^\\d\\d:\\d\\d$/.test(document.querySelector("[data-testid=diag-elapsed] .diag-value").innerText)', timeout=5000)
    assert t('model') == 'Auto (per lingua)'                                  # a inizio coda la tessera torna al valore a riposo
    first = t('elapsed')
    page.wait_for_function('f => document.querySelector("[data-testid=diag-elapsed] .diag-value").innerText !== f', arg=first, timeout=5000)
    env.wq.stop()
    env.wq.join(30)
    frozen = env.wq.diag()['elapsed']
    time.sleep(1.3)
    assert env.wq.diag()['elapsed'] == frozen                                 # a fine coda il tempo si ferma
    assert t('errors') == '0'                                                 # un file fermato non e' un errore del worker (come la GUI)


def test_tessera_errori_si_aggiorna_solo_sugli_errori_del_worker(env):
    page = env.open()
    wait_log(page, 3)
    env.wq.add(kit.make_videos(env.tmp, 'fail.mkv'))
    env.wq.start()
    env.wq.join(60)
    assert env.wq.error_count == 1 and env.wq.diag()['errors'] == '0'        # come la GUI: il file fallito non sposta la tessera
    env.wq.errors_shown = env.wq.error_count = 2                              # errore del worker (eccezione nel motore)
    env.wq.bus.publish('diag', env.wq.diag())
    page.wait_for_function('() => document.querySelector("[data-testid=diag-errors] .diag-value").innerText === "2"')


# ---------------------------------------------------------------------------------------------------------------------- anteprima
def png(path, w=200, h=300):
    from PIL import Image
    Image.new('RGB', (w, h), (200, 30, 30)).save(path)
    return Path(path)


def test_anteprima_locandina_titolo_e_pillole(env):
    poster = png(env.tmp / 'poster.png')
    env.srv.queue.preview._client = e2e.FakeTmdb(poster)
    paths = e2e.seed_rows(env.wq)
    page = env.open()
    wait_rows(page, 3)
    assert page.locator('[data-testid=poster] .poster-text').inner_text().strip().endswith('Nessuna anteprima\ndisponibile')
    assert page.locator('[data-testid=filename-pill]').count() == 0
    page.click('.file-row[data-path="%s"]' % paths[0])
    page.wait_for_selector('[data-testid=poster] img.poster-img', timeout=10000)
    assert page.locator('[data-testid=filename-pill]').inner_text() == 'Film Uno.mkv'
    assert page.locator('[data-testid=overlay-title]').inner_text() == 'Film Uno'
    assert page.locator('.pill-lang').inner_text() == '→ ITA' and page.locator('.pill-status').inner_text() == '✅ Completato'
    assert page.locator('[data-testid=overlay-meta]').inner_text() == '1.5 GB · 100%'
    assert page.locator('.overlay-fill').evaluate('e => e.style.width') == '100%'
    natural = page.locator('img.poster-img').evaluate('e => [e.naturalWidth, e.naturalHeight]')
    assert natural == [200, 300]
    page.click('.file-row[data-path="%s"]' % paths[1])                      # serie: «Nome show SxxExx», lingua dall'eccezione
    page.wait_for_function('() => document.querySelector("[data-testid=overlay-title]").innerText.includes("S01E02")')
    assert page.locator('[data-testid=overlay-title]').inner_text() == 'Serie Due S01E02'
    assert page.locator('.pill-lang').inner_text() == '→ ENG'
    assert 'Elaborazione' in page.locator('.pill-status').inner_text() and page.locator('[data-testid=overlay-meta]').inner_text() == '862 MB · 45%'


def test_anteprima_senza_locandina_e_in_caricamento(env):
    env.srv.queue.preview._client = e2e.FakeTmdb(None, delay=0.8)
    env.wq.add(['/a.mkv'])
    page = env.open()
    wait_rows(page, 1)
    page.click('.file-row[data-path="/a.mkv"]')
    page.wait_for_function('() => document.querySelector("[data-testid=poster] .poster-text").dataset.status === "loading"')
    assert 'Caricamento' in page.locator('.poster-text').inner_text()
    page.wait_for_function('() => document.querySelector("[data-testid=poster] .poster-text").dataset.status === "failed"', timeout=10000)
    assert page.locator('.poster-text').inner_text().startswith('❌')


def test_la_ricerca_annullata_non_sovrascrive_la_locandina_corrente(env):
    """Differenza voluta rispetto alla GUI Qt (corsa nota): un risultato tardivo del file PRECEDENTE non conta."""
    poster = png(env.tmp / 'p.png')
    slow = e2e.FakeTmdb(poster, delays={'a.mkv': 1.5, 'b.mkv': 0.1})       # b finisce prima; a, annullata, finisce dopo
    env.srv.queue.preview._client = slow
    env.wq.add(['/a.mkv', '/b.mkv'])
    page = env.open()
    wait_rows(page, 2)
    page.click('.file-row[data-path="/a.mkv"]')
    page.click('.file-row[data-path="/b.mkv"]')                              # prima che a abbia finito
    page.wait_for_selector('img.poster-img', timeout=10000)
    st = env.srv.queue.preview.state()
    assert st['path'] == '/b.mkv' and st['status'] == 'found'
    time.sleep(2.0)
    assert env.srv.queue.preview.state()['path'] == '/b.mkv' and env.srv.queue.preview.state()['status'] == 'found'
    assert page.locator('[data-testid=filename-pill]').inner_text() == 'b.mkv'


def test_stesso_file_non_ricarica_e_un_file_che_parte_si_seleziona_da_solo(env):
    poster = png(env.tmp / 'p.png')
    fake = e2e.FakeTmdb(poster)
    env.srv.queue.preview._client = fake
    vids = kit.make_videos(env.tmp, 'a.mkv', 'slow.mkv')
    env.wq.add(vids)
    page = env.open()
    wait_rows(page, 2)
    page.click('.file-row[data-path="%s"]' % vids[0])
    page.wait_for_selector('img.poster-img')
    page.click('.file-row[data-path="%s"]' % vids[0], modifiers=['Control'])
    page.click('.file-row[data-path="%s"]' % vids[0], modifiers=['Control'])
    time.sleep(0.4)
    assert len(fake.calls) == 1                                               # lo stesso file non ricarica
    page.click('[data-testid=start]')                                         # a parte: si seleziona e si ricarica (reset)
    page.wait_for_function('p => document.querySelector("[data-testid=filename-pill]") && document.querySelector("[data-testid=filename-pill]").innerText === "slow.mkv"', arg=None, timeout=30000)
    assert page.locator('.file-row.selected').evaluate_all('els => els.map(e => e.dataset.path)') == [vids[1]]


def test_aggiungere_file_seleziona_l_ultimo(env):
    d = env.tmp / 'media'
    d.mkdir()
    vids = kit.make_videos(d, 'uno.mkv', 'due.mkv')
    env.config.set('last_input_folder', str(d), save=False)
    page = env.open()
    page.click('[data-testid=add-files]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.click('.fs-file[data-path$="due.mkv"]')
    page.click('.fs-file[data-path$="uno.mkv"]', modifiers=['Control'])
    page.click('[data-testid=fs-ok]')
    wait_rows(page, 2)
    page.wait_for_function('() => document.querySelectorAll(".file-row.selected").length === 1')
    last = page.locator('.file-row').last.get_attribute('data-path')
    assert page.locator('.file-row.selected').get_attribute('data-path') == last
    page.wait_for_function('() => document.querySelector("[data-testid=filename-pill]")')
    sizes = page.locator('.file-row .meta-text').all_inner_texts()
    assert all(re.match(r'^\d+ B · in coda$', x) for x in sizes)             # le dimensioni arrivano dal server dopo l'aggiunta


def test_svuotare_la_coda_azzera_l_anteprima(env):
    env.srv.queue.preview._client = e2e.FakeTmdb(png(env.tmp / 'p.png'))
    env.wq.add(['/a.mkv'])
    page = env.open()
    wait_rows(page, 1)
    page.click('.file-row[data-path="/a.mkv"]')
    page.wait_for_selector('img.poster-img')
    page.click('[data-testid=clear]')
    wait_rows(page, 0)
    page.wait_for_selector('.poster-text')
    assert page.locator('[data-testid=filename-pill]').count() == 0 and page.locator('[data-testid=overlay-title]').inner_text() == ''


# ------------------------------------------------------------------------------------------------------------ barra e badge GPU
def test_badge_gpu_stato_in_barra_e_conteggi_delle_schede(env):
    page = env.open()
    page.wait_for_selector('[data-testid=gpu-badge]')
    b = page.locator('[data-testid=gpu-badge]')
    assert b.inner_text() == 'NVIDIA RTX 4090' and 'nvidia' in b.get_attribute('class') and 'NVIDIA RTX 4090' in b.get_attribute('title')
    bb, pill = b.bounding_box(), page.locator('.status-pill').bounding_box()
    assert abs((bb['x'] + bb['width'] / 2) - (pill['x'] + pill['width'] / 2)) <= 2          # sotto il centro della pill, come in Qt
    assert page.locator('[data-testid=status]').inner_text() == 'Pronto'
    assert page.locator('[data-tab=queue]').inner_text().strip() == 'Coda di processamento'    # 0 attivi: nessun numero
    assert page.locator('[data-tab=history]').inner_text().strip() == 'Cronologia'
    env.wq.add(['/a.mkv', '/b.mkv'])
    page.wait_for_function('() => document.querySelector("[data-tab=queue]").innerText.includes("(2)")')
    assert page.locator('[data-tab=queue]').inner_text().strip() == 'Coda di processamento  (2)'      # due spazi, come QTabBar
    env.wq.add(kit.make_videos(env.tmp, 'slow.mkv'))
    page.click('[data-testid=start]')
    page.wait_for_function('() => document.querySelector("[data-testid=status]").innerText === "In elaborazione"', timeout=20000)
    assert 'busy' in page.locator('.status-dot').get_attribute('class')


def test_badge_gpu_cpu_senza_scheda_e_secondo_giro(tmp_path, monkeypatch, browser):
    calls = []

    def detect(first):
        calls.append(first)
        return ('CPU only', 'cpu', first)                # il primo giro sembra incompleto: ne segue un secondo
    srv, cfg = e2e.make_server(tmp_path, monkeypatch, gpu_detect=detect)
    try:
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(srv.url)
        page.wait_for_selector('[data-testid=gpu-badge]')
        b = page.locator('[data-testid=gpu-badge]')
        assert b.inner_text() == 'CPU only' and 'cpu' in b.get_attribute('class') and '10 volte' in b.get_attribute('title')
        assert calls == [True]
        page.close()
    finally:
        srv.stop()


# ------------------------------------------------------------------------- geometria come la finestra Qt vera (stato «pipeline»)
def test_geometria_pannelli_centrale_e_destro_come_qt_stato_pipeline(env):
    """Regressione di LAYOUT a 1400x900 (entro 2 px; le larghezze che dipendono dal testo, 7 px): riferimento = cattura Qt su Windows a 100% (L-011). Le net card non si confrontano in y: nel riferimento c'e' la riga GPU/VRAM, qui senza GPU no."""
    e2e.seed_rows(env.wq)
    env.wq.on_file_steps('C:/Video/Serie Due S01E02.mkv', snapshot())
    page = env.open(1400, 900)
    page.wait_for_selector('[data-testid=pipeline-card]')
    time.sleep(0.6)
    g = json.loads((ROOT / 'tpweb' / 'proto' / 'results' / 'p2_qt_windows' / '1.0' / 'pipeline.json').read_text(encoding='utf-8'))
    qt = {}
    for k, v in g['widgets'].items():
        qt.setdefault(k.split('#')[0], []).append(v)
    checks = [('logStatTile', '.stat-tile', 4, 2), ('pipelineCard', '[data-testid=pipeline-card]', 1, 2), ('logText', '[data-testid=log]', 1, 2),
              ('sectionTitle', '.section-title', 1, 2), ('diagTile', '.diag-tile', 5, 2), ('previewHeader', '.preview-header', 1, 2),
              ('posterInfoStrip', '.info-strip', 1, 2), ('metricCard', '.metric', 2, 2), ('cpuBar', '.metric-bar', 1, 2),
              ('centerSplitter', '.center-split', 1, 2), ('posterStage', '.poster-stage', 1, 2), ('uptimeLabel', '.rm-uptime', 1, 2)]
    bad = []
    for name, sel, n, tol in checks:
        refs = sorted(qt[name], key=lambda v: (v[1], v[0]))
        for i in range(n):
            got = [round(v) for v in (lambda b: (b['x'], b['y'], b['width'], b['height']))(page.locator(sel).nth(i).bounding_box())]
            if any(abs(a - b) > tol for a, b in zip(got, refs[i])):
                bad.append((name, i, got, refs[i]))
    for name, sel, ref in (('panelTitle', '.right-panel .panel-title', [v for v in qt['panelTitle'] if v[0] > 900][0]),
                           ('modernCheckbox', '.right-panel label.check', qt['modernCheckbox'][0]), ('resourceTitle', '.rm-title', qt['resourceTitle'][0])):
        b = page.locator(sel).first.bounding_box()
        got = [round(b['x']), round(b['y']), round(b['width']), round(b['height'])]
        if any(abs(a - c) > 13 for a, c in zip(got, ref)) or abs(got[1] - ref[1]) > 2:
            bad.append((name, got, ref))
    assert bad == [], "\n".join(map(str, bad))


def test_server_anteprima_stesso_file_forza_e_svuotamento(env):
    pv = env.srv.queue.preview
    pv._client = e2e.FakeTmdb(png(env.tmp / 'p.png'))
    import httpx
    h = {'X-TP-Token': env.srv.token}
    u = f'http://127.0.0.1:{env.srv.port}'
    assert httpx.post(u + '/api/preview/select', json={'path': '/a.mkv'}, headers=h).json()['started'] is True
    assert httpx.post(u + '/api/preview/select', json={'path': '/a.mkv'}, headers=h).json()['started'] is False       # stesso file: nessun lavoro
    assert httpx.post(u + '/api/preview/select', json={'path': '/a.mkv', 'force': True}, headers=h).json()['started'] is True
    deadline = time.time() + 5
    while pv.state()['status'] != 'found' and time.time() < deadline:
        time.sleep(0.05)
    assert httpx.get(u + f'/api/poster/{pv.poster_id}', headers=h).status_code == 200
    assert httpx.get(u + f'/api/poster/{pv.poster_id + 1}', headers=h).status_code == 404                           # solo l'ultima locandina, per numero
    pv.title_for('/a.mkv', 'a.mkv')
    assert pv.titles.cache
    env.wq.add(['/a.mkv'])
    env.wq.clear()
    assert pv.state() == {'path': None, 'status': 'none', 'poster_id': None} and pv.poster_file is None and not pv.titles.cache
    assert httpx.get(u + f'/api/poster/{pv.poster_id}', headers=h).status_code == 404


def test_tessera_errori_riparte_da_zero_a_ogni_coda(env):
    env.wq.errors_shown = 3
    env.wq.add(kit.make_videos(env.tmp, 'a.mkv'))
    env.wq.start()
    env.wq.join(60)
    assert env.wq.diag()['errors'] == '0'


def test_log_della_pagina_non_supera_5000_righe_anche_con_le_operazioni_dal_vivo(env):
    env.wq.set_compact(False)
    for i in range(5000):
        env.wq.log.add(f'riga {i}')                                          # riempie il buffer del server senza eventi
    page = env.open()
    page.wait_for_function('() => document.querySelectorAll("[data-testid=log] .log-line").length === 5000', timeout=15000)
    for i in range(20):
        env.wq.log_message(f'nuova {i}')
    page.wait_for_function('() => document.querySelector("[data-testid=log] .log-line:last-child").innerText.includes("nuova 19")', timeout=10000)
    assert page.locator('[data-testid=log] .log-line').count() == 5000 and page.locator('[data-testid=log] .log-line').first.inner_text().endswith('riga 20')


def test_conteggio_della_scheda_include_il_file_in_lavorazione(env):
    page = env.open()
    env.wq.add(kit.make_videos(env.tmp, 'slow.mkv'))
    page.wait_for_function('() => document.querySelector("[data-tab=queue]").innerText.includes("(1)")')
    page.click('[data-testid=start]')
    page.wait_for_selector('.file-row[data-status=processing]', timeout=20000)
    assert page.locator('[data-tab=queue]').inner_text().strip().endswith('(1)')          # in coda 0, in lavorazione 1: conta come «attivo»
