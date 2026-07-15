# -*- coding: utf-8 -*-
"""
Speaker Gender Map — Fase 1 del redesign Gender Corrector.
File: core/speaker_gender.py

Costruisce una mappa tempo→(speaker, genere, confidenza) dall'audio:
  1. estrae l'audio del video (traccia originale, 16 kHz mono) con ffmpeg;
  2. diarization con pyannote (riusa core/diarizer.Diarizer);
  3. per ogni cluster speaker: classifica il genere della voce sui segmenti
     più lunghi con ECAPA-TDNN (core/ecapa_gender, VoxCeleb2, ~98% acc)
     e aggrega le probabilità → genere + confidenza per speaker.

La mappa risponde a `gender_for_range(start, end)` → ('F'|'M'|None, conf):
None = UNKNOWN (nessun parlante, o confidenza sotto soglia) → il chiamante
NON deve toccare la riga (principio di prudenza nel codice, non nel prompt).

Nessuna dipendenza Qt: usabile da pipeline (subprocess) e da script headless.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)

# Parametri classificazione per-cluster
MAX_SEGMENTS_PER_SPEAKER = 12    # quanti segmenti (i più lunghi) classificare
MIN_SEGMENT_SEC = 1.0            # segmenti più corti sono inaffidabili
MAX_SEGMENT_SEC = 8.0            # clip: oltre non aggiunge informazione
DEFAULT_CONF_THRESHOLD = 0.75    # sotto → UNKNOWN

_CREATE_NO_WINDOW = 0x08000000   # Windows: niente flash di console


@dataclass
class SpeakerGender:
    speaker: str
    gender: Optional[str]          # 'F' | 'M' | None
    confidence: float              # probabilità media della classe vincente
    n_segments: int                # segmenti classificati
    speech_time: float             # secondi totali di parlato del cluster


@dataclass
class SpeakerGenderMap:
    """Risultato: turni diarization + genere per speaker."""
    turns: List[Tuple[float, float, str]]           # (start, end, speaker)
    speakers: Dict[str, SpeakerGender] = field(default_factory=dict)
    conf_threshold: float = DEFAULT_CONF_THRESHOLD

    def gender_of(self, speaker: str) -> Tuple[Optional[str], float]:
        sg = self.speakers.get(speaker)
        if sg is None or sg.gender is None:
            return None, 0.0
        if sg.confidence < self.conf_threshold:
            return None, sg.confidence
        return sg.gender, sg.confidence

    def speaker_for_range(self, start: float, end: float) -> Optional[str]:
        """Speaker con massimo overlap temporale nell'intervallo, o None."""
        overlap: Dict[str, float] = {}
        for t_start, t_end, spk in self.turns:
            if t_end <= start:
                continue
            if t_start >= end:
                break
            ov = min(end, t_end) - max(start, t_start)
            if ov > 0:
                overlap[spk] = overlap.get(spk, 0.0) + ov
        if not overlap:
            return None
        return max(overlap, key=overlap.get)

    def gender_for_range(self, start: float, end: float) -> Tuple[Optional[str], float]:
        """Genere del parlante dominante nell'intervallo. (None, 0) = UNKNOWN."""
        spk = self.speaker_for_range(start, end)
        if spk is None:
            return None, 0.0
        return self.gender_of(spk)

    def to_json(self) -> str:
        return json.dumps({
            'turns': self.turns,
            'speakers': {k: {'gender': v.gender, 'confidence': v.confidence,
                             'n_segments': v.n_segments, 'speech_time': v.speech_time}
                         for k, v in self.speakers.items()},
            'conf_threshold': self.conf_threshold,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> 'SpeakerGenderMap':
        d = json.loads(text)
        m = cls(turns=[tuple(t) for t in d['turns']],
                conf_threshold=d.get('conf_threshold', DEFAULT_CONF_THRESHOLD))
        for k, v in d['speakers'].items():
            m.speakers[k] = SpeakerGender(
                speaker=k, gender=v['gender'], confidence=v['confidence'],
                n_segments=v['n_segments'], speech_time=v['speech_time'])
        return m


class SpeakerGenderMapper:
    """Orchestrazione: audio → diarization → genere per cluster."""

    def __init__(self, hf_token: str, log_callback: Optional[Callable] = None,
                 conf_threshold: float = DEFAULT_CONF_THRESHOLD):
        self.hf_token = hf_token
        self.log = log_callback or (lambda m: None)
        self.conf_threshold = conf_threshold
        self._gender_model = None
        self._device = None

    # ── Audio ────────────────────────────────────────────────────────────

    def extract_audio(self, media_path: str, out_wav: Path,
                      language: Optional[str] = None) -> Path:
        """Estrae la traccia audio in WAV 16 kHz mono. Se `language` è
        indicata (es. 'eng') seleziona quella traccia, altrimenti la prima."""
        stream = f'0:a:m:language:{language}' if language else '0:a:0'
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', media_path,
               '-map', stream, '-ac', '1', '-ar', '16000',
               '-vn', str(out_wav)]
        try:
            subprocess.run(cmd, check=True, timeout=1800,
                           creationflags=_CREATE_NO_WINDOW)
        except subprocess.CalledProcessError:
            if language:  # fallback: prima traccia audio
                self.log(f"  ⚠️ Traccia '{language}' non trovata, uso la prima")
                return self.extract_audio(media_path, out_wav, language=None)
            raise
        return out_wav

    # ── Modello genere ───────────────────────────────────────────────────

    def _load_gender_model(self):
        if self._gender_model is not None:
            return
        import torch
        from core.ecapa_gender import ECAPA_gender
        self.log("  📦 Caricamento modello genere voce (ECAPA VoxCeleb2)...")
        self._gender_model = ECAPA_gender.from_pretrained(
            "JaesungHuh/voice-gender-classifier")
        self._gender_model.eval()
        self._device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu")
        self._gender_model.to(self._device)

    def _classify_segments(self, waveform, sample_rate: int,
                           segments: List[Tuple[float, float]]) -> List[Tuple[str, float]]:
        """Classifica una lista di (start, end) sec. Ritorna [(label, prob), ...]."""
        import torch
        results = []
        for (s, e) in segments:
            i0 = int(s * sample_rate)
            i1 = int(min(e, s + MAX_SEGMENT_SEC) * sample_rate)
            clip = waveform[:, i0:i1]
            if clip.shape[1] < int(MIN_SEGMENT_SEC * sample_rate):
                continue
            with torch.no_grad():
                logits = self._gender_model(clip.to(self._device))
                probs = torch.softmax(logits, dim=1)[0]
            p_male, p_female = probs[0].item(), probs[1].item()
            if p_female >= p_male:
                results.append(('F', p_female))
            else:
                results.append(('M', p_male))
        return results

    # ── Costruzione mappa ────────────────────────────────────────────────

    def build_map(self, media_path: str, num_speakers: int = 0,
                  diarization: Optional[List[Tuple[float, float, str]]] = None,
                  audio_language: str = 'eng') -> SpeakerGenderMap:
        """Costruisce la SpeakerGenderMap per un file video/audio.

        `diarization` opzionale: se la pipeline l'ha già calcolata (STEP
        trascrizione) viene riusata, saltando il passo pyannote.
        """
        import torch
        import torchaudio

        with tempfile.TemporaryDirectory(prefix="spkgender_") as td:
            wav = Path(td) / "audio.wav"
            src = Path(media_path)
            if src.suffix.lower() in ('.wav', '.flac'):
                wav = src
            else:
                self.log("  🎧 Estrazione audio (16 kHz mono)...")
                self.extract_audio(str(src), wav, language=audio_language)

            # Diarization (riuso o calcolo)
            if diarization is None:
                from core.diarizer import Diarizer
                diar = Diarizer(self.hf_token, log_callback=self.log)
                diar.load()
                try:
                    diarization = diar.diarize(str(wav), num_speakers=num_speakers)
                finally:
                    diar.unload()

            turns = sorted(diarization, key=lambda t: t[0])

            # Waveform completa in RAM (16 kHz mono ≈ 5 MB/min: ok)
            waveform, sr = torchaudio.load(str(wav))

            self._load_gender_model()

            # Genere per cluster
            gmap = SpeakerGenderMap(turns=turns, conf_threshold=self.conf_threshold)
            by_speaker: Dict[str, List[Tuple[float, float]]] = {}
            for (s, e, spk) in turns:
                by_speaker.setdefault(spk, []).append((s, e))

            for spk, segs in by_speaker.items():
                speech_time = sum(e - s for s, e in segs)
                # i segmenti più lunghi sono i più affidabili
                best = sorted(segs, key=lambda x: x[1] - x[0], reverse=True)
                best = [x for x in best if x[1] - x[0] >= MIN_SEGMENT_SEC]
                best = best[:MAX_SEGMENTS_PER_SPEAKER]
                votes = self._classify_segments(waveform, sr, best)
                if not votes:
                    gmap.speakers[spk] = SpeakerGender(spk, None, 0.0, 0, speech_time)
                    continue
                # aggregazione: media delle probabilità per classe
                p_f = sum(p for g, p in votes if g == 'F') + \
                    sum(1 - p for g, p in votes if g == 'M')
                p_f /= len(votes)
                gender = 'F' if p_f >= 0.5 else 'M'
                conf = p_f if gender == 'F' else 1 - p_f
                gmap.speakers[spk] = SpeakerGender(
                    spk, gender, conf, len(votes), speech_time)

            n_f = sum(1 for v in gmap.speakers.values() if v.gender == 'F'
                      and v.confidence >= self.conf_threshold)
            n_m = sum(1 for v in gmap.speakers.values() if v.gender == 'M'
                      and v.confidence >= self.conf_threshold)
            n_u = len(gmap.speakers) - n_f - n_m
            self.log(f"  🎭 Genere parlanti: {n_f} F, {n_m} M, {n_u} incerti "
                     f"(soglia {self.conf_threshold:.2f})")
            return gmap

    def cleanup(self):
        if self._gender_model is not None:
            del self._gender_model
            self._gender_model = None
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
