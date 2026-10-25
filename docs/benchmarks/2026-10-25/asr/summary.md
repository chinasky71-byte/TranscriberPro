# Benchmark results

- **Hardware:** Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB
- **Backend:** rocm (torch 2.10.0+rocm7.0, HIP 7.0.51831, ROCM-SMI version: 4.0.0+unknown)
- **OS:** Ubuntu 26.04.1 LTS / kernel 7.0.0-38-generic
- **CPU:** AMD Ryzen 5 9600X 6-Core Processor (x86_64)
- **Date:** 2026-10-25T12:28:55+01:00
- **Commit:** 21232d8
- **Label:** gpu-rocm-final-asr

| suite | engine | runs | failed | device | backend | hardware | time_s_median | peak_vram_mib | wer | cer | chrf | similarity | untranslated_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asr | faster-whisper | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 32.6571 | 9020 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |  |
| asr | qwen3 | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 57.1536 | 7373 | 0.0037 | 0.0019 | 0.9972 | 0.9963 |  |
