# WebUI implementation plan

Each step is a branch from `development`, a PR into `development`, green
tests, and an update to `docs/STATUS.md` and `docs/PROGRESS.md`.

| Step | Branch | Deliverable | Acceptance | Status |
|---|---|---|---|---|
| 0 | `docs/webui-spec` | `AGENTS.md` entry point, `STATUS`, `PROGRESS`, `docs/README`, this spec/plan, docs guard test | docs tests green; a new session can resume from `AGENTS.md` | done |
| 1 | `feat/jobs-service` | `core/jobs/`: models, process runner, manager, event hub, persistence; `queue_runner` ported | headless queue parity; tests without Qt | done — merged `e87e8ae` (direct commit, deviation recorded) |
| 2 | `feat/web-api` | FastAPI app, health/status/jobs/events/config, token auth, path validation | queue start/stop/cancel via `curl`; SSE works | done — commit `66c426e`, merge `cb962cc` |
| 3 | `feat/webui-mvp` | Dashboard, queue, job detail, logs (HTMX + Alpine) | one real file processed from the browser on AMD | done — commit `ba9ba99`, merge `a9c0975` |
| 4 | `feat/webui-settings` | Settings and history pages | config changes and history work | pending |
| 5 | `feat/webui-ocr` | OCR review page | parity with the Qt dialog | pending |
| 6 | `feat/webui-glossary` | Glossary and library scanner pages | functional parity | pending |
| 7 | `feat/pyqt-optional` | Qt removed from default requirements; `--gui` optional | install without Qt | pending |
| 8 | `feat/docker` | Multi-stage Dockerfile, compose rocm/cuda/cpu, volumes | `docker compose up` produces the SRT | pending |

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

## Step 8 notes

- `rocm` image: `/dev/kfd`, `/dev/dri`, groups `video`/`render`, `ipc: host`.
- `cuda` image: NVIDIA container runtime.
- `cpu` image for smoke tests.
- Models, config, media and output as volumes; non-root; no drivers inside.
