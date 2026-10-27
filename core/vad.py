# -*- coding: utf-8 -*-
"""Voice activity detection with Silero, on `onnxruntime` only.

The subtitle synchroniser anchors an existing SRT to the speech in the audio; it
needs speech intervals, not a transcription. Until now it borrowed the VAD that
ships inside `faster-whisper`; with Whisper removed the model is vendored
(`core/vendor/silero/`, MIT) and driven here, because `onnxruntime` is already a
project dependency and nothing else has to be installed or downloaded.

Nothing here imports torch, ctranslate2 or faster-whisper: the module is usable in
any process.

Model contract (Silero v6): input `(n, 576)` floats = 512 new samples + the last 64
samples of the previous window as context; hidden state `h` and cell state `c`,
each `(1, 1, 128)`; output one speech probability per window.
"""
from __future__ import annotations

import sysconfig
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / "vendor" / "silero" / "silero_vad_v6.onnx"
WINDOW = 512          # samples per inference step at 16 kHz (32 ms)
CONTEXT = 64          # samples of context the model expects
STATE_SHAPE = (1, 1, 128)

_session = None


def _load_session(model_path: Optional[Path] = None):
    """One ONNX session per process (loading costs ~50 ms)."""
    global _session
    if _session is None:
        import onnxruntime as ort
        path = Path(model_path or MODEL_PATH)
        if not path.is_file():
            raise FileNotFoundError(f"Silero VAD model not found: {path}")
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        _session = ort.InferenceSession(str(path), sess_options=options,
                                        providers=["CPUExecutionProvider"])
    return _session


def speech_probabilities(audio: np.ndarray, model_path: Optional[Path] = None) -> np.ndarray:
    """Speech probability for every 512-sample window (32 ms at 16 kHz)."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)
    session = _load_session(model_path)
    state_h = np.zeros(STATE_SHAPE, dtype=np.float32)
    state_c = np.zeros(STATE_SHAPE, dtype=np.float32)
    context = np.zeros((1, CONTEXT), dtype=np.float32)
    probs: List[float] = []
    for start in range(0, samples.size, WINDOW):
        chunk = samples[start:start + WINDOW]
        if chunk.size < WINDOW:                       # last partial window
            chunk = np.pad(chunk, (0, WINDOW - chunk.size))
        model_input = np.concatenate([context, chunk.reshape(1, -1)], axis=1)
        out, state_h, state_c = session.run(None, {"input": model_input,
                                                   "h": state_h, "c": state_c})
        probs.extend(np.asarray(out, dtype=np.float32).reshape(-1).tolist())
        context = chunk.reshape(1, -1)[:, -CONTEXT:]
    return np.asarray(probs, dtype=np.float32)


def segments_from_probs(probs: np.ndarray, sampling_rate: int = 16000,
                        threshold: float = 0.5, min_speech_ms: int = 250,
                        min_silence_ms: int = 300, pad_ms: int = 100,
                        total_samples: Optional[int] = None) -> List[Dict[str, int]]:
    """Speech intervals (in samples) from per-window probabilities.

    Pure function on purpose: the segmentation is where the bugs live (padding
    beyond the end, segments shorter than the minimum, silence shorter than the
    minimum that must not split), so it is tested without the model.
    """
    if probs.size == 0:
        return []
    min_speech = sampling_rate * min_speech_ms / 1000.0
    min_silence = sampling_rate * min_silence_ms / 1000.0
    pad = sampling_rate * pad_ms / 1000.0
    limit = total_samples if total_samples is not None else int(probs.size) * WINDOW

    segments: List[Dict[str, int]] = []
    start: Optional[int] = None
    silence_run = 0
    for index, prob in enumerate(probs):
        window_start = index * WINDOW
        if prob >= threshold:
            silence_run = 0
            if start is None:
                start = window_start
            end = window_start + WINDOW
            segments.append({"start": start, "end": end})       # provisional, merged below
        elif start is not None:
            silence_run += WINDOW
            if silence_run >= min_silence:
                start = None
    # merge provisional windows into intervals separated by real silences
    merged: List[Dict[str, int]] = []
    for segment in segments:
        if merged and segment["start"] - merged[-1]["end"] < min_silence:
            merged[-1]["end"] = segment["end"]
        else:
            merged.append(dict(segment))
    result: List[Dict[str, int]] = []
    for segment in merged:
        if segment["end"] - segment["start"] < min_speech:
            continue
        start = max(0, int(segment["start"] - pad))
        end = min(int(limit), int(segment["end"] + pad))
        if end > start:
            result.append({"start": start, "end": end})
    return result


def speech_timestamps(audio: np.ndarray, sampling_rate: int = 16000,
                      model_path: Optional[Path] = None, **options) -> List[Dict[str, int]]:
    """Speech intervals (in samples) for a mono float array at `sampling_rate`."""
    if sampling_rate != 16000:
        raise ValueError("Silero VAD expects 16 kHz audio: resample before calling")
    probs = speech_probabilities(audio, model_path=model_path)
    return segments_from_probs(probs, sampling_rate,
                               total_samples=int(np.asarray(audio).size), **options)


def decode_audio(path: Path, sampling_rate: int = 16000) -> np.ndarray:
    """Mono float32 audio at `sampling_rate`, without ffmpeg or torch."""
    import soundfile as sf
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if rate != sampling_rate:
        import librosa
        mono = librosa.resample(mono, orig_sr=rate, target_sr=sampling_rate)
    return np.ascontiguousarray(mono, dtype=np.float32)


def available() -> bool:
    """True when the vendored model can be loaded (onnxruntime present)."""
    try:
        _load_session()
        return True
    except Exception:
        return False
