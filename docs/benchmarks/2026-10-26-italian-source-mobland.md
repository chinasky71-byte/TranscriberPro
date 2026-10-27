# Italian source, Italian subtitles (2026-10-26)

The reference evaluation so far used an English source: the pipeline transcribed
English and translated to Italian, so the numbers mixed ASR and translation. This
round measures the configuration the reference machine actually uses for Italian
material — Italian audio, Italian target, **no translation step**.

Source: a 59-minute episode with an Italian dub (2.0) and four SubRip tracks
(ita forced, ita, eng, eng SDH). The audio selector prefers Italian when several
tracks exist, and with `force_audio_transcription` the pipeline ignores the
embedded subtitles: the reference and the generated file are independent.

Clip: 10 minutes from 30:00, chosen because it is the densest window of the
episode (214 cues, 1 196 words after normalisation). Reference extracted from the
cut with `-map 0:4`, so audio and subtitles share one timeline.

## Result

| Metric | Value |
|---|---|
| WER | **11.79%** |
| CER | 6.31% |
| chrF | **94.21** |
| Coverage | **100%** (0 words missing, 0 extra) |
| Words (ratio to reference) | 1 197 vs 1 196 (**1.00x**) |
| Drift median / p90 | 0.72 s / 3.13 s |
| ASR time (10 min of audio) | 75.6 s |
| Wall time | 132.5 s |

For comparison, the same pipeline on an English source translated to Italian scored
59.76% WER: the difference is the translation step, not the transcription.

## What the errors look like

Windows sampled every tenth one, as in the appendix of the English evaluation:

```
[0:00] WER 0%
  ref : Ora... se farai come ti dico, ti prometto che non mi vedrai mai più. Mai. Chiaro?
  qwen: Ora, se farai come ti dico, ti prometto che non mi vedrai mai più, mai, chiaro.

[2:00] WER 33%
  ref : Ok, bene. È di vimini. Molto più ecologica. È anche economica.
  qwen: Ok bene. È divimini, molto più ecologica e anche economica.

[3:00] WER 12%
  ref : Richie! Ho parlato con William, l'amico di Tommy...
  qwen: Ricci, ho parlato con William, l'amico di Tommy...

[1:00] WER 29%
  ref : ...La tua deposizione è questa: "Non so chi mi abbia accoltellato... perché era buio".
  qwen: ...La tua deposizione è questa. Non sono chi mi abbia coltellato, perché era buio.
```

Patterns:

1. **Word boundaries** ("è di vimini" -> "è divimini") and elided prefixes
   ("accoltellato" -> "coltellato", "non so chi" -> "non sono chi").
2. **Proper names again** ("Richie" -> "Ricci"), exactly the failure the ASR
   context is meant to fix — but this run had no glossary, so the decoder had no
   cast list. This episode has no TMDB key available, so the names must be pasted
   in the WebUI form (or a TMDB key configured).
3. **Window spill** inflates WER where the reference cue is short: in one window
   the reference had "Capo. La buona notizia" while the transcript carried the
   whole sentence (275%), which is segmentation, not a transcription error.
4. Interjections and fillers are transcribed rather than dropped, unlike the human
   subtitle, which shortens.

## Observations

- On Italian source the pipeline reproduces the professional subtitle almost word
  for word (1 197 vs 1 196 words) with complete coverage and no hallucination in
  silence.
- The **alignment is worse than on English** (median 0.72 s, p90 3.13 s against
  0.16-0.29 s / 2-3 s): one clip is not enough to call it systematic, but it is
  the first signal that Italian word timestamps from the aligner deserve a look.
- The ASR phase is slower than on English for the same 10 minutes (75.6 s vs
  ~45 s): Italian output carries more tokens per second of speech.

## Second run: the cast as ASR context

The show's cast was pasted in the WebUI form (the parser produced 48 terms: full
names, quoted aliases, and the individual first and last names, because dialogue
says "Richie", not "Richie Stevenson"). The same clip was run again with the
glossary active — confirmed in the log: `ASR context: 48 glossary names given to
the decoder` — with the Italian audio and no translation.

| Run | WER | CER | chrF | Coverage | Drift median | ASR |
|---|---|---|---|---|---|---|
| without glossary | 11.79% | 6.31% | 94.21 | 100% | 0.72 s | 75.6 s |
| with 48 names | 11.79% | **6.10%** | **94.50** | 100% | **0.60 s** | 79.4 s |

The context costs nothing here (unlike the English round, where it moved WER by
half a point) and improves chrF and alignment slightly. But on the name that
mattered it is only half a fix:

```
reference   Richie Stevenson continua a chiamare...     →  qwen3 with context: Richie Stevenson...
reference   Richie dice che Tommy era con Eddie.        →  qwen3 with context: Richie dice che...
reference   Ricci, noi non lavoriamo così.              →  qwen3 with context: Ricci, ...   (5 left)
```

Two of the seven occurrences flipped to `Richie` — exactly those where the surname
follows. The vocatives (`Ricci, ho parlato con...`) stayed: the Italian dub
pronounces the name the way Italians spell "Ricci", and a soft hint in the prompt
loses against the language model's own orthographic prior.

## Next

- Repeat on a second window of the same episode to see whether the alignment gap
  and the WER hold.
- Name correction as a **declared** mapping: the context fixes about a third of the
  occurrences, so the next step is letting the show declare the mishearings
  explicitly (`Ricci -> Richie`) and applying them to the transcript
  deterministically — no guessing, no dictionary, and it composes with the context
  rather than replacing it.
- A second window of the episode, to confirm the alignment gap (0.72 s median on
  Italian against 0.16-0.29 s on English) before it is treated as a property of the
  language rather than of this clip.
