# WebUI specification

Status: MVP implemented (Step 3). Settings/history, OCR review, glossary and
library pages follow (`docs/webui/PLAN.md`).

## 1. Goal

Replace the Qt desktop interface with a **local web interface** to submit
videos, configure jobs and monitor the pipeline. The pipeline stays headless
(`core.pipeline_cli`); the WebUI is a client of a shared job service.

## 2. Non-goals (v1)

- Multi-user, accounts, permissions.
- Editing subtitles by hand (except the OCR review page).
- Cloud hosting, public exposure, mobile app.
- Uploading media through the browser: v1 accepts filesystem paths.
- Replacing the pipeline or the model selection logic.

## 3. Decisions

| Decision | Value |
|---|---|
| Bind address | `0.0.0.0` (remote access allowed) |
| Auth | bearer token **required** when the host is not loopback; `TP_WEB_TOKEN` env var |
| Input | paths under configured `allowed_media_roots`; no upload in v1 |
| UI stack | FastAPI + Jinja2 + **HTMX + Alpine.js**, no Node build |
| GUI | frozen; removed after WebUI parity |
| OCR review | Step 5, not in the MVP |
| Output | sidecar `.srt` next to the media, as today |

Remote access over plain HTTP exposes the token: document SSH tunnel, VPN or
a TLS reverse proxy. The service never stores tokens in logs or pages.

## 4. Architecture

```
browser ── HTTP/SSE ──► web/ (FastAPI + uvicorn)
                         ├── core/jobs/ (JobManager, ProcessRunner, EventHub)
                         │     └── subprocess: core.pipeline_cli (unchanged)
                         ├── config API (whitelist, secrets write-only)
                         ├── static/ (HTMX, Alpine, CSS)
                         └── templates/
```

- One process serves the UI and owns the queue.
- One GPU-heavy job at a time (GPU is the bottleneck).
- Each job runs in its own subprocess, as today, to isolate crashes and free
  VRAM.
- `core/jobs/` is shared by the WebUI, the headless queue and (temporarily)
  the Qt GUI.

## 5. Job service (`core/jobs/`)

| Module | Responsibility |
|---|---|
| `models.py` | `Job` dataclass: id, path, overrides, status, progress, phase, output, error, timestamps |
| `process_runner.py` | spawn `python -m core.pipeline_cli args.json`; parse stdout/stderr and `@@TPEV@@`; kill tree; result file |
| `manager.py` | FIFO queue, concurrency 1, start/stop/cancel/remove, per-file overrides |
| `events.py` | pub/sub hub, per-job log ring buffer, SSE fan-out |
| `persistence.py` | atomic `jobs.json`; `running` → `interrupted` on restart |

**States:** `queued`, `running`, `done`, `failed`, `cancelled`, `interrupted`.

**Invariants:** overrides in memory only; cancel kills the process tree; a job
that produced an SRT with a failed translation is `failed` (existing pipeline
semantics); logs are per job and never contain secrets.

## 6. HTTP API (v1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/status` | version, backend, GPU, VRAM, queue size |
| GET | `/api/jobs` | list jobs |
| POST | `/api/jobs` | add `{path, overrides}` |
| GET | `/api/jobs/{id}` | detail |
| POST | `/api/jobs/{id}/cancel` | cancel |
| DELETE | `/api/jobs/{id}` | remove a queued job |
| GET | `/api/jobs/{id}/logs` | log tail |
| GET | `/api/events` | SSE stream (`Last-Event-ID` supported) |
| GET/PUT | `/api/config` | whitelisted keys; secrets as `is_set` / write-only |
| GET | `/api/history` | completed jobs |
| GET | `/api/models` | available models / VRAM profile |

Errors: JSON `{error: {code, message}}`; no stack traces, no secrets.

## 7. UI pages

| Page | Contents | Phase |
|---|---|---|
| Dashboard | backend, GPU/VRAM, version, queue counters, active job | MVP |
| Queue | add path, per-file overrides, start/stop/cancel, progress, phase, ETA, log tail | MVP |
| Job detail | steps, logs, output path | MVP |
| History | completed/failed jobs, open output folder | Step 4 |
| Settings | general, OCR, translation/models, paths | Step 4 |
| OCR review | bitmap image + text, approve/correct | Step 5 |
| Glossary | per-show terms, candidates, approve | Step 6 |
| Library scanner | scan, filters, bitmap badges, batch OCR | Step 6 |

UI language: IT/EN (the interface only; documentation stays English).
Mobile-friendly layout; no external CDN assets.

## 8. Security

- Bind `0.0.0.0`; **require `TP_WEB_TOKEN`** unless bound to loopback.
- Constant-time token comparison; token accepted via `Authorization: Bearer`
  or an HttpOnly session cookie after a login form.
- CSRF protection for state-changing requests.
- Path validation: resolve with `realpath`, require the file to exist and to
  be under `allowed_media_roots`; reject traversal and symlink escapes.
- Secrets: never returned; `is_set` flags only; write-only updates.
- Headers: `X-Content-Type-Options: nosniff`, CSP without inline scripts.
- No upload endpoint in v1.
- Rate limit login attempts.

## 9. Persistence and paths

- `TP_DATA_DIR` (default `~/.transcriberpro`): config, logs, `jobs.json`.
- `TP_MODELS_DIR` (default `<repo>/models`): model cache.
- Media roots from config; output next to the media.
- Both env vars are implemented in Step 1/2; containers rely on them.

## 10. Testing and acceptance

- Unit tests for `JobManager`, `ProcessRunner`, persistence, path validation.
- API tests with a fake manager; SSE reconnect test.
- End-to-end: a real file on the AMD machine, from the browser.
- Acceptance (MVP): start the server, add `samples/prova_amd_test.mp4`, see
  live progress and logs, cancel a running job, restart the server and find
  the job state preserved.
- No regression in the headless queue (`core.queue_runner`).

## 11. Risks

| Risk | Mitigation |
|---|---|
| Long jobs and browser disconnects | SSE heartbeat + `Last-Event-ID`; state persisted |
| Path escape | realpath + allowed roots |
| Token exposure on LAN | require token; document TLS/VPN; never log it |
| OCR review images | serve only from the job temp dir, with content type |
| GPU contention with the Qt GUI | GUI frozen; one job at a time |
| PyQt remains a dependency | make it optional in Step 7 |
