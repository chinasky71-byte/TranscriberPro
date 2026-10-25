# -*- coding: utf-8 -*-
"""core.lang_vote: scelta dei chunk da sondare e voto di lingua (puro, senza modelli)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import lang_vote as LV  # noqa: E402


def test_spread_indices():
    assert LV.spread_indices(0, 5) == []
    assert LV.spread_indices(3, 5) == [0, 1, 2]
    idx = LV.spread_indices(180, 5)
    assert len(idx) == 5 and idx == sorted(idx) and idx[0] > 0 and idx[-1] < 179


def test_select_skips_unvoiced_chunks():
    paths = list(range(60))
    voiced = {i for i in paths if i >= 30}
    sel = LV.select_probe_chunks(paths, 5, voice_s_fn=lambda p: 10.0 if p in voiced else 0.0)
    assert sel and all(i in voiced for i in sel) and len(sel) <= 5


def test_select_falls_back_when_no_voice_or_errors():
    paths = list(range(20))
    assert LV.select_probe_chunks(paths, 5, voice_s_fn=lambda p: 0.0) == LV.spread_indices(20, 5)

    def boom(p):
        raise OSError

    assert LV.select_probe_chunks(paths, 5, voice_s_fn=boom) == LV.spread_indices(20, 5)


def test_vote_majority_beats_single_wrong_probe():
    assert LV.vote([('nn', 0.5), ('it', 0.95), ('it', 0.9), ('it', 0.8)])[0] == 'it'


def test_vote_merges_nn_into_no():
    assert LV.vote([('nn', 0.6), ('no', 0.5), ('sv', 0.7)])[0] == 'no'


def test_vote_ignores_empty_and_low_confidence():
    assert LV.vote([('', 0.9), (None, 0.9), ('nn', 0.2)]) == (None, 0.0)
    assert LV.vote([]) == (None, 0.0)


def test_module_has_no_heavy_imports():
    code = ("import sys; import core.lang_vote; "
            "bad=[m for m in ('torch','onnxruntime','PyQt6') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, '-c', code], cwd=ROOT).returncode == 0
