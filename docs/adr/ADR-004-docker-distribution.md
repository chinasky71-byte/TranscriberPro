# ADR-004 — Docker is the distribution artifact

- Status: accepted
- Date: 2026-10-25

## Context

Native installation requires Python, system packages, GPU wheels and driver
compatibility, and differs on every distribution. The pipeline is headless and
the WebUI can be served over HTTP, so the application fits a container.

## Decision

Ship one image per backend (`linux-rocm`, `linux-cuda`, `linux-cpu`). Build
with a multi-stage Dockerfile and an `ARG BACKEND`. Ship no drivers and no
models inside the image; mount models, configuration and media as volumes.
Tag images with backend, version and commit.

## Alternatives considered

- Native installers only: rejected, unmaintainable across distributions.
- One image with all backends: rejected, conflicting wheel sets
  (CUDA vs ROCm torch).
- Bake models into the image: rejected, size and licensing.

## Consequences

- `TP_DATA_DIR` and `TP_MODELS_DIR` must become configurable.
- The WebUI is mandatory; the GUI is not available in containers.
- CI builds images; GPU tests run on self-hosted runners.
- Windows is supported only through WSL2 with NVIDIA, or via the legacy native
  path while it exists.
