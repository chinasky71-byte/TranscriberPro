# ADR-007 — Supported compute backends: CUDA and recent ROCm only

- Status: accepted
- Date: 2026-10-26
- Supersedes: nothing; it narrows the backend list that ADR-003 and the
  installer had left open.

## Context

`install.sh` could install four backend shapes: CUDA (the default when no flag
was passed), CPU (`--no-gpu`), Vulkan (torch on CPU plus a Vulkan
`llama-cpp-python`) and ROCm. The choice was a flag, not a decision: running
`./install.sh` on the AMD reference machine without arguments installed
`torch==... +cu126` into the working venv, and the pipeline then ran on the CPU
without a single error — an episode took a whole session instead of 27 minutes,
and nothing in the UI said so. The same accident happened through
`linux_tests/test_install_retry.py`, which executed the installer against the
real venv.

At the same time the backends that only degrade silently were the ones nobody
runs: CPU and Vulkan installs transcribe on the CPU (~10x slower), RDNA2 needs
an unofficial `HSA_OVERRIDE_GFX_VERSION`, and none of them was ever validated
end to end on real media.

## Decision

Two backends are supported, and they are the only ones the installer can
produce:

| Hardware | Backend | Stack |
|---|---|---|
| NVIDIA on Linux x86_64 | `cuda` | `requirements.txt` (torch +cu126), CUDA wheel of `llama-cpp-python` |
| AMD RDNA3 / RDNA4 / CDNA with `/dev/kfd` accessible | `rocm` | `requirements-rocm.txt` (torch +rocm7.0), `ctranslate2` ROCm wheel, Vulkan wheel of `llama-cpp-python` |

Everything else is refused, with an explanation and no fallback: RDNA2 and
older, no discrete GPU, Vulkan, CPU, Python 3.13+, non-x86_64.

Rules that make the decision safe:

1. **Deny by default.** Without `--backend` the installer detects the hardware
   (`utils/gpu_detect.py`) and either proceeds with the detected backend or
   stops. It never "picks the closest" anything.
2. **A mismatch is an error.** `--backend=cuda` on AMD, `--backend=rocm` on
   NVIDIA or without a usable device stops the script. The only escape hatch is
   `--force-backend`, meant for cross-builds (an NVIDIA container image built on
   an AMD host) and for the test suite, and it always prints a warning.
3. **The install is verified, not assumed.** After the pip steps the installer
   imports `torch` and `ctranslate2` and checks the runtime (`torch.version.hip`
   / `torch.version.cuda`, `cuda.is_available()`, `get_cuda_device_count()`).
   If the backend does not answer, the installation fails and no stamp is
   written.
4. **The venv carries its backend.** `venv/.tp-backend` records backend,
   versions, requirements file and date. Re-running the installer with a
   different backend refuses to replace torch unless `--force-backend` is given,
   and the runtime compares the stamp with what the libraries actually report.

## Consequences

- The `cpu` and `vulkan` branches of `install.sh` and the `cpu` service of
  `docker/compose.yaml` are removed. `--no-gpu` no longer exists: a machine
  without a supported GPU cannot be installed, and that is intentional.
- The pipeline keeps its internal `cuda → cpu` fallback (removing it is a large,
  risky refactor), but a job that needs the GPU no longer starts when the
  runtime cannot provide it: it fails in seconds with the remedy, unless the
  job explicitly asks for CPU.
- Users on unsupported hardware are out of scope. That is a product choice, not
  a technical limit: reverting means editing the backend table in `install.sh`
  and this ADR, and adding a tier to `docs/SUPPORT_MATRIX.md`.
- The Docker images inherit the same list: `BACKEND=rocm|cuda`, nothing else.

## Alternatives rejected

- **Keep CPU as a supported fallback**: it is the exact shape of the incident —
  a working-looking system that is 10x slower — and it was never validated on
  real media.
- **Keep RDNA2 via HSA override**: unofficial, slow in bf16, unvalidated here;
  the detector still recognises it so the refusal can explain itself.
- **Make `--backend` mandatory instead of `auto`**: it moves the responsibility
  to the user and still allows the wrong choice; detection plus refusal is
  both safer and shorter to type.
- **Trust the detection without the post-install check**: a heuristic can be
  wrong, and the check costs two seconds.
