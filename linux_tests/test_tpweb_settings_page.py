# -*- coding: utf-8 -*-
"""Le Impostazioni nel browser (fase 3): finestra, schede, salvataggi e messaggi, contro il server vero e la configurazione isolata.
Lo stato si controlla sempre dal server (`/api/settings*`), mai dal solo aspetto della pagina."""
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from test_tpweb_page import browser, Env  # noqa: E402,F401
from utils.translations import Translations  # noqa: E402

pw = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(e2e.CHROME is None, reason='Chromium non disponibile')

IT = Translations.TEXTS['it']
EN = Translations.TEXTS['en']


class FakeRunner:
    lines, exit_code, gate = ['riga uno', '⏳ in corso', 'esito finale'], 0, None

    def __init__(self, command, listener):
        self.command, self.listener = command, listener

    def run(self):
        if FakeRunner.gate is not None:
            FakeRunner.gate.wait(10)
        for l in FakeRunner.lines:
            self.listener.on_line(l)
        self.listener.on_finished(FakeRunner.exit_code)


@pytest.fixture
def env(tmp_path, monkeypatch, browser, request):
    import tpweb.routes_models as rm
    ok = request.node.get_closest_marker('senza_traduttore') is None
    monkeypatch.setattr(rm, 'translator_available', lambda: ok)
    monkeypatch.setattr(rm, 'EnvCliRunner', FakeRunner)
    FakeRunner.gate = None
    e = Env()
    e.tmp, e.browser = tmp_path, browser
    e.srv, e.config = e2e.make_server(tmp_path, monkeypatch)
    e.problems, e.pages = [], []

    def open_page(path_after=None):
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('console', lambda m: e.problems.append(('console', m.type, m.text)) if m.type in ('error', 'warning') and '409' not in m.text else None)   # i 409 sono risposte volute (manca il token)
        page.on('pageerror', lambda x: e.problems.append(('pageerror', str(x))))
        page.on('response', lambda r: e.problems.append(('http', r.status, r.url)) if r.status >= 400 and r.status != 409 else None)
        page.goto(e.srv.url)
        page.wait_for_selector('[data-testid=left-panel]')
        e.pages.append(page)
        return page
    e.open = open_page
    yield e
    e.srv.queue.stop()
    e.srv.queue.join(20)
    for p in e.pages:
        p.close()
    e.srv.stop()


def api(page, path):
    return page.evaluate("p => fetch(p).then(r => r.json())", path)


def open_tab(page, tab):
    if not page.locator('[data-testid=settings-dialog]').count():
        page.click('[data-testid=open-settings]')
        page.wait_for_selector('[data-testid=settings-dialog]')
    page.click(f'.side-item[data-tab={tab}]')
    page.wait_for_selector(f'.settings-page[data-page={tab}]:not(.hidden) .page')


def until(page, expr, timeout=5000):
    """Attende che `expr` (funzione JS) torni vero: `wait_for_function` usa eval e la CSP della pagina lo vieta."""
    for _ in range(timeout // 50):
        if page.evaluate(expr):
            return
        page.wait_for_timeout(50)
    raise AssertionError('condizione non raggiunta: ' + expr)


def tick(page, testid, on=True):
    """Casella o radio: la vera <input> e' nascosta, si clicca l'etichetta come farebbe una persona."""
    loc = page.locator(f'[data-testid={testid}]')
    if loc.is_checked() != on:
        (loc.check() if testid.endswith('-radio') else loc.locator('xpath=..').click())
    assert loc.is_checked() == on


def settle(page):
    page.wait_for_timeout(250)


def message(page):
    page.wait_for_selector('[data-testid=message-box]')
    title = page.locator('[data-testid=message-box] .modal-title').inner_text()
    text = page.locator('[data-testid=message-text]').inner_text()
    page.click('[data-testid=message-ok]')
    page.wait_for_selector('[data-testid=message-box]', state='detached')
    return title, text


# ------------------------------------------------------------------------------------------------------------------ la finestra
def test_finestra_barra_laterale_e_ultima_scheda(env):
    page = env.open()
    page.click('[data-testid=open-settings]')
    d = page.locator('[data-testid=settings-dialog]')
    d.wait_for()
    box = d.bounding_box()
    assert (round(box['width']), round(box['height'])) == (840, 620)
    assert page.locator('.settings-header').bounding_box()['height'] == 48
    assert page.locator('[data-testid=settings-sidebar]').bounding_box()['width'] == 200
    assert page.locator('.side-item').evaluate_all('els => els.map(e => e.dataset.tab)') == \
        ['general', 'jobs', 'transcription', 'translation', 'batch', 'opensubtitles', 'ocr']
    assert page.locator('.side-item.selected').get_attribute('data-tab') == 'general'
    page.click('.side-item[data-tab=batch]')
    assert api(page, '/api/settings')['last_tab'] == 'batch'
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=settings-dialog]', state='detached')
    page.click('[data-testid=open-settings]')                         # come la GUI: si riapre sull'ultima scheda visitata
    page.wait_for_selector('.side-item.selected[data-tab=batch]')
    page.click('[data-testid=settings-close]')
    page.wait_for_selector('[data-testid=settings-dialog]', state='detached')
    assert env.problems == []


def test_il_riepilogo_dei_predefiniti_apre_la_scheda_opzioni_job(env):
    page = env.open()
    page.click('[data-testid=defaults-summary]')
    page.wait_for_selector('.side-item.selected[data-tab=jobs]')
    page.click('[data-testid=jo-go-engine]')
    page.wait_for_selector('.side-item.selected[data-tab=translation]')
    page.click('.side-item[data-tab=jobs]')
    page.click('[data-testid=jo-go-ocr]')
    page.wait_for_selector('.side-item.selected[data-tab=ocr]')


def test_esc_chiude_prima_il_messaggio_poi_la_finestra(env):
    page = env.open()
    open_tab(page, 'general')
    page.select_option('[data-testid=gs-lang]', 'en')
    page.wait_for_selector('[data-testid=message-box]')
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=message-box]', state='detached')
    assert page.locator('[data-testid=settings-dialog]').count() == 1
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=settings-dialog]', state='detached')


# ------------------------------------------------------------------------------------------------------------------------ generali
def test_generali_lingua_url_chiave_e_mostra_nascondi(env):
    page = env.open()
    open_tab(page, 'general')
    page.select_option('[data-testid=gs-lang]', 'en')
    title, text = message(page)
    assert (title, text) == (IT['language_restart_title'], IT['language_restart_msg'])
    assert api(page, '/api/settings')['general']['language'] == 'en'
    page.fill('[data-testid=gs-url]', 'http://10.0.0.5:6680')
    page.press('[data-testid=gs-url]', 'Enter')
    settle(page)
    assert api(page, '/api/settings')['general']['scanner_url'] == 'http://10.0.0.5:6680'
    page.fill('[data-testid=gs-key]', 'chiave-segreta-1234567890')
    page.locator('[data-testid=gs-key]').blur()
    settle(page)
    g = api(page, '/api/settings')['general']
    assert g['scanner_api_key_set'] is True and 'chiave-segreta' not in str(g)           # la chiave non esce mai nello stato
    page.reload()
    page.wait_for_selector('[data-testid=left-panel]')
    open_tab(page, 'general')
    assert page.locator('[data-testid=gs-key]').get_attribute('type') == 'password'
    assert page.locator('[data-testid=gs-key]').get_attribute('placeholder') == '••••••••••••'
    assert page.locator('[data-testid=gs-show]').inner_text() == EN['gs_show']      # la lingua e' stata portata a EN poco sopra
    page.click('[data-testid=gs-show]')
    until(page, "() => document.querySelector('[data-testid=gs-key]').value === 'chiave-segreta-1234567890'")
    assert page.locator('[data-testid=gs-key]').get_attribute('type') == 'text'
    assert page.locator('[data-testid=gs-show]').inner_text() == EN['gs_hide']
    page.click('[data-testid=gs-show]')
    assert page.locator('[data-testid=gs-key]').get_attribute('type') == 'password'


def test_generali_prova_connessione_url_vuoto_e_cartelle_montate(env):
    page = env.open()
    open_tab(page, 'general')
    page.fill('[data-testid=gs-url]', ''); page.press('[data-testid=gs-url]', 'Enter')
    page.click('[data-testid=gs-test]')
    assert page.locator('[data-testid=gs-ping]').inner_text() == IT['gs_invalid_url']
    page.fill('[data-testid=gs-map]', '\\\\srv\\film=/mnt/film')
    settle(page)
    assert api(page, '/api/settings')['general']['scanner_path_map'] == '\\\\srv\\film=/mnt/film'


# ------------------------------------------------------------------------------------------------------------------ opzioni job
def test_opzioni_job_si_salvano_subito(env):
    page = env.open()
    open_tab(page, 'jobs')
    assert page.locator('[data-testid=jo-lang] option').count() == 14
    page.select_option('[data-testid=jo-lang]', 'fra')
    tick(page, 'jo-mux')
    tick(page, 'jo-gender')
    tick(page, 'jo-upload')
    settle(page)
    j = api(page, '/api/settings')['job_options']
    assert (j['target_language'], j['mux_into_video'], j['gender_correction'], j['opensubtitles_upload']) == ('fra', True, True, True)


# ------------------------------------------------------------------------------------------------------------------ batch adattivo
def test_batch_attiva_disattiva_ripristina_e_salva(env):
    page = env.open()
    open_tab(page, 'batch')
    spin = lambda k: page.locator(f'[data-testid=ab-{k}]')            # noqa: E731
    tick(page, 'ab-enable', False)
    assert all(spin(k).is_disabled() for k in ('initial', 'min', 'max', 'warmup', 'high', 'low'))
    tick(page, 'ab-enable')
    assert not any(spin(k).is_disabled() for k in ('initial', 'min', 'max', 'warmup', 'high', 'low'))
    spin('max').fill('40'); spin('max').press('Tab')
    spin('high').fill('0,9'); spin('high').press('Tab')
    before = api(page, '/api/settings')['adaptive_batch']
    assert before['max_size'] != 40                                    # finche' non si preme Salva non si scrive
    page.click('[data-testid=ab-save]')
    settle(page)
    after = api(page, '/api/settings')['adaptive_batch']
    assert (after['max_size'], after['high_threshold'], after['enabled']) == (40, 0.9, True)
    page.click('[data-testid=ab-reset]')                                # Ripristina riempie il modulo, non scrive
    settle(page)
    assert spin('max').input_value() != '40'
    assert api(page, '/api/settings')['adaptive_batch']['max_size'] == 40
    spin('min').fill('99'); spin('min').press('Tab')
    assert spin('min').input_value() == '16'                           # fuori intervallo: si porta al massimo


# ------------------------------------------------------------------------------------------------------------------------- OCR
def test_ocr_strategia_lingua_soglia_worker_e_scrittura(env):
    page = env.open()
    open_tab(page, 'ocr')
    tick(page, 'oc-auto')
    settle(page)
    page.fill('[data-testid=oc-lang]', 'ita+eng'); page.press('[data-testid=oc-lang]', 'Enter')
    page.locator('[data-testid=oc-conf]').fill('70 %'); page.press('[data-testid=oc-conf]', 'Tab')
    settle(page)
    page.locator('[data-testid=oc-workers]').fill('4'); page.press('[data-testid=oc-workers]', 'Tab')
    page.select_option('[data-testid=oc-writeback]', 'sidecar')
    settle(page)
    page.fill('[data-testid=oc-tess]', '/usr/bin/tesseract'); page.press('[data-testid=oc-tess]', 'Enter')
    settle(page)
    o = api(page, '/api/settings')['ocr']
    assert (o['strategy'], o['language'], o['conf_threshold'], o['workers'], o['writeback'], o['tesseract_path']) == \
        ('auto', 'ita+eng', 70, 4, 'sidecar', '/usr/bin/tesseract')
    page.locator('[data-testid=oc-workers]').fill('0'); page.press('[data-testid=oc-workers]', 'Tab')
    settle(page)
    settle(page)
    assert page.locator('[data-testid=oc-workers]').input_value() == IT['ocr_workers_auto']       # valore speciale come QSpinBox
    tick(page, 'oc-review')
    settle(page)
    settle(page)
    assert api(page, '/api/settings')['ocr']['strategy'] == 'review'


# -------------------------------------------------------------------------------------------------------------------- OpenSubtitles
def test_opensubtitles_credenziali_mantieni_invariata_e_guida(env):
    page = env.open()
    open_tab(page, 'opensubtitles')
    assert page.locator('[data-testid=os-upload]').is_disabled()
    assert page.locator('[data-testid=os-test]').is_disabled()
    page.click('[data-testid=os-org-save]')
    assert message(page)[0] == IT['os_missing_fields_title']
    page.fill('[data-testid=os-org-user]', 'mario'); page.press('[data-testid=os-org-user]', 'Tab')
    page.fill('[data-testid=os-org-pass]', 'pw-uno'); page.press('[data-testid=os-org-pass]', 'Tab')
    page.click('[data-testid=os-org-save]')
    assert message(page)[0] == IT['os_creds_saved_title']
    os_ = api(page, '/api/settings')['opensubtitles']
    assert os_['org_username'] == 'mario' and os_['org_password_set'] is True and 'pw-uno' not in str(os_)
    page.fill('[data-testid=os-org-user]', 'mario2'); page.press('[data-testid=os-org-user]', 'Tab')
    page.click('[data-testid=os-org-save]')                           # password non toccata: resta quella salvata
    assert message(page)[0] == IT['os_creds_saved_title']
    os_ = api(page, '/api/settings')['opensubtitles']
    assert os_['org_username'] == 'mario2' and os_['org_password_set'] is True
    page.click('[data-testid=os-org-show]')
    until(page, "() => document.querySelector('[data-testid=os-org-pass]').value === 'pw-uno'")
    assert page.locator('[data-testid=os-upload]').is_enabled()
    tick(page, 'os-upload')
    page.select_option('[data-testid=os-impl]', 'rest')
    settle(page)
    os_ = api(page, '/api/settings')['opensubtitles']
    assert os_['upload_enabled'] is True and os_['implementation'] == 'rest'
    page.click('[data-testid=os-help]')
    page.wait_for_selector('[data-testid=os-guide]')
    assert 'XML-RPC' in page.locator('[data-testid=os-guide]').inner_text()
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=os-guide]', state='detached')
    assert page.locator('[data-testid=settings-dialog]').count() == 1


# ------------------------------------------------------------------------------------------------------------------- trascrizione
def test_trascrizione_motore_stile_dialoghi_e_schede_nascoste(env):
    page = env.open()
    open_tab(page, 'transcription')
    assert page.locator('[data-testid=tr-cards]').count() == 0           # le schede dei profili restano nascoste (profilo fisso)
    values = page.locator('[data-testid=tr-engine] option').evaluate_all('els => els.map(e => e.value)')
    assert values[0] == 'auto' and len(values) >= 3
    page.select_option('[data-testid=tr-engine]', values[1])
    tick(page, 'tr-dialogue')
    settle(page)
    s = api(page, '/api/settings/transcription')
    assert s['engine_mode'] == values[1] and s['dialogue_style'] is True


# --------------------------------------------------------------------------------------------------------------------- traduzione
def test_traduzione_modelli_percorsi_e_chiavi(env, tmp_path):
    page = env.open()
    open_tab(page, 'translation')
    for m, tid in (('claude', 'tm-claude'), ('opensubtitles', 'tm-os'), ('openai', 'tm-openai'), ('llm', 'tm-llm'), ('nllb_finetuned', 'tm-nllbft'), ('nllb', 'tm-nllb')):
        tick(page, tid + '-radio')
        settle(page)
        assert api(page, '/api/settings/translation')['model'] == m
    # percorso inesistente / vuoto / valido
    page.fill('[data-testid=tm-ft-path]', ''); page.click('[data-testid=tm-ft-save]')
    assert message(page)[0] == IT['path_empty']
    page.fill('[data-testid=tm-ft-path]', str(tmp_path / 'nope')); page.click('[data-testid=tm-ft-save]')
    assert message(page)[0] == IT['folder_not_found']
    (tmp_path / 'vuota').mkdir()
    page.fill('[data-testid=tm-ft-path]', str(tmp_path / 'vuota')); page.click('[data-testid=tm-ft-save]')
    assert message(page)[0] == IT['folder_invalid']
    assert page.locator('[data-testid=tm-ft-status]').inner_text() == IT['tmd_not_configured']
    # chiavi: vuota -> avviso; valida -> salvata, mai restituita
    page.click('[data-testid=tm-claude-save]')
    assert message(page)[0] == IT['save_api_key']
    page.fill('[data-testid=tm-claude-key]', 'sk-ant-' + 'x' * 40); page.click('[data-testid=tm-claude-save]')
    assert message(page)[0] == IT['creds_saved_title']
    st = api(page, '/api/settings/translation')
    assert st['claude_key_set'] is True and 'sk-ant-' not in str(st)
    assert page.locator('[data-testid=tm-claude-status]').inner_text() == IT['tmd_creds_configured']
    page.fill('[data-testid=tm-beams]', '7'); page.press('[data-testid=tm-beams]', 'Tab')
    settle(page)
    assert api(page, '/api/settings/translation')['nllb_beams'] == 7


def test_traduzione_flag_diarizzazione_genere_e_audio(env):
    page = env.open()
    open_tab(page, 'translation')
    for tid, key in (('tm-align', 'enable_forced_alignment'), ('tm-diar', 'enable_diarization'), ('tm-gender-enable', 'gender_correction_enabled'),
                     ('tm-force-audio', 'force_audio_transcription')):
        tick(page, tid)
        settle(page)
        assert api(page, '/api/settings/translation')['flags'][key] is True
    tick(page, 'tm-gender-p2', False)
    page.fill('[data-testid=tm-speakers]', '3'); page.press('[data-testid=tm-speakers]', 'Tab')
    settle(page)
    f = api(page, '/api/settings/translation')['flags']
    assert f['gender_correction_second_person'] is False and f['diarization_num_speakers'] == 3
    page.fill('[data-testid=tm-speakers]', '0'); page.press('[data-testid=tm-speakers]', 'Tab')
    settle(page)
    assert page.locator('[data-testid=tm-speakers]').input_value() == IT['auto_speakers']


def test_traduzione_test_diarizzazione_e_scaricamento_con_righe_in_diretta(env):
    page = env.open()
    open_tab(page, 'translation')
    page.click('[data-testid=tm-diar-test]')                           # senza token: avviso, nessun sottoprocesso
    until(page, "() => document.querySelector('[data-testid=tm-diar-result]').innerText.length > 0")
    assert page.locator('[data-testid=tm-diar-result]').inner_text() == IT['tmd_token_not_set_save_first']
    page.click('[data-testid=tm-llm-download]')                         # senza token HF: messaggio
    assert message(page)[0] == IT['tmd_token_missing_title']
    page.fill('[data-testid=tm-diar-token]', 'hf_' + 'a' * 34); page.click('[data-testid=tm-diar-save]')
    assert message(page)[0] == IT['creds_saved_title']
    FakeRunner.gate = threading.Event()
    page.click('[data-testid=tm-diar-test]')
    until(page, "() => document.querySelector('[data-testid=tm-diar-test]').disabled")
    FakeRunner.gate.set()
    until(page, "() => document.querySelector('[data-testid=tm-diar-result]').innerText.includes('esito finale')")
    assert '⏳' not in page.locator('[data-testid=tm-diar-result]').inner_text()          # le righe di avanzamento non fanno parte del verdetto
    FakeRunner.exit_code = 2
    page.click('[data-testid=tm-llm-download]')
    page.wait_for_selector('[data-testid=tm-llm-result]')
    assert page.locator('[data-testid=tm-llm-result]').inner_text().startswith('[X] ')
    assert env.problems == []


@pytest.mark.senza_traduttore
def test_traduzione_non_disponibile_mostra_la_pagina_di_errore(env):
    page = env.open()
    open_tab(page, 'translation')
    assert page.locator('[data-testid=tm-unavailable]').inner_text() == IT['tmd_error_title'] + '\n\n' + IT['tmd_import_error']
    assert page.locator('[data-testid=tm-nllb]').count() == 0
    open_tab(page, 'batch')                                  # le altre schede restano usabili
    assert page.locator('[data-testid=ab-save]').count() == 1


def test_opensubtitles_com_password_non_toccata_resta_quella_salvata(env):
    page = env.open()
    open_tab(page, 'opensubtitles')
    for tid, v in (('os-com-user', 'luigi'), ('os-com-pass', 'pw-com'), ('os-com-key', 'k' * 32)):
        page.fill(f'[data-testid={tid}]', v); page.press(f'[data-testid={tid}]', 'Tab')
    page.click('[data-testid=os-com-save]')
    assert message(page)[0] == IT['os_creds_saved_title']
    page.fill('[data-testid=os-com-user]', 'luigi2'); page.press('[data-testid=os-com-user]', 'Tab')
    page.click('[data-testid=os-com-save]')                     # password e chiave non toccate: si mantengono, niente avviso di campi mancanti
    assert message(page)[0] == IT['os_creds_saved_title']
    os_ = api(page, '/api/settings')['opensubtitles']
    assert os_['com_username'] == 'luigi2' and os_['com_password_set'] is True and os_['com_api_key_set'] is True
    page.click('[data-testid=os-com-show]')
    until(page, "() => document.querySelector('[data-testid=os-com-pass]').value === 'pw-com'")


def test_esc_nel_navigatore_cartelle_non_chiude_le_impostazioni(env):
    page = env.open()
    open_tab(page, 'translation')
    page.click('[data-testid=tm-ft-browse]')
    page.wait_for_selector('[data-testid=file-browser]')
    page.keyboard.press('Escape')
    page.wait_for_selector('[data-testid=file-browser]', state='detached')
    assert page.locator('[data-testid=settings-dialog]').count() == 1
