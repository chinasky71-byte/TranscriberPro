# -*- coding: utf-8 -*-
"""G3 (fase 0 della web UI): CARATTERIZZAZIONE di gui/translation_model_dialog.py (scheda "Traduzione" delle Impostazioni).

Passa identica sul codice vecchio e su quello con la logica in core/services/translation_model_service.py e core/jobs/env_cli.py:
selezione del modello (embed e standalone, con le domande di conferma), percorsi (NLLB fine-tuned, LLM) con le loro validazioni,
chiavi API/token con validazione e stato, diarizzazione, genere, forza-audio, parametri NLLB, download LLM e test pyannote tramite
sottoprocesso (finto). Qt offscreen, config temporaneo, finestre di dialogo registrate."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STUB = Path(__file__).resolve().parent / 'env_cli_stub.py'


@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    yield app
    for w in app.topLevelWidgets():
        w.deleteLater()
    app.processEvents()
    cfg.reset_config()


@pytest.fixture
def boxes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    class Seen(list):
        pass
    seen = Seen()
    answer = {'q': QMessageBox.StandardButton.Yes}
    for kind in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda p, t, m, *a, _k=kind, **k: seen.append((_k, t, m)) or 0))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda p, t, m, *a, **k: seen.append(('question', t, m)) or answer['q']))
    seen.answer = answer
    return seen


@pytest.fixture
def libs(monkeypatch):
    """Il dialogo mostra l'interfaccia solo se transformers e torch 'esistono': li dichiariamo presenti (nessun import reale)."""
    import importlib.util as iu
    real = iu.find_spec
    monkeypatch.setattr(iu, 'find_spec', lambda name, *a, **k: object() if name in ('transformers', 'torch') else real(name, *a, **k))


def cfg():
    from utils.config import get_config
    return get_config()


def make(embed=True):
    from gui.translation_model_dialog import TranslationModelDialog
    return TranslationModelDialog(embed=embed)


def checked(d):
    return [r.objectName() for r in (d.nllb_radio, d.nllb_ft_radio, d.llm_radio, d.claude_radio, d.os_radio, d.oai_radio) if r.isChecked()]


KEY_CLAUDE = 'sk-ant-' + 'a' * 40
KEY_OAI = 'sk-proj-' + 'b' * 40
TOKEN = 'hf_' + 'c' * 30


def model_dir(tmp_path, name='m', config=True):
    p = tmp_path / name
    p.mkdir()
    if config:
        (p / 'config.json').write_text('{}', encoding='utf-8')
    return p


# ------------------------------------------------------------------------------------------------------------- avvio
def test_senza_librerie_mostra_l_errore(qt, monkeypatch):
    import importlib.util as iu
    real = iu.find_spec
    monkeypatch.setattr(iu, 'find_spec', lambda name, *a, **k: None if name in ('transformers', 'torch') else real(name, *a, **k))
    d = make()
    assert not hasattr(d, 'nllb_radio')


def test_modello_corrente_selezionato(qt, libs):
    for model, radio in (('nllb', 'nllb'), ('llm', 'llm'), ('claude', 'claude'), ('openai', 'openai')):
        cfg().set('translation_model', model)
        d = make()
        assert d.selected_model == model
        assert d.get_selected_model() in ('nllb', 'llm', 'claude', 'openai')


@pytest.mark.parametrize('which,expected', [('nllb_radio', 'nllb'), ('nllb_ft_radio', 'nllb_finetuned'), ('llm_radio', 'llm'),
                                            ('claude_radio', 'claude'), ('os_radio', 'opensubtitles'), ('oai_radio', 'openai')])
def test_get_selected_model(qt, libs, which, expected):
    d = make()
    getattr(d, which).setChecked(True)
    assert d.get_selected_model() == expected


def test_embed_salva_subito_la_selezione(qt, libs):
    d = make(embed=True)
    d.claude_radio.setChecked(True)
    assert cfg().get_translation_model() == 'claude' and d.selected_model == 'claude'
    d.nllb_ft_radio.setChecked(True)
    assert cfg().get_translation_model() == 'nllb_finetuned'
    d._on_radio_toggled_embed(d.llm_radio, False)             # deselezione: nessun effetto
    assert cfg().get_translation_model() == 'nllb_finetuned'
    from PyQt6.QtWidgets import QRadioButton
    estraneo = QRadioButton()
    estraneo.setObjectName('boh')
    d._on_radio_toggled_embed(estraneo, True)
    assert cfg().get_translation_model() == 'nllb_finetuned'


@pytest.mark.parametrize('model', ['nllb', 'nllb_finetuned', 'llm', 'claude', 'opensubtitles', 'openai'])
def test_embed_salva_ogni_modello(qt, libs, model):
    cfg().set('translation_model', 'llm' if model != 'llm' else 'nllb')
    d = make(embed=True)
    radio = {'nllb': d.nllb_radio, 'nllb_finetuned': d.nllb_ft_radio, 'llm': d.llm_radio, 'claude': d.claude_radio,
             'opensubtitles': d.os_radio, 'openai': d.oai_radio}[model]
    radio.setChecked(True)
    assert cfg().get_translation_model() == model


def test_salva_senza_domande_se_i_prerequisiti_ci_sono(qt, libs, boxes, tmp_path):
    from utils.translations import tr
    cfg().set_nllb_finetuned_model_path(str(model_dir(tmp_path, 'ok')))
    cfg().set_openai_api_key(KEY_OAI)
    cfg().set('opensubtitles_username', 'u')
    cfg().set('opensubtitles_password', 'p')
    cfg().set('opensubtitles_api_key', 'k')
    d = make(embed=False)
    for radio, model in ((d.nllb_ft_radio, 'nllb_finetuned'), (d.oai_radio, 'openai'), (d.os_radio, 'opensubtitles')):
        boxes.clear()
        radio.setChecked(True)
        d.save_selection()
        assert [b[0] for b in boxes] == ['information'] and cfg().get_translation_model() == model


def test_standalone_non_salva_alla_selezione(qt, libs):
    cfg().set('translation_model', 'nllb')
    d = make(embed=False)
    d.llm_radio.setChecked(True)
    assert cfg().get_translation_model() == 'nllb'


# ----------------------------------------------------------------------------------------------------- save_selection
@pytest.mark.parametrize('which,model', [('nllb_radio', 'nllb'), ('llm_radio', 'llm')])
def test_salva_selezione_semplice(qt, libs, boxes, which, model):
    from utils.translations import tr
    d = make(embed=False)
    getattr(d, which).setChecked(True)
    d.save_selection()
    names = {'nllb': 'NLLB-200', 'llm': 'TranslateGemma_finetuned'}
    assert cfg().get_translation_model() == model
    assert boxes == [('information', tr('model_updated_title'), tr('model_updated_msg').format(model=names[model]))]
    assert d.result() == d.DialogCode.Accepted


def test_salva_claude_senza_chiave(qt, libs, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    d = make(embed=False)
    d.claude_radio.setChecked(True)
    d.save_selection()                                        # risposta Si': resta nel dialogo
    assert boxes == [('question', tr('tmd_api_key_missing_title'), tr('tmd_claude_key_missing_ask'))]
    assert cfg().get_translation_model() != 'claude'
    boxes.clear()
    boxes.answer['q'] = QMessageBox.StandardButton.No          # No: avvisa e salva comunque
    d.save_selection()
    assert [b[0] for b in boxes] == ['question', 'warning', 'information']
    assert boxes[1][2] == tr('tmd_claude_needs_key') and cfg().get_translation_model() == 'claude'
    assert boxes[2][2] == tr('model_updated_msg').format(model='Claude API')


def test_salva_claude_con_chiave(qt, libs, boxes):
    cfg().set_claude_api_key(KEY_CLAUDE)
    d = make(embed=False)
    d.claude_radio.setChecked(True)
    d.save_selection()
    assert [b[0] for b in boxes] == ['information'] and cfg().get_translation_model() == 'claude'


def test_salva_finetuned_senza_percorso(qt, libs, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    d = make(embed=False)
    d.nllb_ft_radio.setChecked(True)
    d.save_selection()
    assert boxes == [('question', tr('tmd_model_not_configured_title'), tr('tmd_ft_path_missing_ask'))]
    boxes.clear()
    boxes.answer['q'] = QMessageBox.StandardButton.No
    d.save_selection()
    assert boxes[1] == ('warning', tr('tmd_attention'), tr('tmd_ft_needs_path'))
    assert cfg().get_translation_model() == 'nllb_finetuned'
    assert boxes[2][2] == tr('model_updated_msg').format(model='NLLB-200 Fine-Tuned (Plex)')


def test_salva_opensubtitles_logica_inversa(qt, libs, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    d = make(embed=False)
    d.os_radio.setChecked(True)
    boxes.answer['q'] = QMessageBox.StandardButton.No          # qui No = resta
    d.save_selection()
    assert boxes == [('question', tr('tmd_creds_missing_title'), tr('tmd_os_creds_missing_ask'))]
    assert cfg().get_translation_model() != 'opensubtitles'
    boxes.clear()
    boxes.answer['q'] = QMessageBox.StandardButton.Yes         # Si' = salva comunque, senza avviso
    d.save_selection()
    assert [b[0] for b in boxes] == ['question', 'information'] and cfg().get_translation_model() == 'opensubtitles'
    assert boxes[1][2] == tr('model_updated_msg').format(model='OpenSubtitles AI')


def test_salva_openai(qt, libs, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    d = make(embed=False)
    d.oai_radio.setChecked(True)
    d.save_selection()
    assert boxes == [('question', tr('tmd_api_key_missing_title'), tr('tmd_openai_key_missing_ask'))]
    boxes.clear()
    boxes.answer['q'] = QMessageBox.StandardButton.No
    d.save_selection()
    assert boxes[1] == ('warning', tr('tmd_attention'), tr('tmd_openai_needs_key')) and cfg().get_translation_model() == 'openai'
    assert boxes[2][2] == tr('model_updated_msg').format(model='OpenAI GPT')


# ------------------------------------------------------------------------------------------------------ percorsi
def test_percorso_finetuned(qt, libs, boxes, tmp_path):
    from utils.translations import tr
    d = make()
    d.save_nllb_ft_path()                                      # vuoto
    assert boxes[-1] == ('warning', tr('path_empty'), tr('tmd_enter_merged_path'))
    d.nllb_ft_path_input.setText(str(tmp_path / 'non_esiste'))
    d.save_nllb_ft_path()
    assert boxes[-1] == ('warning', tr('folder_not_found'), tr('tmd_folder_missing_msg').format(path=str(tmp_path / 'non_esiste')))
    nocfg = model_dir(tmp_path, 'senza', config=False)
    d.nllb_ft_path_input.setText(str(nocfg))
    d.save_nllb_ft_path()
    assert boxes[-1] == ('warning', tr('folder_invalid'), tr('tmd_folder_invalid_msg'))
    assert cfg().get_nllb_finetuned_model_path() == ''
    assert d.nllb_ft_status_label.text() == tr('tmd_not_configured')
    ok = model_dir(tmp_path, 'ok')
    d.nllb_ft_path_input.setText(f'  {ok}  ')
    d.save_nllb_ft_path()
    assert boxes[-1] == ('information', tr('path_saved_title'), tr('path_saved_msg'))
    assert cfg().get_nllb_finetuned_model_path() == str(ok) and d.nllb_ft_status_label.text() == tr('tmd_configured')
    assert 'green' in d.nllb_ft_status_label.styleSheet().lower() or 'font-weight: bold' in d.nllb_ft_status_label.styleSheet()


def test_percorso_finetuned_iniziale(qt, libs, tmp_path):
    ok = model_dir(tmp_path, 'ok')
    cfg().set_nllb_finetuned_model_path(str(ok))
    d = make()
    assert d.nllb_ft_path_input.text() == str(ok)


def test_percorso_llm(qt, libs, boxes, tmp_path):
    from utils.translations import tr
    d = make()
    d.llm_model_path_input.setText(str(tmp_path / 'no'))
    d.save_llm_model_path()
    assert boxes[-1][:2] == ('warning', tr('folder_not_found'))
    d.llm_model_path_input.setText(str(model_dir(tmp_path, 'senza', config=False)))
    d.save_llm_model_path()
    assert boxes[-1] == ('warning', tr('folder_invalid'), tr('tmd_folder_invalid_msg'))
    assert cfg().get_llm_translator_model_path() == ''
    ok = model_dir(tmp_path, 'ok')
    d.llm_model_path_input.setText(str(ok))
    d.save_llm_model_path()
    assert cfg().get_llm_translator_model_path() == str(ok) and boxes[-1][:2] == ('information', tr('path_saved_title'))
    d.llm_model_path_input.setText('  ')                     # vuoto = predefinito: nessuna validazione
    d.save_llm_model_path()
    assert cfg().get_llm_translator_model_path() == ''


def test_sfoglia_percorsi(qt, libs, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog
    seen = []
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', staticmethod(lambda p, t, start='': seen.append((t, start)) or str(tmp_path / 'scelta')))
    d = make()
    d.nllb_ft_path_input.setText('')
    d.browse_nllb_ft_path()
    assert d.nllb_ft_path_input.text() == str(tmp_path / 'scelta') and seen[0][1] == str(Path.home())
    d.llm_model_path_input.setText('/prima')
    d.browse_llm_model_path()
    assert seen[1][1] == '/prima' and d.llm_model_path_input.text() == str(tmp_path / 'scelta')
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', staticmethod(lambda p, t, start='': ''))
    d.browse_llm_model_path()
    assert d.llm_model_path_input.text() == str(tmp_path / 'scelta')


def test_beams_nllb(qt, libs):
    d = make()
    assert d.nllb_beams_spin.value() == 7 and (d.nllb_beams_spin.minimum(), d.nllb_beams_spin.maximum()) == (1, 20)
    d.nllb_beams_spin.setValue(12)
    assert cfg().get_nllb_num_beams() == 12
    cfg().set_nllb_num_beams(3)
    assert make().nllb_beams_spin.value() == 3


# ------------------------------------------------------------------------------------------------ chiavi e token
def test_chiave_claude(qt, libs, boxes):
    from utils.translations import tr
    d = make()
    d.save_claude_api_key()
    assert boxes[-1] == ('warning', tr('save_api_key'), tr('tmd_enter_valid_api_key'))
    d.claude_api_input.setText('sk-sbagliata')
    d.save_claude_api_key()
    ok, err = cfg().validate_claude_api_key('sk-sbagliata')
    assert boxes[-1] == ('warning', tr('tmd_api_key_invalid_title'), tr('tmd_api_key_invalid_msg').format(error=err))
    assert d.claude_status_label.text() == tr('tmd_not_configured')
    d.claude_api_input.setText(f' {KEY_CLAUDE} ')
    d.save_claude_api_key()
    assert cfg().get_claude_api_key() == KEY_CLAUDE and d.claude_status_label.text() == tr('tmd_creds_configured')
    assert boxes[-1] == ('information', tr('creds_saved_title'), tr('creds_saved_msg'))
    assert make().claude_api_input.text() == KEY_CLAUDE


def test_chiave_openai_e_modello(qt, libs, boxes):
    from utils.translations import tr
    d = make()
    assert [d.oai_model_combo.itemText(i) for i in range(d.oai_model_combo.count())] == ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo']
    d.save_openai_api_key()
    assert boxes[-1][:2] == ('warning', tr('tmd_api_key_invalid_title')) and cfg().get_openai_api_key() == ''
    d.oai_api_input.setText(KEY_OAI)
    d.oai_model_combo.setCurrentText('gpt-4o')
    d.save_openai_api_key()
    assert cfg().get_openai_api_key() == KEY_OAI and cfg().get_openai_model() == 'gpt-4o'
    assert d.oai_status_label.text() == tr('tmd_creds_configured') and boxes[-1][0] == 'information'
    cfg().set_openai_model('gpt-4-turbo')
    assert make().oai_model_combo.currentText() == 'gpt-4-turbo'
    cfg().set_openai_model('boh')
    assert make().oai_model_combo.currentText() == 'gpt-4o-mini'          # modello sconosciuto: resta il primo


def test_token_hf_sezione_llm(qt, libs, boxes):
    from utils.translations import tr
    d = make()
    d.save_hf_token()
    assert boxes[-1] == ('warning', tr('token_empty'), tr('tmd_enter_valid_token'))
    d.hf_token_input.setText('xx')
    d.save_hf_token()
    ok, err = cfg().validate_huggingface_token('xx')
    assert boxes[-1] == ('warning', tr('tmd_token_invalid_title'), tr('tmd_token_invalid_msg').format(error=err))
    d.hf_token_input.setText(f' {TOKEN} ')
    d.save_hf_token()
    assert cfg().get_huggingface_token() == TOKEN and boxes[-1] == ('information', tr('creds_saved_title'), tr('creds_saved_msg'))


def test_token_hf_sezione_diarizzazione(qt, libs, boxes):
    from utils.translations import tr
    d = make()
    assert d.diarization_token_status.text() == tr('tmd_not_configured')
    d.save_diarization_hf_token()
    assert boxes[-1] == ('warning', tr('token_empty'), tr('tmd_enter_valid_token'))
    d.diarization_hf_token_input.setText('zz')
    d.save_diarization_hf_token()
    ok, err = cfg().validate_huggingface_token('zz')
    assert boxes[-1] == ('warning', tr('tmd_token_invalid_title'), err)           # qui il messaggio e' l'errore nudo
    d.diarization_hf_token_input.setText(TOKEN)
    d.save_diarization_hf_token()
    assert cfg().get_huggingface_token() == TOKEN and d.hf_token_input.text() == TOKEN        # sincronizza l'altro campo
    assert d.diarization_token_status.text() == tr('tmd_creds_configured')
    assert boxes[-1] == ('information', tr('path_saved_title'), tr('creds_saved_msg'))


def test_stato_opensubtitles(qt, libs):
    from utils.translations import tr
    assert make().os_status_label.text() == tr('tmd_creds_not_configured')
    cfg().set('opensubtitles_username', 'u')
    cfg().set('opensubtitles_password', 'p')
    cfg().set('opensubtitles_api_key', 'k')
    d = make()
    assert d.os_status_label.text() == tr('tmd_creds_configured')
    cfg().set('opensubtitles_api_key', '')
    d.update_os_status()
    assert d.os_status_label.text() == tr('tmd_creds_not_configured')


# ---------------------------------------------------------------------------------------- diarizzazione/genere/audio
def test_interruttori_e_parlanti(qt, libs):
    d = make()
    assert (d.forced_alignment_checkbox.isChecked(), d.diarization_checkbox.isChecked(), d.diarization_num_speakers.value(),
            d.force_audio_checkbox.isChecked(), d.gender_correction_checkbox.isChecked(), d.gender_p2_checkbox.isChecked()) == \
        (False, False, 0, False, False, True)
    d.forced_alignment_checkbox.setChecked(True)
    d.diarization_checkbox.setChecked(True)
    d.diarization_num_speakers.setValue(4)
    d.force_audio_checkbox.setChecked(True)
    d.gender_correction_checkbox.setChecked(True)
    d.gender_p2_checkbox.setChecked(False)
    c = cfg()
    assert (c.get('enable_forced_alignment'), c.get('enable_diarization'), c.get('diarization_num_speakers'),
            c.get('force_audio_transcription'), c.get('gender_correction_enabled'), c.get('gender_correction_second_person')) == \
        (True, True, 4, True, True, False)
    d2 = make()
    assert d2.diarization_num_speakers.value() == 4 and d2.gender_p2_checkbox.isChecked() is False
    assert (d2.diarization_num_speakers.minimum(), d2.diarization_num_speakers.maximum()) == (0, 10)


def test_refresh_genere_senza_segnali(qt, libs, monkeypatch):
    d = make()
    cfg().set('gender_correction_enabled', True)
    writes = []
    monkeypatch.setattr(type(cfg()), 'set', lambda self, k, v, save=True: writes.append(k))
    d.refresh_from_config()
    assert d.gender_correction_checkbox.isChecked() and writes == []


def test_prerequisiti_genere(qt, libs, tmp_path):
    from utils.translations import tr
    d = make()
    assert d.gender_env_status.text() == " — ".join([tr('tmd_gender_missing_nlp'), tr('tmd_gender_missing_hf')])
    cfg().set('huggingface_token', TOKEN)
    d._update_gender_env_status()
    assert d.gender_env_status.text() == tr('tmd_gender_missing_nlp')
    py = tmp_path / 'python.exe'
    py.write_text('x')
    cfg().set('gender_selector_python', str(py))
    d._update_gender_env_status()
    assert d.gender_env_status.text() == tr('tmd_gender_prereq_ok')
    cfg().set('huggingface_token', '')
    d._update_gender_env_status()
    assert d.gender_env_status.text() == tr('tmd_gender_missing_hf')


def test_url_modello_diarizzazione(qt, libs):
    from PyQt6.QtWidgets import QLabel
    from utils.translations import tr
    d = make()
    urls = "  • huggingface.co/pyannote/speaker-diarization-3.1\n  • huggingface.co/pyannote/segmentation-3.0"
    assert tr('tmd_hf_token_howto').format(urls=urls) in [l.text() for l in d.findChildren(QLabel)]
    cfg().set('diarization_model', 'pyannote/speaker-diarization-community-1')
    d = make()
    assert tr('tmd_hf_token_howto').format(urls="  • huggingface.co/pyannote/speaker-diarization-community-1") in [l.text() for l in d.findChildren(QLabel)]


# ------------------------------------------------------------------------------- sottoprocessi (EnvCliWorker)
@pytest.fixture
def env_stub(monkeypatch):
    """Il comando `python -m core.env_check_cli <cmd>` diventa `python env_cli_stub.py <cmd>` (nessun modello)."""
    import subprocess
    real = subprocess.Popen
    seen = []

    def popen(args, *a, **k):
        seen.append((list(args), dict(k)))
        assert args[1:3] == ['-m', 'core.env_check_cli']
        k.pop('creationflags', None)                 # solo Windows: registrato sopra, non passato al vero Popen su POSIX
        return real([args[0], str(STUB), args[3]], *a, **k)
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    return seen


def wait(d, attr, qt, timeout=30):
    t0 = time.time()
    while getattr(d, attr).isRunning():
        qt.processEvents()
        assert time.time() - t0 < timeout
        time.sleep(0.02)
    getattr(d, attr).wait()
    qt.processEvents()


def test_download_llm_senza_token(qt, libs, boxes, env_stub):
    from utils.translations import tr
    d = make()
    d.start_llm_download()
    assert boxes == [('warning', tr('tmd_token_missing_title'), tr('tmd_save_hf_token_first'))] and d.download_worker is None


def test_download_llm_ok(qt, libs, boxes, env_stub):
    from utils.translations import tr
    cfg().set_huggingface_token(TOKEN)
    d = make()
    d.start_llm_download()
    assert d.llm_progress.isVisibleTo(d) and (d.llm_progress.minimum(), d.llm_progress.maximum()) == (0, 0)
    wait(d, 'download_worker', qt)
    assert not d.llm_progress.isVisibleTo(d)
    assert boxes == [('information', tr('tmd_success'), tr('tmd_download_done'))]
    args, kw = env_stub[0]
    assert args[1:] == ['-m', 'core.env_check_cli', 'llm-download'] and kw['cwd'] == str(ROOT)
    assert kw['env']['TP_SUBPROCESS'] == '1' and kw['env']['TQDM_DISABLE'] == '1' and kw['env']['PYTHONIOENCODING'] == 'utf-8'
    assert kw['creationflags'] == 0x08000000
    assert kw['bufsize'] == 1 and kw['encoding'] == 'utf-8' and kw['errors'] == 'replace' and kw['text'] is True


def test_download_llm_fallito_mostra_l_ultima_riga(qt, libs, boxes, env_stub, monkeypatch):
    from utils.translations import tr
    cfg().set_huggingface_token(TOKEN)
    monkeypatch.setenv('ENV_STUB_MODE', 'fail')
    d = make()
    d.start_llm_download()
    wait(d, 'download_worker', qt)
    assert boxes == [('critical', tr('tmd_error'), '[X] ❌ ultima riga d\'errore')]


def test_download_llm_fallito_senza_output(qt, libs, boxes, env_stub, monkeypatch):
    from utils.translations import tr
    cfg().set_huggingface_token(TOKEN)
    monkeypatch.setenv('ENV_STUB_MODE', 'silent_fail')
    d = make()
    d.start_llm_download()
    wait(d, 'download_worker', qt)
    assert boxes == [('critical', tr('tmd_error'), f"[X] {tr('tmd_load_failed')}")]


def test_download_in_corso_non_riparte(qt, libs, boxes, env_stub, monkeypatch):
    cfg().set_huggingface_token(TOKEN)
    monkeypatch.setenv('ENV_STUB_MODE', 'slow')
    d = make()
    d.start_llm_download()
    first = d.download_worker
    time.sleep(0.3)
    d.start_llm_download()
    assert d.download_worker is first and len(env_stub) == 1
    first.wait(40000)
    qt.processEvents()


def test_avvio_sottoprocesso_fallito(qt, libs, boxes, monkeypatch):
    import subprocess
    from utils.translations import tr
    cfg().set_huggingface_token(TOKEN)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
    d = make()
    d.start_llm_download()
    wait(d, 'download_worker', qt)
    assert boxes == [('critical', tr('tmd_error'), '[X] ❌ Avvio subprocess fallito: nope')]


def test_test_pyannote(qt, libs, env_stub, monkeypatch):
    from utils.translations import tr
    d = make()
    d.test_pyannote_download()                                  # senza token
    assert d.diarization_test_label.text() == tr('tmd_token_not_set_save_first') and env_stub == []
    cfg().set_huggingface_token(TOKEN)
    d.test_pyannote_download()
    assert d.diarization_test_label.text() in (tr('tmd_diar_test_started'), '⏳ scarico…', 'riga uno')
    wait(d, '_diar_test_worker', qt)
    assert d.diarization_test_label.text() == "riga uno\nriga due\nriga tre\nOK finale"       # solo le ultime 4, senza le righe di attesa
    assert env_stub[0][0][3] == 'diarization-test'
    assert 'green' in d.diarization_test_label.styleSheet().lower() or d.diarization_test_label.styleSheet() != ''


def test_test_pyannote_fallito_e_senza_output(qt, libs, env_stub, monkeypatch):
    from utils.translations import tr
    cfg().set_huggingface_token(TOKEN)
    monkeypatch.setenv('ENV_STUB_MODE', 'silent_fail')
    d = make()
    d.test_pyannote_download()
    wait(d, '_diar_test_worker', qt)
    assert d.diarization_test_label.text() == tr('tmd_no_test_output')
    ok_style = d.diarization_test_label.styleSheet()
    monkeypatch.setenv('ENV_STUB_MODE', 'ok')
    d.test_pyannote_download()
    wait(d, '_diar_test_worker', qt)
    assert d.diarization_test_label.styleSheet() != ok_style                     # rosso -> verde
