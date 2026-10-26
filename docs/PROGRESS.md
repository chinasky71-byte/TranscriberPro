# Progress log

Append-only record of implementation steps and working sessions. The newest
entry goes at the top.

**Hard rule (`AGENTS.md`): every implementation step is recorded here before
its branch is merged** — one entry per pull request, not one per session. A
step is not done until its entry exists: branch and commits, goal, what
changed, tests and results, decisions, known issues, next step. Entries carry
a date and, when the step is part of a larger effort, the step number from
`docs/webui/PLAN.md`.

The shape is enforced by `linux_tests/test_docs_progress.py` (required fields,
newest-first order, the rule stated in `AGENTS.md` and in this header).

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

## 2026-10-26 — WebUI Step 9: file picker and multi-add

- Branch / commits: `feat/webui-picker`.
- Goal: choose the media from the browser instead of typing an absolute path,
  and queue several files at once, without turning the WebUI into a library
  scanner.
- Done: `web/browse.py` (read-only lister: `VIDEO_EXTENSIONS`, `natural_key`,
  `has_subtitle`, `start_dir`, `resolve_dir`, `list_directory`, `MAX_ENTRIES`);
  API `GET /api/browse`; UI partial `GET /ui/browse` and `_picker.html`
  (roots, breadcrumb/up, folders, checkboxes, `SRT` badge, truncation notice);
  dashboard form gains the picker opened by `<details>`/`<summary>` so it needs
  no JavaScript at all, the `Skip files that already have a subtitle` checkbox
  and repeated `paths` fields; `POST /ui/jobs` queues one job
  per selected file (dedupe, per-path errors, `skip_existing`); new whitelisted
  config key `picker_start_dir` (`utils/config.py`, `web/config_schema.py`,
  `_settings.html` `dir` kind with the `/set/root/dir` placeholder); CSS for the
  picker and `[x-cloak]`.
- Tests and results: `linux_tests/test_web_picker.py` (14 tests: listing and
  folder-first order, hidden entries skipped, `SRT` badge, symlink escape
  dropped, path outside the roots / relative / file / missing rejected,
  `picker_start_dir` honoured and ignored when outside the roots, entry limit
  and `parent`, JSON API plus auth, multi-add, `skip_existing`, empty selection,
  mixed valid/invalid, settings round trip). Full suite: 684 passed,
  11 skipped, only the two known `test_install_retry.py` failures.
- Decisions / ADRs: no ADR. The picker lists only what the queue already
  accepts (`web/paths.py::is_allowed`), so there is one rule for both; no
  database, no recursion, no upload, no index — the non-goal "no library
  scanner" in the SPEC still holds. `has_subtitle` matches any `<stem>.*.srt`
  instead of a language suffix because the pipeline writes ISO 639-1. A start
  folder outside the roots is ignored rather than rejected: the setting cannot
  brick the picker. The panel is a native `<details>` element, not an Alpine
  toggle: a browser with stale cached HTML or without Alpine still opens the
  listing, and HTMX only fetches it.
- Known issues: the picker does not probe the media (no ffprobe), so duration,
  embedded subtitle tracks and audio languages are not shown; the entry limit
  is a silent cap beyond the notice line. Two robustness items found while
  running a real file are still open: the temporary folder under `TMPDIR` is
  left behind when a job is cancelled (`SIGKILL` skips the pipeline `finally`),
  and the pipeline pre-loads Whisper even with
  `transcription_engine_mode=qwen3`, so a `ctranslate2` without the GPU runtime
  fails a job that would never use it. Environment note from the same session:
  the local venv had `torch 2.8.0+cpu`; it was reinstalled to
  `2.10.0+rocm7.0` plus the `ctranslate2` 4.8.4 ROCm wheel, which restored GPU
  processing (a 133-minute episode finished in 25 minutes).
- Next step: run the picker against the real library and queue the remaining
  episodes; then the two robustness items above and the container build
  (Step 8 acceptance).

## 2026-10-26 — Documentation: SPEC/API sync and the PROGRESS rule

- Branch / commits: `docs/spec-sync` (this entry ships in the same commit).
- Goal: close the documentation gaps found while checking the session, and make
  the progress log a hard requirement instead of a habit.
- Done: `AGENTS.md` Workflow gains the rule "every implementation step is
  recorded in `docs/PROGRESS.md` before its branch is merged, one entry per
  PR"; `docs/PROGRESS.md` header restates the rule and now lists every field;
  `docs/CONTRIBUTING.md` has rule 10 and a PR-readiness item; new guard
  `linux_tests/test_docs_progress.py` (7 tests: fields, newest-first order,
  heading format, rule stated in `AGENTS.md`/header, CONTRIBUTING link);
  retroactive entries for `docs/arch-sync` and `docs/status-close`; SPEC §7
  marked page by page and §6 completed with the OCR/glossary endpoints and the
  new parameters; `testing.md` lists the four new test modules.
- Tests and results: `test_docs_progress.py` 7 passed, docs index/links tests
  green, full `linux_tests` unchanged apart from the two known
  `test_install_retry.py` failures.
- Decisions / ADRs: the guard requires the full template only for entries dated
  2026-10-26 or later, because the log is append-only and older entries are not
  rewritten; SPEC §7 uses `done` / `not implemented` instead of a phase number
  once the phase is over.
- Known issues: the guard checks structure, not honesty; a step merged without
  its entry is only caught if someone runs the suite before the next merge.
- Next step: build and validate the container images on a host with a daemon
  (Step 8 acceptance), then the library scanner.

## 2026-10-26 — WebUI Step 8: container artifacts

- Branch / commits: `feat/docker`.
- Goal: ship the WebUI and the pipeline as one image per backend.
- Done: `docker/Dockerfile` (multi-stage, `ARG BACKEND`, no drivers, no
  weights, non-root `tp`, `/data` and `/models` volumes, healthcheck,
  `python -m web.main --host 0.0.0.0`); `docker/compose.yaml` (profiles
  `rocm`/`cuda`/`cpu`, AMD devices and groups, NVIDIA reservation, mandatory
  `TP_WEB_TOKEN`); `.dockerignore`; `docker/README.md`.
- Tests: `linux_tests/test_docker.py` (9 guard tests): one image per backend,
  unknown backend fails the build, no driver packages, no models/media in the
  image, no Qt, non-root plus healthcheck, dirs on volumes, compose wiring for
  AMD and NVIDIA, volumes for data/models/media, build context cleaned.
  `docker compose -f docker/compose.yaml --profile rocm config` renders (exit
  0) and refuses to render without `TP_WEB_TOKEN`.
- Decisions: images carry code and system tools only; no driver, no weights,
  no Qt; the token is mandatory in compose (`:?`) because the server binds
  `0.0.0.0`; media is mounted read-write because the SRT is written next to the
  video.
- Known issues: the images were **not built** here — `docker` daemon not
  reachable in this session and the rocm/cuda layers are several GB, so the
  acceptance "`docker compose up` produces the SRT" is still open. `cpu` image
  builds llama-cpp-python from source (slow) and is a smoke-test target only.
  `dashboard`/WebUI behind a TLS proxy is documented, not provided.
- Next step: build the three images on a host with a container daemon, run the
  rocm profile on the reference machine and record the result here.

## 2026-10-26 — Session close: STATUS handoff

- Branch / commits: `docs/status-close`; commit `f8b0f5c`, merged as `a4ce112`.
- Goal: make a cold start see Steps 4–8 as finished instead of "next: Step 4".
- Done: `docs/STATUS.md` rewritten around the new state (merge `4ef8397`,
  WebUI pages, GUI optional, containers), open items restated as open
  (container build validation, library scanner, glossary report generation,
  CSRF, positive OCR run).
- Tests and results: full `linux_tests` 663 passed, 11 skipped; only the two
  known `test_install_retry.py` failures, which also fail on the unmodified
  branch (checked with `git stash`).
- Decisions / ADRs: no ADR; the STATUS page stays the single place for "what
  works / what is next", the details live in PROGRESS.
- Known issues: this step added no PROGRESS entry at the time; it is recorded
  here retroactively (same day) because the rule was introduced afterwards.
- Next step: the documentation sync PR (SPEC/API and the PROGRESS rule).

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

## 2026-10-26 — Architecture pages aligned with the code

- Branch / commits: `docs/arch-sync`; commit `e6c4780`, merged as `01b47e5`.
- Goal: remove the statements that contradicted the code after WebUI Steps 1–3.
- Done: `docs/architecture/README.md` (the `core -> gui` exception for
  `file_progress` is resolved, `web/`/`core/jobs` no longer labelled *target*),
  `layers.md`, `contracts.md` and `config.md` (no environment override for
  config keys, only `TP_DATA_DIR`/`TP_MODELS_DIR`), `events.md` (consumer is
  `core/jobs/progress.py`), `testing.md` (web UI/paths tests, legacy root
  `unittest` modules that `pytest linux_tests` does not collect), `web/README.md`
  (Step 3 UI present), `docs/README.md` (`CLAUDE_INTEGRATION.txt` indexed as
  historical Italian documentation, to be translated as separate work).
- Tests and results: docs index and link tests 10 passed.
- Decisions / ADRs: `CLAUDE_INTEGRATION.txt` is indexed, not translated, because
  a full translation is separate work (documentation rule, point 3).
- Known issues: the legacy root tests are documented, not moved; they need the
  GUI removal step.
- Next step: WebUI Step 4, settings and history.

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
