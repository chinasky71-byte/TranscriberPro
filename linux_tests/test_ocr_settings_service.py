# -*- coding: utf-8 -*-
"""core/services/ocr_settings_service.py: logica delle impostazioni OCR, senza Qt (copre cio' che il widget maschera con i limiti dei suoi spin)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import pgs_types as P
from core.services.ocr_settings_service import OcrSettingsService


class Cfg(dict):
    def set(self, k, v):
        self[k] = v


def test_limiti_e_default():
    c = Cfg()
    s = OcrSettingsService(c)
    for k, raw, soglia, workers in [(0, -5, 0, 0), (1, 150, 100, 0), (2, 'x', P.DEFAULT_CONF_THRESHOLD, 0)]:
        c[P.CFG_CONF_THRESHOLD] = raw
        c[P.CFG_OCR_WORKERS] = {0: -3, 1: 99, 2: None}[k]
        v = s.load()
        assert v.conf_threshold == soglia
        assert v.workers == {0: 0, 1: 32, 2: P.DEFAULT_OCR_WORKERS}[k]


def test_writeback_e_strategia():
    c = Cfg()
    s = OcrSettingsService(c)
    c[P.CFG_WRITEBACK] = 'boh'
    assert s.load().writeback == 'boh'
    assert s.load([P.WRITEBACK_MUX, P.WRITEBACK_SIDECAR]).writeback == P.DEFAULT_WRITEBACK
    assert s.set_writeback(None) == P.DEFAULT_WRITEBACK and c[P.CFG_WRITEBACK] == P.DEFAULT_WRITEBACK
    c[P.CFG_STRATEGY] = 'qualunque'
    assert s.load().strategy == P.STRATEGY_REVIEW
    assert s.set_strategy(False) == P.STRATEGY_AUTO and c[P.CFG_STRATEGY] == P.STRATEGY_AUTO


def test_testi_tagliati():
    c = Cfg()
    s = OcrSettingsService(c)
    assert s.set_tesseract_path('  /x ') == '/x' and c[P.CFG_TESSERACT_PATH] == '/x'
    assert s.set_language('   ') == P.DEFAULT_LANGUAGE
    assert s.set_language(' eng ') == 'eng'
    assert s.load().tesseract_path == '/x'
