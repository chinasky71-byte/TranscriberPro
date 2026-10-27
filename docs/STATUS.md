# Project status

Updated: 2026-10-26
Line: `development` (active product); `master` is legacy (ADR-006)
Branch: `development` · last merge: `d17f601` (test isolation)
WebUI: **not running** (start it with the command in `web/README.md`; `--no-auth` for a private network)
Environment: Ubuntu 26.04, Radeon RX 9060 XT 16 GB (gfx1200, RDNA4),
ROCm 7.0, torch 2.10.0+rocm7.0 + ctranslate2 4.8.4 ROCm (verify with
`venv/bin/python -c "import torch;print(torch.cuda.is_available())"`), venv
~16 GB, model cache ~33 GB

## What works

- **Headless pipeline**: `core.queue_runner` / `core.pipeline_cli` process a
  video end to end (Demucs, chunking, ASR, clean/format, translation, save).
- **ASR**: faster-whisper large-v3 and Qwen3-ASR on ROCm; automatic fallback.
- **Translation**: NLLB base, NLLB fine-tuned (4-bit), TranslateGemma 12B GGUF
  on Vulkan; HTTP engines for benchmark experiments.
- **Measured throughput** (reference machine, ROCm, one job at a time): a
  134-minute episode in 25 min and a 144-minute one in 27 min, i.e. ~5.3x
  realtime. During a run the GPU is busy at 94% of the samples (96% of them
  above 80%), VRAM peaks at 7.5 GB of 15.9 GB, and the media is read in a
  single sequential pass, so the storage is not a bottleneck — see
  `docs/PROGRESS.md`, 2026-10-26.
- **Benchmark harness**: `bench/` with hardware fingerprint, ASR and
  translation suites, sanitized export into `docs/benchmarks/`, plus
  `bench/asr_ab.py` for A/B on a fixed clip. Measured and rejected: a bigger
  ASR batch (no effect) and longer chunks (3.4x slower) — see
  `docs/benchmarks/2026-10-26-asr-knobs.md`; the current ASR configuration is
  the measured optimum.
- **Architecture baseline**: layers, contracts, runtime policy, platform
  services, events, config, security, testing, extension guide.
- **Job service**: `core/jobs/` owns the queue (manager, process runner, event
  hub, persistence, progress). `core.queue_runner` is a thin client; the
  headless pipeline was validated end to end after the extraction.
- **Web UI + API**: FastAPI app in `web/` with optional token auth (bearer +
  HttpOnly session cookie; `--no-auth` for private networks, warning on the
  dashboard), a system status card (backend stamp, GPU verdict, versions, work
  dir), path validation, jobs, SSE, config, history and a read-only file picker. Pages: dashboard and queue (add form, **file picker with
  multi-select and `skip_existing`**, cancel, remove, logs), history with a
  status filter, settings (whitelisted keys, write-only secrets, value
  validation, `picker_start_dir`) and OCR review (bitmap next to the OCR text,
  corrections, sidecar SRT). Glossary review reads `glossary_engine` reports.
  Server-rendered with HTMX + Alpine, assets vendored locally.
- **Install policy and preflight (ADR-007)**: two supported backends, CUDA and
  ROCm on AMD RDNA3/RDNA4/CDNA; a job whose GPU does not answer fails in a
  second with the remedy (`allow_cpu` per job to override). `install.sh` detects the hardware (`auto` is the
  default), refuses anything else instead of falling back, verifies the
  installed backend by importing torch/ctranslate2, and stamps the result in
  `venv/.tp-backend`; a mismatched re-run refuses to replace torch. CPU and
  Vulkan installs no longer exist.
- **Containers**: `docker/Dockerfile` (one image per backend) and
  `docker/compose.yaml` (profiles `rocm`/`cuda`); not built yet, see the open
  items.
- **GUI optional**: PyQt6 moved to `requirements-gui.txt`; `main.py` exits with
  a message pointing at the WebUI when Qt is absent.
- **ADRs** 001–007, support matrix, contributing rules, guard tests.
- **Tests**: unit/guard tests in `linux_tests/` (bench, boundaries, events,
  docs links, translation gate, i18n, web API/UI/picker/OCR/glossary, Docker,
  install isolation). The suite is fully green: 689 passed, 11 skipped.

## In progress / next

1. **Container validation** — build the three images on a host with a container
   daemon and run the `rocm` profile on the reference machine (Step 8
   acceptance is still open).
2. **One robustness item found on a real file** — the pipeline pre-loads
   Whisper even with `transcription_engine_mode=qwen3`, so a GPU-less
   `ctranslate2` can fail a job that would never use Whisper. (The orphan
   `TMPDIR` work folder of cancelled jobs is fixed: `utils/temp_cleanup.py`.)
3. **Library scanner in the WebUI** — separate FastAPI + SQLite service, needs
   a database location decision and real media to validate (`docs/webui/PLAN.md`,
   Step 6 notes).
4. **Glossary report generation** — building a report is still a CLI/offline
   job; the page only reviews it.
5. **CSRF token** for state-changing requests (currently SameSite=Lax only).
6. Reference evaluation **done for the ASR choice**: one episode with
   professional SubRip tracks, three 10-minute clips, qwen3 against
   faster-whisper with a tuned VAD. Weighted over 1742 reference words qwen3 has
   the lower error (6.95% vs 8.60%) and better alignment; Whisper's ASR phase is
   40% faster but its coverage stays below 93% on two clips of three. **qwen3
   stays the default**; Whisper remains a per-install choice —
   `docs/benchmarks/2026-10-26-asr-reference-clip-a.md`. The end-to-end round
   (Italian reference) confirmed it and taught the important lesson: WER against
   a human translation rewards under-transcription, so the engine with the best
   WER there was the one that lost 4% of the dialogue. The Italian output now goes
   through an accent fix (`core/italian_accents.py`, `e'` -> `è`), worth 4.5 WER
   points on the end-to-end round. Proper names are fixed at the source: the
   glossary is passed to the ASR decoder as context (Borden instead of Bond /
   Burton), and with a TMDB id the glossary builds itself from the cast.

## Known issues and limits

- The **Qt GUI is frozen**: no new features; it will be removed after WebUI
  parity. Its dependencies are optional (`requirements-gui.txt`) and it is not
  in the container image.
- **No positive OCR run** has been validated: `samples/` has no bitmap subtitle
  track, so only the failure path ("no PGS/VOBSUB track") is proven end to end.
- **Container images not built** in this session (no daemon reachable); only
  the compose schema and the guard tests are verified.
- The **library scanner** is not part of the WebUI yet (separate service).
- `linux_tests/test_install_retry.py` used to run `install.sh` against the
  working venv and installed `requirements.txt` (torch **CPU**) into it: running
  the suite silently disabled the GPU. Fixed in `fix/install-test-isolation`
  (`install.sh` honours `TP_INSTALL_VENV`, the tests point it at `tmp_path`);
  the two long-standing failures went away with the same change.
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
# WebUI (token required on a non-loopback host)
venv/bin/python -m web.main --host 0.0.0.0 --port 8080

venv/bin/python -m pytest linux_tests -q
venv/bin/python -m core.queue_runner samples/prova_amd_test.mp4 \
  --status /tmp/queue.json --log-dir /tmp/queue_logs
venv/bin/python -m bench.run --suite all --repeat 3
```
