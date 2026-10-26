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

## 2026-10-26 — WebUI Step 7: PyQt optional

- Branch / commits: `feat/pyqt-optional`.
- Goal: a default install without Qt (ADR-002).
- Done: `requirements-gui.txt` holds `PyQt6==6.10.2`, `PyQt6-Qt6`, `PyQt6_sip`;
  those pins removed from `requirements.txt` and `requirements-rocm.txt`
  (comment pointing at the new file); `main.py` imports Qt behind
  `try/except ImportError` and exits 2 with a message naming both
  `requirements-gui.txt` and `python -m web.main`; `install.sh --with-gui`
  installs the optional file, default installs do not.
- Tests: `linux_tests/test_gui_optional.py` (4 guard tests): no Qt pin in any
  default requirements file, Qt pinned in `requirements-gui.txt`, install
  script exposes the flag, `main.py` keeps the guarded import (AST check for an
  unguarded module-level import and for a `try` that catches `ImportError`).
  Simulated a missing Qt with `sys.modules['PyQt6'] = None`: `main.py` printed
  the message and exited 2. Full suite: 654 passed, same two pre-existing
  `test_install_retry.py` failures.
- Decisions: `onnxruntime` stays in the default requirements (it must be
  imported before Qt and is used by the VAD); the GUI entry point is kept
  working for users who install the extra file, not removed (removal happens
  after WebUI parity, ADR-002).
- Known issues: the Qt GUI is still present in the tree and imports `core.jobs`
  only; `README.md`/`CHANGELOG.md` (historical, Italian) still describe the
  GUI-first install and are not updated in this step.
- Next step: Step 8, Docker.

## 2026-10-26 — WebUI Step 6: glossary review, and the library scanner scoped out

- Branch / commits: `feat/webui-glossary`.
- Goal: review the per-show glossary candidates from the browser.
- Done: `web/glossary.py` (read-only view of
  `glossary_engine.build_glossary_candidates` reports plus a
  `<report>.decisions.json` written next to the report); API
  `/api/glossary/reports` (list, detail, decide by index); pages `/glossary`
  and `/glossary/{name}` with per-term decision, rendering and note; nav link.
- Tests: `linux_tests/test_web_glossary.py` (7 tests) on a fixture report:
  list/view, decision round trip, decisions file separate from the report,
  name traversal rejected, pages, login redirect, empty directory.
- Decisions: the web layer does **not** build reports. `build_full_report()`
  needs the show folder, an English reference track and the Qwen extractor
  (long GPU job), and `glossary_engine`'s CLI does not write the full report
  at all; the page shows the one-line Python call instead and reviewers only
  read and decide. Library scanner: **not implemented here**, it is a separate
  FastAPI + SQLite service (`library scanner per server- va su docker/`) with
  its own data model and a 1290-line Qt widget as the only reference; it needs
  real media to validate and a decision about where its database lives, so it
  stays a separate work item (see `docs/webui/PLAN.md`).
- Known issues: no CSRF token; reports must be produced and copied under
  `TP_DATA_DIR/glossary/` by hand; no bulk approve.
- Next step: Step 7, optional PyQt.

## 2026-10-26 — WebUI Step 5: OCR review

- Branch / commits: `feat/webui-ocr`.
- Goal: correct bitmap-subtitle OCR in the browser with the same data contract
  as the Qt dialog.
- Done: `core/ocr_review_job.py` (worker CLI, `ocr` and `writeback` modes,
  sidecar only); `web/ocr_review.py` (session store under `TP_DATA_DIR/ocr/`,
  atomic JSON, subprocess runner, image serving, text limits); API
  `/api/ocr/sessions` (create/list/detail/update event/image/write-back/
  delete); pages `/ocr` and `/ocr/{id}` with self-polling while the worker
  runs and a `flagged` filter; nav link, grid styles.
- Tests: `linux_tests/test_web_ocr.py` (8 tests) with a synchronous fake
  runner that writes the same files as the worker: lifecycle, validation
  (outside roots, missing file, relative path, bad language, unknown session,
  oversized text), pages, login redirect, image serving, and
  `build_events` -> `events_to_srt` on corrected text. Architecture guard
  tests still green (the worker lives in `core/`, so `web/` imports no domain
  module directly).
- Real validation: server on `127.0.0.1:8097`, real subprocess; a session on
  `samples/prova_amd_test.mp4` (no bitmap track) reached `failed` with
  "no PGS/VOBSUB bitmap subtitle track found" and the page showed it. A
  positive end-to-end OCR run needs bitmap media, which `samples/` does not
  contain yet.
- Decisions: the OCR worker is a domain CLI (`core/ocr_review_job.py`) like
  `core.pipeline_cli`, not a web module, so the layer rules hold; write-back
  is always a sidecar, never an in-place mux from the browser; sessions store
  one PNG per event instead of holding PIL images in memory.
- Known issues: no CSRF token; no real bitmap sample to validate a successful
  OCR + write-back; session files are not cleaned up automatically.
- Next step: Step 6, glossary and library pages.

## 2026-10-26 — WebUI Step 4: settings and history

- Branch / commits: `feat/webui-settings`.
- Goal: config editing and a history view from the browser, with no JSON
  access required.
- Done: `web/config_schema.py` (whitelist + value validation + secret
  masking, shared by API and UI); `GET /api/history` gains `status` and
  `limit`; `PUT /api/config` validates every value before `Config.set`;
  `GET /api/models` reads `MODEL_SPECS` without loading weights; new pages
  `/history` (filter, duration, output) and `/settings` (grouped form,
  write-only secrets, `clear:` checkbox, draft redisplay on error); nav links
  and fieldset/textarea styles.
- Tests: `test_web_api.py` +5 (history filter/limit, invalid values, secret
  clear, models registry), `test_web_ui.py` +6 (history page and filter,
  settings render and secret masking, save, validation error keeps nothing,
  secret never echoed, auth redirect). Full suite: 635 passed, 2 failed — the
  two `test_install_retry.py` failures are the documented local-venv issue and
  fail identically on the unmodified branch (verified with `git stash`).
- Real validation: server on `127.0.0.1:8098`, `TP_DATA_DIR=/tmp/tp-data`,
  token auth; `/settings` 200, config PUT accepted, invalid value 400,
  `/api/models` lists the registry; `samples/prova_amd_test.mp4` queued over
  HTTP and finished `done` in ~285 s with `prova_amd_test.it.srt`; history
  filter and page list the job. Server stopped afterwards.
- Decisions: one schema module for the API and the UI so the two write paths
  cannot drift; `allowed_media_roots` must be existing absolute directories;
  an empty secret field never overwrites, the `clear:` checkbox removes.
- Known issues: no CSRF token (SameSite=Lax only, as recorded in Step 3);
  history is in memory + `jobs.json`, not a separate archive.
- Next step: Step 5, OCR review page.

## 2026-10-25 — Documentation sync (handoff)

- Branch / commits: `docs/progress-sync`; commit `92c2580`, merged as `31bd740`.
- Goal: make a cold start unambiguous.
- Done: commit/merge hashes for WebUI Steps 1–3 in `PROGRESS` and `PLAN`;
  `STATUS` updated with the last merge and the WebUI start command.
- Tests: docs index and link tests (10 passed).
- Next step: Step 4, settings and history.

## 2026-10-25 — WebUI MVP (Step 3)

- Branch / commits: `feat/webui-mvp`; commit `ba9ba99`, merged as `a9c0975`.
- Goal: browser interface for dashboard, queue, logs.
- Done: Jinja2 templates (`base`, `index`, `_status`, `_queue`, `login`),
  HTMX + Alpine vendored locally, `web/ui.py` routes (page, queue/status
  partials, add/cancel/remove, login/logout), cookie session auth, CSP and
  security headers, static CSS/JS.
- Tests: 6 UI tests (render, static + headers, form add, invalid path, login
  flow, open-redirect); real smoke test: 303 without cookie, login, form add,
  SSE events (created/status/log), job done in ~78 s with SRT.
- Decisions: Alpine used for the logs panel; token stored in an HttpOnly
  cookie for browser sessions; CSP allows `unsafe-eval` for Alpine expressions
  (no inline scripts); media roots and token still from env/config.
- Known issues: no settings/history/OCR/glossary pages yet; no CSRF token
  beyond SameSite=Lax; logs panel is per job only.
- Next step: Step 4, settings and history.

## 2026-10-25 — Web API (WebUI Step 2)

- Branch / commits: `feat/web-api`; commit `66c426e`, merged as `cb962cc`.
- Goal: expose the shared job queue over HTTP with auth, path validation and SSE.
- Done: `web/` (FastAPI factory, entry point, auth, paths, SSE bridge);
  `TP_DATA_DIR`/`TP_MODELS_DIR`; manager `keep_alive` mode; whitelisted
  config API with masked secrets; requirements-web.txt; web/README.md.
- Tests: 16 unit tests (paths, API with fake runner, SSE bridge, env dirs);
  real smoke test on 127.0.0.1:8099: auth 401/200, real job completed in ~78 s
  with SRT and history, second job cancelled via HTTP in ~2 s.
- Decisions: token required on non-loopback; token accepted as query param for
  SSE only; media roots from `TP_MEDIA_ROOTS` or config, else home.
- Known issues: no UI yet; no login page (token only); job step detail is the
  next UI step.
- Next step: Step 3, WebUI MVP.

## 2026-10-25 — Job service extracted (`core/jobs`)

- Branch / commits: **deviation** — the branch `feat/jobs-service` was not
  created and the work landed directly on `development` as `e87e8ae`
  (already pushed; published history is not rewritten). Future steps use
  feature branches. Documentation correction: `54a1913`.
- Goal: one implementation of the queue, shared by CLI and (later) WebUI.
- Done: `core/jobs/` with `Job`, `ProcessRunner`, `JobManager`, `EventHub`,
  atomic persistence, legacy status snapshot; `core/queue_runner.py` is now a
  thin client; `FileProgress` moved to `core/jobs/progress.py` with a shim in
  `gui/file_progress.py`; boundary allowlist for `core -> gui` is now empty.
- Tests: `linux_tests/test_jobs_manager.py` (8 tests, fake runner); headless
  queue on a real sample (71 s, status schema and SRT correct).
- Decisions: manager persists only when a path is given (the CLI keeps its own
  `--status` file); Qt worker untouched until WebUI parity. Process note: a
  feature branch must be created **before** the first commit.
- Known issues: GUI still has its own queue; API not started.
- Next step: Step 2, HTTP API.

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
