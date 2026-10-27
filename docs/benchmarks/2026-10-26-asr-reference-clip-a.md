# ASR against a human reference — clip A (2026-10-26)

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

## Next

- Round 2: same two variants on clip B (20:00–30:00, the densest stretch), then
  clip C (40:00–50:00).
- Before that, one Whisper variant with a lower VAD threshold on clip A: it
  costs three minutes and tells whether point 3 is real.
- The Italian reference (index 22) is reserved for the end-to-end round: it
  measures translation as well, and it must be read as a relative ranking.
