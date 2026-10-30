# Project status

Updated: 2026-10-30
Line: `development` (active product); `master` is legacy (ADR-006)
Branch: `development` · last merge: WebUI library search (Sonarr/Radarr)
WebUI: **not running** (start it with the command in `web/README.md`; `--no-auth` for a private network)
Environment: Ubuntu 26.04, Radeon RX 9060 XT 16 GB (gfx1200, RDNA4),
ROCm 7.0, torch 2.10.0+rocm7.0 only — no ctranslate2/whisperx (ADR-008);
verify with `venv/bin/python -c "import torch;print(torch.cuda.is_available())"`.
venv ~15 GB, model cache ~33 GB (still holds 2.9 GB of Whisper weights that
nothing reads).

## What works

- **Headless pipeline**: `core.queue_runner` / `core.pipeline_cli` process a
  video end to end (Demucs, chunking, ASR, clean/format, translation, save).
- **ASR**: **Qwen3-ASR only** (ADR-008): faster-whisper, Canary, ctranslate2 and
  whisperx were removed; the VAD needed by the subtitle synchroniser is ours
  (`core/vad.py`, Silero on onnxruntime, vendored weights). NVIDIA's
  Nemotron 3.5 ASR streaming models were re-tested on the same reference clip in
  round 8: the English-only 0.6B comes within 1.4 WER points (10.58% against
  9.17%) and does expose token-level timestamps, but it would cost a second
  transformers version in the product for a phase that is 40 s of a 5-minute run,
  so ADR-008 stands —
  `docs/benchmarks/2026-10-26-asr-reference-clip-a.md`. Round 9 of the same file
  measures NVIDIA's speech-LLM (Nemotron 3.5 Transcribe 30B): from audio alone it
  reaches chrF 74.5 with the best length control of any engine (1.075×) in 24 s per
  10 minutes, but it emits **no timestamps** for its own translation, and every
  workaround (CTC times, per-cue slicing, post-hoc alignment) costs coverage or
  quality. It is the closest thing to a one-stage engine we have measured, and it
  needs an aligner the repository does not have.
- **Translation**: **TranslateGemma-12B GGUF on llama.cpp only**, English →
  Italian (ADR-009). The GGUF file is resolved from `llm_translator_gguf_dir`
  and `llm_translator_gguf_quant` (`Q4_K_M` by default; `Q3_K_M`/`IQ3_M` as
  alternatives) and a missing file is a job error, not a silent substitute. A
  non-English source is refused with a message. `check_translation_ready()` runs
  at pipeline STEP 0 (file, llama.cpp, GPU offload) and STEP 6 (free VRAM against
  `gguf_need_gib`), so a broken engine costs seconds. What survives L1/L2 stays
  in the source language, is counted by the audit and is judged by
  `translation_max_untranslated_pct`. NLLB base and fine-tuned survive in
  `core/translator.py` for `bench/` only.
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
- **Library search through Sonarr/Radarr**: the queue page asks a configured
  Sonarr/Radarr for a title, shows every episode with its subtitle state and
  queues the missing ones with one click. Off until `sonarr_url`/`sonarr_api_key`
  (or the Radarr pair) are set in Settings; server paths are mapped to local
  ones with `arr_path_map` (`<server>=<local>`), validated against the allowed
  media roots and never guessed. A server that is down is reported next to the
  results. Validated against two fake servers only — not yet against a real
  instance (`docs/PROGRESS.md`, 2026-10-30).
- **Install policy and preflight (ADR-007)**: two supported backends, CUDA and
  ROCm on AMD RDNA3/RDNA4/CDNA; a job whose GPU does not answer fails in a
  second with the remedy (`allow_cpu` per job to override). `install.sh` detects the hardware (`auto` is the
  default), refuses anything else instead of falling back, verifies the
  installed backend by importing torch, and stamps the result in
  `venv/.tp-backend`; a mismatched re-run refuses to replace torch. CPU and
  Vulkan installs no longer exist.
- **Containers**: `docker/Dockerfile` (one image per backend) and
  `docker/compose.yaml` (profiles `rocm`/`cuda`); not built yet, see the open
  items.
- **GUI optional**: PyQt6 moved to `requirements-gui.txt`; `main.py` exits with
  a message pointing at the WebUI when Qt is absent.
- **ADRs** 001–009, support matrix, contributing rules, guard tests.
- **Tests**: unit/guard tests in `linux_tests/` (bench, boundaries, events,
  docs links, translation gate, i18n, web API/UI/picker/OCR/glossary, Docker,
  install isolation). The suite is fully green: 722 passed, 15 skipped.

## In progress / next

1. **Container validation** — build the three images on a host with a container
   daemon and run the `rocm` profile on the reference machine (Step 8
   acceptance is still open).
2. **End-to-end run of the translation engine — done.** A full film from the
   WebUI (The Lost Leonardo, 1149 cues) completed in 316 s with the single engine,
   the GGUF resolved, the watermark signed `TGemma` and 2 blocks left in English
   out of 1158 (both proper names). The engine comparison that followed — eleven
   configurations on an episode with a professional Italian reference — is in
   `docs/benchmarks/2026-10-28-translation-engines.md`: TranslateGemma-12B Q4
   remains the reference, EuroLLM-22B + rules is the only credible alternative
   (better chrF, 3.8× the time), and the remaining margin is a human-curated
   glossary rather than another model. The refusal path for a non-English source
   is covered by tests, not yet by a real file.
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
   stays, and it is the only one (ADR-008) —
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
  they are downloaded locally, never committed. Since ADR-009 nothing in the
  product loads them: only the `bench/` comparison arms do.
- Names and config keys still say `whisper` although no such engine exists:
  the `whisper_language` keyword (8 call sites), `_step1_whisper_fallback`,
  `sync_allow_whisper_fallback`, 8 `whisper_*` config keys and 30 `sy_*`/`er_*`/
  `ca_*` i18n keys. Renaming them is an API/config change, so it waits for its
  own decision (recorded in `docs/PROGRESS.md`, 2026-10-27).
- ~190 i18n keys are dead (they belonged to the Whisper/Canary code paths).
  They are harmless and cost nothing at runtime, but the two tables are harder
  to read than they need to be.
- The 2026-10-25 translation benchmark table compares six engines; four of them
  no longer exist. It is marked historical and its `llm` row is the reference
  figure for the GGUF engine.
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
