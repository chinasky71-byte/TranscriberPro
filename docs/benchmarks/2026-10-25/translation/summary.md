# Benchmark results

- **Hardware:** Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB
- **Backend:** rocm (torch 2.10.0+rocm7.0, HIP 7.0.51831, ROCM-SMI version: 4.0.0+unknown)
- **OS:** Ubuntu 26.04.1 LTS / kernel 7.0.0-38-generic
- **CPU:** AMD Ryzen 5 9600X 6-Core Processor (x86_64)
- **Date:** 2026-10-25T12:16:22+01:00
- **Commit:** f87c326
- **Label:** gpu-rocm-final-translation

| suite | engine | runs | failed | device | backend | hardware | time_s_median | peak_vram_mib | wer | cer | chrf | similarity | untranslated_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| translation | http:gemma4-12b-dense | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 25.4554 | 9017 | 0.4174 | 0.3170 | 0.7853 | 0.6738 | 0.0213 |
| translation | http:gpt-oss-20b | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 11.7995 | 11471 | 0.4522 | 0.3197 | 0.7760 | 0.6379 | 0.0426 |
| translation | llm | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 14.5295 | 8798 | 0.4130 | 0.3083 | 0.7630 | 0.6578 | 0.0426 |
| translation | nllb | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 17.8967 | 12540 | 0.5130 | 0.3555 | 0.7563 | 0.6151 | 0.0213 |
| translation | nllb_finetuned | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 15.6222 | 6286 | 0.4304 | 0.3013 | 0.7595 | 0.6564 | 0.0426 |
