# WebUI specification

Status: Steps 0–9 done (`docs/webui/PLAN.md`). The library scanner is a
separate FastAPI + SQLite service, not part of this spec.

## 1. Goal

Replace the Qt desktop interface with a **local web interface** to submit
videos, configure jobs and monitor the pipeline. The pipeline stays headless
(`core.pipeline_cli`); the WebUI is a client of a shared job service.

## 2. Non-goals (v1)

- Multi-user, accounts, permissions.
- Editing subtitles by hand (except the OCR review page).
- Cloud hosting, public exposure, mobile app.
- Uploading media through the browser: the file picker lists folders under the
  allowed roots and queues paths; there is no upload endpoint and no library
  index (the picker is a lister, not a scanner).
- Replacing the pipeline or the model selection logic.

## 3. Decisions

| Decision | Value |
|---|---|
| Bind address | `0.0.0.0` (remote access allowed) |
| Auth | bearer token via `TP_WEB_TOKEN`; **optional** — `--no-auth` (or `TP_WEB_NO_AUTH=1`) serves without it and the dashboard shows a permanent warning |
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
| GET/PUT | `/api/config` | whitelisted keys; value validation (enum, 0–100, existing roots); secrets as `is_set` / write-only |
| GET | `/api/history` | finished jobs, `?status=` (terminal state) and `?limit=` (1–1000, default 100), newest first |
| GET | `/api/models` | engine modes, translation models and `MODEL_SPECS` keys; registry only, no weights |
| GET | `/api/browse` | folder listing for the file picker: `?path=` (absolute, under a root; empty = start folder); returns folders, video files, `has_subtitle`, `parent`, `roots`, `truncated`; 400 when the path is rejected |
| POST | `/api/ocr/sessions` | start an OCR review session `{path, language?}` |
| GET | `/api/ocr/sessions` | list sessions |
| GET | `/api/ocr/sessions/{id}` | session status plus its events |
| PUT | `/api/ocr/sessions/{id}/events/{index}` | save corrected text / `verified` |
| GET | `/api/ocr/sessions/{id}/images/{index}` | the bitmap as `image/png` |
| POST | `/api/ocr/sessions/{id}/srt` | write the sidecar SRT from the events |
| DELETE | `/api/ocr/sessions/{id}` | remove the session directory |
| GET | `/api/glossary/reports` | glossary reports found under `TP_DATA_DIR/glossary` |
| GET | `/api/glossary/reports/{name}` | report with the decisions attached |
| PUT | `/api/glossary/reports/{name}/terms/{index}` | save `decision`, `translation`, `note` |

Errors: JSON `{error: {code, message}}`; no stack traces, no secrets.

## 7. UI pages

| Page | Contents | Phase |
|---|---|---|
| Dashboard | **system status** (backend + stamp, GPU ok/problem, torch/HIP/CUDA/ctranslate2 versions, work dir and free space, auth state), version, queue counters, active job | MVP + Step 10 (done) |
| Queue | add path, **file picker with multi-select**, per-file overrides, `skip_existing`, start/stop/cancel, progress, phase, log tail | MVP + Step 9 (done) |
| Job detail | steps, logs, output path | MVP (logs panel; no separate page) |
| History | finished jobs, status filter, duration, output path, log | Step 4 (done) |
| Settings | general, transcription, translation, media roots, secrets | Step 4 (done; no OCR tab, OCR has its own page) |
| OCR review | bitmap image + text, approve/correct, sidecar SRT | Step 5 (done) |
| Glossary | per-show terms, candidates, approve/reject | Step 6 (done; review only, reports are built offline) |
| Library scanner | scan, filters, bitmap badges, batch OCR | Step 6 (not implemented: separate service, see PLAN.md) |

UI language: IT/EN (the interface only; documentation stays English).
Mobile-friendly layout; no external CDN assets.

## 8. Security

- Bind `0.0.0.0`; a token is required unless bound to loopback **or** started
  with `--no-auth`, which is meant for a private network (VPN/Twingate), an SSH
  tunnel or a TLS proxy. Without a token the dashboard shows an unmissable
  warning and `/login` redirects to `/`.
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
- `picker_start_dir` (default empty = the first allowed root) is the folder the
  file picker opens on; the value is used only when it sits under an allowed
  root, so a stale setting cannot lock the picker. Both env vars are
  implemented in Step 1/2; containers rely on them.

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
| PyQt remains a dependency | resolved in Step 7: Qt lives in `requirements-gui.txt`, `main.py` exits with a message pointing at the WebUI |
