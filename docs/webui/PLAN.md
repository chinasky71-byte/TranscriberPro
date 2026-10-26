# WebUI implementation plan

Each step is a branch from `development`, a PR into `development`, green
tests, and an update to `docs/STATUS.md` and `docs/PROGRESS.md`.

| Step | Branch | Deliverable | Acceptance | Status |
|---|---|---|---|---|
| 0 | `docs/webui-spec` | `AGENTS.md` entry point, `STATUS`, `PROGRESS`, `docs/README`, this spec/plan, docs guard test | docs tests green; a new session can resume from `AGENTS.md` | done |
| 1 | `feat/jobs-service` | `core/jobs/`: models, process runner, manager, event hub, persistence; `queue_runner` ported | headless queue parity; tests without Qt | done — merged `e87e8ae` (direct commit, deviation recorded) |
| 2 | `feat/web-api` | FastAPI app, health/status/jobs/events/config, token auth, path validation | queue start/stop/cancel via `curl`; SSE works | done — commit `66c426e`, merge `cb962cc` |
| 3 | `feat/webui-mvp` | Dashboard, queue, job detail, logs (HTMX + Alpine) | one real file processed from the browser on AMD | done — commit `ba9ba99`, merge `a9c0975` |
| 4 | `feat/webui-settings` | Settings and history pages | config changes and history work | done |
| 5 | `feat/webui-ocr` | OCR review page | parity with the Qt dialog | done |
| 6 | `feat/webui-glossary` | Glossary and library scanner pages | functional parity | glossary review done; library scanner is separate work (see below) |
| 7 | `feat/pyqt-optional` | Qt removed from default requirements; `--gui` optional | install without Qt | done |
| 8 | `feat/docker` | Multi-stage Dockerfile, compose rocm/cuda/cpu, volumes | `docker compose up` produces the SRT | artifacts done — image build and GPU run pending (no container daemon on the dev host; see notes) |

## Step 0 checklist

- [x] `AGENTS.md` with what the repo is, reading order, map, workflow
- [x] `docs/STATUS.md`
- [x] `docs/PROGRESS.md` with history and template
- [x] `docs/README.md` index (authoritative vs historical, language)
- [x] `docs/webui/SPEC.md` and `docs/webui/PLAN.md`
- [x] `linux_tests/test_docs_index.py`
- [x] merge into `development`

## Step 1 notes

- Source of truth today: `gui/workers.py::ProcessingWorker`,
  `gui/services/queue_service.py`, `core/queue_runner.py`,
  `gui/file_progress.py` (Qt-free).
- Keep the CLI compatible: `core.queue_runner` becomes a thin client of the
  manager.
- Tests: fake process runner, no GPU.
- Do not change pipeline behaviour.

## Step 2 notes

- Add `TP_DATA_DIR` / `TP_MODELS_DIR` while touching config.
- Token required when host is not loopback; refuse to start otherwise.
- SSE events reuse the existing `@@TPEV@@` kinds.

## Step 3 notes

- Server-rendered pages + HTMX partials; no Node build.
- Reuse `gui/file_progress.FileProgress` (move it under `core/jobs/`).
- Show `device`/backend warnings like the benchmark report.

## Step 6 notes

- Glossary: the page reads reports produced by
  `glossary_engine.build_glossary_candidates.build_full_report(report_out=...)`
  from `TP_DATA_DIR/glossary/` and stores decisions in
  `<report>.decisions.json`. Building a report is not exposed in the browser:
  it needs the show folder, an English reference track and the Qwen extractor,
  and `glossary_engine`'s own CLI writes only the candidates JSONL.
- Library scanner: **not done**. It is a separate FastAPI + SQLite service
  (`library scanner per server- va su docker/library_scanner/`, plan in
  `LIBRARY_SCANNER_DEVELOPMENT_PLAN.md`) whose only reference implementation is
  the 1290-line `gui/library_scanner_widget.py`. Doing it needs (a) a decision
  on where its database lives (`TP_DATA_DIR`), (b) real media with bitmap
  tracks to validate a scan, (c) its own support story for the watch folder.
  It stays an explicit work item before Step 7 is considered complete for the
  GUI removal.

## Step 7 notes

- PyQt6, PyQt6-Qt6 and PyQt6_sip moved to `requirements-gui.txt`.
- `main.py` imports Qt behind `try/except ImportError` and exits 2 with a
  message pointing at `requirements-gui.txt` and `python -m web.main`.
- `install.sh --with-gui` installs the optional file; without it the install
  has no Qt.

## Step 8 notes

- `docker/Dockerfile`: multi-stage, `ARG BACKEND=rocm|cuda|cpu`, runtime stage
  runs as `tp` (uid 1000), `TP_DATA_DIR=/data`, `TP_MODELS_DIR=/models`,
  healthcheck on `/api/health`, `CMD python -m web.main --host 0.0.0.0`.
- `docker/compose.yaml`: one service per backend with `profiles`, `rocm` gets
  `/dev/kfd`, `/dev/dri`, `video`/`render` groups and `ipc: host`, `cuda` uses
  the NVIDIA device reservation, `cpu` has no device. `TP_WEB_TOKEN` is
  mandatory (`:?`), the media mount is read-write because the SRT is written
  next to the video.
- Not validated here: the image build (several GB, `docker` daemon not
  reachable in the development session) and a GPU run inside the container.
  `docker compose config` validates both the schema and the token guard.
- Guard tests: `linux_tests/test_docker.py`.

- `rocm` image: `/dev/kfd`, `/dev/dri`, groups `video`/`render`, `ipc: host`.
- `cuda` image: NVIDIA container runtime.
- `cpu` image for smoke tests.
- Models, config, media and output as volumes; non-root; no drivers inside.
