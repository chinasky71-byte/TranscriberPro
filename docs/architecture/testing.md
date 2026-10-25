# Testing strategy

Tests are grouped by what they protect. A change must keep the relevant group
green; CI enforces the groups that do not need a GPU.

## Test layers

| Layer | Purpose | Location | Hardware |
|---|---|---|---|
| Unit | pure logic (parsing, formatting, thresholds, config merge) | `linux_tests/` | CPU |
| Contract | interfaces (`TranscriptionEngine`, `JobManager`, `Caps`) | `linux_tests/test_jobs_manager.py` + `linux_tests/` | CPU |
| Guard | architecture and protocol rules | `linux_tests/test_architecture_boundaries.py`, `test_events_schema.py` | CPU |
| Integration (headless) | pipeline on a real sample via `core.queue_runner` | manual / `samples/` | GPU |
| End-to-end (web) | API + SSE + job lifecycle | `linux_tests/` with a fake manager | CPU |
| Container smoke | image starts, `--help`, import | CI | CPU |
| Hardware validation | ROCm/CUDA end-to-end | self-hosted runner / manual | GPU |

## Fakes

- `FakePlatform` and `FakeCaps` for domain code: no OS, no GPU.
- A fake `JobManager` for the web API tests: deterministic events, no subprocess.
- A fake subprocess for `ProcessRunner`: canned stdout/stderr and exit codes.
- Never mock GPU kernels; if a test needs a GPU, it belongs to the hardware
  group and must be marked as such.

## Guard tests

### `test_architecture_boundaries.py`

- `core/` must not import `platform_services` or `runtime` (they do not exist
  yet; the rule prevents them from leaking in later).
- `core/` must not import `PyQt6` / `PySide6`.
- OS checks in `core/` are rejected unless present in an explicit allowlist
  (file + exact line). The allowlist must only shrink.

### `test_events_schema.py`

- Prefix and JSON round-trip of `@@TPEV@@` lines.
- Literal `emit(...)` / `_tp_emit(...)` calls in `core/` must use a documented
  kind.
- Malformed input is ignored.

### `test_docs_links.py`

- Relative Markdown links in `docs/architecture/` and `docs/adr/` must resolve.
- ADR file names must be unique and numerically ordered.

## Commands

```bash
venv/bin/python -m pytest linux_tests -q
venv/bin/python -m pytest linux_tests/test_architecture_boundaries.py -q
venv/bin/python -m pytest linux_tests/test_events_schema.py -q
```

Hardware validation (AMD):

```bash
venv/bin/python scripts_manutenzione/amd_smoke_test.py --whisper
venv/bin/python -m core.queue_runner samples/prova_amd_test.mp4 \
  --status /tmp/queue_status.json --log-dir /tmp/queue_logs
```

## CI matrix (target)

| Job | OS | GPU | Contents |
|---|---|---|---|
| `unit` | Linux | none | full `linux_tests` suite |
| `import-windows` | Windows | none | `python -m core.pipeline_cli --help`, imports |
| `docker-build` | Linux | none | build `rocm`, `cuda`, `cpu` images |
| `smoke-cpu` | Linux | none | run the pipeline on a tiny clip in the CPU image |
| `gpu-amd` | Linux | AMD | smoke test + one real file (self-hosted) |
| `gpu-nvidia` | Linux | NVIDIA | same, when a runner is available |

## Rules

- A bug fix ships with a test that fails before and passes after.
- Tests must not write inside the project directory; use `tmp_path`,
  `~/.transcriberpro/` or `/tmp` (privacy rule).
- No test may require network access unless it is explicitly marked.
- Skipped hardware tests must state why.
