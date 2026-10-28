# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/ocr_settings_widget.py::OcrSettingsWidget.

Passa identica sul codice vecchio e su quello con la logica in core/services/ocr_settings_service.py: normalizzazione dei valori
letti dal config, chiavi scritte da ogni controllo, segnale settings_changed. Qt offscreen, config temporaneo."""
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
    cfg.reset_config()


def cfg():
    from utils.config import get_config
    return get_config()


def make():
    from gui.ocr_settings_widget import OcrSettingsWidget
    w = OcrSettingsWidget()
    w.emitted = []
    w.settings_changed.connect(lambda: w.emitted.append(1))
    return w


def state(w):
    return (w.review_radio.isChecked(), w.auto_radio.isChecked(), w.language_input.text(), w.conf_spin.value(),
            w.workers_spin.value(), w.writeback_combo.currentData(), w.tesseract_input.text())


def test_default(qt):
    from core import pgs_types as P
    w = make()
    assert state(w) == (P.DEFAULT_STRATEGY != P.STRATEGY_AUTO, P.DEFAULT_STRATEGY == P.STRATEGY_AUTO, P.DEFAULT_LANGUAGE,
                        P.DEFAULT_CONF_THRESHOLD, P.DEFAULT_OCR_WORKERS, P.DEFAULT_WRITEBACK, '')


def test_carica_valori_salvati(qt):
    from core import pgs_types as P
    c = cfg()
    c.set(P.CFG_STRATEGY, P.STRATEGY_AUTO)
    c.set(P.CFG_LANGUAGE, 'eng+ita')
    c.set(P.CFG_CONF_THRESHOLD, 55)
    c.set(P.CFG_OCR_WORKERS, 6)
    c.set(P.CFG_WRITEBACK, P.WRITEBACK_SIDECAR)
    c.set(P.CFG_TESSERACT_PATH, '/usr/bin/tesseract')
    assert state(make()) == (False, True, 'eng+ita', 55, 6, P.WRITEBACK_SIDECAR, '/usr/bin/tesseract')


@pytest.mark.parametrize('raw,exp', [('77', 77), (150, 100), (-5, 0), ('x', None), (None, None)])
def test_soglia_normalizzata(qt, raw, exp):
    from core import pgs_types as P
    cfg().set(P.CFG_CONF_THRESHOLD, raw)
    assert make().conf_spin.value() == (P.DEFAULT_CONF_THRESHOLD if exp is None else exp)


@pytest.mark.parametrize('raw,exp', [('4', 4), (99, 32), (-1, 0), ('x', None), (None, None)])
def test_worker_normalizzati(qt, raw, exp):
    from core import pgs_types as P
    cfg().set(P.CFG_OCR_WORKERS, raw)
    assert make().workers_spin.value() == (P.DEFAULT_OCR_WORKERS if exp is None else min(32, max(0, exp)))


def test_lingua_vuota_e_writeback_sconosciuto(qt):
    from core import pgs_types as P
    c = cfg()
    c.set(P.CFG_LANGUAGE, '')
    c.set(P.CFG_WRITEBACK, 'boh')
    w = make()
    assert w.language_input.text() == P.DEFAULT_LANGUAGE and w.writeback_combo.currentData() == P.DEFAULT_WRITEBACK


def test_scrittura_dai_controlli(qt):
    from core import pgs_types as P
    w = make()
    c = cfg()
    (w.auto_radio if w.review_radio.isChecked() else w.review_radio).setChecked(True)
    after = P.STRATEGY_REVIEW if w.review_radio.isChecked() else P.STRATEGY_AUTO
    assert c.get(P.CFG_STRATEGY) == after
    w.language_input.setText('  fra ')
    w.language_input.editingFinished.emit()
    assert c.get(P.CFG_LANGUAGE) == 'fra'
    w.language_input.setText('   ')
    w.language_input.editingFinished.emit()
    assert c.get(P.CFG_LANGUAGE) == P.DEFAULT_LANGUAGE
    w.conf_spin.setValue(33)
    assert c.get(P.CFG_CONF_THRESHOLD) == 33
    w.workers_spin.setValue(7)
    assert c.get(P.CFG_OCR_WORKERS) == 7
    w.writeback_combo.setCurrentIndex(1 - w.writeback_combo.currentIndex())
    assert c.get(P.CFG_WRITEBACK) == w.writeback_combo.currentData()
    w.tesseract_input.setText(' /opt/t ')
    w.tesseract_input.editingFinished.emit()
    assert c.get(P.CFG_TESSERACT_PATH) == '/opt/t'
    assert len(w.emitted) >= 7


def test_caricamento_non_emette_ne_scrive(qt, monkeypatch):
    c = cfg()
    writes = []
    monkeypatch.setattr(type(c), 'set', lambda self, k, v, save=True: writes.append(k))
    w = make()
    w.update_status()
    assert writes == [] and w.emitted == []
