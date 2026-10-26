# Structured events (v1)

The pipeline reports progress with one JSON line per event, next to the
human-readable log. Consumers (GUI, headless queue, WebUI) must rely on these
events, never on log text.

## Transport

- Producer: `core.pipeline_cli.py` (child process).
- Transport: stdout, one line per event.
- Prefix: `@@TPEV@@ ` followed by a JSON object.
- Enabled only when the parent sets `TP_EVENTS=1` in the child environment.
- Invalid lines with the prefix are dropped silently.
- Implementation: `utils/events.py` (`emit`, `format_line`, `parse_line`,
  `install_stdout_sink`).

Example:

```
@@TPEV@@ {"k":"phase","name":"asr","engine":"qwen3"}
@@TPEV@@ {"k":"bar","phase":"asr","pct":42}
```

## Event kinds (v1)

| `k` | Fields | When |
|---|---|---|
| `phase` | `name` (str), optional `engine` (str), optional `fraction` (0–1, `final` only) | a pipeline phase starts |
| `route` | `path="ocr"`, `translate` (bool) | bitmap branch: OCR with or without translation |
| `audio_lang` | `lang` (ISO 639-2) | audio language detected/selected |
| `embedded` | `lang` (ISO 639-2) | embedded subtitle chosen; audio not needed |
| `skip` | `phases` (list[str]) | phases that will not run |
| `step` | `name` (`save`, `mux`, `upload`), `state` (`start`, `done`, `skip`), optional `ok` (bool), optional `reason` (`disabled`, `no_imdb`, `video_changed`) | a finalisation step starts, ends or is skipped |
| `ocr_leave` | — | OCR failed; falling back to text/audio |
| `bar` | `phase` (`demucs`, `asr`, `translate`, `gender`), `pct` (0–100) | progress inside a phase |

## Compatibility

- Adding an **optional** field is backward compatible.
- Adding a new `k` requires: this table, the schema test
  (`linux_tests/test_events_schema.py`), and every consumer updated.
- Removing or renaming a field is **breaking**.
- A `v` field is not present yet; introduce it before the first breaking
  change. Consumers must ignore unknown fields.
- Consumers must be resilient to missing optional fields.

## Consumers

| Consumer | Usage |
|---|---|
| `core/queue_runner.py` / `core/jobs/progress.py` | progress and phase |
| `gui/workers.py` | forward to the UI |
| `web/` | SSE stream to the browser |

## Invariants

1. No personal data in event fields.
2. `pct` is monotonic inside a phase and never 100 before completion.
3. Events never carry file contents or credentials.
4. Emitting never raises; a lost event must not stop processing.

## Testing

`linux_tests/test_events_schema.py`:
- validates the prefix and JSON round-trip;
- scans `core/` for literal `emit(...)` / `_tp_emit(...)` calls and rejects
  kinds outside the table above;
- checks that `parse_line` ignores malformed input.
