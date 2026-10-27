# ADR-008 — One ASR engine: Qwen3-ASR

- Status: accepted
- Date: 2026-10-27
- Supersedes: the multi-engine routing introduced with `core/engine_router.py`
  (Canary for English, Whisper as universal fallback).

## Context

Three ASR engines were kept alive at once: faster-whisper large-v3 (the historical
one), Canary-Qwen-2.5B (English only), and Qwen3-ASR-1.7B. The reference
evaluation decided the question with numbers:

- on English material qwen3 scored **9.17% WER** against professional subtitles
  (whisper, after tuning its VAD, 8.89%): a tie inside the noise of one clip, with
  qwen3 covering more speech;
- on the second English clip qwen3 won clearly (matched-window WER **4.30% vs
  7.65%**);
- on Italian material — the actual reference library — qwen3 produced **11.79%
  WER with 100% coverage** and a word-for-word reproduction of the human subtitle;
- whisper's only remaining advantage was speed (30-40% of the ASR phase), which is
  real but worth about four minutes per episode.

Meanwhile Whisper cost real money to keep: `ctranslate2` (67 MB, and the ROCm wheel
is not on PyPI — it is a zip asset downloaded by the installer, the most fragile
step of the whole ROCm setup), `whisperx` (18 MB, used only by an alignment path
that qwen3 does its own way), 2.9 GB of model cache, a preload of 2.1 s and 1.5 GB
of VRAM per episode whose only purpose was to initialise ctranslate2 before
PyTorch, and a whole class of failures where a broken `ctranslate2` killed a job
that would have used qwen3.

## Decision

`Qwen3-ASR` is the only ASR engine.

**Removed:** `core/engines/faster_whisper_engine.py`, `core/engines/canary_engine.py`,
`core/engines/canary_cli.py`, `core/aligner.py` (whisperx), `core/whisper_lang_retry.py`,
`utils/ct2_bootstrap.py`, the multi-engine routing and its silent fallback, the
"2.5 preload" step, the batched single-file mode, `enable_forced_alignment`, the
`whisper_*` and `canary_*` configuration keys, and the `faster-whisper` /
`ctranslate2` / `whisperx` requirements (plus the ctranslate2 ROCm wheel and the
`whisperx --no-deps` step in the installer).

**Kept, replaced or re-homed:**

- the VAD needed by the subtitle synchroniser is ours: `core/vad.py` drives Silero
  v6 on `onnxruntime` with vendored weights (verified: 98% interval overlap with
  the Whisper one, median start difference 0.000 s);
- word timestamps come from qwen3's own aligner, so forced alignment through
  whisperx has no job left;
- `transcription_engine_mode` stays as a key for compatibility: `auto` and the old
  values (`canary`, `faster-whisper`) are migrated to `qwen3` on read, with a
  message in the log;
- an engine failure is now a **job failure**, never a silent switch to a slower
  model.

## Consequences

- A language outside qwen3's aligner set (11 languages for timestamps, 30 for
  transcription) is refused with a clear error instead of being transcribed slowly
  by Whisper. The reference library is Italian and English, both covered.
- No batched single-file mode: the pipeline always chunks (20 s target, 150 s cap
  for qwen3), which is what it already did on every measured episode.
- Installer: no ctranslate2 wheel, no whisperx; verification checks torch only.
  Virtualenv ~87 MB smaller, model cache ~3 GB smaller.
- Runtime: no preload (2.1 s and 1.5 GB of VRAM churn per episode), no
  ctranslate2/PyTorch initialisation order to respect, no abort class of bugs.
- Verified after removal (10-minute clips, same references as before):
  Italian **11.71% WER** against 11.79% baseline, English 10.01% and 9.59% on two
  consecutive runs against a 9.17% baseline — the spread between two identical
  runs is 0.42 points, so the difference is inside the noise of the clip and no
  mechanism would explain it anyway.

## Alternatives rejected

- **Keep Whisper as fallback**: it is what made the install fragile (ct2 wheel),
  the preload necessary (initialisation order) and the venv heavy. The fallback was
  never observed helping on this library.
- **Keep Canary for English**: no measurable advantage over qwen3 on the English
  clip, and it drags a separate environment and code path.
- **Fuzzy post-correction instead of fixing the ASR**: measured and rejected — at
  the edit distance that catches real errors it rewrites ordinary words
  (`Would`→`Lourd`, `Thank`→`Hall`). Names are better handled by giving the
  decoder the cast as context, which is what the pipeline now does.
- **Own VAD only if it matches**: if `core/vad.py` had not reproduced the Whisper
  intervals, Whisper would have stayed for the synchroniser alone. It did (98%
  overlap, 0.000 s median).
