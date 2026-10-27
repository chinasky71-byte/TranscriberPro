# -*- coding: utf-8 -*-
"""core/vad.py: Silero su onnxruntime, senza faster-whisper."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import vad  # noqa: E402


def test_modello_vendorizzato_presente():
    assert vad.MODEL_PATH.is_file()
    assert vad.MODEL_PATH.stat().st_size > 500_000
    assert (vad.MODEL_PATH.parent / "VENDOR.md").is_file()


def test_il_modello_si_carica_e_risponde():
    probs = vad.speech_probabilities(np.zeros(16000, dtype=np.float32))
    assert probs.size == -(-16000 // vad.WINDOW)       # una probabilita' per finestra (ultima parziale)
    assert float(probs.min()) >= 0.0 and float(probs.max()) <= 1.0
    assert float(probs.max()) < 0.5                    # silenzio: nessuna voce


def test_nessun_import_di_whisper_o_torch():
    """Nessun import reale (i commenti possono nominarli per spiegare la storia)."""
    import re
    text = (ROOT / "core" / "vad.py").read_text(encoding="utf-8")
    imports = " ".join(re.findall(r"^\s*(?:from|import)\s+[^\n]+", text, re.MULTILINE))
    for forbidden in ("torch", "faster_whisper", "ctranslate2"):
        assert forbidden not in imports


def test_segmentazione_base():
    probs = np.array([0.1, 0.9, 0.9, 0.1, 0.1, 0.9, 0.9, 0.1], dtype=np.float32)
    segs = vad.segments_from_probs(probs, threshold=0.5, min_speech_ms=0,
                                   min_silence_ms=64, pad_ms=0, total_samples=8 * 512)
    assert len(segs) == 2
    assert segs[0] == {"start": 512, "end": 3 * 512}
    assert segs[1] == {"start": 5 * 512, "end": 7 * 512}


def test_pausa_corta_non_spezza_il_segmento():
    probs = np.array([0.9, 0.9, 0.1, 0.9, 0.9], dtype=np.float32)
    segs = vad.segments_from_probs(probs, threshold=0.5, min_speech_ms=0,
                                   min_silence_ms=300, pad_ms=0, total_samples=5 * 512)
    assert len(segs) == 1


def test_segmento_troppo_corto_scartato():
    probs = np.array([0.9, 0.1, 0.1, 0.1], dtype=np.float32)
    segs = vad.segments_from_probs(probs, threshold=0.5, min_speech_ms=250,
                                   min_silence_ms=64, pad_ms=0, total_samples=4 * 512)
    assert segs == []


def test_padding_non_esce_dai_limiti():
    probs = np.array([0.9, 0.9, 0.9], dtype=np.float32)
    segs = vad.segments_from_probs(probs, threshold=0.5, min_speech_ms=0,
                                   min_silence_ms=64, pad_ms=500, total_samples=3 * 512)
    assert segs[0]["start"] == 0
    assert segs[0]["end"] == 3 * 512


def test_audio_vuoto():
    assert vad.speech_probabilities(np.array([], dtype=np.float32)).size == 0
    assert vad.segments_from_probs(np.array([], dtype=np.float32)) == []


def test_richiede_16khz():
    with pytest.raises(ValueError):
        vad.speech_timestamps(np.zeros(1600, dtype=np.float32), sampling_rate=48000)


def test_decode_audio_legge_un_wav(tmp_path):
    import soundfile as sf
    tone = (0.1 * np.sin(np.linspace(0, 1000, 16000))).astype(np.float32)
    path = tmp_path / "tone.wav"
    sf.write(str(path), tone, 16000)
    decoded = vad.decode_audio(path)
    assert decoded.shape == (16000,)
    assert decoded.dtype == np.float32
