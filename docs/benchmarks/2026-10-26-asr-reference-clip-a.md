# ASR against a human reference — clips A and B (2026-10-26)

First round of the reference-based evaluation: instead of a synthetic clip, the
output is compared with the **professional subtitles already inside the file**.

Source: an episode with 38 SubRip tracks and English 5.1 audio. The Italian
track (index 22) and the plain English track (index 2) are used as references;
`force_audio_transcription` is enabled so the pipeline ignores them and really
transcribes the audio, which is the whole point of the exercise.

Clip A is 10 minutes cut with `-c copy` from 10:00, with both references
extracted **from the cut**, so audio and subtitles share one timeline:

| Reference | Cues | Words (after exclusions) |
|---|---|---|
| English (`--stream 2`) | 135 → 129 | 709 |
| Italian (`--stream 22`) | 104 | — (round 2) |

## Method

`bench/subtitle_eval.py` (new, tested):

- both files normalized the same way (`bench.text.normalize` after stripping
  `<i>`/`{\an8}` tags), so punctuation and case never count as errors;
- text compared inside **10-second windows** (each cue assigned by its midpoint),
  because a human subtitle and an ASR segment the sentence differently;
- metrics: WER, CER, chrF, coverage (reference windows with no output),
  words produced in windows with no reference ("silence"), median/p90 offset of
  the cue starts, per-window WER;
- two artifacts excluded, and both changed the result enough to matter: the
  **watermark** this pipeline writes at the top (12.43% → 9.17% WER for qwen3)
  and **italic-only reference cues** — the theme song, 6 cues / 43 words, which
  no ASR transcribes.

## Results (round 1, clip A, English target)

| Variant | WER | WER (matched windows) | CER | chrF | Coverage | Missing words | Extra words | Drift median | Drift p90 | ASR time |
|---|---|---|---|---|---|---|---|---|---|---|
| **qwen3** (current) | **9.17%** | 8.78% | **4.33%** | **94.36** | **96.2%** | 3 (2 windows) | 9 | **0.29 s** | 2.07 s | 41.5 s |
| faster-whisper large-v3 | 10.72% | 9.16% | 6.54% | 92.83 | 90.4% | 21 (5 windows) | 1 | 0.49 s | 3.50 s | **26.2 s** |

Wall time for the clip: qwen3 96.5 s, whisper 77.5 s (Demucs dominates the rest
in both cases).

## Observations

1. **qwen3 wins on accuracy**, on every metric that measures content; it is also
   the better aligned one (median 0.29 s vs 0.49 s, p90 2.07 s vs 3.50 s).
2. **Whisper's loss is coverage, not transcription**: in the windows where it
   produces text its WER is 9.16%, essentially the same as qwen3's 8.78%. It
   simply says nothing for 5 windows (21 words) — the shape of a VAD threshold
   cutting quiet speech (default `threshold=0.5`, `min_silence_duration_ms=500`).
   That is a recoverable defect, worth one variant with a lower threshold before
   concluding anything about the engine.
3. **Whisper is 37% faster in the ASR phase** (26.2 s vs 41.5 s). If the
   coverage gap closes with a looser VAD, it becomes the speed/quality trade-off
   worth having.
4. **Almost no hallucination**: 1 extra word in whisper, 9 in qwen3, none in
   windows without dialogue. The classic failure mode of this pipeline is absent
   on clean WEB-DL audio.
5. The absolute WER (~9%) must not be read as the ASR error rate: a human
   subtitle condenses and rephrases. These numbers rank configurations that share
   the same handicap; they do not grade the engine.

## Round 1b — Whisper with a looser VAD

The VAD thresholds were hardcoded (`threshold=0.5`, `min_silence_duration_ms=500`);
they are now config keys (`whisper_vad_threshold`, `whisper_vad_min_silence_ms`,
**defaults unchanged**) so the hypothesis could be tested instead of assumed.

| Variant | WER | WER (matched) | chrF | Coverage | Missing words | Extra words | ASR time |
|---|---|---|---|---|---|---|---|
| qwen3 | 9.17% | 8.78% | 94.36 | **96.2%** | 3 | 9 | 41.5 s |
| whisper 0.50 (default) | 10.72% | 9.16% | 92.83 | 90.4% | 21 | 1 | 26.2 s |
| whisper 0.35 | 10.44% | 10.19% | 93.34 | 92.3% | 12 | 2 | 26.2 s |
| **whisper 0.25** | **8.89%** | **7.98%** | **94.43** | 94.2% | 7 | 2 | **25.9 s** |

- The coverage gap was indeed the VAD: 21 missing words at 0.5, 7 at 0.25.
- At 0.25 Whisper matches qwen3 on accuracy (0.3 points of WER, below the
  resolution of one clip) and keeps its **37% faster ASR phase**.
- qwen3 still covers more: 96.2% vs 94.2% and 3 missing words vs 7.
- No hallucination penalty from the looser threshold on this clip (2 extra
  words), but that is exactly what clips B and C must confirm: a threshold this
  low is one step from transcribing music and audience noise.
- Production defaults stay at 0.5/500: the knob exists, the change is not
  decided.

## Round 2 — clip B (20:00–30:00) and a correction to the metric

Clip B was chosen because it has the most cues (162). It turned out to be
**music-heavy**: 226 of its words sit in italic cues (songs), which the earlier
version of the harness counted as "extra words" when a variant transcribed them
and excluded from the reference at the same time. qwen3, which does transcribe
singing, was therefore penalised twice.

The harness now **ignores italic-only windows on both sides**: transcribing a
song earns nothing, skipping it costs nothing, and the amount ignored is
reported. Both clips were re-scored with the same rule.

| Clip | Variant | WER | WER (matched) | chrF | Coverage | Missing words | Extra words | Drift median | ASR time |
|---|---|---|---|---|---|---|---|---|---|
| A (709 w) | qwen3 | 9.17% | 8.78% | 94.36 | 96.2% | 3 | 1 | 0.29 s | 41.5 s |
| A | whisper 0.25 | **8.89%** | **7.98%** | **94.43** | 94.2% | 7 | 0 | 0.55 s | **25.9 s** |
| B (749 w) | qwen3 | **7.88%** | **4.30%** | **94.04** | **93.6%** | 28 | 7 | **0.16 s** | 46.6 s |
| B | whisper 0.25 | 8.41% | 7.65% | 93.62 | 91.5% | 30 | 7 | 0.46 s | **32.4 s** |

Read together:

- **qwen3 wins clip B clearly** (matched WER 4.30% vs 7.65%) and keeps a better
  alignment (0.16 s vs 0.46 s median drift);
- **whisper-0.25 wins clip A by a hair** (0.28 points, inside the resolution of
  one clip) and is **30–37% faster in the ASR phase** on both clips;
- coverage: qwen3 96.2% / 93.6%, whisper 94.2% / 91.5% — the energy gate after
  Demucs loses less speech than the neural VAD, even at 0.25;
- extra words are now equal (7 and 7 on clip B): no hallucination advantage for
  either engine;
- clip B is dominated by songs (226 of 975 words), so the two clips test
  different material: B is the "noisy/musical" case, A the dialogue case.

## Next

- Round 3: clip C (40:00–50:00), the tie-break with the same two variants.
- Then the end-to-end round with the Italian reference, and one full episode on
  the winner to confirm the per-episode gain.
- The Italian reference (index 22) is reserved for the end-to-end round: it
  measures translation as well, and it must be read as a relative ranking.
