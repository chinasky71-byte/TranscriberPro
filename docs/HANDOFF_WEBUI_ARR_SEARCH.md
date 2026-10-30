# Handoff — WebUI: library search via Sonarr/Radarr (WIP)

Resume point for the feature the user asked for on 2026-10-29: **stop walking the
filesystem from the browser, ask Sonarr/Radarr instead**, everything from the
WebUI. Written so a cold session can finish it without re-reading the long chat
that produced it.

- Branch: **`feat/webui-arr-search`**, one commit (`3da25b7`), **not merged**.
- Working tree at handoff: clean, on `development` (the branch holds the work).
- State: **code complete, tests written, tests not green yet** (they hung before
  pytest could report; see "The blocker").

## What is in the branch

| File | What it does |
|---|---|
| `web/arr.py` *(new)* | `servers()` reads URL+key from config; `search(term)` queries `/api/v3/series/lookup` and `/api/v3/movie/lookup`; `_series_group()` lists `/api/v3/episode?seriesId=` and skips episodes without a file; `_movie_group()` reads `/api/v3/movie/{id}`. Every server path is mapped with `utils/path_map.to_local()` (`<server>=<local>` rules, same as the Library Scanner), validated with `web/paths.py::is_allowed`, and annotated with `browse.has_subtitle()`. Items carry `allowed`/`has_subtitle`/`reason`; `Group.missing` is what the button queues. Calls use an opener with an empty `ProxyHandler` — a Sonarr on the LAN must not go through `http_proxy` |
| `utils/config.py` | new keys `sonarr_url`, `sonarr_api_key`, `radarr_url`, `radarr_api_key`, `arr_path_map`, all empty (feature off by default) |
| `web/config_schema.py` | `sonarr_url`, `radarr_url`, `arr_path_map` whitelisted as safe; the two API keys in `SECRET_CONFIG_KEYS` (write-only, never echoed) |
| `web/ui.py` | settings group "Library search (Sonarr / Radarr)"; `GET /ui/search?term=`; `search_enabled` in the queue context |
| `web/templates/_search.html` *(new)* | results per series with per-episode status and a "Queue the N missing" form that posts `paths` to the existing `POST /ui/jobs` |
| `web/templates/index.html` | search box above the picker, rendered only when `search_enabled` |
| `linux_tests/test_web_arr.py` *(new)* | six tests with two fake HTTP servers (Sonarr + Radarr): path mapping, subtitle state, paths outside the roots, empty map, Radarr movie, HTTP error without leaking the key |

## The blocker

`venv/bin/python -m pytest linux_tests/test_web_arr.py -q` prints one dot and then
hangs. What was tried and did **not** fix it:

- `daemon_threads = True` + `allow_reuse_address` on a `ThreadingHTTPServer`
  subclass, and `shutdown()` + `server_close()` in the fixture teardown;
- building the request opener with an empty `ProxyHandler` (still a good change:
  it is kept, because a proxy in the environment would break real calls);
- `faulthandler` dumps only ever showed `serve_forever` threads, never the main
  thread's frame, so the hang is inside the test but the frame was not captured.

The last session then died with `ENOSPC` in the harness's own log, so the runs
after that point prove nothing. **First thing to do in a fresh session**: run that
single test file with a small `--timeout` if available, or reproduce the fixture
outside pytest (a standalone script that starts the two servers and calls
`arr.search`) to see whether the hang is in the fixture or in `arr.search`.

If the fake servers keep misbehaving, the cheap alternative is to drop the HTTP
layer from the tests: monkeypatch `web.arr._api` and test `search()`, the mapping
and the validation as pure functions. The fake-server pattern that *does* work in
this repo is `linux_tests/test_library_scanner_fake_server.py` (module-level
handler class, `NO_PROXY` set, `srv.server_address[1]`, `shutdown()` +
`server_close()`).

## What the user must fill in (Settings → "Library search")

- **Sonarr URL** (e.g. `http://sonarr:8989`) and **API key** (Settings → General);
- **Radarr URL** and key, if films matter;
- **path map**, one rule per line or separated by `;`: how the *arr sees the media
  root versus the local one, e.g. `/tv=/mnt/storage/tvshows`. Without it every
  result is reported as `outside the allowed roots` with the server path shown,
  which is the intended failure mode (no silent guessing).

For the reference machine the TV root is `/mnt/storage/tvshows` and it is already
in `allowed_media_roots`.

## Context from the same session that matters for this feature

- The queue already accepts many paths at once (`POST /ui/jobs` with repeated
  `paths`) and `skip_existing` is language-agnostic: any `<stem>.*.srt` counts, so
  a `.it.hi.srt` sidecar makes the file "already subtitled". The search results
  use `has_subtitle` for exactly that reason — expect S1E2-E9 of *Outlander* to
  show `sub ok` for that reason.
- The pipeline writes `<name>.it.srt`; an existing `.it.srt` is **overwritten**
  without backup.
- WebUI start command: `TP_DATA_DIR=~/.transcriberpro TMPDIR=/dev/shm/tp
  venv/bin/python -m web.main --host 0.0.0.0 --port 8080 --no-auth`.
- Conventions the branch follows: settings keys need to be in
  `web/config_schema.py` (`SAFE_CONFIG_KEYS` / `SECRET_CONFIG_KEYS`) and in a
  `SETTINGS_GROUPS` tuple; docs tests (`test_docs_index`, `test_docs_links`,
  `test_docs_progress`) run in the suite.

## Close-out, once the tests are green

1. `pytest linux_tests -q` (the whole suite, not only the new file);
2. entry in `docs/PROGRESS.md` (branch, goal, files, tests, decisions, known
   issues, next step — `test_docs_progress.py` enforces the fields), a line in
   `docs/STATUS.md` ("library search through Sonarr/Radarr") and a row in
   `docs/webui/PLAN.md` if it is treated as a step;
3. `--no-ff` merge into `development`, delete the branch, `git push`.

## Housekeeping left over from that session

- The harness died of `ENOSPC` while writing its own log, not because `/` was
  full (`/` has ~31 GB free, inodes 5%). Suspected cause: many killed-but-alive
  processes from the hung tests plus very large tool outputs. No stray `pytest`
  process was left running when this note was written; check with
  `ps -eo pid,args | grep pytest` before starting.
- Regenerable space, if it is needed: `~/.cache` (~24 GB, pip/HuggingFace),
  `.pytest_cache/`, `/tmp` artifacts from the benchmark runs, old logs in
  `~/.transcriberpro/logs`. **Do not** delete `models/` (38 GB) or `venv/` (15 GB)
  without asking the owner: the product needs them.
- Model weights from the 2026-10-28 campaign live in `/mnt/data/models-eval/`
  (~100 GB) and the NeMo-Speech.cpp build (with the local `NEMO_SALM_NGL` patch)
  in `/mnt/data/NeMo-Speech.cpp`. Both are experiments, not product assets.
