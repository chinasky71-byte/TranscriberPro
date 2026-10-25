# Benchmark results

- **Hardware:** Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB
- **Backend:** rocm (torch 2.10.0+rocm7.0, HIP 7.0.51831, ROCM-SMI version: 4.0.0+unknown)
- **OS:** Ubuntu 26.04.1 LTS / kernel 7.0.0-38-generic
- **CPU:** AMD Ryzen 5 9600X 6-Core Processor (x86_64)
- **Date:** 2026-10-25T12:24:02+01:00
- **Commit:** f87c326
- **Label:** gpu-rocm-lfm

| suite | engine | runs | failed | device | backend | hardware | time_s_median | peak_vram_mib | wer | cer | chrf | similarity | untranslated_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| translation | http:lfm2.5-24b-a2b | 3 | 0 | gpu | rocm | Radeon RX 9060 XT (gfx1200, RDNA4), 16304 MiB; Radeon Graphics (gfx1036, RDNA2), 512 MiB | 11.3749 | 11137 | 0.8261 | 0.6803 | 0.7408 | 0.5403 | 0.0426 |
