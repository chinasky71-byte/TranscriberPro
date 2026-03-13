"""
Speaker Diarizer
File: core/diarizer.py

Integra pyannote.audio per identificare i parlanti in un file audio
e assegnare il campo 'speaker' a ogni segmento Whisper.

Word-level alignment: se il segmento ha word timestamps (BatchedInferencePipeline),
il segmento viene diviso ai confini esatti di cambio parlante, rilevando cambi
anche all'interno di un singolo segmento Whisper.
"""
from __future__ import annotations
import torch
from typing import List, Tuple, Dict, Optional, Callable


class Diarizer:
    def __init__(self, hf_token: str, log_callback: Optional[Callable] = None):
        self.hf_token = hf_token
        self.log = log_callback or print
        self._pipeline = None

    def load(self) -> None:
        import warnings
        # Sopprimi warning noti e non azionabili
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")               # torchcodec
        warnings.filterwarnings("ignore", module=r"torchaudio\._backend\.utils")             # torchaudio 2.9 deprecation
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.utils\.reproducibility") # TF32
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.models\.blocks\.pooling") # std() on short audio
        warnings.filterwarnings("ignore", message=r".*speechbrain\.pretrained.*")            # speechbrain 1.0 module redirect

        # Salva stato TF32 prima che pyannote lo disabiliti
        self._tf32_matmul = torch.backends.cuda.matmul.allow_tf32
        self._tf32_cudnn  = torch.backends.cudnn.allow_tf32

        from pyannote.audio import Pipeline
        self.log("  📦 Caricamento modello pyannote speaker-diarization-3.1...")
        self._pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=self.hf_token
        )
        if torch.cuda.is_available():
            self._pipeline = self._pipeline.to(torch.device("cuda"))
            self.log("  ✅ Diarizer caricato su CUDA")
        else:
            self.log("  ✅ Diarizer caricato su CPU")

    def diarize(self, audio_path: str, num_speakers: int = 0) -> List[Tuple[float, float, str]]:
        """Restituisce lista di (start, end, speaker_id).

        Pre-carica l'audio con torchaudio per evitare dipendenza da torchcodec.
        """
        import torchaudio
        waveform, sample_rate = torchaudio.load(audio_path)
        audio_input = {'waveform': waveform, 'sample_rate': sample_rate}

        kwargs = {}
        if num_speakers > 0:
            kwargs['num_speakers'] = num_speakers
        output = self._pipeline(audio_input, **kwargs)
        # pyannote 4.x: DiarizeOutput con .speaker_diarization; 3.x: Annotation diretta
        annotation = getattr(output, 'speaker_diarization', output)
        result = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            result.append((turn.start, turn.end, speaker))
        unique_speakers = len(set(s for _, _, s in result))
        self.log(f"  🎭 Trovati {unique_speakers} parlanti, {len(result)} turni")
        return result

    # ── Assegnazione speaker ──────────────────────────────────────────────────

    def assign_speakers(
        self,
        segments: List[Dict],
        diarization: List[Tuple[float, float, str]]
    ) -> List[Dict]:
        """Assegna il campo 'speaker' a ogni segmento Whisper.

        Se il segmento ha word timestamps (BatchedInferencePipeline), usa
        l'allineamento word-level: divide il segmento ai confini di cambio
        parlante, creando sotto-segmenti separati per ogni speaker.

        Altrimenti fallback a overlap massimo sull'intero segmento.
        """
        result = []
        for seg in segments:
            words = seg.get('words', [])
            if not words:
                self._assign_segment_speaker(seg, diarization)
                result.append(seg)
            else:
                sub_segs = self._split_at_speaker_changes(seg, words, diarization)
                result.extend(sub_segs)
        self.log(f"  📝 Segmenti dopo word-level alignment: {len(result)}")
        return result

    def _assign_segment_speaker(
        self, seg: Dict, diarization: List[Tuple[float, float, str]]
    ) -> None:
        """Assegna speaker per overlap massimo (in-place). Fallback senza words."""
        seg_start, seg_end = seg['start'], seg['end']
        overlap_by_speaker: Dict[str, float] = {}
        for d_start, d_end, speaker in diarization:
            overlap = min(seg_end, d_end) - max(seg_start, d_start)
            if overlap > 0:
                overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0) + overlap
        if overlap_by_speaker:
            seg['speaker'] = max(overlap_by_speaker, key=overlap_by_speaker.get)

    def _get_speaker_at(
        self, timestamp: float, diarization: List[Tuple[float, float, str]]
    ) -> Optional[str]:
        """Trova il parlante attivo a un dato timestamp. None = silenzio/pausa."""
        for d_start, d_end, speaker in diarization:
            if d_start <= timestamp <= d_end:
                return speaker
        return None

    def _split_at_speaker_changes(
        self,
        seg: Dict,
        words: List[Dict],
        diarization: List[Tuple[float, float, str]],
        min_words_per_turn: int = 3,
    ) -> List[Dict]:
        """Divide un segmento in sotto-segmenti ai confini di cambio parlante.

        Algoritmo run-based con soglia minima:
        1. Assegna speaker a ogni parola (midpoint)
        2. Riempi silenzi (None) con speaker precedente/successivo
        3. Identifica run consecutive di stesso speaker
        4. Fonde run troppo corte (< min_words_per_turn) nella run precedente
           → previene falsi split su singole parole tipo "Va", "Sì", "No"
        5. Crea sotto-segmenti solo per le run rimanenti
        """
        if not words:
            return [seg]

        # Passo 1: speaker per ogni parola
        word_speakers: List[Optional[str]] = []
        for word in words:
            w_mid = (word['start'] + word['end']) / 2
            word_speakers.append(self._get_speaker_at(w_mid, diarization))

        # Passo 2a: fill in avanti (silenzi ereditano speaker precedente)
        current: Optional[str] = None
        for i, sp in enumerate(word_speakers):
            if sp is not None:
                current = sp
            elif current is not None:
                word_speakers[i] = current

        # Passo 2b: fill indietro per silenzi iniziali
        last: Optional[str] = None
        for i in range(len(word_speakers) - 1, -1, -1):
            if word_speakers[i] is not None:
                last = word_speakers[i]
            elif last is not None:
                word_speakers[i] = last

        # Passo 3: identifica run (sequenze di parole stesso speaker)
        runs: List[Tuple[int, int, Optional[str]]] = []  # (start_idx, end_idx, speaker)
        run_start = 0
        run_spk = word_speakers[0]
        for i in range(1, len(word_speakers)):
            if word_speakers[i] != run_spk:
                runs.append((run_start, i - 1, run_spk))
                run_start = i
                run_spk = word_speakers[i]
        runs.append((run_start, len(word_speakers) - 1, run_spk))

        # Passo 4: fonde run troppo corte nella precedente
        merged_runs: List[Tuple[int, int, Optional[str]]] = []
        for start_i, end_i, spk in runs:
            length = end_i - start_i + 1
            if length < min_words_per_turn and merged_runs:
                prev_s, _, prev_spk = merged_runs[-1]
                merged_runs[-1] = (prev_s, end_i, prev_spk)
            else:
                merged_runs.append((start_i, end_i, spk))

        # Solo un run → assegna speaker al segmento intero senza splitting
        if len(merged_runs) <= 1:
            result = dict(seg)
            spk = merged_runs[0][2] if merged_runs else None
            if spk:
                result['speaker'] = spk
            return [result]

        # Passo 5: costruisce sotto-segmenti per ogni run
        sub_segs = []
        for start_i, end_i, spk in merged_runs:
            run_words = words[start_i:end_i + 1]
            sub_segs.append({
                'start':   run_words[0]['start'],
                'end':     run_words[-1]['end'],
                'text':    ''.join(w['word'] for w in run_words).strip(),
                'speaker': spk,
            })

        return sub_segs

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def unload(self) -> None:
        del self._pipeline
        self._pipeline = None
        # Ripristina stato TF32 precedente
        torch.backends.cuda.matmul.allow_tf32 = getattr(self, '_tf32_matmul', True)
        torch.backends.cudnn.allow_tf32        = getattr(self, '_tf32_cudnn',  True)
        import gc; gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
