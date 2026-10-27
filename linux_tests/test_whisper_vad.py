# -*- coding: utf-8 -*-
"""Soglie VAD di faster-whisper: configurabili, con default invariati."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.engines.faster_whisper_engine import FasterWhisperEngine  # noqa: E402


class FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _engine(values=None):
    engine = object.__new__(FasterWhisperEngine)     # niente caricamento del modello
    engine.config = FakeConfig(values)
    return engine


def test_default_invariati():
    params = _engine()._vad_parameters()
    assert params == {"min_silence_duration_ms": 500, "threshold": 0.5}


def test_valori_dalla_config():
    params = _engine({"whisper_vad_threshold": 0.35, "whisper_vad_min_silence_ms": 300})._vad_parameters()
    assert params == {"min_silence_duration_ms": 300, "threshold": 0.35}


def test_valori_fuori_scala_vengono_limitati():
    params = _engine({"whisper_vad_threshold": 4, "whisper_vad_min_silence_ms": -50})._vad_parameters()
    assert params == {"min_silence_duration_ms": 0, "threshold": 1.0}


def test_valori_rotti_non_sollevano():
    params = _engine({"whisper_vad_threshold": "abc", "whisper_vad_min_silence_ms": None})._vad_parameters()
    assert params == {"min_silence_duration_ms": 500, "threshold": 0.5}


def test_nessuna_soglia_cablata_nell_engine():
    text = (ROOT / "core/engines/faster_whisper_engine.py").read_text(encoding="utf-8")
    assert "min_silence_duration_ms=500" not in text
    assert text.count("vad_parameters=self._vad_parameters()") == 3
