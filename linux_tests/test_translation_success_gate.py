# -*- coding: utf-8 -*-
"""Criterio di successo della traduzione (falso positivo corretto il 24/10/2026).

`translate_file` ritornava True anche quando OGNI batch falliva e tutti i
blocchi restavano in lingua originale (osservato su AMD/ROCm: HIP error su
tutti i batch, 41/46 righe in inglese, exit 0). Ora:
  - un errore GPU fatale interrompe subito (return False);
  - troppi blocchi non tradotti (> translation_max_untranslated_pct,
    default 80%) rendono la traduzione fallita.

Esecuzione (dalla radice):  python -m pytest linux_tests/test_translation_success_gate.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.translator as translator_mod  # noqa: E402
from core.translator import BaseTranslator, NLLBTranslator  # noqa: E402

SRT = """1
00:00:01,000 --> 00:00:03,000
Good morning, everyone.

2
00:00:03,500 --> 00:00:05,000
What's going on?

3
00:00:05,500 --> 00:00:07,000
We lost the account.

"""


class _Dummy(BaseTranslator):
    def translate_file(self, *a, **k):        # pragma: no cover - solo per istanziare
        return True

    def cleanup(self):                         # pragma: no cover
        pass


class _Cfg:
    """Config minimale per il criterio (nessun file scritto)."""

    def __init__(self, limit):
        self._limit = limit

    def get(self, key, default=None):
        if key == 'translation_max_untranslated_pct':
            return self._limit
        return default


@pytest.fixture
def dummy(monkeypatch):
    import utils.config as cfg_mod
    monkeypatch.setattr(cfg_mod, 'get_config', lambda: _Cfg(80.0))
    return _Dummy()


@pytest.fixture
def nllb(monkeypatch):
    """NLLBTranslator senza caricare il modello (13 GB) ne' la GPU."""
    import utils.config as cfg_mod
    monkeypatch.setattr(cfg_mod, 'get_config', lambda: _Cfg(80.0))
    monkeypatch.setattr(translator_mod, '_get_nllb_translator_resources',
                        lambda: (None, None, 'cpu'))
    t = NLLBTranslator(log_callback=None)
    t.use_gpu = False
    monkeypatch.setattr(t, '_reservoir_translate', lambda mapping: {})
    return t


def test_marker_errori_gpu_fatali(dummy):
    assert dummy._is_fatal_gpu_error(RuntimeError('HIP error: invalid device function'))
    assert dummy._is_fatal_gpu_error(RuntimeError('CUDA error: an illegal memory access'))
    assert dummy._is_fatal_gpu_error(RuntimeError('device-side assert triggered'))
    assert dummy._is_fatal_gpu_error(RuntimeError('no kernel image is available'))
    assert not dummy._is_fatal_gpu_error(RuntimeError('timeout di rete'))
    assert not dummy._is_fatal_gpu_error(RuntimeError('SRT vuoto'))


def test_soglia_errore_default_80(dummy):
    assert dummy._max_untranslated_pct() == 80.0
    # 80/100 = esattamente al limite: non fallisce (si fallisce solo se SUPERIORE)
    assert dummy._translation_exceeds_error_budget(80, 100) is False
    assert dummy._translation_exceeds_error_budget(81, 100) is True
    assert dummy._translation_exceeds_error_budget(46, 46) is True


def test_soglia_configurabile(monkeypatch):
    import utils.config as cfg_mod
    monkeypatch.setattr(cfg_mod, 'get_config', lambda: _Cfg(20.0))
    d = _Dummy()
    assert d._max_untranslated_pct() == 20.0
    assert d._translation_exceeds_error_budget(21, 100) is True
    assert d._translation_exceeds_error_budget(20, 100) is False


def test_errore_gpu_fatale_fa_fallire_il_file(nllb, tmp_path, monkeypatch):
    src = tmp_path / 'in.srt'
    src.write_text(SRT, encoding='utf-8')
    out = tmp_path / 'out.srt'

    def _boom(*a, **k):
        raise RuntimeError('HIP error: invalid device function')

    monkeypatch.setattr(nllb, '_run_translation', _boom)
    assert nllb.translate_file(src, out, 'eng', 'ita') is False
    assert not out.exists()      # nessun file spacciato per tradotto


def test_tutti_i_blocchi_non_tradotti_fa_fallire(nllb, tmp_path, monkeypatch):
    src = tmp_path / 'in.srt'
    src.write_text(SRT, encoding='utf-8')
    out = tmp_path / 'out.srt'

    # Il traduttore "restituisce" il testo sorgente: e' cio' che succede
    # quando ogni batch viene saltato e si rimettono gli originali.
    monkeypatch.setattr(nllb, '_run_translation',
                        lambda texts, *a, **k: list(texts))
    assert nllb.translate_file(src, out, 'eng', 'ita') is False
    assert not out.exists()


def test_traduzione_completa_resta_un_successo(nllb, tmp_path, monkeypatch):
    src = tmp_path / 'in.srt'
    src.write_text(SRT, encoding='utf-8')
    out = tmp_path / 'out.srt'

    monkeypatch.setattr(nllb, '_run_translation',
                        lambda texts, *a, **k: ['Buongiorno a tutti voi.'] * len(texts))
    assert nllb.translate_file(src, out, 'eng', 'ita') is True
    assert out.exists() and 'Buongiorno' in out.read_text(encoding='utf-8')


def test_nllb_device_map_solo_su_rocm():
    """Su CUDA resta 'auto' (offload CPU del ramo 8-bit); {'': 0} solo con HIP."""
    import torch
    expected = ({'': 0} if translator_mod._use_gpu
                and getattr(torch.version, 'hip', None) else 'auto')
    assert translator_mod._NLLB_DEVICE_MAP == expected


def test_ct2_bootstrap_noop_fuori_da_linux(monkeypatch):
    import utils.ct2_bootstrap as b
    monkeypatch.setattr(b, '_done', False)
    monkeypatch.setattr(b.sys, 'platform', 'win32')
    assert b.ensure_ct2_initialized() is False
