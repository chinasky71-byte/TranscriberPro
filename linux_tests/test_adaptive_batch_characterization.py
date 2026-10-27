# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/adaptive_batch_settings_widget.py.

Passa identica sul codice vecchio e su quello con la logica in core/services/adaptive_batch_service.py: valori caricati,
testo di stato, abilitazione dei controlli, chiavi scritte da Salva, valori di Ripristina. Qt offscreen, config temporaneo."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KEYS = ['adaptive_batch_enabled', 'adaptive_batch_initial_size', 'adaptive_batch_min_size', 'adaptive_batch_max_size',
        'adaptive_batch_warmup_batches', 'adaptive_batch_high_threshold', 'adaptive_batch_low_threshold']


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
    cfg.reset_config()


def cfg():
    from utils.config import get_config
    return get_config()


def make():
    from gui.adaptive_batch_settings_widget import AdaptiveBatchSettingsWidget
    return AdaptiveBatchSettingsWidget()


def values(w):
    return (w.enable_checkbox.isChecked(), w.initial_spin.value(), w.min_spin.value(), w.max_spin.value(),
            w.warmup_spin.value(), w.high_spin.value(), w.low_spin.value())


def test_carica_i_valori_del_config(qt):
    c = cfg()
    for k, v in zip(KEYS, (True, 8, 2, 32, 7, 0.9, 0.4)):
        c.set(k, v)
    w = make()
    assert values(w) == (True, 8, 2, 32, 7, 0.9, 0.4)


def test_stato_attivo_con_autodetect(qt):
    from utils.translations import tr
    c = cfg()
    c.set('adaptive_batch_enabled', True)
    c.set('adaptive_batch_initial_size', 0)
    w = make()
    cf = c.get_adaptive_batch_config()
    assert w.status_label.text() == tr('abs_active_status').format(
        initial=tr('abs_autodetect'), min=cf['min_size'], max=cf['max_size'], warmup=cf['warmup_batches'])


def test_stato_con_dimensione_iniziale(qt):
    c = cfg()
    c.set('adaptive_batch_enabled', True)
    c.set('adaptive_batch_initial_size', 12)
    assert ' 12' in make().status_label.text() or '12' in make().status_label.text()


def test_disabilitato_blocca_i_controlli(qt):
    from utils.translations import tr
    cfg().set('adaptive_batch_enabled', False)
    w = make()
    assert w.status_label.text() == tr('abs_disabled_status')
    assert not any(s.isEnabled() for s in (w.initial_spin, w.min_spin, w.max_spin, w.warmup_spin, w.high_spin, w.low_spin))
    w.enable_checkbox.setChecked(True)
    assert all(s.isEnabled() for s in (w.initial_spin, w.min_spin, w.max_spin, w.warmup_spin, w.high_spin, w.low_spin))
    assert w.status_label.text() != tr('abs_disabled_status')


def test_salva_scrive_tutte_le_chiavi_con_un_solo_save(qt, monkeypatch):
    w = make()
    w.enable_checkbox.setChecked(True)
    w.initial_spin.setValue(4)
    w.min_spin.setValue(3)
    w.max_spin.setValue(20)
    w.warmup_spin.setValue(9)
    w.high_spin.setValue(0.95)
    w.low_spin.setValue(0.25)
    c = cfg()
    writes, saves = [], []
    monkeypatch.setattr(type(c), 'set', lambda self, k, v, save=True: writes.append((k, v, save)))
    monkeypatch.setattr(type(c), 'save', lambda self: saves.append(1))
    got = []
    w.settings_changed.connect(lambda: got.append(1))
    w._save()
    assert writes == [(k, v, False) for k, v in zip(KEYS, (True, 4, 3, 20, 9, 0.95, 0.25))]
    assert saves == [1] and got == [1]


def test_ripristina_valori_di_default(qt):
    w = make()
    w.initial_spin.setValue(9)
    w.min_spin.setValue(5)
    w.max_spin.setValue(50)
    w.warmup_spin.setValue(1)
    w.high_spin.setValue(0.99)
    w.low_spin.setValue(0.7)
    w.enable_checkbox.setChecked(False)
    w._reset_defaults()
    assert values(w) == (True, 0, 1, 24, 5, 0.85, 0.6)
