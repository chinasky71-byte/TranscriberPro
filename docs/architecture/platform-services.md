# Platform services

The platform layer owns **OS facts and side effects**. It does not decide
product behaviour and does not touch domain code.

## What belongs here

| Concern | Examples | Current location |
|---|---|---|
| Data paths | config directory, cache root, default folders | `utils/config.py` (`CONFIG_DIR = Path.home()/'.transcriberpro'`), `utils/cache_bootstrap.py` (project `models/.cache`) |
| Process creation | hidden console on Windows | `gui/workers.py`, `core/queue_runner.py` (`CREATE_NO_WINDOW`) |
| Process termination | kill a process tree on cancel | `core/queue_runner.py::kill_tree` |
| File locking | one queue at a time | `core/queue_runner.py::QueueLock` |
| Notifications | toast/notification at the end of a queue | `core/queue_runner.py::notify` |
| VRAM settle | wait for VRAM to be released (Windows) | `core/vram_settle.py` |
| Display | whether a GUI can start | GUI only |
| Bootstrap hooks | initialize ctranslate2 before torch | `utils/ct2_bootstrap.py` (Linux) |

Target package: `platform_services/` with one module per OS
(`linux.py`, `windows.py`, `macos.py`) and a `Protocol` defined in
[contracts.md](contracts.md).

## Per-OS behaviour

| Behaviour | Linux | Windows | macOS |
|---|---|---|---|
| Hidden console flag | not needed | `CREATE_NO_WINDOW` | not needed |
| Kill tree | process group | `taskkill /T /F` | process group |
| Notifications | `notify-send` (optional) | toast/`powershell` | not supported |
| VRAM settle | not needed | wait loop | not needed |
| ctranslate2 bootstrap | yes on ROCm | no (PR #28) | no |
| Display required | only for the legacy GUI | only for the legacy GUI | — |

## Rules

1. **Never install or modify drivers, kernel modules or system services.**
   Read facts, use the host stack, fail with a clear message.
2. **No root at runtime.** System packages are installed by the user or the
   container image, never by the application.
3. **No personal data on disk inside the project.**
   Logs, caches and test artifacts go to `TP_DATA_DIR`, the user's home or
   `/tmp` (see `AGENTS.md`).
4. **No business decisions.** “Which model fits” belongs to the domain with
   `Caps`; “how to hide a console” belongs here.
5. **Degrade, do not raise.** Unsupported features become no-ops reported
   through `Caps`.

## Containers

In Docker the platform is always Linux. The layer must therefore:
- read data and model directories from `TP_DATA_DIR` / `TP_MODELS_DIR`
  (planned, see [config.md](config.md));
- not assume a writable home;
- not require a display;
- not attempt notifications unless explicitly enabled.

## Known exceptions (guard-test allowlist)

These OS checks currently live outside `platform_services/` and must be
removed during the migration:

| File | Check |
|---|---|
| `core/queue_runner.py` | `sys.platform.startswith('linux')`, `os.name != 'nt'` |
| `core/llm_subtitle_translator/gguf_worker.py` | `os.name != 'nt'` |
| `core/llm_subtitle_translator/engine.py` | `sys.platform != "win32"` |
| `core/translator.py` | `sys.platform == 'win32'` |
| `core/pipeline_cli.py` | `sys.platform != 'win32'` |

The list is enforced by `linux_tests/test_architecture_boundaries.py`; adding a
new entry requires a code review justification.
