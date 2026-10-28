# Web API

FastAPI application that exposes the shared job queue and the browser UI.
Steps 2 (API), 3 (MVP UI), 4 (settings, history), 5 (OCR review) and 9 (file
picker) of `docs/webui/PLAN.md` are done.

## Run

Install the web dependencies once:

```bash
venv/bin/pip install -r requirements-web.txt
```

```bash
export TP_MEDIA_ROOTS="/media:/srv/media"     # os.pathsep-separated
export TP_DATA_DIR="$HOME/.transcriberpro"
export TP_MODELS_DIR="/srv/transcriberpro/models"

# with a token (recommended when the port is reachable by others)
export TP_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
venv/bin/python -m web.main --host 0.0.0.0 --port 8080

# without authentication, on a private network only (VPN/Twingate, SSH tunnel,
# TLS proxy): the dashboard shows a permanent warning
venv/bin/python -m web.main --host 0.0.0.0 --port 8080 --no-auth
```

A non-loopback host **refuses to start** without a token unless `--no-auth` (or
`TP_WEB_NO_AUTH=1`) is given. The token is accepted as
`Authorization: Bearer <token>` and, for SSE only, as `?token=<token>`; without
a token `/login` redirects to `/`.

The dashboard shows the system status: backend from `venv/.tp-backend`, whether
the GPU answers (`utils/backend_preflight.py`), the torch/HIP/CUDA versions, the
work directory with its free space, and the auth state. Jobs are refused when the
GPU does not answer (per-job "Allow CPU" overrides it).

It also shows a **Translator** line: the configured GGUF quantization, whether the
file is where the resolver looks, and the VRAM it needs against the VRAM free
right now. After ADR-009 that engine is the only translator, so a missing file is
not a degraded mode — every job would fail at its first step — and the line turns
red with the reason before anything is queued. The check is
`utils/backend_preflight.translation_status()`; the probe runs in a subprocess and
is cached for 300 s.

## Settings that exist

The settings page only lists choices that change something (ADR-009 removed the
alternatives):

| Key | Meaning |
|---|---|
| `transcription_engine_mode` | `qwen3` or `auto` (ADR-008: no other engine) |
| `llm_translator_gguf_quant` | `Q4_K_M` (default), `Q3_K_M`, `IQ3_M` |
| `llm_translator_gguf_dir` | where the `.gguf` file lives; empty = `models/translategemma-12b-gguf` |
| `target_language` | `ita` (the engine translates into Italian only) |
| `translation_max_untranslated_pct` | failure threshold for blocks left untranslated |
| `allowed_media_roots`, `picker_start_dir` | what the queue and the picker may reach |

`whisper_model`, the Whisper VAD pair, `translation_model` and
`llm_translator_model` are **not** settings any more: the engines they configured
do not exist, and the ones they name have a single possible value. The keys stay
in `Config` for old `config.json` files and for the frozen Qt dialog.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `TP_WEB_TOKEN` | none | bearer token; required for remote access |
| `TP_MEDIA_ROOTS` | config `allowed_media_roots`, else `$HOME` | roots accepted for media paths |
| `TP_DATA_DIR` | `~/.transcriberpro` | config, `jobs.json`, queue logs |
| `TP_MODELS_DIR` | `<repo>/models` | model cache |

`TP_DATA_DIR` and `TP_MODELS_DIR` are read at import time: `web.main` sets them
before importing `utils.config` and `utils.cache_bootstrap`.

## UI

Open `/` in the browser. When a token is configured, `/login` sets an
HttpOnly `tp_session` cookie (SameSite=Lax) holding the token; the token is
never written into the HTML. Log out from the top bar.

The page is server-rendered with Jinja2, HTMX (polling the queue) and Alpine
(logs panel). HTMX and Alpine are vendored in `web/static/vendor/`; no CDN is
used at runtime. The logs panel subscribes to `/api/events` with
`EventSource` and reconnects automatically (the server supports
`Last-Event-ID`).

Pages:

| Path | Content |
|---|---|
| `/` | dashboard: current queue (active job with progress, phase and elapsed time), counters, job table with elapsed/total time, add form with the file picker, logs panel |
| `/status` | system status (backend, GPU verdict, versions, work dir) and processing details |
| `/history` | finished jobs with `done`/`failed`/`cancelled`/`interrupted` filter |
| `/ocr` | OCR review: start a session, open one, correct the text, write the SRT |
| `/settings` | whitelisted config keys and write-only secrets |

Plain HTTP on a LAN exposes both the token and the cookie: use a TLS reverse
proxy, a VPN or an SSH tunnel.

## API

See [`docs/webui/SPEC.md`](../docs/webui/SPEC.md) for the full contract.

```
GET    /api/health
GET    /api/status
GET    /api/jobs
POST   /api/jobs                    {"path": "...", "overrides": {...}}
GET    /api/jobs/{id}
POST   /api/jobs/{id}/cancel
DELETE /api/jobs/{id}
GET    /api/jobs/{id}/logs?lines=200
GET    /api/events?job_id=&after=   (SSE)
GET    /api/history?status=&limit=
GET    /api/models
GET    /api/config
PUT    /api/config                  {"values": {...}}
POST   /api/ocr/sessions            {"path": "...", "language": "ita"?}
GET    /api/ocr/sessions
GET    /api/ocr/sessions/{id}       session + events
PUT    /api/ocr/sessions/{id}/events/{index}   {"text": "...", "verified": true}
GET    /api/ocr/sessions/{id}/images/{index}   PNG bitmap
POST   /api/ocr/sessions/{id}/srt   write the sidecar SRT
DELETE /api/ocr/sessions/{id}
```

Interactive schema: `/docs`.

## Notes

- One GPU-heavy job at a time; the manager owns the queue.
- Media paths must exist and resolve under an allowed root (realpath, no
  traversal).
- Config writes are restricted to a whitelist and every value is validated in
  `web/config_schema.py` before `Config.set`: enum keys against the lists in
  `utils/config.py`, `translation_max_untranslated_pct` in 0–100,
  `allowed_media_roots` as existing absolute directories, booleans from
  `true/false` strings. Secrets are returned as `{"is_set": true}` and are
  never logged; an empty secret field leaves the stored value untouched, the
  `clear:` checkbox removes it.
- The queue is persisted in `TP_DATA_DIR/jobs.json`; jobs left `running` at
  startup become `interrupted`.

## OCR review

`POST /api/ocr/sessions` starts `python -m core.ocr_review_job ocr` in a
subprocess (PIL, tesseract and ffmpeg stay out of the web process). The
session lives in `TP_DATA_DIR/ocr/<id>/` with `session.json`, `events.json`,
one PNG per event under `images/` and the worker log; media-derived text and
bitmaps therefore never enter the project tree.

The data contract is `core/pgs_types.py` (`OcrEvent`, `events_to_srt`), the
same one the Qt dialog uses. The write-back is always a **sidecar**
`<video>.<language>.srt` next to the media: the browser review never rewrites
the video file, like the headless pipeline.

The page polls `/ui/ocr/{id}` while the worker runs and shows the failure
reason when a file has no PGS/VOBSUB track or tesseract lacks the language.
