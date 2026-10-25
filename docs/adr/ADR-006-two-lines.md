# ADR-006 — Two lines: legacy master and development

- Status: accepted
- Date: 2026-10-25

## Context

`development` now carries the architecture baseline, the benchmark harness and
the direction for the Linux-first / WebUI / Docker product. `master` still
holds the historical desktop line (Windows/GUI) and is maintained by another
contributor. The two lines no longer have the same target, and a future split
into a separate repository is possible.

## Decision

Keep two lines for now:

- **`master`** — legacy line, maintained outside this workflow. No merges from
  `development` for now.
- **`development`** — integration line for the new product (Linux-family,
  WebUI, Docker). Feature branches merge here.
- **`master` hotfixes** are merged into `development` to stay current.
- `development` may later become a new repository. The split decision is
  deferred; when it happens, freeze `development` with a tag and choose between
  preserving history (`git filter-repo`) and a clean first commit.

## Alternatives considered

- Single line, `development` merges into `master` at every milestone: rejected
  for now, the targets differ (desktop/GUI vs server/WebUI).
- Fork immediately: premature; the new product is not stable enough.
- Abandon `master`: rejected, it still serves existing users.

## Consequences

- Two release trains and two sets of tags. `development` releases are tagged
  independently; `master` releases remain with its maintainer.
- Documentation and rules that belong to the new product (`AGENTS.md`,
  architecture, benchmarks) live only in `development`.
- Contributors must know which line they are targeting; this document and the
  contributing guide state it.
- A future repository split must carry `AGENTS.md`, `docs/architecture/`,
  `docs/benchmarks/`, `bench/`, `core/`, `utils/`, `web/`, `docker/` and the
  Linux tests, and must leave the legacy GUI/Windows pieces behind.
