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

## 2026-10-26 — WebUI Step 11: sidebar layout, queue-first dashboard, timings

- Branch / commits: `feat/webui-layout`.
- Goal: navigation on the left and data on the right, the landing page showing
  the state of the queue instead of the machine, and real timings while a job
  runs.
- Done: `base.html` rewritten as a shell with an `<aside class="sidebar">`
  (Queue, Status, History, OCR, Glossary, Settings, API, auth pill, logout) and
  a `<main class="content">`, with the current section highlighted through the
  new `path` value that `_render` passes to every template; the system card moved
  to its own `/status` page (`status.html`, new route) which also shows engine,
  target language, data dir and models dir; the dashboard opens on a hero block
  with the active job (name, progress bar, phase, **elapsed**, estimated
  remaining, log/cancel) and the queue counters; the job table gained a **Time**
  column with elapsed for running jobs and total time for finished ones;
  `_hms`, `_elapsed_of` and `_eta_of` format the durations (the estimate is
  labelled and only shown from 5% on); the auth warning became a compact banner
  on every page; `_queue.html` now takes its context under `queue` so the page
  and the HTMX partial share one shape; CSS for the shell, the sidebar, the hero
  and the pills, with the sidebar collapsing to a bar under 760 px.
- Tests and results: `test_web_ui.py` +5 (sidebar order and active item,
  queue-first landing with a running job and "12m 34s elapsed", elapsed/total in
  the table, the helper formatting, `/status` details) and the system-card tests
  moved to `/status`. Suite: 744 passed, 11 skipped, 0 failed. Verified live: the
  landing page renders `Nothing running` with the counters, `/status` returns 200
  with the system facts, and the queue table shows `25m 06s` for the finished
  episode.
- Decisions / ADRs: no ADR. The dashboard answers "what is happening now", the
  Status page answers "can this machine work": two questions, two pages. The
  estimated remaining time is derived from the achieved percentage, so it is
  explicitly labelled `est.` and hidden below 5%.
- Known issues: the estimate is naive (it assumes a constant rate across
  phases, while Demucs and ASR have different speeds); the logs panel is still a
  floating card at the bottom of the dashboard.
- Next step: container validation (Step 8) remains the only open acceptance;
  otherwise this closes the WebUI work.

## 2026-10-26 — ASR knobs measured: batch and chunk length are not a speed lever

- Branch / commits: `docs/asr-ab-measurements`.
- Goal: answer, with numbers instead of intuition, whether the ASR half of the
  wall time can be shortened by configuration alone (bigger batch, longer
  chunks) without touching the model.
- Done: `bench/asr_ab.py` (harness: one variant per run, isolated `TP_DATA_DIR`,
  phase timings from `@@TPEV@@`, `build_config`/`parse_events`/`phase_timeline`
  as pure functions) and `bench/asr_ab_variants.json`;
  `docs/benchmarks/2026-10-26-asr-knobs.md` with method, table and conclusion;
  `docs/STATUS.md` records the outcome so nobody repeats the experiment.
- Tests and results: `linux_tests/test_bench_asr_ab.py` (config building,
  profile lock, event parsing, timeline, summary, CLI validation). Measurement
  on a fixed 10-minute clip, four runs: current config ASR 64.3 s; profile
  balanced (batch 8) 63.6 s; profile batch (batch 8) 65.1 s; chunk 45 s
  **221.5 s**. Battery of the full episode stays as recorded (25 and 27 minutes
  for 134 and 144 minutes of audio).
- Decisions / ADRs: no ADR, and **no configuration change**: the current
  `chunk 20/10/25` + profile `maximum` + batch 2 is the best of the four tested.
  The free VRAM is not a lever (the engine is compute-bound per chunk), and
  longer chunks are 3.4x slower because generation is autoregressive. One
  trap documented: `transcription_profile_locked` defaults to true and makes the
  profile read-only, so the first A/B measured the same configuration four
  times; the harness forces it to false and the guard test pins that.
- Known issues: output is not bit-exact across runs (bfloat16 + batched
  generation): three runs of the same variant produced 553, 554 and 556 cues, so
  future comparisons must treat a few-cue difference as noise.
- Next step: the remaining levers are structural (overlap Demucs with ASR) or
  model-level (needs a human reference set); both are out of scope for now.

## 2026-10-26 — Temp folders of killed jobs no longer stay in RAM

- Branch / commits: `fix/temp-cleanup`.
- Goal: cancel and crash left the pipeline work folder behind — 854 MB of
  extracted audio and chunks in `/dev/shm` (i.e. RAM) after one cancelled
  episode — and the test suite copied ~485 MB of repository per test into
  `/tmp`, which on the reference machine is also tmpfs.
- Done: `utils/temp_cleanup.py` (`temp_base`, `stale_dirs`, `sweep`,
  `sweep_summary`, `directory_size`) removes only `$TMPDIR/TranscriberPro/vid_*`
  folders, with an age filter; the sweep runs at startup of `web.main` and
  `core.queue_runner` (nothing can be running) and right after a job ends
  `cancelled`/`failed` in `JobManager._run_one` (one job at a time, so nothing
  in use can be deleted). `linux_tests/pytest.ini` pins
  `--basetemp=/var/tmp/tp-pytest` (disk, and pytest clears it each run, so no
  accumulation); the `full` fixture became session-scoped and ignores `.tools`
  and `samples`, so the 485 MB copy happens once instead of once per test.
- Tests and results: `linux_tests/test_temp_cleanup.py` (11: orphan removal,
  age filter, missing base, files vs folders, summary, size, manager sweeping
  after a failure and not after a success, plus guards on the pytest basetemp
  and the session-scoped fixture). Suite: all green. Measured on the reference
  machine: 854 MB of orphan chunks and 7.7 GB of pytest copies removed by hand
  before the fix (RAM in use 11 GiB -> 2.4 GiB, available 18 -> 27 GiB); after
  the fix one suite run leaves 7.7 MB in `/var/tmp` and `/tmp` stays empty.
- Decisions / ADRs: no ADR. The sweep is deliberately conservative: only our
  prefix, only the age filter, only when no job can be running. The
  `/dev/shm/u1000-Shm_*` segments leaked by killed GPU processes (150 orphans,
  1.3 GB) are **left alone**: they belong to the graphics driver (some are in
  use by running applications) and are freed at reboot.
- Known issues: the age filter is not used at the manager sweep (it removes
  every `vid_*` right after a failure) — safe because the queue runs one job at
  a time, but it would need revisiting if the manager ever runs jobs
  concurrently.
- Next step: keep an eye on `/dev/shm` growth after cancelled jobs; the
  container runs will need the same behaviour inside the image.

## 2026-10-26 — WebUI: system status on the landing page, token removed (Step 10)

- Branch / commits: `feat/webui-system-status`.
- Goal: make the state of the machine visible where the work starts, and run
  the UI without a token on a private network while keeping the mechanism.
- Done: `_system_status()` in `web/app.py` (backend stamp, GPU verdict from
  `utils/backend_preflight.py`, torch/HIP/CUDA/ctranslate2 versions, device
  count, `TMPDIR` with free space) exposed in `/api/status` and rendered by
  `_status.html` as a "System" card with two conditional alerts — GPU not
  usable (with the `./install.sh --verify-only` remedy) and "No authentication";
  `web/main.py` gains `--no-auth` / `TP_WEB_NO_AUTH=1`, which serves without a
  token on any interface, prints a warning at startup and no longer refuses the
  bind; `/login` redirects to `/` when no token is configured; `--no-auth` in
  `web/README.md`, SPEC §3/§7/§8 and `docs/STATUS.md`.
- Tests and results: `test_web_ui.py` +4 (system card with backend/versions/work
  dir, GPU-problem alert with the remedy, no-auth warning plus `/login`
  redirect, `/api/status` payload). Suite: 720 passed, 11 skipped, 0 failed.
- Decisions / ADRs: no ADR. The token stays in the code (it can be re-enabled
  with one environment variable) but the reference deployment runs with
  `--no-auth` behind Twingate; the warning is part of the page, not a hidden
  note, because without auth anyone reaching the port can queue jobs.
- Known issues: `/api/status` runs the cached preflight probe, so the first
  request after five minutes can take a couple of seconds; the "System" card
  shows the discrete GPU only (the iGPU appears in `/api/status`).
- Next step: merge the three backend branches, push, and re-run one episode to
  confirm the UI status and the preflight agree with a real job.

## 2026-10-26 — Runtime preflight: a GPU job no longer starts on a CPU venv

- Branch / commits: `feat/gpu-preflight`.
- Goal: close the second half of the ADR-007 problem — the installer now refuses
  a wrong backend, but nothing stopped a job from starting on a venv that had
  been changed by hand afterwards.
- Done: `utils/backend_preflight.py` reads `venv/.tp-backend`, probes the real
  libraries in a subprocess (torch version, HIP/CUDA runtime,
  `cuda.is_available()`, device count, ctranslate2 device count), caches the
  answer for five minutes and turns it into a verdict plus a remedy sentence;
  `JobManager` accepts a `preflight(job)` hook and fails the job before spawning
  the pipeline; `web.main` prints the backend banner at startup and passes the
  check, `core.queue_runner` does the same for the CLI; new job override
  `allow_cpu` (checkbox "Allow CPU" in the add form) lets a single job skip the
  check on purpose; `install.sh --verify-only` re-checks an existing venv and
  rewrites the stamp without installing anything (the remedy when a stamp is
  missing), and the stamp now records ctranslate2 by importing it after torch.
- Tests and results: `linux_tests/test_backend_preflight.py` (11: stamp parsing,
  healthy/missing/wrong-runtime reports, cache, `allow_cpu`, `use_gpu=false`, the
  manager failing the job without calling the runner, override sanitising) and
  two installer tests for `--verify-only`. Suite: 714 passed, 11 skipped, 0
  failed. On the reference machine `--verify-only` writes `backend=rocm`,
  `torch=2.10.0+rocm7.0`, `ctranslate2=4.8.4`, and the banner reads
  `rocm: torch 2.10.0+rocm7.0 (7.0.51831), device 2, ctranslate2 4.8.4`.
- Decisions / ADRs: ADR-007 extended in practice. The probe is a subprocess
  because the web server must not import torch; the cache keeps a ten-file queue
  at one probe. A job that fails the preflight is `failed` with the reason in
  `error` and in the job log — the same shape the UI already renders.
- Known issues: the preflight checks `use_gpu` from the config, not the
  per-engine requirement (a job that would only translate also fails when the
  GPU is missing); `utils/backend_preflight.py` has no CLI of its own, it is
  used through the queue.
- Next step: landing page with the system status and removal of the WebUI token.

## 2026-10-26 — Installer: automatic backend choice with deny-by-default (ADR-007)

- Branch / commits: `feat/backend-auto`.
- Goal: make it impossible to end up with a venv whose backend does not match
  the hardware — the accident that turned a 27-minute GPU job into a CPU job
  without a single error.
- Done: `install.sh` rewritten around a backend decision: `--backend=auto|cuda|rocm`
  (`auto` is the default, `--gpu-backend` kept as an alias), `--force-backend`
  for cross-builds and tests; `--no-gpu` and the `cpu`/`vulkan` branches removed;
  the AMD decision uses `utils/gpu_detect.py` (`path=rocm` and `/dev/kfd`
  accessible) and refuses RDNA2/`rocm_override`, older families, missing devices
  and unknown hardware with an explanation; explicit mismatch refuses; a
  post-install verification imports torch/ctranslate2 and checks the runtime
  before declaring success, writing `venv/.tp-backend` only then; a venv stamped
  with another backend refuses to be replaced without `--force-backend`;
  `--with-models` reads VRAM from the detector instead of nvidia-smi; the GGUF
  downloader no longer receives `--no-gpu`. `docker/compose.yaml` loses the
  `cpu` service and `docker/Dockerfile` accepts only `rocm|cuda`.
  `docs/adr/ADR-007-supported-backends.md` records the policy, and
  `docs/SUPPORT_MATRIX.md` moves CPU/Vulkan/older-AMD to "not supported".
- Tests and results: `linux_tests/test_install_backend.py` (11 new: retired
  backends refused, unknown value refused, `auto` with no hardware stops before
  touching the venv, `auto` picks cuda, RDNA2 and older families refused,
  explicit mismatch refused, `--force-backend` allowed, stamp mismatch refuses
  without pip, same stamp proceeds, no `--no-gpu`/`NOGPU` left in the script);
  `test_install_retry.py` +2 (stamp written with backend and requirements,
  failed verification aborts and leaves no stamp) and adapted to
  `--backend=cuda --force-backend`; `test_amd_rocm_f6.py` now asserts the
  retired backends are rejected; `test_docker.py` expects two services.
- Decisions / ADRs: ADR-007. `auto` is authoritative instead of advisory, and
  the detection is backed by a real import check so a wrong heuristic cannot
  produce a "successful" wrong install. The pipeline keeps its internal
  `cuda -> cpu` fallback; the job-level refusal arrives with the runtime
  preflight (next branch).
- Known issues: the ROCm Docker image installs `requirements-rocm.txt` but not
  the `ctranslate2` ROCm wheel (the Step 8 build is still unvalidated); the
  `llama-cpp-python` Vulkan wheel for the ROCm backend is likewise only
  installed by `install.sh`, not by the image.
- Next step: runtime preflight (stamp vs reality, job refused when the GPU does
  not answer), then the landing page status and the removal of the WebUI token.

## 2026-10-26 — Session close: throughput measured, GPU verdict, docs sync

- Branch / commits: `docs/session-close` (this entry ships in the same commit).
- Goal: record what the session proved about performance, close the pending
  documentation drift and leave the tree ready for the next step.
- Done: `docs/STATUS.md` gains the measured throughput bullet (per-episode
  times, GPU occupancy, single-pass read), the current `last merge` and a
  "suite fully green" line; this entry; the two steps merged earlier today
  (`3dae384` WebUI Step 9/file picker, `d17f601` test isolation) are the only
  code changes of the session besides the ROCm environment repair.
- Tests and results: full suite on `development` after both merges, 689
  passed, 11 skipped, 0 failed (71 s). Runtime checks: `torch 2.10.0+rocm7.0`,
  `cuda True`, `ctranslate2 4.8.4`, `use_gpu=true`, picker served, HTML
  `Cache-Control: no-store`.
- Measurements (reference machine, one job at a time, AMD RX 9060 XT 16 GB):
  a 134-minute episode took 25 min; a 144-minute one took 27 min (1619.7 s per
  the pipeline clock) for 1968 cues; a third run sampled every 2 s showed the
  GPU at 94% average, 96% of samples at or above 80%, VRAM peak 7.5 GB and only
  51 MB of reads outside the extraction phase. Conclusion: the workload is
  GPU-bound, the media read is one sequential pass (~4% of the wall time) and
  staging a copy on the local disk would add I/O instead of saving time.
- Decisions / ADRs: no ADR. The pipeline chain (Demucs htdemucs, 20/10/25 s
  energy chunking with per-engine caps, Qwen3-ASR, punctuation, cleaner) stays
  untouched: it is the result of months of tuning on the hardest kind of
  material (music, audience, overlapping speech) and measured results are good.
  No quality A/B is planned until a human reference exists for the evaluation
  set; the benchmark's single synthetic clip is not a basis for model choices.
- Known issues: the reference evaluation set does not exist yet (a 10-minute
  hand-corrected slice would unlock WER-based comparisons). The cancel path
  still leaves the `TMPDIR` work folder behind, and the pipeline pre-loads
  Whisper even when the engine is Qwen3 (a `ctranslate2` without the GPU
  runtime fails a job that would never use it). The library scanner remains a
  separate service.
- Next step: container validation (Step 8 acceptance) on a host with a
  container daemon; then the two robustness items above.

## 2026-10-26 — Test isolation: the suite no longer destroys the GPU venv

- Branch / commits: `fix/install-test-isolation`.
- Goal: stop `pytest linux_tests` from reinstalling `requirements.txt` (torch
  CPU) into the working venv, which silently turned every job into a CPU job.
- Done: `install.sh` resolves the target venv with
  `VENV="${TP_INSTALL_VENV:-$ROOT/venv}"` and explains why in a comment; the
  `env` fixture of `linux_tests/test_install_retry.py` sets
  `TP_INSTALL_VENV` under `tmp_path`; three guard tests added (the override is
  honoured, the literal is present in `install.sh`, the fixture points away
  from `$ROOT/venv`).
- Tests and results: `test_install_retry.py` 20 passed — the two failures that
  had been documented as "local venv only" are gone, because they were caused
  by the real `pip install` that the test triggered. Full suite: **689 passed,
  11 skipped, 0 failed** (first fully green run), 71 s instead of 129 s.
  `torch 2.10.0+rocm7.0`, `cuda True`, `ctranslate2 4.8.4` still in place after
  the run.
- Decisions / ADRs: no ADR. The override is an installer knob, not a product
  setting: nothing else changes behaviour when the variable is absent. The
  guard tests check the literal in `install.sh` so a refactor cannot quietly
  remove the isolation.
- Known issues: other `install.sh` paths still write into `$ROOT`
  (`requirements-gui.txt` install, the local model download section) — they
  are out of the test's reach today but the same class of accident remains
  possible. The venv had already been downgraded once before this session, so
  the documented "known failure" was the symptom of this bug, not an
  environment quirk.
- Next step: re-queue the season (E02–E07) with the GPU validated, and record
  the real per-episode timings.

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
  listing, and HTMX only fetches it. The panel is always visible (no toggle at
  all: the `<details>` version could be closed by one click and looked broken),
  and every
  non-static response now carries `Cache-Control: no-store` (`web/app.py`):
  a page cached before the deploy was showing a UI without the picker, and the
  server had no header to prevent it.
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
