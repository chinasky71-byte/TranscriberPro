# Progress log

Append-only record of working sessions. The newest entry goes at the top.
Every session that touches the repository must add an entry before the merge.

## Template

```markdown
## YYYY-MM-DD — short title

- Branch / commits:
- Goal:
- Done (files, commands):
- Tests and results:
- Decisions / ADRs:
- Known issues:
- Next step:
```

## 2026-10-25 — WebUI specification and agent entry point

- Branch / commits: `docs/webui-spec` (this branch).
- Goal: make `AGENTS.md` the single entry point, record the project state and
  write the WebUI specification and step plan.
- Done: `AGENTS.md` now has project description, reading order, repository
  map, workflow; added `docs/STATUS.md`, `docs/PROGRESS.md`,
  `docs/README.md`, `docs/webui/SPEC.md`, `docs/webui/PLAN.md`; guard test
  `linux_tests/test_docs_index.py`.
- Tests: `test_docs_index.py` and the existing docs link tests.
- Decisions: WebUI binds `0.0.0.0` with a required token; path-only input in
  v1; HTMX + Alpine, no Node build; Qt GUI frozen; OCR review at Step 5.
- Known issues: service layer and API not started.
- Next step: Step 1, extract `core/jobs/`.

## 2026-10-25 — Two lines: legacy master and development

- Branch / commits: `docs/development-strategy`, merged as `a71ddc4`.
- Goal: record that `master` is the legacy line maintained outside this
  workflow and `development` is the product line, with a possible future
  repository split.
- Done: ADR-006; `docs/CONTRIBUTING.md` updated (branch model, merge strategy,
  releases).
- Tests: docs link tests.
- Decisions: no `development` → `master` merges for now; master changes are
  merged into development; split deferred.
- Next step: WebUI specification.

## 2026-10-25 — Benchmarks and results in the repository

- Branch / commits: `bench/asr-translation`, merged as `0bbab20`.
- Goal: measure ASR and translation engines on the AMD machine and keep the
  results in git, sanitized.
- Done: `bench/` harness (ASR, translation, HTTP engines, NLLB-FT, hardware
  fingerprint, sanitized export); `docs/benchmarks/2026-10-25/`.
- Tests: bench unit tests, guard tests.
- Results: Whisper WER 0.000; Qwen3 WER 0.0037; TranslateGemma GGUF balanced;
  NLLB-FT best under 8 GB; gemma4 best chrF but slow; gpt-oss fast but
  11.5 GB; LFM rejected.
- Known issues: single synthetic clip; HTTP cold/warm difference; NLLB-FT
  non-commercial license.
- Next step: none for the harness; WebUI specification.

## 2026-10-25 — Architecture baseline

- Branch / commits: `docs/architecture-baseline`, merged as `0bbab20` (same
  merge as the benchmarks, separate history below it).
- Goal: define layers, contracts, runtime/platform split and guard rails.
- Done: `docs/architecture/`, ADR-001…005, `docs/SUPPORT_MATRIX.md`,
  `docs/CONTRIBUTING.md`, PR template, guard tests
  (`test_architecture_boundaries.py`, `test_events_schema.py`,
  `test_docs_links.py`), `utils/events.py` `step` event documented.
- Tests: 11 guard tests green; full suite green except the two `install_retry`
  tests caused by the local venv (proven green in a clean worktree).
- Next step: benchmarks.

## 2026-10-24 — AMD validation and fixes

- Branch / commits: `test/amd-rocm-validazione`, merged into master as
  `1.34.34` (legacy line).
- Goal: make the stack work on Linux + AMD ROCm.
- Done: Python 3.12 via uv in `.tools/`; system deps; ROCm install; fixes:
  `torchaudio.info` → `soundfile.info`, ctranslate2 bootstrap before torch
  (Linux), NLLB `device_map={"": 0}` on ROCm, translation success gate
  (`translation_max_untranslated_pct`, fatal GPU errors, audit before writing);
  `docs/VALIDAZIONE_AMD_2026-10-24.md`.
- Tests: full suite; AMD smoke test; pipeline on the sample (Whisper 98.8%,
  Qwen3 99.5% similarity at the time).
- Known issues: GUI skipped (no display); Windows untested.
- Next step: architecture baseline.
