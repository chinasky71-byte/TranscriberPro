# Benchmark session — 2026-10-25

Reference machine and software:

- **GPU:** Radeon RX 9060 XT 16 GB (gfx1200, RDNA4); iGPU gfx1036 not used
- **Backend:** ROCm, torch 2.10.0+rocm7.0, HIP 7.0.51831
- **OS:** Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic
- **CPU:** AMD Ryzen 5 9600X
- **Input:** `samples/prova_amd_test.mp4` (130.6 s, two-voice English)
- **References:** `samples/correct_transcription_en.txt`,
  `samples/correct_translation_it.txt` (local, gitignored)

Three runs per engine; values are medians. Translation source is split into
one sentence per block with realistic durations (~15 chars/s); HTTP models
use one request per block with a single generic prompt.

## ASR — [results](asr/summary.md)

| Engine | Time | Peak VRAM | WER | CER | chrF |
|---|---|---|---|---|---|
| faster-whisper large-v3 | **32.7 s** | 9020 MiB | **0.0000** | 0.0000 | 1.0000 |
| Qwen3-ASR-1.7B | 57.2 s | **7373 MiB** | 0.0037 | 0.0019 | 0.9972 |

Whisper is word-perfect on this sample and about 1.7x faster; Qwen3 is
slightly behind on accuracy and uses less VRAM. The current default
(Whisper as universal engine, Qwen3 for its supported languages) is not
contradicted by this run.

## Translation — [in-process results](translation/summary.md), [LFM results](translation-lfm/summary.md)

> **Historical (ADR-009).** This table compares engines that no longer exist in
> the product: NLLB base, NLLB fine-tuned, the two HTTP models and the LFM run.
> The only engine that stayed is the `llm` row (TranslateGemma-12B GGUF). The
> numbers remain the reference for what the GGUF engine costs on this clip
> (~14.5 s, ~8.8 GiB, WER 0.413, chrF 0.763) and are what a fresh run is
> compared against.

| Engine | Time | Peak VRAM | WER | CER | chrF | Similarity | Untranslated |
|---|---|---|---|---|---|---|---|
| `http:gemma4-12b-dense` | 25.5 s | 9017 MiB | 0.417 | 0.317 | **0.785** | **0.674** | 2.1% |
| `http:gpt-oss-20b` | **11.8 s** | 11471 MiB | 0.452 | 0.320 | 0.776 | 0.638 | 4.3% |
| TranslateGemma 12B GGUF (`llm`) | 14.5 s | 8798 MiB | **0.413** | **0.308** | 0.763 | 0.658 | 4.3% |
| NLLB-200-3.3B (`nllb`) | 17.9 s | 12540 MiB | 0.513 | 0.356 | 0.756 | 0.615 | 2.1% |
| NLLB fine-tuned 4-bit (`nllb_finetuned`) | 15.6 s | **6286 MiB** | 0.430 | 0.301 | 0.760 | 0.656 | 4.3% |
| `http:lfm2.5-24b-a2b` | 11.4 s | 11137 MiB | 0.826 | 0.680 | 0.741 | 0.540 | 4.3% |

## Conclusions

- **The models already in the project remain the right defaults.**
  TranslateGemma 12B GGUF is the best balance of quality, time and VRAM among
  the engines that fit the 8–12 GB target.
- **NLLB fine-tuned is the best option under 8 GB**: competitive quality
  (chrF 0.760) with only 6.3 GB, thanks to the published 4-bit NF4 weights.
  It is the project's measured quality anchor and confirms its role as
  fallback.
- **gemma4-12b-dense** reaches the highest chrF (0.785) but is the slowest
  (25.5 s) and needs a 16 GB card; it is a quality-first option, not a new
  default.
- **gpt-oss-20b** is the fastest warm engine (11.8 s) but uses 11.5 GB and
  scores below gemma4 and TranslateGemma; only for speed-first 16 GB setups.
- **LFM 2.5 24B A2B is rejected**: fastest warm time but the lowest quality
  (chrF 0.741, WER 0.826). The Q3 quantization does not help.
- **NLLB base is heavier and worse than NLLB-FT**; it should not be the
  default for this pair.
- No change to the project's model selection is justified by this session.

## Caveats

- One 130 s synthetic clip and an Italian reference with a few typos: the
  numbers reject clearly worse candidates but are not a product decision.
- The two `http:` models are general-purpose, not MT-tuned, and share a single
  generic prompt. A per-model prompt could change the ranking.
- HTTP models stay resident in the server: run 1 includes the cold load,
  later runs are warm. In-process engines load the model in every run.
- `reasoning` is disabled for gpt-oss and LFM via the benchmark server preset
  (`reasoning-budget = 0`).
- NLLB-FT is published under **CC-BY-NC-4.0** (non-commercial). The weights
  are downloaded locally and are not part of the repository.

## Commits

- ASR report: `21232d8`
- Translation and LFM reports: `f87c326` (the translation code is unchanged by
  the later export commit)
