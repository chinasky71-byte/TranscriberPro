# Benchmark results

Sanitized benchmark runs, kept in the repository for traceability. Raw runs
(logs, per-run SRTs, intermediate failures) stay outside the project in
`~/.transcriberpro/bench/`; only the environment, summary and result files are
exported here.

## Policy

- No personal data: absolute home paths are replaced with `~` and the
  repository path with `<repo>`. No hostname, username or token is recorded.
- No media, model weights or logs are committed.
- Every report starts with the hardware block (GPU, backend, OS, CPU, commit)
  produced by `bench/environment.py`.
- The source reference files live in `samples/`, which is gitignored local
  test material.

## How to reproduce

```bash
# ASR
venv/bin/python -m bench.run --suite asr --engines qwen3 --repeat 3

# Translation: the product engine (ADR-009) is `llm` = TranslateGemma-12B GGUF.
# The NLLB arms still exist in bench/ only, as a comparison baseline.
venv/bin/python -m bench.run --suite translation --engines llm --repeat 3
venv/bin/python -m bench.run --suite translation \
  --engines nllb,nllb_finetuned,llm --repeat 3

# Translation engines against a professional reference (the 2026-10-28 campaign)
venv/bin/python -m bench.translation_compare translate --engine translategemma \
  --gguf models/translategemma-12b-gguf/translategemma-12b-it-finale-Q4_K_M.gguf \
  --src <work>/en_professional.srt --ref <work>/it_professional.srt \
  --out <work> --name tg12b_q4
venv/bin/python -m bench.translation_compare translate --engine chat --family eurollm \
  --gguf <models>/EuroLLM-22B-Instruct-2512.Q4_K_M.gguf --rules ...

# Translation through a llama.cpp server
venv/bin/python -m bench.run --suite translation \
  --engines http:gemma4-12b-dense,http:gpt-oss-20b --repeat 3 \
  --server-url http://127.0.0.1:9091

# Export a run into the repository
venv/bin/python -m bench.export --run ~/.transcriberpro/bench/<stamp> \
  --suite translation --out docs/benchmarks/<name>
```

## How to read a table

- `device` says whether the run actually used the GPU; `backend` is the stack
  (rocm/cuda/cpu). A CPU fallback is visible and carries a warning.
- `time_s_median` is the median of repeated runs. In-process engines load the
  model in every run; an HTTP server keeps it resident, so only the first run
  includes the cold load.
- `peak_vram_mib` is sampled from `rocm-smi` on device 0 every 0.5 s.
- `wer` is the primary metric for ASR. For translation it is only a proxy:
  read `chrf` first, then `cer`, `similarity` and `untranslated_ratio`.
- One short sample can reject clearly worse candidates; it cannot crown a
  winner. Product decisions need more material.

Method details: [`bench/README.md`](../../bench/README.md).

## Runs

| Date | Directory | Content |
|---|---|---|
| 2026-10-28 | [`2026-10-28-translation-engines.md`](2026-10-28-translation-engines.md) | Eleven translation engines against a professional Italian reference: table, defect taxonomy, what did not work, reproduce commands |
| 2026-10-25 | [`2026-10-25/`](2026-10-25/README.md) | ASR and translation on the AMD reference machine. The translation table compares six engines: **historical**, four of them no longer exist (ADR-009). `llm` is the one that stayed. |
