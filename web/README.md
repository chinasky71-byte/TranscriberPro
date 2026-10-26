# Web API

FastAPI application that exposes the shared job queue and the browser UI.
Steps 2 (API), 3 (MVP UI), 4 (settings, history) and 5 (OCR review) of
`docs/webui/PLAN.md` are done.

## Run

Install the web dependencies once:

```bash
venv/bin/pip install -r requirements-web.txt
```

```bash
export TP_WEB_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export TP_MEDIA_ROOTS="/media:/srv/media"     # os.pathsep-separated
export TP_DATA_DIR="$HOME/.transcriberpro"
export TP_MODELS_DIR="/srv/transcriberpro/models"

venv/bin/python -m web.main --host 0.0.0.0 --port 8080
```

A non-loopback host **refuses to start** without a token. Generate one as
above; the token is accepted as `Authorization: Bearer <token>` and, for SSE
only, as `?token=<token>`.

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
| `/` | dashboard, add form, queue, logs panel |
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
