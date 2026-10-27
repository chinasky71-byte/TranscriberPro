# -*- coding: utf-8 -*-
"""G3 (fase 0 della web UI): CARATTERIZZAZIONE di gui/profile_dialog.py::ProfileSelectionDialog (scheda "Trascrizione").

Passa identica sul codice vecchio e su quello con la logica in core/services/transcription_settings_service.py: voci e selezione del
motore, salvataggio immediato, stile dei dialoghi, schede dei profili (testi, badge, avvisi), selezione in modalita' embed/standalone.
Qt offscreen, config temporaneo."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


def cfg():
    from utils.config import get_config
    return get_config()


def make(embed=True, cards=False, monkeypatch=None):
    import gui.profile_dialog as pd
    if cards:
        monkeypatch.setattr(pd, 'SHOW_PROFILE_CARDS', True)
    return pd.ProfileSelectionDialog(embed=embed)


def test_voci_del_motore(qt):
    from utils.translations import tr
    d = make()
    assert [(d.engine_combo.itemText(i), d.engine_combo.itemData(i)) for i in range(d.engine_combo.count())] == [
        (tr('engine_auto'), 'auto'), (tr('engine_canary'), 'canary'), (tr('engine_qwen3'), 'qwen3'),
        (tr('engine_whisper'), 'faster-whisper')]
    assert d.engine_combo.currentData() == 'auto'


@pytest.mark.parametrize('mode', ['auto', 'canary', 'qwen3', 'faster-whisper'])
def test_motore_salvato_selezionato_senza_scrivere(qt, mode, monkeypatch):
    cfg().set('transcription_engine_mode', mode)
    writes = []
    monkeypatch.setattr(type(cfg()), 'set', lambda self, k, v, save=True: writes.append(k))
    assert make().engine_combo.currentData() == mode and writes == []


def test_motore_sconosciuto_diventa_auto(qt):
    cfg().set('transcription_engine_mode', 'boh')
    assert make().engine_combo.currentData() == 'auto' and cfg().get('transcription_engine_mode') == 'auto'


def test_cambio_motore_scrive_subito(qt):
    d = make()
    d.engine_combo.setCurrentIndex(d.engine_combo.findData('qwen3'))
    assert cfg().get('transcription_engine_mode') == 'qwen3'
    d.engine_combo.setCurrentIndex(d.engine_combo.findData('faster-whisper'))
    assert cfg().get_transcription_engine_mode() == 'faster-whisper'
    d._on_engine_changed(-1)                     # nessun dato: ripiega su auto
    assert cfg().get('transcription_engine_mode') == 'auto'


def test_stile_dialoghi(qt):
    d = make()
    assert d.dialogue_checkbox.isChecked() is True
    d.dialogue_checkbox.setChecked(False)
    assert cfg().get('dialogue_style_enabled') is False
    cfg().set('dialogue_style_enabled', False)
    assert make().dialogue_checkbox.isChecked() is False
    d.dialogue_checkbox.setChecked(True)
    assert cfg().get('dialogue_style_enabled') is True


def test_schede_nascoste_di_default(qt):
    from PyQt6.QtWidgets import QRadioButton
    d = make()
    assert d.findChildren(QRadioButton) == []


@pytest.mark.parametrize('f,exp', [(1.0, '100%'), (1.5, '+50%'), (1.2, '+19%'), (0.8, '-19%'), (0.5, '-50%'), (2.0, '+100%')])
def test_formato_velocita(qt, f, exp):
    assert make()._format_speed(f) == exp


def test_schede_dei_profili(qt, monkeypatch):
    from PyQt6.QtWidgets import QLabel, QRadioButton
    from utils.config import Config
    from utils.transcription_profiles import ProfileConfig, TranscriptionProfile
    from utils.translations import tr
    cfg().set('transcription_profile_locked', False)
    cfg().set('transcription_profile', 'quality')
    d = make(embed=True, cards=True, monkeypatch=monkeypatch)
    radios = d.findChildren(QRadioButton)
    assert [r.property('profile') for r in radios] == [p.value for p in TranscriptionProfile]
    assert [r.property('profile') for r in radios if r.isChecked()] == ['quality']
    texts = {l.objectName(): [] for l in d.findChildren(QLabel)}
    for l in d.findChildren(QLabel):
        texts[l.objectName()].append(l.text())
    assert texts['recommendedBadge'] == [tr('recommended')]
    for p in TranscriptionProfile:
        c = ProfileConfig.get_profile_config(p)
        assert f"<b>{tr(f'profile_{p.value}_name')}</b>" in texts['profileName']
        assert tr(f'profile_{p.value}_desc') in texts['profileDesc']
        params = (f"⚙️ Whisper · W:{c['num_workers']} | 🎯 B:{c['beam_size']} | ⚡ {d._format_speed(c['speed_factor'])} | ✨ {c['quality_percent']:.0f}%")
        assert params in texts['profileParams']
        assert f"⏱️ ~{c['time_1h_audio_min']}min/h" in texts['profileTime']
        if 'warning' in c:
            assert f"⚠️ {tr(f'profile_{p.value}_warning')}" in texts['profileWarning']
    assert len(texts.get('profileWarning', [])) == sum(1 for p in TranscriptionProfile if 'warning' in ProfileConfig.get_profile_config(p))


def test_selezione_profilo_embed_scrive_standalone_no(qt, monkeypatch):
    from PyQt6.QtWidgets import QRadioButton
    cfg().set('transcription_profile_locked', False)
    cfg().set('transcription_profile', 'balanced')
    d = make(embed=True, cards=True, monkeypatch=monkeypatch)
    r = next(x for x in d.findChildren(QRadioButton) if x.property('profile') == 'fast')
    r.setChecked(True)
    assert d.get_selected_profile() == 'fast' and cfg().get('transcription_profile') == 'fast'
    s = make(embed=False, cards=True, monkeypatch=monkeypatch)
    r2 = next(x for x in s.findChildren(QRadioButton) if x.property('profile') == 'maximum')
    r2.setChecked(True)
    assert s.get_selected_profile() == 'maximum' and cfg().get('transcription_profile') == 'fast'    # standalone: non scrive
    s.on_profile_toggled('quality', False)
    assert s.get_selected_profile() == 'maximum'


def test_profilo_bloccato_resta_maximum(qt):
    cfg().set('transcription_profile_locked', True)
    assert make().get_selected_profile() == 'maximum'


def test_modalita_standalone_ha_titolo_e_pulsanti(qt):
    from PyQt6.QtWidgets import QPushButton
    from utils.translations import tr
    d = make(embed=False)
    assert d.windowTitle() == tr('profiles_title') and d.isModal()
    assert sorted(b.text() for b in d.findChildren(QPushButton)) == sorted([tr('cancel'), tr('confirm')])
    assert make(embed=True).findChildren(QPushButton) == []


def test_badge_solo_sul_profilo_bilanciato(qt):
    from core.services.transcription_settings_service import profile_cards
    from utils.translations import tr
    badges = {c.value: c.recommended_badge for c in profile_cards()}
    assert badges.pop('balanced') == tr('recommended') and set(badges.values()) == {None}
