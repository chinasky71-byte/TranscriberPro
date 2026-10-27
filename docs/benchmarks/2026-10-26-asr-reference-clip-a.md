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

## Round 4 — end-to-end against the Italian reference (clip A)

Same clip, target `ita`, translation NLLB, compared with the **Italian**
professional track (`ref-ita.srt`, 584 words after normalisation). This measures
ASR + translation together, which is what the product actually delivers.

| Variant | WER | chrF | Coverage | Words (ratio to reference) | Extra words | Drift median | ASR | Wall |
|---|---|---|---|---|---|---|---|---|
| qwen3 + NLLB | 63.18% | **74.11** | **100.0%** | 658 (**1.13x**) | 12 | **0.22 s** | 41.4 s | 124.5 s |
| whisper-0.25 + NLLB | **60.45%** | 73.11 | 96.0% | 590 (**1.01x**) | 2 | 0.49 s | **25.9 s** | 99.6 s |

**The WER of this round must not be used to rank the engines**, and the reason is
visible in the table: the reference is a *human translation of a human subtitle*,
which already condensed the speech, while the pipeline translates everything it
hears. Whisper's better WER comes with the word ratio closest to the reference
(1.01x) **because it under-transcribes** — 96% coverage against 100%: 4% of the
speech is missing, and missing speech cannot be counted as a wording error.

Read with the metrics that do not reward silence:

- **chrF**: qwen3 74.11 vs whisper 73.11 — qwen3 slightly ahead;
- **coverage**: 100% vs 96% — qwen3 ahead;
- **alignment**: median drift 0.22 s vs 0.49 s, p90 2.18 s vs 3.30 s — qwen3 ahead.

So the end-to-end round does not reorder the engines: it confirms they are close
on the wording of the translation and that qwen3 delivers more of the dialogue,
slightly better placed. The earlier verdict stands — **qwen3 stays the default**.

Example of what the two produce (same window):

    ref  : e, quando torno a casa, devo rilassarmi, per così dire.
    qwen3: Beh, devo rilassarmi, per così dire.
    whis : Devo rilassarmi, per così dire.

Both drop the opening clause because the clip starts mid-sentence there; neither
invents content.

## Round 5 — glossary with the cast names, and the accent defect

The glossary mechanism (`~/.transcriberpro/glossary/`, fixed rendering per
proper name, applied at translation time) needed a TMDB id that does not exist on
this machine (no API key), so it was extended: `glossary_id` in the config, file
`manual_<slug>.json`, and a key derived from the show folder
(`<...>/Monster (2022)/Season 4/x.mkv` -> `monster-2022`). A 38-entry glossary
with the cast names was created for the episode and the run confirms it is
loaded: `Active glossary: 38 terms`.

Effect on clip A, Italian target, qwen3 only:

| Run | WER | chrF | Coverage |
|---|---|---|---|
| without glossary | 63.18% | 74.11 | 100% |
| with glossary | 63.36% | 74.20 | 100% |

**No measurable difference**, and the reason is not the glossary's fault:

1. the names appear six times in ten minutes (Lizzie x4, Maggie, Borden);
2. NLLB already keeps proper names as they are, so a name->same-name entry has
   nothing to fix;
3. the visible name errors of this episode (Borden -> Bond / Potter / Burton)
   happen at the **ASR** stage: the translator never sees "Borden". A glossary
   cannot repair a mishearing.

**The real defect this round found is elsewhere: accents.** The Italian output
uses apostrophes where Italian needs accented letters.

```
reference : Sì, madre.          perché   così   è
qwen3     : Sì, mamma.          perche'  cosi'  e'
```

Counted on clip A: the output has **49 apostrophe-instead-of-accent forms and 13
accented characters**, the reference has 12 and 42. Folding accents and final
apostrophes on both sides drops the measured WER from **64.21% to 59.97%**: about
four points of the end-to-end score is a systematic rendering defect of the
deliverable, not a translation error. It is also cheap to fix, because the forms
are a fixed list (`e'`, `si'`, `perche'`, `cosi'`, `piu'`, `puo'`, `gia'`,
`qualita'`, ...) and the exceptions are known (`un po'`, `d'accordo`).

## Round 6 — the accent fix, measured, and the glossary isolated

Two follow-ups from round 5.

**Accents.** `core/italian_accents.py` maps the apostrophe forms to accented
letters from a closed list (`e'`->`è`, `perche'`->`perché`, `cosi'`->`così`,
`piu'`->`più`, `citta'`->`città`, ...), preserving capitals, and leaves the
legitimate apostrophes alone (`un po'`, `d'accordo`, `va'`, `sta'`, `fa'`,
`vent'anni`). It runs **at the exit of the pipeline**, not in the cleaner: the
cleaner runs before translation, on the source language, which is why the first
attempt changed nothing (a useful reminder that the step order matters more than
the code).

| Italian round, clip A | WER | CER | chrF |
|---|---|---|---|
| without the fix | 64.21% | 45.66% | 74.14 |
| with the fix | **59.76%** | **42.91%** | **75.34** |

Four and a half WER points and nearly three CER points were a rendering defect,
not translation quality. Apostrophes in the output: 36 -> 13 (the reference has
12), accented characters 13 -> 37 (the reference has 42).

**Glossary, isolated.** `bench/glossary_check.py` translates the reference lines
that contain cast names twice — with an empty glossary and with the 38-term one —
so only the translator is measured. Result: **7 of 7 names kept in both cases,
0 of 7 lines changed**. NLLB does not mangle proper names, so the glossary has
nothing to correct on this show. The glossary remains useful for terms a
translator *does* invent a rendering for (invented names, machines, places), and
it cannot repair a name the ASR misheard: that needs a post-ASR correction, which
is a different feature.

## Next

- Round 3: clip C (40:00–50:00), the tie-break with the same two variants.
- Then the end-to-end round with the Italian reference, and one full episode on
  the winner to confirm the per-episode gain.
- The Italian reference (index 22) is reserved for the end-to-end round: it
  measures translation as well, and it must be read as a relative ranking.

---

# Appendix — what the numbers look like in the text

Selection from the SRTs already produced for clips A and B (English target,
Whisper at VAD threshold 0.25). Times are relative to the clip, not to the
episode.

## 1. Short lines that qwen3 keeps and Whisper drops

```
clip A, 7:10
  ref  : Get out! You're fired!
  qwen3: Get out! You're fired.
  whis : (nothing)

clip B, 0:40
  ref  : Drink it.
  qwen3: Drink it.
  whis : (nothing)
```

Short isolated utterances are classified as non-speech by the neural VAD and
vanish. This is Whisper's structural defect; lowering the threshold reduces it
(from 21 missing words to 7 on clip A) but does not remove it.

## 2. Proper names: both engines are wrong, differently

```
clip B, 9:20      ref: - Any dust, Ms. Borden? - I'm not finished.
  qwen3: Any dust, Miss Bond? I'm not finished.
  whis : Any dust, Miss Potter? I'm not finished.

clip B, 9:40      ref: That's your footprint, Mrs. Borden. I will clean it up for you...
  qwen3: That's your footprint. Mrs. Burton, I will clean it up for you...
  whis : That's your footprint, Mrs. Borland, I will clean it up for you...
```

Borden becomes Bond / Potter / Burton / Borland. No engine switch fixes this: it
is what the per-show **glossary** is for, and the glossary is empty today.

## 3. Where Whisper is more accurate word by word

```
clip A, 2:00
  ref  : Oh, and look, it's the couch we're to sit on.
  qwen3: Oh, and lookit's the couch where to sit on.        "we're" -> "where", "look it's" fused
  whis : Oh, and look, it's the couch we're to sit on.      correct

clip B, 5:00
  ref  : ...this sort of casket. It's mahogany.
  qwen3: ...this sort of gasket. Mahogany.                  "casket" -> "gasket"
  whis : ...this sort of casket.                            correct, but loses "It's mahogany"

clip A, 2:00 (other window)
  ref  : I also have a dovecote.
  qwen3: I also have a dove coat.                           both wrong, same rendering
  whis : I also have a dove coat.
```

## 4. Where qwen3 spills into the next window — not a real error

```
clip A, 7:30
  ref  : It's quite good. That's six maids in a year.
  qwen3: It's quite good. That's six maids in a year. Yes, Mister Barton. And what about it?
  whis : quite good. That's six maids in a year.
```

"Yes, Mister Barton. And what about it?" belongs to the following window. Window
boundary spill inflates qwen3's WER and explains why its output is 1.13x the
reference length: part of the measured gap is segmentation, not wrong content.

## 5. Where both stay silent, and that is fine

```
clip A, 4:20   ref: Mmm. Mmm.    -> both: (nothing)
clip B, 9:10   ref: Hm.          -> both: (nothing)
```

Grunts and interjections are transcribed by neither. They still count as errors
in WER against a human subtitle.

## Patterns

| Pattern | qwen3 | whisper |
|---|---|---|
| Short isolated lines | **keeps them** | loses them (VAD) |
| Boundary spill / longer output | frequent | rare |
| Rare English words ("casket", "we're") | occasional swaps | **more accurate** |
| Proper names | wrong | wrong |
| Interjections and noises | silent | silent |

Two practical consequences:

1. **The glossary is the cheapest win for both engines**: names are the most
   visible error and need neither GPU time nor an engine change.
2. **WER rewards whichever engine speaks less**: Whisper wins several windows
   because it produces nothing where qwen3 produces correct text or spill. That
   is why the verdict was taken on chrF, coverage and drift together with WER,
   and why the end-to-end round (round 4) had to be read the same way.
