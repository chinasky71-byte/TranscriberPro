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

## Next

- Repeat on a second window of the same episode to see whether the alignment gap
  and the WER hold.
- Paste the show's cast in the WebUI form and re-run the same clip: the visible
  name error ("Ricci" for "Richie") is exactly what the ASR context addresses.
