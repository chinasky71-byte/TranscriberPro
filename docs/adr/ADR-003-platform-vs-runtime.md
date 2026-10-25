# ADR-003 — Separate platform services from the GPU runtime

- Status: accepted
- Date: 2026-10-25

## Context

“Platform” was being used for two different concerns: operating-system
behaviour (paths, processes, notifications) and accelerator behaviour (CUDA,
ROCm, Vulkan, initialization order, compute types). They vary independently:
Linux can be CUDA or ROCm; the same CUDA stack can be Linux or Windows.

## Decision

Two layers:

- `platform_services/` — OS facts and side effects.
- `runtime/` — GPU backend detection and policy.

Both expose capabilities through `Caps` / `RuntimeProfile`, injected into the
domain. The domain never inspects `sys.platform` or `torch.version.hip`.

## Alternatives considered

- One “platform” layer for everything: rejected, mixes two axes and recreates
  the conditional soup.
- No layer, checks inline: rejected, already caused platform-specific bugs.

## Consequences

- Clear ownership: OS bugs go to platform services, GPU bugs to runtime.
- Parallel work on AMD and NVIDIA touches different files.
- The existing inline checks are tracked in a guard-test allowlist that must
  shrink over time.
