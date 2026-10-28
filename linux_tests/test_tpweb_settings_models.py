# -*- coding: utf-8 -*-
"""Impostazioni di trascrizione e traduzione (fase 3) e ritocchi alle altre schede: servizi G3 senza Qt dietro l'API, nessun segreto in uscita."""
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

from tpweb.events import EventBus  # noqa: E402
from tpweb.runner import ServerThread  # noqa: E402


class FakeRunner:
    """Al posto di `core.env_check_cli`: scrive righe e termina con il codice voluto."""
    exit_code = 0
    lines = ['riga uno', 'riga due']
    gate = None

    def __init__(self, command, listener):
        self.command, self.listener = command, listener

    def run(self):
        if FakeRunner.gate is not None:
            FakeRunner.gate.wait(10)
        for l in FakeRunner.lines:
            self.listener.on_line(l)
        self.listener.on_finished(FakeRunner.exit_code)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    config = cfg.get_config()
    from tpweb.routes_models import EnvJobs
    bus = EventBus()
    FakeRunner.exit_code, FakeRunner.lines, FakeRunner.gate = 0, ['riga uno', 'riga due'], None
    s = ServerThread(bus=bus, config=config, env_jobs=EnvJobs(bus, FakeRunner), translator_ok=lambda: True).start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    e = type('E', (), dict(c=c, srv=s, config=config, tmp=tmp_path, bus=bus))
    yield e
    c.close()
    s.stop()
    cfg.reset_config()


# ------------------------------------------------------------------------------------------------------------------- trascrizione
def test_trascrizione_stato_e_schede_dei_profili(env):
    r = env.c.get('/api/settings/transcription').json()
    assert r['engine_mode'] == 'auto' and r['dialogue_style'] is True and r['profile'] in {c['value'] for c in r['cards']}
    assert [e['value'] for e in r['engines']] == ['auto', 'canary', 'qwen3', 'faster-whisper']
    assert [c['value'] for c in r['cards']] == ['fast', 'balanced', 'quality', 'maximum', 'batch']
    bal = next(c for c in r['cards'] if c['value'] == 'balanced')
    assert bal['recommended'] is True and bal['name_key'] == 'profile_balanced_name' and bal['params'].startswith('⚙️ Whisper · W:')
    assert bal['time'].startswith('⏱️ ~') and sum(c['recommended'] for c in r['cards']) == 1
    from utils.translations import Translations
    for lang in ('it', 'en'):                                   # ogni chiave citata esiste nella lingua
        for c in r['cards']:
            for k in (c['name_key'], c['desc_key'], c['warning_key']):
                assert k is None or k in Translations.TEXTS[lang]


def test_schede_dei_profili_come_il_servizio_della_gui(env):
    from core.services.transcription_settings_service import profile_cards, profile_specs
    from utils.translations import tr
    for card, spec in zip(profile_cards(), profile_specs()):
        assert card.value == spec.value and card.params == spec.params and card.time == spec.time
        assert card.description == tr(spec.desc_key) and card.name_html == f"<b>{tr(spec.name_key)}</b>"
        assert (card.recommended_badge is not None) == spec.recommended
        assert card.warning == (f"⚠️ {tr(spec.warning_key)}" if spec.warning_key else None)


def test_le_schede_dei_profili_restano_nascoste_come_nella_gui(env):
    from gui import profile_dialog
    from core.services.transcription_settings_service import SHOW_PROFILE_CARDS
    assert profile_dialog.SHOW_PROFILE_CARDS == SHOW_PROFILE_CARDS is False
    assert env.c.get('/api/settings/transcription').json()['show_cards'] is False


def test_trascrizione_scrittura_e_rifiuto_dei_valori_sconosciuti(env):
    env.config.set('transcription_profile_locked', False, save=False)          # senza il blocco su 'maximum' la scelta del profilo vale
    r = env.c.put('/api/settings/transcription', json={'engine_mode': 'qwen3', 'dialogue_style': False, 'profile': 'quality'}).json()
    assert (r['engine_mode'], r['dialogue_style'], r['profile']) == ('qwen3', False, 'quality')
    on_disk = json.loads(env.config.CONFIG_FILE.read_text(encoding='utf-8'))
    assert on_disk['transcription_engine_mode'] == 'qwen3' and on_disk['dialogue_style_enabled'] is False and on_disk['transcription_profile'] == 'quality'
    assert env.c.put('/api/settings/transcription', json={'engine_mode': 'boh'}).status_code == 422
    assert env.c.put('/api/settings/transcription', json={'profile': 'boh'}).status_code == 422
    assert env.c.get('/api/settings/transcription').json()['engine_mode'] == 'qwen3'


# --------------------------------------------------------------------------------------------------------------------- traduzione
def test_traduzione_stato_iniziale_senza_segreti(env):
    r = env.c.get('/api/settings/translation').json()
    assert r['translator_available'] is True and r['model'] in r['models'] and r['models'] == ['nllb', 'nllb_finetuned', 'llm', 'claude', 'opensubtitles', 'openai']
    assert r['nllb_beams'] >= 1 and r['hf_token_set'] is False and r['claude_key_set'] is False and r['openai_key_set'] is False
    assert r['openai_models'] == ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'] and 'huggingface.co/' in r['diarization_urls']
    assert set(r['flags']) == {'enable_forced_alignment', 'enable_diarization', 'diarization_num_speakers', 'gender_correction_enabled',
                               'gender_correction_second_person', 'force_audio_transcription'}
    assert r['flags']['gender_correction_second_person'] is True and r['flags']['enable_diarization'] is False


def test_scheda_traduzione_non_disponibile_senza_torch(tmp_path, monkeypatch):
    from tpweb.routes_models import translator_available
    import importlib.util
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None)
    assert translator_available() is False
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    assert translator_available() is True


def test_scelta_del_modello_si_salva_subito_e_aya_vale_llm(env):
    assert env.c.put('/api/settings/translation/model', json={'name': 'claude'}).json()['model'] == 'claude'
    assert json.loads(env.config.CONFIG_FILE.read_text(encoding='utf-8'))['translation_model'] == 'claude'
    assert env.c.put('/api/settings/translation/model', json={'name': 'sconosciuto'}).status_code == 422
    env.config.set('translation_model', 'aya', save=False)
    assert env.c.get('/api/settings/translation').json()['model'] == 'llm'


def test_percorsi_dei_modelli_validati_come_la_gui(env):
    d = env.tmp / 'modello'
    d.mkdir()
    put = lambda name, p: env.c.put(f'/api/settings/translation/{name}', json={'path': str(p)}).json()           # noqa: E731
    assert put('nllb_ft_path', '')['kind'] == 'empty' and put('nllb_ft_path', env.tmp / 'manca')['kind'] == 'missing'
    assert put('nllb_ft_path', d)['kind'] == 'invalid'
    (d / 'config.json').write_text('{}')
    r = put('nllb_ft_path', d)
    assert r['kind'] == 'ok' and r['state']['nllb_ft'] == {'path': str(d), 'configured': True}
    assert put('llm_path', '')['kind'] == 'ok' and put('llm_path', env.tmp / 'manca')['kind'] == 'missing'       # vuoto = predefinito: valido
    assert put('llm_path', d)['state']['llm_path'] == str(d)


def test_beams_e_flag_con_i_limiti(env):
    assert env.c.put('/api/settings/translation/nllb_beams', json={'value': 7}).json()['nllb_beams'] == 7
    assert env.c.put('/api/settings/translation/nllb_beams', json={'value': 0}).status_code == 422
    assert env.c.put('/api/settings/translation/nllb_beams', json={'value': 21}).status_code == 422
    for k, v in (('enable_diarization', True), ('diarization_num_speakers', 10), ('gender_correction_second_person', False), ('force_audio_transcription', True)):
        assert env.c.put('/api/settings/translation/flag', json={'key': k, 'value': v}).json()['flags'][k] == v
    for k, v in (('diarization_num_speakers', 21), ('diarization_num_speakers', -1), ('diarization_num_speakers', True), ('enable_diarization', 1),
                 ('enable_forced_alignment', 'si'), ('translation_model', 'x'), ('library_scanner_api_key', 'x')):
        assert env.c.put('/api/settings/translation/flag', json={'key': k, 'value': v}).status_code == 422, (k, v)


def test_chiavi_e_token_validati_e_mai_restituiti(env, monkeypatch):
    import utils.config as cfgmod
    monkeypatch.setattr(cfgmod.Config, 'validate_huggingface_token', lambda self, t: (t.startswith('hf_'), 'token non valido'))
    monkeypatch.setattr(cfgmod.Config, 'validate_claude_api_key', lambda self, k: (k.startswith('sk-ant-'), 'chiave non valida'))
    monkeypatch.setattr(cfgmod.Config, 'validate_openai_api_key', lambda self, k: (k.startswith('sk-'), 'chiave OpenAI non valida'))
    put = lambda name, body: env.c.put(f'/api/settings/translation/{name}', json=body).json()                    # noqa: E731
    assert put('hf_token', {'value': '  '})['kind'] == 'empty' and put('hf_token', {'value': 'x'}) ['kind'] == 'invalid'
    assert put('hf_token', {'value': 'x'})['error'] == 'token non valido'
    assert put('hf_token', {'value': 'hf_SEGRETO1_lungo_abbastanza'})['kind'] == 'ok'
    assert put('claude_key', {'value': ''})['kind'] == 'empty' and put('claude_key', {'value': 'zzz'})['kind'] == 'invalid'
    assert put('claude_key', {'value': 'sk-ant-SEGRETO2-lunga-abbastanza'})['kind'] == 'ok'
    assert put('openai', {'key': 'zzz', 'model': 'gpt-4o'})['kind'] == 'invalid'
    r = put('openai', {'key': 'sk-SEGRETO3-lunga-abbastanza-1', 'model': 'gpt-4o'})
    assert r['kind'] == 'ok' and r['state']['openai_model'] == 'gpt-4o'
    assert env.c.put('/api/settings/translation/openai', json={'key': 'sk-x', 'model': 'gpt-9'}).status_code == 422
    s = env.c.get('/api/settings/translation')
    assert (s.json()['hf_token_set'], s.json()['claude_key_set'], s.json()['openai_key_set']) == (True, True, True)
    everything = s.text + env.c.get('/api/settings').text + env.c.get('/api/state').text
    for secret in ('hf_SEGRETO1_lungo_abbastanza', 'sk-ant-SEGRETO2-lunga-abbastanza', 'sk-SEGRETO3-lunga-abbastanza-1'):
        assert secret not in everything and secret not in json.dumps(put('hf_token', {'value': 'hf_SEGRETO1_lungo_abbastanza'}).get('state'))


def test_prerequisiti_del_genere_mancanti(env):
    r = env.c.get('/api/settings/translation').json()
    assert 'tmd_gender_missing_hf' in r['gender_missing']
    env.config.set('huggingface_token', 'hf_x', save=False)
    assert 'tmd_gender_missing_hf' not in env.c.get('/api/settings/translation').json()['gender_missing']


# ----------------------------------------------------------------------------------------------------------- lavori in sottoprocesso
def wait_job(env, name, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = env.c.get('/api/settings/translation').json()['jobs'].get(name)
        if j and not j['running']:
            return j
        time.sleep(0.05)
    raise AssertionError('lavoro non terminato')


def test_download_llm_richiede_il_token_poi_parte_e_pubblica_le_righe(env):
    r = env.c.post('/api/settings/translation/llm_download')
    assert r.status_code == 409 and r.json() == {'kind': 'token_missing'}
    env.config.set('huggingface_token', 'hf_x', save=False)
    assert env.c.post('/api/settings/translation/llm_download').json() == {'kind': 'started'}
    j = wait_job(env, 'llm-download')
    assert j == {'running': False, 'last_line': 'riga due', 'exit_code': 0}
    ev = [(e['k'], e['d']) for e in env.bus.since(0)[0] if e['k'].startswith('env_')]
    assert ev == [('env_line', {'job': 'llm-download', 'line': 'riga uno'}), ('env_line', {'job': 'llm-download', 'line': 'riga due'}),
                  ('env_done', {'job': 'llm-download', 'exit_code': 0, 'last_line': 'riga due'})]


def test_un_solo_lavoro_alla_volta_per_tipo_e_codice_di_errore(env):
    import threading
    env.config.set('huggingface_token', 'hf_x', save=False)
    gate = threading.Event()
    FakeRunner.gate, FakeRunner.exit_code = gate, 3
    assert env.c.post('/api/settings/translation/diarization_test').json() == {'kind': 'started'}
    assert env.c.post('/api/settings/translation/diarization_test').json() == {'kind': 'running'}          # gia' in corso
    assert env.c.post('/api/settings/translation/llm_download').json() == {'kind': 'started'}              # un altro tipo parte
    gate.set()
    assert wait_job(env, 'diarization-test')['exit_code'] == 3
    assert env.c.post('/api/settings/translation/diarization_test').json() == {'kind': 'started'}          # finito: si puo' rilanciare
    wait_job(env, 'diarization-test')


def test_test_pyannote_senza_token(env):
    r = env.c.post('/api/settings/translation/diarization_test')
    assert r.status_code == 409 and r.json() == {'kind': 'token_missing'}


# --------------------------------------------------------------------------------------------- ritocchi alle altre schede e segreti
def test_mostra_del_segreto_solo_su_richiesta_e_solo_per_i_nomi_ammessi(env):
    env.c.put('/api/settings/general', json={'scanner_api_key': 'CHIAVE-SCANNER'})
    env.c.put('/api/settings/opensubtitles/com', json={'username': 'u', 'password': 'PW-COM', 'api_key': 'KEY-COM'})
    env.c.put('/api/settings/opensubtitles/org', json={'username': 'o', 'password': 'PW-ORG'})
    for name, val in (('scanner_api_key', 'CHIAVE-SCANNER'), ('os_com_password', 'PW-COM'), ('os_com_api_key', 'KEY-COM'), ('os_org_password', 'PW-ORG')):
        assert env.c.post('/api/settings/reveal', json={'name': name}).json() == {'value': val}
    assert env.c.post('/api/settings/reveal', json={'name': 'huggingface_token'}).status_code == 422
    assert env.c.post('/api/settings/reveal', json={'name': '../config'}).status_code == 422
    assert httpx.post(f'http://127.0.0.1:{env.srv.port}/api/settings/reveal', json={'name': 'scanner_api_key'}).status_code == 401
    r = env.c.post('/api/settings/reveal', json={'name': 'scanner_api_key'}, headers={'Origin': 'https://evil.example'})
    assert r.status_code == 403


def test_credenziali_opensubtitles_campo_non_inviato_resta_invariato(env):
    env.c.put('/api/settings/opensubtitles/com', json={'username': 'u1', 'password': 'PW', 'api_key': 'KEY'})
    r = env.c.put('/api/settings/opensubtitles/com', json={'username': 'u2'})                       # solo lo username cambia
    assert r.status_code == 200 and r.json()['com_username'] == 'u2'
    assert env.c.post('/api/settings/reveal', json={'name': 'os_com_password'}).json()['value'] == 'PW'
    assert env.c.post('/api/settings/reveal', json={'name': 'os_com_api_key'}).json()['value'] == 'KEY'
    r = env.c.put('/api/settings/opensubtitles/com', json={'username': 'u2', 'password': '', 'api_key': ''})
    assert r.status_code == 422                                                                       # password vuota esplicita: rifiutata
    env.c.put('/api/settings/opensubtitles/org', json={'username': 'o1', 'password': 'PO'})
    assert env.c.put('/api/settings/opensubtitles/org', json={'username': 'o2'}).json()['org_username'] == 'o2'
    assert env.c.post('/api/settings/reveal', json={'name': 'os_org_password'}).json()['value'] == 'PO'


def test_ultima_scheda_ricordata_e_dati_per_le_schede(env):
    s = env.c.get('/api/settings').json()
    assert s['last_tab'] == 'general' and s['general']['platform'] in ('windows', 'other')
    assert s['job_options']['engine_short'] in ('NLLB', 'TG', 'NLLB-FT') and s['job_options']['ocr_mode_key'] in ('job_ocr_mode_auto', 'job_ocr_mode_targeted')
    assert env.c.put('/api/settings/last_tab', json={'tab': 'ocr'}).json() == {'tab': 'ocr'}
    assert env.c.get('/api/settings').json()['last_tab'] == 'ocr'
    assert env.c.put('/api/settings/last_tab', json={'tab': 'boh'}).status_code == 422
