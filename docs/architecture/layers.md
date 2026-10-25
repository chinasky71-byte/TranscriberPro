# Layers

Each layer has one job and a fixed set of allowed dependencies. If a change
does not fit a layer, the design is wrong, not the rule.

## Domain — `core/`

**Responsibility:** orchestration and business rules.

- `core/pipeline.py` — the processing pipeline (steps 0–9)
- `core/engines/` — ASR engines and the engine router
- `core/translator.py`, `core/llm_subtitle_translator/` — translation
- `core/audio_processor.py`, `core/aligner.py` — audio preparation and alignment
- `core/subtitle_*`, `core/diarizer.py`, `core/gender_*`, `core/ocr_auto.py`,
  `core/pgs_ocr.py`, `core/vobsub_ocr.py` — subtitle, voice and OCR logic
- `core/jobs/` *(target)* — queue and job lifecycle, shared by GUI, WebUI and CLI

**Allowed:** `contracts`, `utils`, stdlib, ML libraries.
**Forbidden:** `platform_services`, `runtime`, Qt.

**Rule:** `core/` may ask *what* is available (`Caps`) and *do* domain work,
but it must not know *how* the OS or the GPU runtime implements it.

## Job service — `core/jobs/` (present)

**Responsibility:** own the queue and the lifecycle of one subprocess per file.

Implemented modules: `models.py` (`Job`), `process_runner.py` (spawn
`core.pipeline_cli`, parse stdout/stderr, kill tree, result file), `manager.py`
(FIFO, concurrency 1, cancel, per-file overrides), `events.py` (pub/sub and
per-job log ring buffer), `persistence.py` (atomic `jobs.json`,
`running` → `interrupted` on restart).

`core/queue_runner.py` is a thin CLI client; `core/jobs/progress.py` holds the
former `gui/file_progress.py` (Qt-free). The Qt worker still uses its own queue
until the WebUI parity, but `core/` no longer imports `gui/`.

**Allowed:** `core.pipeline_cli` (as a subprocess), `utils`, stdlib.
**Forbidden:** Qt, `runtime` internals.

## Platform services — `platform_services/` (target)

**Responsibility:** OS facts and side effects that are not business decisions.

Examples: default data paths, subprocess creation flags (`CREATE_NO_WINDOW`),
process killing, file locking, notifications, display detection, Windows VRAM
settle, process bootstrap hooks.

**Allowed:** `contracts`, `utils`, stdlib, OS libraries.
**Forbidden:** `core`.

## Runtime — `runtime/` (target)

**Responsibility:** GPU backend facts and runtime policy.

Examples: backend detection (`cuda`, `rocm`, `vulkan`, `cpu`), device count and
free VRAM, initialization order (ctranslate2 before torch on ROCm), compute
type policy (`int8_float16` on CUDA, `int8` on CPU), device pinning for
multi-GPU machines, fallbacks.

**Allowed:** `contracts`, `utils`, stdlib, ML libraries.
**Forbidden:** `core`.

**Why separate from platform services:** the same OS can expose different
backends (Linux with NVIDIA = CUDA, Linux with AMD = ROCm), and the same
backend can run on different OSes. OS and accelerator are two axes.

## Infrastructure — `utils/`

**Responsibility:** technical services without domain rules.

Config singleton, logging, i18n, file handlers, model cache bootstrap, HTTP
clients (TMDB, IMDb, OpenSubtitles), GPU probing, event transport, job
overrides.

**Allowed:** stdlib, `contracts`.
**Forbidden:** `core`, `platform_services`, `runtime`.

## Web — `web/` (target)

**Responsibility:** HTTP API, SSE stream and static UI.

**Allowed:** `core.jobs`, `contracts`, `utils`, stdlib, web framework.
**Forbidden:** `runtime` internals, `platform_services` internals, Qt.

## GUI — `gui/` (legacy, frozen)

**Responsibility:** historical desktop interface. No new features.

**Allowed:** `core.jobs` (after extraction), `utils`, Qt.
**Forbidden:** new domain logic.

## Anti-patterns seen in the current code

- `if sys.platform == ...` inside `core/` — allowed only in the guard-test
  allowlist, and must shrink over time.
- `torch.version.hip` decisions inside `core/translator.py` — belongs to
  `runtime/` policy, injected through `Caps`.
- `core/queue_runner.py` importing `gui.file_progress` — move the class to
  `core/jobs/`.
- Windows-only behaviour (VRAM settle, hidden console) inside domain modules —
  belongs to `platform_services/`.

## Migration order

1. Extract `core/jobs/` and port `queue_runner` and the GUI worker onto it.
2. Introduce `Caps`/`RuntimeProfile` and move backend decisions into `runtime/`.
3. Move OS-specific code into `platform_services/` and empty the guard-test
   allowlist.
4. Remove the GUI after WebUI parity.
