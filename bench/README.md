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

- `environment.json` — hardware, backend, driver/ROCm, CPU, kernel, commit
- `results.json` — every run, metrics, timings, peak VRAM, device used
- `summary.md` — **hardware block at the top**, then medians per engine
- `summary.csv` — same columns as the Markdown table
- `asr/<engine>/runN.srt`, `runN.log`, `translation/<engine>/runN.srt`
- `manifest.txt` — commit, dataset, backend, hardware

Example header in `summary.md`:

```markdown
# Benchmark results

- **Hardware:** Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB
- **Backend:** rocm (torch 2.10.0+rocm7.0, HIP 7.0.51831)
- **OS:** Ubuntu 26.04.1 LTS / kernel 7.0.0-38-generic
- **CPU:** AMD Ryzen 5 9600X (x86_64)
- **Date:** 2026-10-25T12:00:00+02:00
- **Commit:** abc1234
```

CPU-only runs carry an explicit warning: timings and VRAM are not
representative of GPU performance, and the `device` column says `cpu`.

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
| device | `gpu`, `cpu` or `unknown`, inferred per run from the log and VRAM peak |
| backend | `rocm`, `cuda`, `cpu` — from the environment fingerprint |
| hardware | GPU summary repeated on each row for easy copy/paste |

## Known limitations

- One 130 s synthetic clip: the harness can reject clearly bad candidates but
  cannot crown a winner. Extend `samples/` with real material before making
  product decisions.
- The Italian reference contains a few typos (`controtto`, `Apsetta`, `lavor`);
  they penalize every engine equally and are not corrected in the gold file.
- The ASR reference has no timestamps, so timestamp accuracy is not measured.
- CPU-only runs report no VRAM.
