# Runtime and GPU backends

The runtime layer answers: *which accelerator is usable, and how must the
process behave on it?* It does not orchestrate the pipeline.

## Backends

| Backend | Detection | Typical hardware | Status |
|---|---|---|---|
| `cuda` | `torch.cuda.is_available()` with CUDA build | NVIDIA | Tier 2, best-effort/CI |
| `rocm` | `torch.version.hip` set and device visible | AMD | **Tier 1, tested** (RX 9060 XT, gfx1200, ROCm 7.0) |
| `vulkan` | Vulkan loader + device | AMD/Intel, older AMD | Tier 3, used by llama.cpp |
| `cpu` | fallback | any | Tier 3 |

Detection source: `utils/gpu_detect.py` (`--json`). It reports vendor, name,
VRAM, `gfx`, `amd_family`, `rocm_support`, available backends and the
recommended backend.

## Current runtime facts (2026-10-25)

- torch `2.10.0+rocm7.0`, HIP `7.0.51831`, ctranslate2 `4.8.3` (ROCm wheel).
- **ctranslate2 must initialize before torch touches the GPU.** On ROCm this
  is mandatory: Demucs or a VRAM query (`torch.cuda.mem_get_info`) before the
  first Whisper inference causes a SIGSEGV in `encode()`/`detect_language()`.
  Implemented by `utils/ct2_bootstrap.py` at the start of
  `core/pipeline_cli.main()`, **Linux only** (PR #28).
- **Whisper compute type:** `int8_float16` on GPU, `int8` on CPU
  (`core/engines/faster_whisper_engine.py`).
- **NLLB device map:** `{"": 0}` on ROCm when more than one device is visible
  (the iGPU has no compiled kernels); `"auto"` everywhere else, because CUDA
  needs it for the 8-bit CPU-offload branch below 7 GB free VRAM
  (`core/translator.py`, PR #28).
- **NLLB quantization:** fp16 when free VRAM ≥ 7 GB, otherwise 8-bit.
- **llama.cpp:** GGUF models run on Vulkan on AMD; `gpu_offload=true`.
- **Qwen3-ASR:** bf16 on GPU; falls back to faster-whisper when the detected
  language is outside the ForcedAligner set (`LanguageNotAlignable`).
- **VRAM thresholds for translation** (`utils/config.py`):
  `llm_translator_gguf_q4_min_free_gb = 10.0`,
  `llm_translator_gguf_iq3_min_free_gb = 7.5`,
  `llm_translator_nf4_min_free_gb = 10.5`.

## Runtime policy (target)

| Situation | Policy |
|---|---|
| ROCm, multiple devices | pin the compute device to 0; never let accelerate spread layers over an iGPU |
| CUDA, free VRAM < 7 GB | keep `device_map="auto"` so 8-bit CPU offload works |
| Linux + ROCm | initialize ctranslate2 before any `torch.cuda` call |
| Any OS | never install, replace or pin GPU drivers; use the host driver |

These are decisions of the **runtime** layer, exposed through
`RuntimeProfile` (see [contracts.md](contracts.md)). The domain must not
re-derive them.

## Driver policy

- The project never installs or modifies drivers, DKMS modules or kernel
  parameters.
- Host requirements are documented, not enforced: ROCm 7.x for AMD, a recent
  NVIDIA driver for CUDA, a Vulkan loader for llama.cpp.
- `HSA_OVERRIDE_GFX_VERSION` is applied to child processes only when the user
  has not set it (RDNA2 fallback); it is never written globally.
- Containers use the host driver plus the container runtime; no driver files
  inside images.

## Known failure modes

| Symptom | Cause | Handling |
|---|---|---|
| `HIP error: invalid device function` | work spread over an iGPU without kernels | pin device 0 on ROCm |
| SIGSEGV in `encode()` / `detect_language()` | torch initialized the HIP context before ctranslate2 | ct2 bootstrap on Linux |
| `MIOpen(HIP) IsEnoughWorkspace` warnings | fallback solver, harmless | ignore |
| `CUDA out of memory` on translation | batch too large | adaptive batch manager reduces it |
| Vulkan model fails to load | loader/ICD missing | fall back to CPU or NLLB |

## Testing

- Tier 1 (AMD ROCm) is validated on real hardware; results are recorded in
  `docs/VALIDAZIONE_AMD_2026-10-24.md`.
- Tier 2 (CUDA) requires a CI runner or a machine; until then it is
  best-effort and must be labelled as such.
- CPU is exercised by the unit tests and by container smoke tests.
