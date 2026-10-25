# ADR-005 — Explicit support matrix

- Status: accepted
- Date: 2026-10-25

## Context

The project grew from Windows/NVIDIA and later gained Linux/AMD support. Without
an explicit matrix, every combination looks supported and untested claims
accumulate.

## Decision

Publish a support matrix with three tiers:

- Tier 1 — supported and tested: Linux + AMD (ROCm).
- Tier 2 — supported, best-effort: Linux + NVIDIA (CUDA), with CI or community
  validation.
- Tier 3 — best-effort: CPU, Vulkan on older AMD/Intel.
- Windows native: frozen, no new features.
- macOS: not supported.

## Alternatives considered

- Support everything equally: rejected, no capacity to test it.
- AMD only: rejected for now; NVIDIA code exists and is useful to users.

## Consequences

- Documentation and error messages state the tier.
- Unsupported hardware fails fast with a clear message.
- Adding a tier requires hardware access and a test plan.
