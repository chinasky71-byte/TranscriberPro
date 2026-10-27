# ASR against a human reference — clips A, B and C (2026-10-26)

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

## Round 3 — clip C (40:00–50:00) and the verdict

Clip C has 91 cues but **335 of its words are italic** (music), so after the
italic rule only 284 words of dialogue remain: the noisiest measurement of the
three. The same two variants, same harness.

| Clip | Reference words | qwen3 WER | whisper WER | qwen3 coverage | whisper coverage | qwen3 drift | whisper drift | qwen3 ASR | whisper ASR |
|---|---|---|---|---|---|---|---|---|---|
| A | 709 | 9.17% | **8.89%** | **96.2%** | 94.2% | **0.29 s** | 0.55 s | 41.5 s | **25.9 s** |
| B | 749 | **7.88%** | 8.41% | **93.6%** | 91.5% | **0.16 s** | 0.46 s | 46.6 s | **32.4 s** |
| C | 284 | **11.97%** | 14.44% | 83.3% | **87.5%** | **0.20 s** | 1.07 s | 45.3 s | **22.2 s** |
| **weighted** | **1742** | 6.95%* | 8.60%* | — | — | — | — | **133.4 s** | **80.5 s** |

\* matched-window WER, weighted by reference words.

## Decision

The criteria fixed before round 3 were: Whisper becomes the default only if, on
clips B and C, its WER is no worse than qwen3 by more than one point, coverage
stays at or above 93%, extra words do not double qwen3's, and the 25% speed
advantage holds.

| Criterion | Clip B | Clip C | Outcome |
|---|---|---|---|
| WER within 1 point | +0.53 ✅ | **+2.47 ❌** | fails |
| Coverage >= 93% | 91.5% ❌ | 87.5% ❌ | fails |
| Extra words | 7 vs 7 ✅ | 3 vs 7 ✅ | ok |
| >= 25% faster ASR | yes ✅ | yes ✅ | ok |

**qwen3 stays the default engine.** Whisper keeps a consistent and real
advantage in speed (**-40% of the ASR phase**, about four minutes per episode)
and a slightly better result on one clip, but it loses accuracy where the
material is harder and it covers less speech on two clips of three; on clip C its
alignment degrades too (median 1.07 s, p90 5.32 s against 0.20 s / 3.03 s).

Both engines remain available: `transcription_engine_mode` is a setting, so
Whisper is one click away when speed matters more than the last points of
accuracy, and the VAD knobs added in round 1b stay useful in that case.

## Caveats worth keeping

- Clip C is thin evidence: 284 words of dialogue against 335 of lyrics. Its
  coverage numbers (83–87%) say more about the material than about the engines.
- The clips were picked by cue count, which turned out to correlate with music
  rather than with dialogue. A future round should pick windows by *spoken* words
  only, if the question is ever reopened.
- The end-to-end round with the Italian reference is still not done: it measures
  ASR + translation together and could change the ranking, because the two
  engines punctuate and segment differently, and the translator consumes that
  text.

## Next

- Round 3: clip C (40:00–50:00), the tie-break with the same two variants.
- Then the end-to-end round with the Italian reference, and one full episode on
  the winner to confirm the per-episode gain.
- The Italian reference (index 22) is reserved for the end-to-end round: it
  measures translation as well, and it must be read as a relative ranking.
