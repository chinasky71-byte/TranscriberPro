# Contracts

Interfaces and data structures shared across layers. A contract is a promise:
changing it requires updating this document and the tests that enforce it.

Status legend: **current** = exists in the code today; **target** = to be
introduced by the service-layer and runtime refactors.

## `Caps` (target)

Immutable facts about the machine, built once at process start and injected
into the domain. The domain asks *what is possible*, never *which OS is this*.

| Field | Type | Meaning |
|---|---|---|
| `os` | `"linux" \| "windows" \| "macos"` | operating system |
| `cuda` | bool | CUDA runtime usable |
| `rocm` | bool | ROCm/HIP runtime usable |
| `vulkan` | bool | Vulkan loader and device usable |
| `nvidia` | bool | NVIDIA GPU present |
| `amd` | bool | AMD GPU present |
| `device_count` | int | torch-visible devices |
| `multigpu` | bool | more than one torch device |
| `vram_free_gb` / `vram_total_gb` | float | current values at startup |
| `case_sensitive_fs` | bool | filesystem semantics |
| `has_display` | bool | graphical session available (expected false in containers) |
| `can_notify` | bool | native notifications available |
| `supports_ct2_bootstrap` | bool | ctranslate2 must initialize before torch |

Source today: `utils/gpu_detect.py` (`--json` output). `Caps` is a typed view
over that data, not a second detector.

## `RuntimeProfile` (target)

The runtime policy derived from `Caps` and configuration:

| Field | Meaning |
|---|---|
| `backend` | `cuda \| rocm \| vulkan \| cpu` |
| `whisper_compute_type` | `int8_float16` on CUDA, `int8` on CPU |
| `nllb_device_map` | `{"": 0}` on multi-GPU ROCm, `"auto"` elsewhere |
| `ct2_init_first` | whether to initialize ctranslate2 before torch |
| `vram_budget_gb` | usable VRAM after the platform reserve |

Invariant: the domain reads `RuntimeProfile`; it never derives the same values
from `torch.version.hip` or `sys.platform` itself.

## `Platform` (target)

Side effects owned by the OS layer:

```python
class Platform(Protocol):
    caps: Caps
    def prepare_process(self) -> None: ...       # bootstrap hooks (e.g. ct2 order)
    def subprocess_flags(self) -> int: ...       # hidden console on Windows, else 0
    def kill_tree(self, pid: int) -> None: ...
    def settle_vram(self, budget_s: float) -> None: ...
    def notify(self, title: str, message: str) -> None: ...
    def default_data_dir(self) -> Path: ...
```

Rules: no business decisions, never install or modify drivers, never raise on
unsupported features (degrade to a no-op and report through `Caps`).

## `JobManager` (current)

The single owner of the queue, shared by WebUI, CLI and (temporarily) the GUI.

```python
class JobManager(Protocol):
    def add(self, path: Path, overrides: dict | None = None) -> str: ...
    def start(self) -> None: ...
    def cancel(self, job_id: str) -> bool: ...
    def remove(self, job_id: str) -> bool: ...
    def snapshot(self) -> list[Job]: ...
    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]: ...
```

Invariants:
- one GPU-heavy job at a time (concurrency 1);
- each job runs in its own subprocess (`python -m core.pipeline_cli`);
- per-file overrides live in memory only, never on disk;
- state is persisted atomically (`jobs.json`); jobs left `running` at startup
  become `interrupted`;
- cancel kills the process tree and frees the GPU.

Implementation: `core/jobs/manager.py`. The Qt worker still has its own copy;
it will be ported during the WebUI work. `legacy_snapshot()` keeps the
historical `queue_status.json` schema for the headless CLI.

## `Event` (current, v1)

Transport: one stdout line per event from `core.pipeline_cli`, prefixed with
`@@TPEV@@ ` and followed by a JSON object. Enabled only when the parent sets
`TP_EVENTS=1`. Implementation: `utils/events.py`.

| `k` | Fields | Meaning |
|---|---|---|
| `phase` | `name`, optional `engine`, optional `fraction` | a pipeline phase started |
| `route` | `path="ocr"`, `translate` | bitmap branch (OCR), with or without translation |
| `audio_lang` | `lang` | audio track language |
| `embedded` | `lang` | embedded subtitle chosen, audio not needed |
| `skip` | `phases` | phases that will not run |
| `ocr_leave` | — | OCR failed, falling back to text/audio |
| `bar` | `phase`, `pct` (0–100) | progress inside a phase |

Compatibility rules:
- adding an optional field is backward compatible;
- adding a new `k` requires updating this table and the schema test;
- removing or renaming a field is a breaking change and needs a version field
  (`v`) — not present yet;
- consumers must ignore unknown fields.

Guard: `linux_tests/test_events_schema.py` scans `core/` for literal `emit(...)`
and `_tp_emit(...)` calls and rejects kinds outside the table.

## `TranscriptionEngine` (current)

`core/engines/base_engine.py`. Lifecycle `load()` → `transcribe_chunks()` →
`unload()`; one engine resident at a time; `is_available()` and
`supports_language()` never raise. `LanguageNotAlignable` asks the router to
retry once with faster-whisper.

## Configuration contract

`utils/config.py` is a process-wide singleton reading
`~/.transcriberpro/config.json`. Precedence: **defaults < config file <
per-job in-memory overlay**. Only the directory roots are overridable from the
environment (`TP_DATA_DIR`, `TP_MODELS_DIR`, read at import time); no config
key has an environment override. Secrets are stored in the config file or read
from the environment, never in logs or API responses.
