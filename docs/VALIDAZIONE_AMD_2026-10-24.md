# AMD validation — 2026-10-24

Execution of the checklist `docs/PROVA_AMD_COMPLETA.md` on Linux + AMD GPU.
The GUI tests (Sections 3 and 5) were **skipped by user decision** (no display
in the test session).

> This report was translated from Italian to English to comply with the
> repository documentation rule (`AGENTS.md`). The file name is unchanged so
> existing links keep working.

## Environment (Section 0)

| Item | Value |
|---|---|
| Distribution | Ubuntu 26.04.1 LTS |
| Kernel | 7.0.0-38-generic |
| GPU | **Radeon RX 9060 XT 16 GB — gfx1200, RDNA4, ROCm "official"** |
| IGPU | Radeon Graphics gfx1036 (RDNA2) — not used for compute |
| `/dev/kfd` | accessible to the user running the tests |
| Groups | `render`, `video`, `sudo` present |
| Driver | `amdgpu` loaded — **never modified** |
| System ROCm | absent (`/opt/rocm`, `rocminfo`); not required: the wheels ship the runtime |
| Libdrm | `libdrm_amdgpu.so.1` present; `amdgpu.ids` warning is cosmetic |
| Initial disk space | 110 GB free |
| Python | system only 3.14.4 → standalone CPython 3.12.15 installed in `.tools/` |

Actual versions: Python 3.12.15, torch 2.10.0+rocm7.0 (HIP 7.0.51831),
ctranslate2 4.8.3, transformers 4.57.6, faster-whisper 1.2.1, llama_cpp 0.3.34,
soundfile 0.13.1, ffmpeg 8.0.1, tesseract 5.5.0 (eng+ita+osd), mkvtoolnix 97.

## Section 1 — Installation

| # | Test | Result | Notes |
|---|---|---|---|
| 1.1 | `install.sh --gpu-backend=rocm --check` | **OK** | exit 0 after installing Python 3.12; before: KO on python/ffmpeg/tesseract |
| 1.2 | `install.sh --gpu-backend=rocm --yes` | **OK** | exit 0, 15 GB venv, selfcheck without KO, ~12 GB downloaded. No sudo, no system package touched by the script |
| 1.3 | Vulkan fallback (RDNA1 or older) | **SKIPPED** | RDNA4 card: not needed |

System dependencies installed separately (user, `apt`, **only 15 new
packages, zero upgrades**): ffmpeg, mkvtoolnix, tesseract-ocr + ita/eng.
No mesa/libdrm/amdgpu/kernel/xorg/wayland package was touched.

## Section 2 — Detection and smoke test

| # | Test | Result | Detail |
|---|---|---|---|
| 2.1 | `gpu_detect.py --json` | **OK** | RX 9060 XT, gfx1200, RDNA4, official; recommended backend `rocm` |
| 2.2 | `amd_smoke_test.py --whisper` | **OK** | torch/HIP ok (matmul 0.268 s), ctranslate2 2 devices, bf16/fp16/int8, llama.cpp Vulkan `gpu_offload=true`, Whisper tiny on GPU ok |
| 2.3 | GGUF/Vulkan | **OK (covered by 4.8)** | TranslateGemma GGUF Q4_K_M loaded and run on Vulkan |

Report: `amd_smoke_report.txt`.

## Section 3 — GUI app

`SKIPPED` entirely by user decision (no display).

## Section 4 — Real processing

Input: `samples/prova_amd_test.mp4` (130.6 s, two-voice English audio).
Expected: `samples/testo_atteso.txt`.

| # | Step | Result | Time | Peak VRAM | Notes |
|---|---|---|---|---|---|
| 4.1 | **Whisper large-v3** (`faster-whisper`) | **OK** | 29–32 s | **9207 MiB** | auto-detect `en`; 23 SRT blocks; **98.8% similarity** (only "thirty percent" → "30%") |
| 4.2 | **Qwen3-ASR-1.7B** | **OK** | 44 s | **7254 MiB** | bf16; **99.5% similarity** |
| 4.3 | Canary | **OK (fallback)** | 31 s | ~9 GB | NeMo/ROCm unavailable → automatic fallback to Faster-Whisper, as expected |
| 4.4 | `auto` mode | **OK** | 45 s | ~7 GB | language `und` → Qwen3 auto-detect |
| 4.5 | Demucs + pyannote | **OK / SKIPPED** | 29 s | ~9 GB | Demucs runs on GPU; diarization skipped: no HF token (gated models returned 401), job completed |
| 4.6 | Punctuation | **OK** | — | — | Whisper/Qwen3 produce native punctuation; restorer not needed |
| 4.7 | **NLLB-200-3.3B** | **OK** | 64–69 s | **12857 MiB** | en→it, `residual source language: 0`, correct translation |
| 4.8 | **TranslateGemma-12B GGUF Q4_K_M** | **OK** | 62–66 s | **9454 MiB** | llama.cpp on **Vulkan**, 4 parallel sequences, residual 0 |
| 4.9 | Glossary (Qwen2.5-14B) | **SKIPPED** | — | — | GUI workflow over multiple episodes + ~9 GB GGUF; the Vulkan part is covered by 4.8 |
| 4.10 | PGS/VOBSUB OCR + gender | **SKIPPED** | — | — | the sample has no bitmap subtitles; gender requires diarization/token |

No `out of memory`, `segmentation fault` or `Aborted` errors in the tests run
**after the fixes** below. Only harmless MIOpen warnings
(`IsEnoughWorkspace`) and torch warnings about experimental ROCm
flash/mem-efficient attention remain.

## Section 5 — Queue and UI

`SKIPPED` (5.1–5.3): requires the GUI. The headless queue
(`core.queue_runner`) was used for all tests and worked (status, logs, exit
codes).

## Section 6 — Defects found and fixed

Three real problems blocked the pipeline on AMD. The fixes are merged into
`master` (1.34.34); two platform guards were refined during review (PR #28),
as noted below.

### 1. `torchaudio.info` removed in torchaudio 2.10
`core/audio_processor.py` used `torchaudio.info` in batched mode. With
torchaudio 2.10 the attribute no longer exists: an `AttributeError` masked as
"no chunks created", pipeline stopped before transcription.
**Fix:** `soundfile.info` (dependency already present).

### 2. ctranslate2 SIGSEGV when torch initializes the HIP context first
With ROCm, if Demucs or the VRAM checks (`torch.cuda.mem_get_info`) touch the
GPU before the first Whisper inference, `ctranslate2` 4.8.3 crashes with
SIGSEGV (exit -11) in `encode()`, including in `detect_language()`.
Reproduced in minimal form; reversing the order removed the crash.
**Fix:** `utils/ct2_bootstrap.py` — `ctranslate2.get_cuda_device_count()` at
the start of `core/pipeline_cli.main()`, before importing the pipeline.
Costs a few ms, loads no model. Can be disabled with
`TP_SKIP_CT2_INIT=1`. **Review update (PR #28):** the bootstrap now runs on
Linux only, to avoid changing the torch/onnxruntime/llama_cpp import order on
Windows.

### 3. NLLB spread over the iGPU → `HIP error: invalid device function`
`device_map="auto"` spread NLLB across device 0 (gfx1200) and device 1
(gfx1036). The iGPU has no compiled kernels: every batch failed and was
skipped, yet the pipeline reported success and saved an English `.it.srt`.
**Fix:** `device_map={"": 0}` for base and fine-tuned NLLB
(`core/translator.py`). NLLB-3.3B fp16 (~6.6 GB) fits on a single GPU.
**Review update (PR #28):** the pin now applies on ROCm only; on CUDA
`"auto"` is required for the 8-bit CPU-offload branch used below 7 GB.

### 4. False positive translation success (fixed)
`translate_file` returned `True` even when **all** batches failed and the
blocks stayed in English (observed with the HIP error from point 3: residual
41/46 lines, exit 0, English `.it.srt`). The loop swallowed every exception
("Batch skipped"), the audit counted residual blocks but the value was
unused, and the final `return True` checked nothing.
**Fix:** new key `translation_max_untranslated_pct` (default **80**), fatal
GPU errors are no longer swallowed, audit runs before writing the file; same
criterion for the LLM translator. On `False` the pipeline keeps the
original-language file and marks the job as failed.
Tests: `linux_tests/test_translation_success_gate.py`.

## Machine state

- No changes to driver, kernel, mesa, xorg, wayland, systemd or Steam.
- No reboot.
- Files created outside the repository: `~/.transcriberpro/config.json` and
  logs (the app expects them). Everything else is inside the repository:
  `venv/`, `models/` (33 GB at the time of the run), `.tools/`.
  Test artifacts were moved to `~/.transcriberpro/validation-logs/` according
  to the privacy rule.
- Disk: 34 GB free at the end.
