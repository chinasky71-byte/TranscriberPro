# Benchmark harness

Reproducible comparison of ASR engines and translation engines on the files in
`samples/`. It is a development tool, not part of the shipped application.

## Data

| File | Used as |
|---|---|
| `prova_amd_test.mp4` | input audio/video (130 s, English) |
| `correct_transcription_en.txt` | gold transcription (ASR) |
| `correct_translation_it.txt` | gold Italian translation (translation) |

`samples/` is gitignored: the media and references are local test material and
must never be committed.

## Usage

```bash
# ASR: Whisper vs Qwen3-ASR, 3 runs each
venv/bin/python -m bench.run --suite asr --engines faster-whisper,qwen3 --repeat 3

# Translation: NLLB vs TranslateGemma (GGUF), 3 runs each
venv/bin/python -m bench.run --suite translation --engines nllb,llm --repeat 3

# Both
venv/bin/python -m bench.run --suite all --repeat 3
```

Results are written to `~/.transcriberpro/bench/<timestamp>/`:

- `results.json` — every run, metrics, timings, peak VRAM
- `summary.md`, `summary.csv` — medians per engine
- `asr/<engine>/runN.srt`, `translation/<engine>/runN.srt` — raw outputs
- `manifest.txt` — commit and dataset path

## Method

- **ASR**: the real headless pipeline (`core.queue_runner`) with a forced
  engine and English target, so Demucs, chunking and segmentation are included.
  The config file is modified for the duration of each run and restored
  byte-for-byte afterwards.
- **Translation**: an SRT built from the reference English lines (synthetic
  timings) is translated by the engine through the project's factory. This
  isolates translation quality from ASR errors and segmentation.
- **Runs**: 3 by default; the summary reports medians, not a single run.
- **VRAM**: `rocm-smi` on device 0 is sampled every 0.5 s; the peak is reported.
- **Normalization**: lowercase, NFKC, numbers to digits, `percent`/`percento`
  to `%`, punctuation removed, spaces collapsed. It is identical for reference
  and hypothesis.

## Metrics

| Metric | Meaning |
|---|---|
| WER | word error rate (substitutions + deletions + insertions) |
| CER | character error rate |
| chrF | character n-gram F-score (n = 1..6, beta = 2) |
| similarity | word-level sequence similarity (0..1) |
| untranslated_ratio | translation blocks identical to the source (translation only) |
| time_s_median | wall-clock time per run |
| peak_vram_mib | peak VRAM on device 0 |

## Known limitations

- One 130 s synthetic clip: the harness can reject clearly bad candidates but
  cannot crown a winner. Extend `samples/` with real material before making
  product decisions.
- The Italian reference contains a few typos (`controtto`, `Apsetta`, `lavor`);
  they penalize every engine equally and are not corrected in the gold file.
- The ASR reference has no timestamps, so timestamp accuracy is not measured.
- CPU-only runs report no VRAM.
