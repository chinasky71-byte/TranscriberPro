# Project status

Updated: 2026-10-25
Line: `development` (active product); `master` is legacy (ADR-006)
Branch: `development` · last merge: `a9c0975` (WebUI MVP)
Environment: Ubuntu 26.04, Radeon RX 9060 XT 16 GB (gfx1200, RDNA4),
ROCm 7.0, torch 2.10.0+rocm7.0, venv ~16 GB, model cache ~33 GB

## What works

- **Headless pipeline**: `core.queue_runner` / `core.pipeline_cli` process a
  video end to end (Demucs, chunking, ASR, clean/format, translation, save).
- **ASR**: faster-whisper large-v3 and Qwen3-ASR on ROCm; automatic fallback.
- **Translation**: NLLB base, NLLB fine-tuned (4-bit), TranslateGemma 12B GGUF
  on Vulkan; HTTP engines for benchmark experiments.
- **Benchmark harness**: `bench/` with hardware fingerprint, ASR and
  translation suites, sanitized export into `docs/benchmarks/`.
- **Architecture baseline**: layers, contracts, runtime policy, platform
  services, events, config, security, testing, extension guide.
- **Job service**: `core/jobs/` owns the queue (manager, process runner, event
  hub, persistence, progress). `core.queue_runner` is a thin client; the
  headless pipeline was validated end to end after the extraction.
- **Web UI + API**: FastAPI app in `web/` with token auth (bearer + HttpOnly
  session cookie), path validation, jobs, SSE, config and history. The MVP UI
  (dashboard, add form, queue, logs) is server-rendered with HTMX + Alpine,
  assets vendored locally. Validated with a real job over HTTP and through
  the UI.
- **ADRs** 001–006, support matrix, contributing rules, guard tests.
- **Tests**: unit/guard tests in `linux_tests/` (bench, boundaries, events,
  docs links, translation gate, i18n).

## In progress / next

1. **WebUI Step 4** — settings and history pages. See `docs/webui/PLAN.md`.
2. OCR review (Step 5), glossary and library (Step 6), PyQt removal and
   Docker (Steps 7–8).
3. Docker packaging after the WebUI MVP.
4. Reference dataset extension (real clips with human Italian references)
   before any model decision beyond the current sample.

## Known issues and limits

- The **Qt GUI is frozen**: no new features; it will be removed after WebUI
  parity (`docs/webui/SPEC.md`).
- **Windows pipeline** startup is untested; Windows is a frozen line.
- `master` does not contain `AGENTS.md`; development does, by decision.
- The benchmark uses a **single synthetic clip** and an Italian reference with
  a few typos; results reject clearly worse candidates, they do not crown a
  winner.
- **NLLB-FT** weights are published under **CC-BY-NC-4.0** (non-commercial);
  they are downloaded locally, never committed.
- Many legacy documents under `docs/` are still in Italian. They are marked
  `historical` in `docs/README.md` and must be translated when touched.
- The local `venv` must stay ROCm; a CPU-only reinstall breaks GPU
  benchmarks (the report shows `device=cpu`).

## Useful commands

```bash
venv/bin/python -m pytest linux_tests -q
venv/bin/python -m core.queue_runner samples/prova_amd_test.mp4 \
  --status /tmp/queue.json --log-dir /tmp/queue_logs
venv/bin/python -m bench.run --suite all --repeat 3
```
