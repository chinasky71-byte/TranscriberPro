# Support matrix

Status as of 2026-10-25. “Tested” means executed on real hardware and recorded;
anything else is best-effort.

| Tier | Platform | Backend | Interface | Tested | Notes |
|---|---|---|---|---|---|
| **1** | Linux x86_64 + AMD | ROCm 7.x (+ Vulkan for GGUF) | WebUI (target), CLI | **yes** — RX 9060 XT, gfx1200, Ubuntu 26.04 | reference platform; see `docs/VALIDAZIONE_AMD_2026-10-24.md` |
| 2 | Linux x86_64 + NVIDIA | CUDA 12.x | WebUI (target), CLI | no — CI/community needed | best-effort until a runner exists |
| 3 | Linux x86_64, no GPU | CPU (+ Vulkan optional) | WebUI (target), CLI | partial (unit/smoke) | slow; OCR and translation on CPU |
| 3 | Linux + older AMD / Intel | Vulkan (GGUF only) | WebUI (target), CLI | no | transcription/translation on CPU |
| frozen | Windows x86_64 + NVIDIA | CUDA | legacy GUI / native | previously | no new features |
| not supported | Windows + AMD | — | — | — | ROCm is not available; Vulkan/CPU only via native code |
| not supported | macOS | — | — | — | out of scope |

## Minimum requirements

| Component | Requirement |
|---|---|
| OS | Linux x86_64 (Ubuntu 24.04+ / 26.04 tested) |
| Python (native install) | 3.11 or 3.12 |
| AMD driver | kernel `amdgpu` with compute support (`/dev/kfd`), user in `render` and `video` |
| ROCm | 7.x user-space runtime; the torch wheels ship their own libraries |
| NVIDIA driver | recent driver compatible with the CUDA 12.x wheels |
| Vulkan | loader `libvulkan.so.1` + ICD (for llama.cpp GGUF models) |
| Disk | ~15 GB for the environment, ~30 GB for models |
| VRAM | 8 GB minimum for the small profiles, 12 GB recommended, 16 GB for the XL profile |

## What “tested” means

A configuration is tested when:
1. installation completes with exit 0;
2. the smoke test passes (`scripts_manutenzione/amd_smoke_test.py` or the CUDA
   equivalent);
3. one real file is processed end-to-end with a known result;
4. the result is recorded in the repository (documentation, in English).

## Reporting a platform

Open an issue with: OS, GPU, driver/ROCm/CUDA version, `gpu_detect --json`
output, the failing command and the relevant log lines (no personal data).
