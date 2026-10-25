# ADR-001 — One codebase, N distribution artifacts

- Status: accepted
- Date: 2026-10-25

## Context

Supporting every permutation of OS, GPU vendor and driver in one installation
path is not maintainable. Splitting the code into one repository per stack
would duplicate the business logic, the routing and the tests.

## Decision

Keep a single codebase. Separate only the **distribution artifacts** (Docker
images and requirements files) per stack: Linux+ROCm, Linux+CUDA,
Linux+CPU/Vulkan. A thin optional native installer may exist for development,
but the supported distribution is the container image.

## Alternatives considered

- One repository per stack: rejected, duplicates 90% of the code.
- Core package plus four distribution repositories: acceptable later, but not
  needed while the packaging is small.
- One repository with all permutations supported natively: rejected as
  unmaintainable.

## Consequences

- One issue tracker, one test suite, atomic cross-cutting changes.
- CI must build and test several artifacts.
- The support matrix must be explicit about what is tested and what is not.
