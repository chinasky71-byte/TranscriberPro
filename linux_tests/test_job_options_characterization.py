# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di JobOptionsService, SettingsService e gui/job_options_card.py::JobOptionsPanel.

Usa i NOMI VECCHI (gui.services.*): passa identica prima dello spostamento in core/services e dopo (i nomi vecchi sono alias dello
stesso modulo). Qt offscreen per il pannello, config temporaneo."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def conf(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    yield cfg.get_config()
    cfg.reset_config()


@pytest.fixture
def qt(conf, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------------------------------------ JobOptionsService
def test_summary_text():
    from gui.services.job_options_service import JobOptionsService as J
    assert J.summary_text('ita', True, True, True, True) == 'ITA · ↗ OS · ⧉ mux · ⚧ · ⏻'
    assert J.summary_text('eng', False, False, False, False) == 'ENG'
    assert J.summary_text('', False, True, False, False) == '— · ⧉ mux'
    assert J.summary_text(None, True, False, True, False) == '— · ↗ OS · ⚧'


def test_load_e_setter_su_disco(conf):
    import json
    from gui.services.job_options_service import JobOptionsService
    s = JobOptionsService(conf)
    o = s.load()
    assert (o.opensubtitles_upload, o.mux_into_video, o.gender_correction, o.shutdown_after) == (True, False, False, False)
    def disk():
        return json.loads(conf.CONFIG_FILE.read_text(encoding='utf-8'))
    s.set_opensubtitles_upload(False)
    assert disk()['opensubtitles_upload_enabled'] is False        # scrittura SINCRONA su disco
    s.set_mux_into_video(True)
    assert disk()['mux_subtitle_into_video'] is True
    s.set_gender_correction(True)
    s.set_shutdown_after(True)
    s.set_target_language('fra')
    s.set_target_language('')            # vuoto: ignorato
    s.set_target_language(None)
    on_disk = json.loads(conf.CONFIG_FILE.read_text(encoding='utf-8'))
    assert on_disk['opensubtitles_upload_enabled'] is False and on_disk['mux_subtitle_into_video'] is True
    assert on_disk['gender_correction_enabled'] is True and on_disk['shutdown_after_processing'] is True
    assert s.target_language() == 'fra' and s.load().target_language == 'fra'


def test_card_open(conf):
    from gui.services.job_options_service import JobOptionsService
    s = JobOptionsService(conf)
    assert s.card_open() is False
    s.set_card_open(True)
    assert s.card_open() is True


def test_card_open_non_solleva(conf):
    from gui.services.job_options_service import JobOptionsService

    class Boom:
        def set(self, *a, **k):
            raise OSError('x')
    JobOptionsService(Boom()).set_card_open(True)


def test_engine_short_e_ocr_label(conf):
    from gui.services.job_options_service import engine_short, ocr_review_label, defaults_summary
    from utils.translations import tr
    for model, exp in (('llm', 'TG'), ('nllb_finetuned', 'NLLB-FT'), ('nllb', 'NLLB')):
        conf.get_translation_model = lambda m=model: m
        assert engine_short(conf) == exp
    conf.get_translation_model = lambda: 'altro'
    assert engine_short(conf) == 'ALTRO'

    def boom():
        raise RuntimeError
    conf.get_translation_model = boom
    assert engine_short(conf) == '?'
    conf.set('ocr_strategy', 'auto')
    assert ocr_review_label(conf) == tr('job_ocr_mode_auto')
    conf.set('ocr_strategy', 'review')
    assert ocr_review_label(conf) == tr('job_ocr_mode_targeted')
    conf.get_translation_model = lambda: 'llm'
    conf.set('mux_subtitle_into_video', True)
    assert defaults_summary(conf).endswith(' · TG') and '⧉ mux' in defaults_summary(conf)


# --------------------------------------------------------------------------------------------------- SettingsService
def test_settings_snapshot_e_diff(conf):
    from gui.services.settings_service import SettingsService, SettingsSnapshot
    from utils.translations import tr
    s = SettingsService(conf)
    a = SettingsSnapshot('auto', 'llm', True)
    b = SettingsSnapshot('canary', 'nllb', True)
    assert s.diff_messages(a, a) == []
    assert s.diff_messages(a, b) == ['⚙️ Motore di trascrizione: Canary', tr('translation_model_changed').format(model='nllb')]
    assert s.engine_mode_label('auto') == 'Auto' and s.engine_mode_label('canary') == 'Canary'
    assert s.engine_mode_label('qwen3') == 'Qwen3-ASR' and s.engine_mode_label('boh') == 'Auto'
    conf.set('transcription_engine_mode', 'faster-whisper')
    assert s.engine_mode_label() == 'Faster-Whisper' and s.snapshot().engine_mode == 'faster-whisper'
    conf.set('opensubtitles_upload_enabled', False)
    assert s.reload_from_config().upload_enabled is False


def test_settings_profilo(conf):
    from gui.services.settings_service import SettingsService
    from utils.translations import tr
    s = SettingsService(conf)
    msg = s.select_profile('maximum')
    assert msg == f"⚙️ Profilo selezionato: {tr('profile_maximum_name')}" and s.current_profile() == 'maximum'


def test_settings_stato_interfaccia(conf):
    from gui.services.settings_service import SettingsService
    s = SettingsService(conf)
    assert s.main_splitter_sizes() is None
    s.save_main_splitter_sizes([100, 0, 5])          # una dimensione nulla: non salva
    assert s.main_splitter_sizes() is None and conf.get('ui_splitter_sizes', None) is None
    s.save_main_splitter_sizes([100, 200, 300])
    assert s.main_splitter_sizes() == [100, 200, 300]
    conf.set('ui_splitter_sizes', [1, 2])            # lunghezza sbagliata
    assert s.main_splitter_sizes() is None
    conf.set('ui_splitter_sizes', [1, 'a', 3])
    assert s.main_splitter_sizes() is None
    conf.set('ui_splitter_sizes', [1, 0, 3])
    assert s.main_splitter_sizes() is None
    assert s.center_split_sizes() is None
    s.save_center_split_sizes([4, 5])
    assert s.center_split_sizes() == [4, 5]
    assert s.scanner_card_open() is False and s.pipeline_card_open() is True
    s.set_scanner_card_open(True)
    s.set_pipeline_card_open(False)
    assert s.scanner_card_open() is True and s.pipeline_card_open() is False
    assert s.last_input_folder() == ''
    s.set_last_input_folder('/v')
    assert s.last_input_folder() == '/v'


# ------------------------------------------------------------------------------------------------------ JobOptionsPanel
def test_pannello_valori_e_scrittura(qt, conf):
    from gui.job_options_card import JobOptionsPanel, SUBTITLE_LANGUAGE_CODES
    conf.set('opensubtitles_upload_enabled', True)
    conf.set('mux_subtitle_into_video', False)
    conf.set('gender_correction_enabled', True)
    p = JobOptionsPanel()
    got = []
    p.summary_changed.connect(got.append)
    assert [p.target_lang_combo.itemData(i) for i in range(p.target_lang_combo.count())] == list(SUBTITLE_LANGUAGE_CODES)
    assert (p.opensubtitles_checkbox.isChecked(), p.mux_checkbox.isChecked(), p.gender_correction_checkbox.isChecked()) == (True, False, True)
    p.mux_checkbox.setChecked(True)
    p.opensubtitles_checkbox.setChecked(False)
    p.gender_correction_checkbox.setChecked(False)
    p.target_lang_combo.setCurrentIndex(p.target_lang_combo.findData('deu'))
    assert (conf.get('mux_subtitle_into_video'), conf.get('opensubtitles_upload_enabled'),
            conf.get('gender_correction_enabled'), conf.get_target_language()) == (True, False, False, 'deu')
    assert got[-1] == 'DEU · ⧉ mux' and len(got) == 4


def test_pannello_show_rilegge_senza_scrivere(qt, conf, monkeypatch):
    from gui.job_options_card import JobOptionsPanel
    p = JobOptionsPanel()
    conf.set('mux_subtitle_into_video', True)
    writes = []
    monkeypatch.setattr(type(conf), 'set', lambda self, k, v, save=True: writes.append(k))
    p.show()
    assert p.mux_checkbox.isChecked() and writes == []
    p.hide()


def test_pannello_pulsanti_altre_schede(qt, conf):
    from PyQt6.QtWidgets import QPushButton
    from gui.job_options_card import JobOptionsPanel
    calls = []
    p = JobOptionsPanel(go_to_tab=calls.append)
    btns = [b for b in p.findChildren(QPushButton)]
    assert len(btns) == 2 and all(b.isEnabled() for b in btns)
    for b in btns:
        b.click()
    assert calls == ['translation', 'ocr']
    assert not any(b.isEnabled() for b in JobOptionsPanel().findChildren(QPushButton))
