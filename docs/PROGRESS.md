# Progress log

Append-only record of implementation steps and working sessions. The newest
entry goes at the top.

**Hard rule (`AGENTS.md`): every implementation step is recorded here before
its branch is merged** — one entry per pull request, not one per session. A
step is not done until its entry exists: branch and commits, goal, what
changed, tests and results, decisions, known issues, next step. Entries carry
a date and, when the step is part of a larger effort, the step number from
`docs/webui/PLAN.md`.

The shape is enforced by `linux_tests/test_docs_progress.py` (required fields,
newest-first order, the rule stated in `AGENTS.md` and in this header).

## Template

```markdown
## YYYY-MM-DD — short title

- Branch / commits:
- Goal:
- Done (files, commands):
- Tests and results:
- Decisions / ADRs:
- Known issues:
- Next step:
```

## 2026-10-30 — WebUI library search through Sonarr/Radarr

- Branch / commits: `feat/webui-arr-search` — `3da25b7` (work in progress, tests
  hanging), resumed and finished here, merged `--no-ff` into `development`.
- Goal: choosing what to transcribe should not mean walking the filesystem from
  the browser. Sonarr and Radarr already know the library, so the queue page asks
  them for a title, shows the episodes with their subtitle state and queues the
  missing ones with one click. Optional and off by default: without URL and key
  the box is not rendered and the file picker stays the only way in.
- Done (files, commands):
  - `web/arr.py` (new): `servers()` from `sonarr_url`/`sonarr_api_key` and
    `radarr_url`/`radarr_api_key`; `search()` over `/api/v3/series/lookup` +
    `/api/v3/episode?seriesId=` and `/api/v3/movie/lookup` + `/api/v3/movie/{id}`;
    every server path mapped with `utils/path_map.to_local()` (`<server>=<local>`
    rules, same as the Library Scanner), validated with `web/paths.py::is_allowed`
    and annotated with `browse.has_subtitle()`. Returns `SearchResult(groups,
    warnings)`: a server that does not answer becomes a warning, not a missing
    panel. `MIN_TERM = 2` and `MAX_LOOKUPS = 3` bound the fan-out of a box that
    fires while typing. Requests use an opener with an empty `ProxyHandler` — a
    Sonarr on the LAN must not go through `http_proxy` — and only `http`/`https`
    bases are ever used.
  - `web/config_schema.py`: `as_url()` (empty = off; otherwise `http(s)` with a
    host, so a `file://` URL cannot reach `urllib`) and `as_path_map()` (one
    `<server>=<local>` rule per line or `;`-separated, invalid lines rejected
    instead of silently dropped); the two API keys join `SECRET_CONFIG_KEYS`
    (write-only).
  - `utils/config.py`: `sonarr_url`, `sonarr_api_key`, `radarr_url`,
    `radarr_api_key`, `arr_path_map`, all empty — the feature is off until
    someone fills them in.
  - `web/ui.py`: settings group "Library search (Sonarr / Radarr)" with a
    `map` field kind (textarea), `GET /ui/search`, `_search_enabled()` computed
    once per page instead of inside the 2-second queue poll.
  - `web/templates/_search.html` (new) and `index.html`: results per series with
    per-episode status and a "Queue the N missing" form that posts `paths` to the
    existing `POST /ui/jobs`; the search box appears only when a server is
    configured and re-runs after a queue to refresh the badges. `app.css`: the
    results list was unstyled.
  - `linux_tests/test_web_arr.py`: 12 tests with two fake servers (Sonarr and
    Radarr on 127.0.0.1) plus the config contract; `linux_tests/test_web_ui.py`:
    6 more (settings group, save/validate/never-echo, search box only when
    configured, "not configured" message, dead server, minimum term).
- Tests and results: `venv/bin/python -m pytest linux_tests -q` → **722 passed,
  15 skipped** in 69.5 s (737 collected; this branch adds 18 tests, the earlier
  701 in `STATUS.md` predates commits landed after 2026-10-27).
  The hang that stopped the previous session was the fixture itself:
  `for srv in servers: ... servers.append(srv)` appended to the list it was
  iterating, so teardown never started working and the process spawned threads
  until the harness died of `ENOSPC`. Reproduced with `timeout 25 pytest
  linux_tests/test_web_arr.py` (one dot, exit 124) while the one test without the
  fixture passed in 0.05 s; isomorphing the loop shape outside pytest reached
  100 000 iterations without terminating. The fixture now starts a fixed tuple of
  servers, answers 401 on a wrong key instead of asserting inside a handler
  thread, clears `TP_MEDIA_ROOTS` (it overrides `allowed_media_roots`) and sets
  `NO_PROXY`, and shuts both servers down in teardown: 0.31 s for the file.
  Two further bugs were found by testing the feature end to end rather than the
  module: `sonarr_url`/`radarr_url`/`arr_path_map` were whitelisted but had no
  validator, so `normalise_values()` raised `keys not writable` and the settings
  group could never be saved; and `search_enabled` was computed inside
  `_queue_context`, whose dict `index.html` receives as `queue`, so the search box
  would never have appeared.
- Decisions / ADRs: no new ADR — the integration is optional, read-only on both
  sides and silent until configured, so it adds no default dependency. Path
  mapping reuses `utils/path_map.py` instead of inventing a second rule format;
  validation reuses `web/paths.py::is_allowed`, the check the queue applies.
  Failures are per server (warning next to the results) so a Radarr that is down
  cannot hide the Sonarr library.
- Known issues: the episode list is whatever `/api/v3/episode?seriesId=` returns,
  so a series with thousands of episodes is rendered in full (no paging, no
  server-side filter); a title that matches more than three series shows only the
  first three (deliberate, but invisible in the UI); the movie panel issues one
  extra `GET /api/v3/movie/{id}` per match; nothing was validated against a real
  Sonarr/Radarr instance yet — only against the two fake servers — because the
  reference machine has neither configured.
- Next step: point a real Sonarr and Radarr at it on the reference machine
  (`/tv=/mnt/storage/tvshows`), transcribe one season from the browser, and check
  that the `arr_path_map` hint is enough when it is wrong; then decide whether the
  picker is demoted below the search box.

## 2026-10-28 — Nemotron 3.5 Transcribe 30B (SALM): the best audio→Italian, no timings

- Branch / commits: `docs/nemotron-transcribe-round9`.
- Goal: NVIDIA's speech-LLM is the only candidate that could collapse ASR and
  translation into one stage. Round 9 measures it on clip A against the same
  professional Italian reference as rounds 1-8.
- Done (files, commands): round 9 appended to
  `docs/benchmarks/2026-10-26-asr-reference-clip-a.md`. Environment built for the
  test, outside the repository: NeMo-Speech.cpp `66d50d9` (llama.cpp `bd4f514`),
  preset `vulkan-speech -DNEMO_SPEECH_BUILD_SPEECHLM=ON`, apt deps
  (`libvulkan-dev glslc spirv-headers libsentencepiece-dev pkg-config`) plus
  CMake/Ninja from pip, weights `AD-Q2_0_M` + `Encoder-F16` (14.2 GiB) from a
  third-party GGUF of `nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B`.
- Tests and results: **N** (`--translate-to it`, whole audio) gives Italian from
  audio at **chrF 74.5**, length **1.075x** (best of every engine tried), in
  **24.3 s per 10 minutes** — against 76.9 chrF and ~3 minutes for the 12B
  translating a professional English subtitle. But **no timestamps**: `words: []`,
  and the tool rejects `--word-times` with `--translate-to` because the CTC head is
  trained on transcription. Forcing them via the card's canonical instruction (row
  B) gives timed Italian with **coverage 80%** and fragmented cues; qwen3 cues plus
  per-cue audio translation (row D) restores coverage to 96% but drops chrF to 72.7,
  length to 1.20x and costs **8.4 min per 10 min** (2.8 s/cue, model reload each
  call). Post-hoc alignment of N's Italian onto VAD spans covers only 56 of 104
  professional cues. VRAM measured at **15.25 GiB of 15.92 (96%)**, peak 15.77 with
  the desktop. `AD-IQ4_NL` cannot load: the SALM loader hardcodes
  `n_gpu_layers = 999 or 0`, and a local fork (NGL override + CPU in the device
  list) is what makes it load — out of scope.
- Decisions / ADRs: **ADR-008 and ADR-009 stand**. N is the best audio→Italian
  engine measured, but a subtitle needs words on a timeline and none of the three
  workarounds closes that gap; the missing component is a forced aligner for the
  translated text, which the repository does not have since ADR-009 removed the
  matching stage of the synchroniser.
- Known issues: the round's N figure is text-level (no cues to window) while B and D
  are windowed, so they are comparable in direction, not exactly; the two plain
  transcription rows are measured against the **English** reference, not the
  Italian one. Build and weights stay outside the repository (scratch dir).
- Next step: nothing on this model family unless it emits word times for its own
  translation; the next practical work is the glossary for rare terms and replacing
  the broken Italian sidecars on the `Our Oceans` season.

## 2026-10-28 — Nemotron 3.5 ASR streaming tried against the ASR reference

- Branch / commits: `docs/nemotron-asr-round8`.
- Goal: NVIDIA published two streaming ASR models with open weights
  (`nemotron-speech-streaming-en-0.6b`, English-only, and
  `nemotron-3.5-asr-streaming-0.6b`, multilingual). Round 8 of the ASR reference
  evaluation asks whether either can replace Qwen3-ASR (ADR-008).
- Done (files, commands): round 8 appended to
  `docs/benchmarks/2026-10-26-asr-reference-clip-a.md`, with the table of both
  models across chunk sizes, on **clip A** and with the same reference and the
  same exclusions as rounds 1-7 (135 cues -> 129, 709 words), so the numbers sit
  next to the qwen3 baseline. Test environment: `transformers>=5.13` with
  `AutoModelForRNNT` in a separate venv with CPU-only torch, because the product
  venv is pinned at transformers 4.57 and was not touched.
- Tests and results: English-only model **10.58% WER / chrF 0.931** at 15 s
  chunks (674 of 709 words), against **9.17% / 0.944** for qwen3 on the same
  clip; multilingual model 15.94% at 60 s and **51.76% at 240 s**, where it drops
  half the audio. CPU speed ~16x realtime (36 s for 10 minutes) against 41.5 s of
  GPU for qwen3.
- Decisions / ADRs: none changed — **ADR-008 stands**, but for accuracy rather
  than for timestamps. An earlier reading of this round said the models return no
  cue timestamps; that was wrong: `processor.decode(sequences, durations=...)`
  yields token-level `{token, start, end}` in seconds at 80 ms granularity
  (verified on clip A). The English-only model is therefore technically
  integrable; what it costs is +1.4 WER points (~10 more word errors per
  10 minutes), a second transformers version in the product (5.13 against the
  pinned 4.57, either re-verify the venv or use a subprocess with its own venv as
  the spaCy gender selector does) and a new engine module with cue building and
  language detection — for a phase that is 40 s of a run whose translation is
  ~4 minutes and never shares VRAM with it. Recorded in the round: the
  large-chunk collapse, that removing fillers *worsens* the WER because the
  reference keeps them, and the condition under which this model becomes the
  right trade (ASR-bound hosts: many files, no GPU for ASR).
- Known issues: the comparison is text-level, not windowed, because rounds 1-7
  compared text inside 10-second windows and that is what makes the figures
  comparable; the models do emit token timestamps, so a windowed comparison is
  possible in a future round. qwen3's figure comes from the pipeline (cleanup,
  watermark removed) while the Nemotron figures are raw model output, so the gap
  is directionally solid but not measured with identical post-processing. The
  weights stay outside the repository.
- Next step: none on the ASR side. If a future model returns word timestamps at
  0.6B, it becomes worth a second look; otherwise Qwen3-ASR stays.

## 2026-10-28 — Translation engine campaign: compendium and harness

- Branch / commits: `docs/translation-engine-compendium`.
- Goal: eleven translation configurations were measured on one episode with a
  professional reference; without a written record the next session would repeat
  the runs and re-learn the two metric traps. This step records the campaign and
  makes it reproducible.
- Done (files, commands): new `bench/translation_compare.py`, the harness used for
  every run, self-contained and with three modes (`translategemma` = the product's
  own prompt path, `chat` = a model with a system role and optional subtitle
  rules, `raw` = no chat template) plus the `edit` subcommand for a second
  constrained pass. New `docs/benchmarks/2026-10-28-translation-engines.md`:
  material, method, the table of all eleven configurations, what did not work
  (context in the prompt, the editor pass, "just use a bigger model"), the defect
  taxonomy, the limits, the reproduce commands and an appendix with short
  excerpts. `docs/benchmarks/README.md` gains the row and the command;
  `docs/STATUS.md` item 2 records that the end-to-end run has been done.
- Tests and results: `pytest linux_tests -q` -> see the suite figure in the merge
  commit; docs guard tests green. Repro of the first run:
  `python -m bench.translation_compare translate --engine translategemma ...`
  reproduces the baseline (chrF 0.7608, WER 0.7393, 28.3 chars/cue).
- Decisions / ADRs: no new ADR; ADR-009 stays as it is because no engine replaced
  the current one. Recorded conclusions: TranslateGemma-12B Q4 remains the
  reference (best WER, tightest length, fastest, half the weights); EuroLLM-22B +
  rules is the only credible alternative (chrF 0.7682 vs 0.7608, tied on
  untranslated blocks, Apache-2.0, but 3.8x the time and 1.9x the VRAM);
  context as prose is archived (inert on the 12B: 0-1 cues changed of 630; it
  hurts the 22B: untranslated 33 -> 45/46); the editor pass is rejected (chrF
  +0.008, WER worse, invents words such as "altana" for a gallows); the
  remaining margin is a human-curated glossary for rare terms, plus referent
  errors that no validator can catch.
- Known issues: the campaign is **one episode** of one genre. The mechanisms it
  exposes are portable, the absolute numbers and the 8-thousandths margin between
  12B and 22B are not. Nothing in the product changed, so the 22B is *measured
  but not adopted*. Seed-X was not evaluated as a model: its unofficial GGUF
  degenerates, which matches the model card's warning.
- Next step: if the ranking needs to be firmer, repeat on 2-3 episodes of
  different genres with the three finalists only (12B, 22B + rules, 27B) and
  report per episode; then attack the glossary with a paired en/it episode
  (glossary from episode A, applied to episode B, measured against B's
  professional track).

## 2026-10-27 — WebUI aligned with the single engine

- Branch / commits: `feat/webui-single-engine`, from `development` (`1e6507b`).
- Goal: after ADR-008 and ADR-009 the settings page still offered controls that
  controlled nothing, and the dashboard was silent about the one thing that can
  be missing. Three keys (`whisper_model`, `whisper_vad_threshold`,
  `whisper_vad_min_silence_ms`) were not even in `Config.DEFAULTS`: the UI wrote
  them into the config and no module read them. `llm_translator_model` is a free
  text field where only one value is valid, and `translation_model` a select with
  one option. There was, in exchange, no way to say where the GGUF weights are.
- Done (files, commands):
  - `web/config_schema.py`: the three dead keys and their numeric limits are
    gone, `translation_model` and `llm_translator_model` are no longer writable,
    `FREE_TEXT_KEYS` is empty (no free fields); `target_language` becomes an enum
    `('ita',)` instead of a regex over ISO codes; new `as_dir(key, value)` used by
    `picker_start_dir` and the new `llm_translator_gguf_dir` (empty = default,
    otherwise an absolute directory that exists).
  - `web/ui.py`: settings reduced to what changes something, with the weights
    (`llm_translator_gguf_quant`, `llm_translator_gguf_dir`); the dashboard
    computes the engine status on every render.
  - `utils/backend_preflight.py`: `translation_status(config)` — GGUF file,
    llama.cpp with offload, quantization, VRAM needed against VRAM free. It is
    not `check_translation_ready`: that one **refuses** when the free VRAM is not
    enough right now, this one **describes** the engine, otherwise the dashboard
    would turn red during every translation in progress.
  - `web/templates/_status.html` + `web/app.py`: a **Translator** row
    (quantization, file, "needs >= 8.8 GiB, 15.8 free") and a red alert with the
    reason and the remedy when the engine is not ready; `/api/status` exposes the
    same block.
  - `web/README.md`: the ctranslate2 reference is gone, new "Settings that exist"
    section, explanation of the Translator row.
  - `utils/job_overrides.py`: comment on why `TRANSLATION` stays (the frozen Qt
    builds its per-file menu with it) while its historical values are dropped.
- Tests and results: `pytest linux_tests -q` -> **704 passed, 15 skipped, 0
  failed**. New tests: the settings page no longer shows the five dead keys and
  does show the weights; the GGUF folder is saved, rejects a relative path and a
  missing directory, and empty returns to the default; the dashboard shows the
  Translator row with its numbers and the alert when the engine is missing (the
  probe is stubbed: llama.cpp and torch are not touched in tests); `/api/config`
  rejects an unknown quantization, a relative folder and `target_language: eng`.
  `test_vad_knobs_in_settings` was removed: it asserted the presence of the dead
  keys.
- Decisions / ADRs: no new ADR, ADR-009 applies. Two explicit choices: (1) the
  keys stay in `Config` as legacy — the frozen Qt and old `config.json` files are
  not touched, they are simply no longer offered; (2) the dashboard distinguishes
  "engine ready" from "enough VRAM right now", because a running job holds the
  card by definition.
- Known issues: the server running on the reference machine was started before
  these merges: `/api/models` still answers with the six old engines until it is
  restarted (the job itself runs the new code, being a child process).
  `translation_model` remains a per-file override key that accepts only the
  canonical value.
- Next step: restart the server and check both pages by hand; then, if wanted,
  the rename pass for the `whisper_*` names and keys (see the entry about the
  Whisper leftovers).

## 2026-10-27 — One translation engine (ADR-009)

- Branch / commits: `feat/single-translation-engine` — `8906970` (1), `bf549f2`
  (2), `4ca8f8a` (3), `fe749cc` (3b), `3d408fd` (4), `3e432a0` (5), `f10565f`
  (6), `f3c7715` (7), `1040e66` (docs), `f66753c` (alignment with `development`).
- Goal: translation had four engine families (NLLB base and fine-tuned,
  TranslateGemma in three shapes, three cloud engines) plus an L3 reservoir that
  handed the hard lines to a second model on a CLI of its own. Every branch ended
  in a **silent** substitute: an LLM that would not start became NLLB-FT, a GGUF
  that would not load became NF4, a missing GGUF became the transformers path, a
  non-English source was routed to NLLB. The user saw a finished subtitle and did
  not know which model had written it. The measurements said one engine was
  good; the rest was cost.
- Done (files, commands), per step:
  1. non-English sources are **refused** in `core/pipeline.py` STEP 6 and
     `core/ocr_auto.py`; `route_non_english_away_from_llm()` deleted;
     `test_translation_routing.py` -> `test_translation_refusal.py`.
  2. `core/subtitle_synchronizer.py` timing-only: `_LocalQwenMatcher`,
     `_step2_translate_anchors`, `_step3_match_subtitles`, the LLM path of
     `_step1_whisper_fallback`, `sync_engine` and 26 `sy_*` strings removed
     (1942 -> 1062 lines).
  3. cloud engines removed (`ClaudeTranslator`, `OpenAITranslator`,
     `utils/opensubtitles_ai_translator.py`, the hallucination guard), keys and
     strings; 3b: the cloud-API config methods stay **legacy** because the frozen
     Qt calls them (static check: 0 missing methods).
  4. L3 reservoir removed: `core/fallback_translate_cli.py` deleted,
     `RESERVOIR_*` and its two call sites gone, `reservoir_engine` /
     `fallback_translator_model_path` gone, `tl_reservoir_*` / `fb_*` strings gone
     from both tables and from the manifest.
  5. quant policy: `utils/translator_path_select.py` -> `utils/gguf_quant.py`
     (the measured numbers and `normalize_quant` stay), `path_router.py` deleted,
     `resolve_gguf_path()` in `gguf_engine.py` **raises** naming the directory and
     the files it found; `engine.py` keeps one `ModelSpec` and
     `build_mt_messages()`, loses `SubtitleLLMEngine`/`get_engine`/`unload_engine`
     and the bf16/NF4/LoRA loaders; `GGUFEngine` no longer subclasses it.
     Config: `llm_translator_gguf_quant` defaults to `Q4_K_M`,
     `llm_translator_gguf_enabled`, `_before_nf4`, `_nf4_min_free_gb`,
     `_q4_min_free_gb`, `_iq3_min_free_gb` are gone. Installer:
     `gguf_download.py` no longer asks for VRAM, `auto` = `Q4_K_M`.
  6. one engine and one target language: `VALID_TRANSLATION_MODELS =
     ['translategemma-12b-gguf']` with `LEGACY_TRANSLATION_MODELS` mapping
     `nllb`, `nllb_finetuned`, `llm`, `aya`, `claude`, `openai`,
     `opensubtitles` (on read **and** on write, with a log line);
     `LANGUAGES = ('ita',)` in `web/ui.py` and `utils/job_overrides.py`; the
     engine select is gone from the queue; `_NOMI_MOTORE` and `_TM_SHORT`
     collapsed; `get_translation_model_info()` removed.
  7. a missing engine is a job that fails in seconds:
     `utils/backend_preflight.check_translation_ready()` (quantization, GGUF
     file, llama.cpp with GPU offload, and only with `check_fit` the VRAM against
     `gguf_need_gib`) called at STEP 0 and STEP 6, with the probe in a subprocess
     (llama_cpp must not be imported after torch in a process that already has
     PyQt).
- Tests and results: `pytest linux_tests -q` green at every step: 801 -> 692
  (step 5: the selector, router, flag and NLLB-fallback tests went away with the
  code they tested) -> 701 (steps 6 and 7 add the refusal, legacy mapping and
  preflight tests, 8 new). After the alignment with `development`:
  **701 passed, 15 skipped, 0 failed**. `git diff origin/development -- gui/`
  empty at every commit.
- Decisions / ADRs: **ADR-009** (`docs/adr/ADR-009-single-translation-engine.md`),
  with the measured context, the rejected alternatives and the consequences.
  Choices inside the ADR: quantization as a **setting** and not as a VRAM guess;
  the GGUF is **resolved** and not chosen; non-English sources refused; NLLB kept
  in `core/translator.py` **only** for the benches, and it says so in the log;
  `llm_translator_adapter` and `llm_translator_model_path` kept because the frozen
  Qt writes them (the adapter is reported as not applied, the path counts as an
  alternative GGUF directory).
- Known issues: **the end-to-end run had not been executed at merge time** (it was
  run later the same session: The Lost Leonardo, 316 s, one file end to end). The
  branch left names and keys that still say `whisper` (the `whisper_language`
  keyword, `_step1_whisper_fallback`, `sync_allow_whisper_fallback`, 30 i18n keys
  and 8 config keys): documented, not renamed. About 190 i18n keys were already
  dead before this work (whisper/canary).
- Next step: end-to-end run and export (done the same day, see the 2026-10-28
  entry); then, if wanted, the rename pass for the `whisper_*` names and keys.

## 2026-10-27 — Removing the committed key and address

- Branch / commits: `fix/no-committed-endpoint`, from `development` (`95729de`).
- Goal: remove the two default values that cannot stay in the repository — an API
  key and a private network address — without breaking the Library Scanner.
- Done (files, commands): in `utils/config.py` `library_scanner_url` and
  `library_scanner_api_key` default to `''`, with a comment saying where to set
  them; `docs/architecture/config.md` has a rewritten "Secrets and local
  endpoints" section: updated list (`claude_api_key` / `openai_api_key` no longer
  exist with ADR-009, an old config is harmless), the rule that no default is a
  secret or an address, and the historical note that the key has been in git
  since `1ab14ab` and must be **rotated**, because removing it from the working
  tree does not remove it from history.
- Tests and results: `pytest linux_tests -q` -> **798 passed, 15 skipped, 0
  failed**. No test depended on the defaults:
  `test_library_scanner_fake_server.py` sets url and key itself, and the GUI
  already handles empty values (`gui/library_scanner_widget.py` shows
  `config_missing`).
- Decisions / ADRs: no ADR. Empty string, not an example value: a placeholder
  such as `http://example:6680` would be copied into a real config and is an
  invented address to maintain. With the empty value the GUI says "config
  missing", which is the true state of a fresh installation.
- Known issues: the key stays in git history (commit `1ab14ab`): it must be
  rotated on the service, an owner action. Other references to the same private
  address remain in the working tree — `gui/general_settings_widget.py:131`
  (placeholder), `utils/path_map.py:8` (docstring example), `CHANGELOG.md:183`
  (historical entry) and six occurrences in the `docker/library_scanner/` service
  (sample data and placeholders) — **not touched here**: the GUI is frozen
  (ADR-002) and replacing them is a separate decision (the obvious replacement is
  `192.0.2.10`, TEST-NET-1 from RFC 5737, reserved for documentation).
- Next step: `--no-ff` merge into `development`; rotating the key; deciding
  whether to sanitise the other references (GUI included).

## 2026-10-27 — Whisper leftovers: the `docs/cleanup-after-whisper` stash

- Branch / commits: `chore/cleanup-after-whisper` (`150a366`), from
  `origin/development` (`c5b856d`).
- Goal: close the debt left in `stash@{0}` — the comment cleanup for the
  multi-engine architecture that ADR-008 made false — and extend it to the places
  the stash did not cover, before another session finds it stale.
- Done (files, commands): the stash was applied (clean `git stash apply` on
  `origin/development`) and the misindented banner it introduced was fixed; then
  the same class of defect wherever the stash did not reach. Comments and
  docstrings: `core/pipeline.py` (the "STEP 2.5: preload WhisperModel" block above
  code that preloads nothing; the CUDA-workspace cleanup docstring that cited
  `ctranslate2 4.6.0` and the crash under PyQt6; "whisper + Canary/Qwen3" in the
  resource cleanup), `core/engines/base_engine.py` and
  `core/engines/qwen3_asr_engine.py` (`LanguageNotAlignable` "retranscribes with
  faster-whisper" is no longer true: since ADR-008 the job fails),
  `core/pipeline_cli.py`, `core/sync_cli.py` (which still advertised the `llm`
  sync engine removed with ADR-009, and still described the ctranslate2 load
  order), `core/subtitle_synchronizer.py` (VAD "included in faster-whisper" ->
  `core/vad.py`), `core/diarizer.py`, `core/translator.py` (batch cap comment),
  `core/gender_line_selector.py`, `core/gender_selector_cli.py`,
  `utils/cache_bootstrap.py` (`whisperx` -> `qwen3` among the modules to import
  after the cache bootstrap). Two dead entries removed: `ENGINE_CHUNK_CAP_S` in
  `core/audio_processor.py` (only `qwen3` remains; `min()` on the dictionary still
  gives the prudent cap to a caller that does not name the engine) and
  `_ASR_BY_ENGINE` in `core/jobs/progress.py` (the `canary` row). The condition
  `_planned_engine != 'faster-whisper'` became `len(chunk_list) > 1`: it was
  always true. `git stash drop` executed: the content is in the commit.
- Tests and results: `pytest linux_tests -q` -> **798 passed, 15 skipped, 0
  failed**; no test changed, as expected for a branch of comments and dead
  entries only.
- Decisions / ADRs: no ADR. A branch separate from ADR-009 because the work is
  unrelated to the single-engine translation: mixing them would have made the
  ADR-009 series unreadable.
- Known issues: names and keys that mention Whisper remain, deliberately **not**
  touched because they are API and configuration rather than comments: the
  `whisper_language` keyword (8 places across `core/pipeline.py`,
  `core/transcriber.py`, `core/subtitle_synchronizer.py`),
  `_step1_whisper_fallback` and `sync_allow_whisper_fallback`, 30 `sy_*`/`er_*`/
  `ca_*` i18n keys that mention Whisper or Canary, 8 `whisper_*` config keys
  (`whisper_model` and `whisper_vad_*` included) and the
  `pl_early_unload_of_demus_whisper` key. Renaming them changes API, user
  strings and config: that needs a decision, not a cleanup.
- Next step: `--no-ff` merge into `development` and branch deletion; the rename
  of names and keys, if wanted, as a separate step with its own entry.

## 2026-10-27 — Venv rebuilt from the new requirements (no Whisper)

- Branch / commits: `fix/venv-rebuild-notes`.
- Goal: prove that the requirements really are self-sufficient after removing
  Whisper — a claim a rebuilt environment can settle in ten minutes.
- Done: `venv/` deleted and rebuilt with `./install.sh --backend=rocm --yes`;
  `install.sh` fixed: removing the ctranslate2 probe left an `if backend in
  ('rocm','cuda'):` with no body, so the post-install verification died with an
  `IndentationError` after a full install; `pytest` added to
  `requirements-dev.txt` (it was installed by hand before, so a fresh venv could
  not run the suite).
- Tests and results: new venv 15 GB, `faster-whisper`, `ctranslate2` and
  `whisperx` **not installed** (0 matches), `torch 2.10.0+rocm7.0` with
  `cuda True`, `qwen-asr 0.0.6`, `demucs 4.0.1`, `llama_cpp_python 0.3.34`
  (Vulkan), `onnxruntime 1.24.3`, our VAD loads. `--verify-only` writes the stamp
  (backend rocm, torch, torchaudio, llama, requirements, date — no ctranslate2).
  Suite: 797 passed, 15 skipped (the extra 4 are the PyQt6 scanner tests, correctly
  skipped without the optional GUI), 0 failed. End-to-end on the rebuilt venv:
  MobLand Italian clip **WER 11.87%**, chrF 94.33, coverage 100% — equal to the
  11.71-11.87% of the previous venv.
- Decisions / ADRs: no ADR. The rebuild is the acceptance for ADR-008: the install
  no longer touches ctranslate2, whisperx or any Whisper wheel, and the pipeline
  runs the same.
- Known issues: the Hugging Face cache still holds `faster-whisper-large-v3`
  (2.9 GB) and `faster-whisper-tiny`; nothing reads them any more, but deleting them
  is a housekeeping decision, not a code one.
- Next step: rebuild the Docker images from the new requirements (Step 8
  acceptance), which is now simpler: no ctranslate2 wheel to fetch.

## 2026-10-27 — Whisper removed: one ASR engine (ADR-008)

- Branch / commits: `feat/remove-whisper`.
- Goal: keep only what the pipeline actually uses. The reference evaluation showed
  qwen3 equal or better than Whisper on both languages of the library, so the
  second engine, its runtime and everything that existed to keep them apart could
  go.
- Done: deleted `faster_whisper_engine.py` (837 lines), `canary_engine.py`,
  `canary_cli.py`, `aligner.py` (whisperx), `whisper_lang_retry.py`,
  `ct2_bootstrap.py`; `core/transcriber.py` rewritten as a Qwen3-only facade (no
  preload, no fallback: an engine error is a job error); `core/engine_router.py`
  shrunk to a single-engine `plan()` that keeps the pipeline's contract and logs
  the reason; the pipeline lost the "2.5 preload", the early unload of Whisper, the
  batched single-file branch, the forced-alignment block and the fatigue counter;
  `transcription_engine_mode` accepts `qwen3` (and `auto`), migrating `canary` and
  `faster-whisper` on read with a log line; config lost `whisper_model`,
  `whisper_model_by_language`, the two VAD keys, `whisper_preload_mode`,
  `enable_forced_alignment` and every `canary_%` key; `backend_preflight` probes
  torch only; `requirements*.txt` lost `faster-whisper`, `ctranslate2` and
  `whisperx`; `install.sh` lost the **ctranslate2 ROCm wheel** download and the
  `whisperx --no-deps` step, the backend verification no longer asks ctranslate2 and
  the stamp records torch only; `engine_labels` and the WebUI status card follow.
- Tests and results: suite green after removing the tests of the deleted pieces and
  with new guards (no preload, no `whisper_preload_mode`, engine migration). Measured
  after removal on the 10-minute clips: Italian **11.71% WER** (baseline 11.79%),
  English **10.01% and 9.59%** on two runs (baseline 9.17%): the spread between two
  identical runs is 0.42 points, so the difference is inside the noise and has no
  mechanism — the preload never touched qwen3's output. Wall time 133.1 s against
  134.4 s (Italian), 94.8/95.2 s against 102.9 s (English).
- Decisions / ADRs: **ADR-008**. A language outside qwen3's aligner is refused with
  a clear error instead of being transcribed slowly by Whisper; that is acceptable
  because the library is Italian and English and both are covered.
- Known issues: the venv still contains the three packages until it is rebuilt
  (`pip uninstall` or a fresh `./install.sh`), and the model cache holds
  `faster-whisper-large-v3` (2.9 GB) until someone deletes it; the stamp will record
  torch only at the next install. The noise floor of a 10-minute clip is ~0.4 WER
  points, which is the resolution of every comparison in the benchmark docs.
- Next step: rebuild the venv from the new requirements on a clean machine (and in
  the container images) to confirm the install has no hidden whisper dependency.

## 2026-10-26 — Benchmark appendix: the errors in the text

- Branch / commits: `docs/benchmark-examples`.
- Goal: make the evaluation readable to someone who will not look at the tables,
  and keep the qualitative evidence next to the numbers.
- Done: appendix in `docs/benchmarks/2026-10-26-asr-reference-clip-a.md` with
  five groups of examples (short lines that qwen3 keeps and Whisper's VAD drops;
  proper names mangled differently by both; words Whisper gets right and qwen3
  does not; qwen3's window spill that looks like an error but is segmentation;
  interjections that neither transcribes), plus a pattern table and the two
  practical consequences (the glossary is the cheapest win; WER rewards the
  engine that speaks less).
- Tests and results: documentation only; docs guard tests green, full suite
  green.
- Decisions / ADRs: no ADR. The appendix is evidence, not a new measurement: the
  texts come from the SRTs produced in rounds 1 and 2.
- Known issues: the examples are hand-picked from two clips of one episode and
  illustrate the failure modes, they do not quantify them — the tables do that.
- Next step: none for the ASR question; the evaluation is closed and documented.

## 2026-10-26 — Verified the own VAD before removing Whisper

- Branch / commits: `feat/vad-without-whisper`.
- Goal: prove the new VAD path equivalent before deleting the dependency it
  replaces, as agreed (tests first, removal after).
- Done: `docs/benchmarks/2026-10-26-vad-port-verification.md` with the three
  checks; the clip without subtitle streams and the shifted reference used for the
  sync test were prepared with the harness tools and kept outside the repository.
- Tests and results: (1) same audio, old vs new VAD: 154 vs 166 segments, 420.0 vs
  411.4 s of speech, **98.0% intersection, 0.000 s median start difference**, 0.52
  vs 0.76 s runtime; (2) synchroniser on a clip with **no subtitle streams** and a
  reference shifted **+2.5 s**: output within **0.183 s median / 0.21 s max** of the
  truth, 214 cues preserved, text WER 0.00% (log: `VAD: 168 speech intervals`,
  `Global alignment: scale 1.00010, offset -2.35 s`); (3) transcription regression:
  WER 11.79% -> 11.87%, chrF 94.50 -> 94.35, drift 0.60 -> 0.66 s, wall 134.4 ->
  134.7 s, all inside the noise of this clip.
- Decisions / ADRs: no ADR yet; ADR-008 ("a single ASR engine") comes with the
  removal.
- Known issues: the new VAD splits a few segment boundaries differently and reports
  ~2% less speech — irrelevant for an anchor that feeds a global alignment, but
  recorded.
- Next step: remove `faster-whisper`, `ctranslate2` and `whisperx` together with
  the router fallback, the preload, the aligner and the installer step; then re-run
  the same two clips.

## 2026-10-26 — Why Whisper is preloaded with qwen3, and why it stays

- Branch / commits: `feat/whisper-preload-optional`.
- Goal: answer "why load Whisper when the engine is qwen3?" with the code's own
  reason and with a measurement, instead of removing it on instinct.
- Done: documented the reason found in the code — `ctranslate2` initialises CUDA
  lazily, and initialising it *after* PyTorch/Demucs has used the GPU ends in a
  silent `std::abort`, so Whisper is loaded before Demucs to initialise it with a
  virgin context (and doubles as a warm fallback); added the config key
  `whisper_preload_mode` (`always`, the historical behaviour, or `auto`, which
  loads it only when the planned engine is faster-whisper) and moved the engine
  planning **before** the preload so the decision can be made; i18n string
  `pl_whisper_preload_skipped`.
- Tests and results: `test_i18n_texts.py` and the scan keep the new string
  honest; suite green. Measured on the Italian clip with `auto`: the log confirms
  `⏭️ Whisper preload skipped: engine planned is qwen3`, the job completes
  normally (qwen3 never needs ctranslate2) and the wall time is 136.2 s against
  134.4 s — the 2.1 s preload disappears into run-to-run variance.
- Decisions / ADRs: **the default stays `always`**. The saving is 2.1 s and
  ~1.5 GB of VRAM churn per episode, but the preload protects a real path: qwen3
  raises `LanguageNotAlignable` for languages outside the aligner's set and the
  router re-transcribes with faster-whisper *after* Demucs, which is exactly the
  late-initialisation case the preload exists for. `auto` is available for
  benchmarking or for installations that accept that risk.
- Known issues: the failure that started this investigation — a broken
  ctranslate2 killing a qwen3 job — is not solved by `auto`; it is solved earlier,
  by the installer verification (ADR-007) and the runtime preflight, which refuse
  the venv before a job starts.
- Next step: none. If the fallback path is ever removed, `auto` becomes the right
  default and the preload can go.

## 2026-10-26 — Italian source: cast glossary in the ASR context, and where it stops

- Branch / commits: `feat/glossary-first-names`.
- Goal: measure the ASR context on an Italian source with a real cast, and check
  whether the name error of the previous run gets fixed.
- Done: `web/glossary.py::parse_cast_text()` now also emits the **individual first
  and last names** (particles like `Da`, `de`, `van` excluded), because dialogue
  says "Richie" and not "Richie Stevenson": the MobLand credits produce 48 terms
  instead of 22. The cast was written through the WebUI code path
  (`write_fixed_glossary`, `manual_mobland.json`) and the clip was re-run with
  `glossary_id: mobland`.
- Tests and results: parser test updated for the extra single names; suite green.
  Measured on the same 10-minute Italian clip: WER 11.79% -> 11.79%, CER 6.31% ->
  **6.10%**, chrF 94.21 -> **94.50**, drift median 0.72 s -> **0.60 s**, ASR 75.6 s
  -> 79.4 s. Names: **2 of 7** `Ricci` occurrences became `Richie` — precisely the
  two where the surname follows (`Richie Stevenson`, `Richie dice`); the vocatives
  (`Ricci, ho parlato con...`) stayed, because the Italian dub pronounces the name
  the way Italians spell "Ricci" and a prompt hint loses against the model's
  orthographic prior.
- Decisions / ADRs: no ADR. The context costs nothing on Italian material (unlike
  the English round, where it moved WER by half a point) and improves chrF and
  alignment, so it stays; but it is not a complete fix for names that the dub
  pronounces like a common Italian word.
- Known issues: five `Ricci` remain in one clip; the honest next step is a
  **declared** mishearing map (`Ricci -> Richie`) applied to the transcript
  deterministically, which is different from fuzzy matching (no guessing) and
  composes with the context. The alignment gap on Italian (0.72 s median against
  0.16-0.29 s on English) is still a single-clip observation.
- Next step: implement the declared mishearing map in the glossary file and the
  UI, then re-measure; and run a second window to confirm the alignment figure.

## 2026-10-26 — First measurement on Italian source (no translation)

- Branch / commits: `docs/italian-source-measurement`.
- Goal: measure the configuration used for Italian material — Italian audio,
  Italian target, no translation — which the English-source rounds could not
  isolate.
- Done: `docs/benchmarks/2026-10-26-italian-source-mobland.md` with method,
  result, sampled examples and observations; the clip (30:00-40:00, the densest
  window of a 59-minute episode with an Italian dub and four SubRip tracks) and
  its reference were cut with the harness and are kept outside the repository.
- Tests and results: one run, qwen3 only: **WER 11.79%, CER 6.31%, chrF 94.21,
  coverage 100%** (0 words missing, 0 extra), 1 197 output words against 1 196 of
  reference (1.00x), drift median 0.72 s / p90 3.13 s, ASR 75.6 s for 10 minutes.
  The same pipeline on an English source translated to Italian scored 59.76% WER:
  the gap is the translation step.
- Decisions / ADRs: no ADR. This is the reference figure for the Italian workflow:
  ~12% WER against a professional subtitle with complete coverage, no hallucination
  and no lost lines.
- Known issues: the alignment is measurably worse than on English (0.72 s median
  against 0.16-0.29 s) — one clip, so not yet a conclusion; a name error appears
  ("Richie" -> "Ricci") because no glossary was active, and this episode has no
  TMDB key, so the cast must be pasted manually; window spill inflates the WER of
  short reference cues.
- Next step: a second window on the same episode, then the same clip with the
  cast pasted in the WebUI to measure the ASR context on Italian names.

## 2026-10-26 — WebUI: build the fixed-rendering glossary from the browser

- Branch / commits: `feat/glossary-ui` (same branch as the TMDB seeding).
- Goal: stop hand-editing JSON — the glossary that feeds the ASR context and the
  translator is created from `/glossary`, either from a TMDB id or from a cast
  list pasted the way the show's credits are written.
- Done: `web/glossary.py` gains `parse_cast_text()` (handles `Actor as Character`,
  a line ending with `as` whose character sits on the next line, descriptions after
  a comma, `[n]` notes, quoted aliases used as separate entries, generic roles
  dropped), `list_fixed_glossaries()` and `write_fixed_glossary()`;
  `build_from_tmdb()` reuses `core.glossary.ensure_glossary` and explains the
  missing-key case instead of failing silently; `POST /glossary/build` renders the
  page with the outcome; `/glossary` now lists the glossaries in use (key, source,
  term count, path) above the form and the report review.
- Tests and results: `linux_tests/test_web_glossary_build.py` (8: parsing of a
  real credits block including the wrapped `as` line and the `"Maggie"` alias,
  plain-name lists, generic roles dropped, page renders the form and the empty
  state, manual creation writes `manual_<key>.json` and shows up in the list,
  missing show key explains itself, TMDB without a key explains the remedy,
  non-numeric id rejected). `test_glossary_from_cast.py` (6) covers the seeding
  module. Suite: 796 passed, 11 skipped, 0 failed.
- Decisions / ADRs: no ADR. Two sources, one file format: TMDB when a key exists,
  pasted cast otherwise, and the pasted list is what covers names TMDB does not
  list (in clip B the song's murderers came from outside the cast). The page shows
  the *show key* prominently because that string must match what the pipeline
  derives from the folder, and a mismatch is the one silent failure mode left.
- Known issues: no preview of the parsed terms before saving (the page shows the
  count only); the show key is free text, so a typo creates a glossary the
  pipeline will never read; TMDB path untested end to end because this machine
  has no API key.
- Next step: with a key available, exercise the TMDB path; optionally add a
  "preview parsed cast" button and a dropdown of the show keys the pipeline can
  derive from the configured media roots.

## 2026-10-26 — Glossary built from the TMDB cast, automatically

- Branch / commits: `feat/glossary-from-tmdb-cast`.
- Goal: remove the last manual step — with a TMDB id the glossary should build
  itself from the cast, and feed both the ASR context and the translation.
- Done: `core/glossary.py::cast_to_terms()` (TMDB `{character: gender}` ->
  `{character: character}`, dropping placeholders like `Himself`/`Narrator` and
  names shorter than three characters) and `ensure_glossary()`, which builds and
  saves the file **once per show**, never overwrites an existing one (manual edits
  win) and never raises: a network or key problem leaves the previous behaviour.
  The pipeline calls it before transcription when `metadata['id']` exists, so the
  same names reach the qwen3 decoder (`asr_context`) and the translator
  (`translation_glossary`).
- Tests and results: `linux_tests/test_glossary_from_cast.py` (6: builds from the
  cast and writes `tmdb_<id>.json`, does not overwrite and does not even call
  TMDB when a glossary exists, empty cast writes nothing, network error is logged
  and ignored, placeholders and short names dropped, pipeline wiring).
- Decisions / ADRs: no ADR. The cast fetch already existed for the gender
  corrector (`get_cast_info`), so this is wiring, not new capability: TMDB ids
  were never unavailable in principle, only unused for the glossary. The manual
  path (`glossary_id`, `manual_<slug>.json`) stays for shows without a TMDB id or
  for names TMDB does not list (in clip B, the song's murderers — Báthory,
  Wuornos, Manchester — come from outside the cast).
- Known issues: TMDB returns the main cast only (`max_cast` 15, configurable), so
  minor characters still need a manual entry; the seeded file has no provenance
  marker, so it is indistinguishable from a hand-written one — acceptable because
  it is never overwritten.
- Next step: with a TMDB key on this machine, confirm the whole path end to end
  (id -> cast -> glossary -> asr context -> translated names).

## 2026-10-26 — Names: fuzzy matching rejected, ASR context adopted

- Branch / commits: `feat/asr-context-names`.
- Goal: decide how to fix proper names after the reference evaluation showed them
  as the remaining visible error, judging three routes: fuzzy post-processing, an
  extra AI pass, or biasing the ASR.
- Done: measurement that rejects fuzzy matching (capitalised tokens of the
  transcripts compared with the 43 cast names: `Would`~`Lourd` at distance 2,
  `They`~`Abby`, `Thank`~`Hall`, `Bomb`~`Emma` at distance 3, i.e. the real errors
  share the distance band with ordinary words); the qwen3 engine gained
  `_context()`, which passes a config string `asr_context` to
  `transcribe(context=...)`, and the pipeline now loads the glossary **before**
  transcription and sets `asr_context` with the cast names (up to 60), logging
  `ASR context: N glossary names`.
- Tests and results: test for `_context()` and for the pipeline wiring in
  `linux_tests/test_italian_accents.py` (9 in total now), i18n string
  `pl_asr_context_from_glossary`. Measured on clip A: without context `Borden x1`
  plus a wrong `Barton`, with context `Borden x2, Lizzie x4, Maggie x1` — identical
  to the reference; WER 9.17% -> 9.45%, chrF 94.36 -> 94.46. On clip B: without
  context `Borden x3` plus wrong `Bond` and `Burton`; with context `Borden x11`,
  and the names Báthory, Wuornos, Manchester, Morse, Nance, Abby, Andrew, Emma
  spelled correctly in the song; WER 7.88% -> 8.41%, chrF 94.04 -> 93.80, ASR
  phase 46.6 s -> 60.0 s.
- Decisions / ADRs: no ADR. Context biasing is adopted as the mechanism (opt-in:
  it needs a glossary, so it costs nothing when there is none); fuzzy matching is
  rejected on measurement, not on taste; the extra AI pass is dropped from the
  plan because the ASR now gets the names right at the source, without a second
  model in the loop.
- Known issues: one error survives (`Barden` once) and the WER/chrF wobble of
  about half a point must be confirmed on more material; the ASR slowdown on clip
  B (46.6 -> 60.0 s) is unexplained and may be variance or prompt overhead —
  worth one more sample before it is treated as a cost. faster-whisper does not
  receive the context yet (it accepts `initial_prompt`/`hotwords`).
- Next step: re-measure the context on clip C and on a full episode to settle the
  speed question; give faster-whisper the same names through `initial_prompt`.

## 2026-10-26 — Italian accents fixed at the exit, glossary measured in isolation

- Branch / commits: `feat/italian-accents`.
- Goal: two follow-ups from round 5 — repair the apostrophe-for-accent defect and
  find out whether the glossary does anything at all.
- Done: `core/italian_accents.py` (closed-list mapping with capitalisation
  handling and a `KEEP` set for the legitimate apostrophes: `un po'`,
  `d'accordo`, `va'`, `sta'`, `fa'`, `da'`, `di'`, `be'`, `vent'anni`), applied in
  `ProcessingPipeline._finalize_output` when the final language is Italian — the
  cleaner runs **before** translation, so the first attempt had modified the
  English text and changed nothing; `SubtitleCleaner.clean_file(...,
  italian_accents)` stays available as a helper; i18n string
  `pl_italian_accents_fixed`; `bench/glossary_check.py` (translates the reference
  lines containing glossary terms with and without the glossary, reports kept
  terms and changed lines).
- Tests and results: `linux_tests/test_italian_accents.py` (8: mapping,
  capitals, legitimate apostrophes untouched, SRT timestamps preserved, count,
  cleaner flag, the pipeline applies it only for Italian at the exit) and
  `linux_tests/test_bench_glossary_check.py` (5). Measured on clip A, Italian
  target: WER **64.21% -> 59.76%**, CER 45.66% -> 42.91%, chrF 74.14 -> 75.34;
  apostrophes 36 -> 13 (reference 12), accented characters 13 -> 37 (reference
  42). Glossary in isolation: 7/7 names kept with and without the glossary, 0/7
  lines changed.
- Decisions / ADRs: no ADR. The accent fix is a post-processing step on the
  delivered text, not a translator change: it is deterministic, it cannot alter
  meaning, and it applies only when the final language is Italian. The glossary
  stays in the product (it is what fixes invented terms), but the measurements
  say it is not the lever for this show: NLLB already keeps proper names, and the
  names it would need to fix are lost at the ASR stage, before translation.
- Known issues: the accent list is closed on purpose, so a word outside it stays
  as the translator wrote it; `e'` as an imperative (`va' e'`?) would be wrong,
  but the forms in `KEEP` cover the real cases seen in the corpus. The post-ASR
  name correction is still unimplemented and unmeasured.
- Next step: if names matter, a post-ASR correction pass against the glossary
  (edit distance with a tight threshold) measured on the English reference, where
  the errors actually are; otherwise this closes the Italian side.

## 2026-10-26 — Glossary without TMDB, and the accent defect in the Italian output

- Branch / commits: `feat/glossary-offline`.
- Goal: use the per-show glossary on a machine without a TMDB key, load the cast
  names of the evaluated episode and measure whether they change anything.
- Done: `core/glossary.py` accepts a non-numeric key (`manual_<slug>.json` next
  to the existing `tmdb_<id>.json`) and gains `show_key_from_path()`, which
  derives the show key from the media folder (`Monster (2022)/Season 4/x.mkv` ->
  `monster-2022`); `utils/config.py` gets `glossary_id` for an explicit key; the
  pipeline uses TMDB id, else `glossary_id`, else the folder key;
  `bench/asr_ab.py` now writes the full pipeline log next to each run
  (`log-<tag>.txt`), which is how the glossary activation was verified; a
  38-entry cast glossary was written to `~/.transcriberpro/glossary/`
  (outside the repository, 0600).
- Tests and results: two tests for the manifest (`glossary_path` numeric vs
  manual, `load_glossary` with a missing key, `show_key_from_path` with and
  without a `Season N` level); suite green. Run: clip A, Italian target, qwen3
  only, glossary active (log: `Active glossary: 38 terms`): WER 63.36% vs 63.18%
  without, chrF 74.20 vs 74.11 — **no effect**, explained in the document (names
  appear six times, NLLB already keeps them, and the real name errors happen at
  the ASR stage where the translator never sees "Borden").
- Decisions / ADRs: no ADR. The glossary stays a translation-time tool; making it
  repair ASR mishearings would need a post-ASR correction pass, which is a
  different feature and must be measured against the same reference.
- Known issues: **found a systematic defect in the Italian output**: apostrophes
  where Italian needs accented letters (`e'`, `si'`, `perche'`, `cosi'`). Counted
  on clip A: 49 such forms and 13 accented characters in the output against 12 and
  42 in the reference; folding accents drops the measured WER from 64.21% to
  59.97%, so about four points of the end-to-end score is this defect, not
  translation. Fix is cheap (fixed word list plus known exceptions like `un po'`)
  but not implemented yet.
- Next step: implement the accent normalisation in the subtitle post-processing
  and re-measure the Italian round; then decide on a post-ASR name correction.

## 2026-10-26 — Reference evaluation round 4 (end-to-end, Italian)

- Branch / commits: `feat/asr-reference-ita`.
- Goal: the last open question of the evaluation — does translation change the
  ranking between the two engines?
- Done: clip A run end to end (target `ita`, NLLB) with both engines and scored
  against the Italian professional track; document updated with the round, the
  warning about the metric and the example comparison.
- Tests and results: no new code paths (harness already covered); suite green.
  qwen3 + NLLB: WER 63.18%, chrF 74.11, coverage 100%, words 658 (1.13x the
  reference), drift 0.22 s, ASR 41.4 s. whisper-0.25 + NLLB: WER 60.45%,
  chrF 73.11, coverage 96.0%, words 590 (1.01x), drift 0.49 s, ASR 25.9 s.
- Decisions / ADRs: **no change**, qwen3 stays the default. The round also
  produced the most important methodological finding of the whole evaluation:
  WER against a human *translation* rewards under-transcription, because the
  reference condensed the speech while the pipeline translates everything. The
  engine with the best WER here (whisper, 1.01x words) is the one that lost 4%
  of the dialogue (96% coverage against 100%). Ranking on this round would have
  rewarded silence; chrF, coverage and drift all point to qwen3.
- Known issues: one clip only for the end-to-end round, and the Italian reference
  is a translation of the English subtitle, not of the audio: part of the gap
  (60%+ WER, chrF ~74) is the distance between two translators, not an error.
- Next step: none for this question. The evaluation set exists and is documented;
  reopening it means better clip selection (by spoken words, not cue count) and,
  if wanted, a hand-corrected transcript instead of a subtitle track.

## 2026-10-26 — Reference evaluation round 3 (clip C): qwen3 stays the default

- Branch / commits: `feat/asr-reference-round3`.
- Goal: tie-break between qwen3 and whisper-0.25 with a third clip and apply the
  decision rule fixed before the measurement.
- Done: clip C cut at 40:00 with its references; both variants run and scored;
  the benchmark document gained the three-clip table, the criteria table and the
  verdict.
- Tests and results: no new tests (harness already covered); suite green.
  Clip C (284 reference words after ignoring 335 italic ones): qwen3 WER 11.97%,
  matched 9.36%, coverage 83.3%, drift 0.20 s, ASR 45.3 s; whisper-0.25
  WER 14.44%, matched 12.64%, coverage 87.5%, drift 1.07 s (p90 5.32 s),
  ASR 22.2 s. Weighted over the three clips (1742 reference words):
  qwen3 matched-WER **6.95%**, whisper **8.60%**; whisper's ASR phase is
  **40% faster** (80.5 s vs 133.4 s on 30 minutes of audio).
- Decisions / ADRs: **qwen3 remains the default engine**. The rule (no worse than
  one WER point on B and C, coverage >= 93%, extra words not doubled, >= 25%
  faster) fails on two counts: clip C WER is 2.47 points worse and coverage stays
  below 93% on both B and C. Whisper's speed advantage is real and remains
  available as a per-install choice (`transcription_engine_mode`) with the VAD
  knobs from round 1b. No defaults changed.
- Known issues: clip C is thin evidence (335 words of lyrics against 284 of
  dialogue) and its coverage numbers say more about the material than about the
  engines; the clips were selected by cue count, which correlates with music
  rather than dialogue. The end-to-end round with the Italian reference is still
  missing and could reorder the two engines, because translation consumes text
  that the two engines punctuate differently.
- Next step: optional end-to-end round on the Italian reference, then a full
  episode on qwen3 to confirm the per-episode time.

## 2026-10-26 — Reference evaluation round 2 (clip B) and a metric fix

- Branch / commits: `feat/asr-reference-round2`.
- Goal: test qwen3 against whisper-0.25 on the densest stretch of the episode,
  and fix what the first round got wrong.
- Done: the harness now ignores **italic-only windows on both sides** (songs and
  off-screen voices): transcribing the lyrics earns nothing, skipping them costs
  nothing, and the ignored words/windows are reported
  (`excluded_italic.windows`); clip B cut at 20:00 and its two references
  extracted from the cut; both variants run on it; both clips re-scored under the
  new rule for comparability.
- Tests and results: new guard test for the italic rule (a variant that
  transcribes a song neither gains nor loses). Suite: full green. Clip B results
  (reference 749 words, 226 of them ignored as italic): qwen3 **WER 7.88%**,
  matched 4.30%, chrF 94.04, coverage 93.6%, drift 0.16 s, ASR 46.6 s;
  whisper-0.25 WER 8.41%, matched 7.65%, chrF 93.62, coverage 91.5%, drift
  0.46 s, ASR 32.4 s. Clip A unchanged after re-scoring (qwen3 9.17%,
  whisper-0.25 8.89%).
- Decisions / ADRs: no ADR. The metric change was necessary for honesty: the
  earlier version penalised qwen3 twice for transcribing songs and made clip B
  look like a 133-word fabrication problem that did not exist (7 extra words
  after the fix, the same as whisper). Clip B is not a dialogue-outside-music
  test after all: 226 of its 975 words are lyrics, which makes it the "musical
  material" case and leaves the tie-break to clip C.
- Known issues: two clips still disagree on accuracy (A favours whisper by 0.28
  points, B favours qwen3 by 0.53 with a much larger matched-WER gap), so the
  engine choice is not decided; whisper's speed advantage (30-37% of the ASR
  phase) is consistent, its coverage disadvantage is too.
- Next step: clip C (40:00–50:00) as the tie-break, then the end-to-end round
  with the Italian reference.

## 2026-10-26 — Whisper VAD as a config knob (round 1b of the reference eval)

- Branch / commits: `feat/whisper-vad-knobs`.
- Goal: make the VAD thresholds configurable so the Whisper coverage gap could be
  tested instead of assumed, without changing the shipped defaults.
- Done: `utils/config.py` gains `whisper_vad_threshold` (0.5) and
  `whisper_vad_min_silence_ms` (500); `core/engines/faster_whisper_engine.py`
  reads them through one `_vad_parameters()` helper used at all three call sites
  (a guard test fails if a hardcoded threshold comes back);
  `web/config_schema.py` gets a `NUMBER_CONFIG_KEYS` table with per-key bounds
  (0-1, 0-2000 ms) and treats an empty value as "leave it alone";
  `/settings` renders both keys with their own min/max/step.
- Tests and results: `linux_tests/test_whisper_vad.py` (5: defaults unchanged,
  values from config, out-of-range clamped, broken values ignored, no hardcoded
  threshold left) and a settings round-trip test with the validation errors.
  Suite: full green. Measurement on clip A: Whisper with `threshold=0.25` moves
  from **10.72% to 8.89% WER** and its coverage from 90.4% to 94.2% (missing
  words 21 -> 7), keeping its 37% faster ASR phase (25.9 s vs 41.5 s for qwen3).
  At 0.25 Whisper matches qwen3 on accuracy within the resolution of one clip;
  qwen3 still covers slightly more (96.2%, 3 missing words).
- Decisions / ADRs: no ADR and **no default change**: the knobs exist with the
  historical values, because a threshold of 0.25 on material with music and
  audience noise is exactly the setting that could start transcribing noise.
  Clips B and C must confirm it before anything moves.
- Known issues: one clip cannot separate 8.89% from 9.17%; the hypothesis that a
  low VAD threshold is safe on this material is still untested.
- Next step: round 2 on clip B with qwen3 and whisper-0.25, then round 3 on
  clip C.

## 2026-10-26 — Reference evaluation: harness and round 1 (clip A)

- Branch / commits: `feat/asr-reference-eval`.
- Goal: replace "looks good" with a measurement against professional subtitles,
  in rounds that can be reviewed one at a time.
- Done: `bench/subtitle_eval.py` (reference extraction and clip cutting with
  ffmpeg, SRT parsing, shared normalisation, 10-second window alignment,
  WER/CER/chrF/coverage/silence-insertions/timing offsets, per-window WER,
  JSON report, CLI); `bench/asr_eval_variants.json` (qwen3 and faster-whisper,
  English target, `force_audio_transcription`); `bench/asr_ab.py` now takes the
  target language from the variant and finds the SRT next to the video;
  `docs/benchmarks/2026-10-26-asr-reference-clip-a.md` with method and results.
- Tests and results: `linux_tests/test_bench_subtitle_eval.py` (15: timestamp
  parsing, identical content, tag and punctuation normalisation, different
  segmentation, silence insertions, missing coverage, WER on a substitution,
  median offset, bucketing by midpoint, summary, CLI JSON, watermark removal,
  italic exclusion counted both ways, variant file validity, no personal paths);
  `test_bench_asr_ab.py` still green. Round 1 on clip A (10 minutes, English
  reference): **qwen3 WER 9.17%, chrF 94.36, coverage 96.2%, drift 0.29 s**;
  faster-whisper WER 10.72%, chrF 92.83, coverage 90.4%, drift 0.49 s but **37%
  faster in the ASR phase**.
- Decisions / ADRs: no ADR. Two measurement artifacts are now handled inside the
  harness because they changed the numbers by 3 points: the pipeline watermark
  (dropped) and italic-only reference cues, i.e. the theme song, which no ASR
  transcribes (excluded and reported). Absolute WER against human subtitles is
  not an error rate; it ranks configurations that share the same handicap.
- Known issues: one clip is not enough to crown a winner, and whisper's gap is
  coverage (VAD threshold), not transcription quality — a lower-threshold
  variant must be measured before judging the engine. The Italian reference is
  untouched: the end-to-end round comes after the three English clips.
- Next step: optional whisper VAD variant on clip A, then round 2 on clip B and
  round 3 on clip C.

## 2026-10-26 — WebUI Step 11: sidebar layout, queue-first dashboard, timings

- Branch / commits: `feat/webui-layout`.
- Goal: navigation on the left and data on the right, the landing page showing
  the state of the queue instead of the machine, and real timings while a job
  runs.
- Done: `base.html` rewritten as a shell with an `<aside class="sidebar">`
  (Queue, Status, History, OCR, Glossary, Settings, API, auth pill, logout) and
  a `<main class="content">`, with the current section highlighted through the
  new `path` value that `_render` passes to every template; the system card moved
  to its own `/status` page (`status.html`, new route) which also shows engine,
  target language, data dir and models dir; the dashboard opens on a hero block
  with the active job (name, progress bar, phase, **elapsed**, estimated
  remaining, log/cancel) and the queue counters; the job table gained a **Time**
  column with elapsed for running jobs and total time for finished ones;
  `_hms`, `_elapsed_of` and `_eta_of` format the durations (the estimate is
  labelled and only shown from 5% on); the auth warning became a compact banner
  on every page; `_queue.html` now takes its context under `queue` so the page
  and the HTMX partial share one shape; CSS for the shell, the sidebar, the hero
  and the pills, with the sidebar collapsing to a bar under 760 px.
- Tests and results: `test_web_ui.py` +5 (sidebar order and active item,
  queue-first landing with a running job and "12m 34s elapsed", elapsed/total in
  the table, the helper formatting, `/status` details) and the system-card tests
  moved to `/status`. Suite: 744 passed, 11 skipped, 0 failed. Verified live: the
  landing page renders `Nothing running` with the counters, `/status` returns 200
  with the system facts, and the queue table shows `25m 06s` for the finished
  episode.
- Decisions / ADRs: no ADR. The dashboard answers "what is happening now", the
  Status page answers "can this machine work": two questions, two pages. The
  estimated remaining time is derived from the achieved percentage, so it is
  explicitly labelled `est.` and hidden below 5%.
- Known issues: the estimate is naive (it assumes a constant rate across
  phases, while Demucs and ASR have different speeds); the logs panel is still a
  floating card at the bottom of the dashboard.
- Next step: container validation (Step 8) remains the only open acceptance;
  otherwise this closes the WebUI work.

## 2026-10-26 — ASR knobs measured: batch and chunk length are not a speed lever

- Branch / commits: `docs/asr-ab-measurements`.
- Goal: answer, with numbers instead of intuition, whether the ASR half of the
  wall time can be shortened by configuration alone (bigger batch, longer
  chunks) without touching the model.
- Done: `bench/asr_ab.py` (harness: one variant per run, isolated `TP_DATA_DIR`,
  phase timings from `@@TPEV@@`, `build_config`/`parse_events`/`phase_timeline`
  as pure functions) and `bench/asr_ab_variants.json`;
  `docs/benchmarks/2026-10-26-asr-knobs.md` with method, table and conclusion;
  `docs/STATUS.md` records the outcome so nobody repeats the experiment.
- Tests and results: `linux_tests/test_bench_asr_ab.py` (config building,
  profile lock, event parsing, timeline, summary, CLI validation). Measurement
  on a fixed 10-minute clip, four runs: current config ASR 64.3 s; profile
  balanced (batch 8) 63.6 s; profile batch (batch 8) 65.1 s; chunk 45 s
  **221.5 s**. Battery of the full episode stays as recorded (25 and 27 minutes
  for 134 and 144 minutes of audio).
- Decisions / ADRs: no ADR, and **no configuration change**: the current
  `chunk 20/10/25` + profile `maximum` + batch 2 is the best of the four tested.
  The free VRAM is not a lever (the engine is compute-bound per chunk), and
  longer chunks are 3.4x slower because generation is autoregressive. One
  trap documented: `transcription_profile_locked` defaults to true and makes the
  profile read-only, so the first A/B measured the same configuration four
  times; the harness forces it to false and the guard test pins that.
- Known issues: output is not bit-exact across runs (bfloat16 + batched
  generation): three runs of the same variant produced 553, 554 and 556 cues, so
  future comparisons must treat a few-cue difference as noise.
- Next step: the remaining levers are structural (overlap Demucs with ASR) or
  model-level (needs a human reference set); both are out of scope for now.

## 2026-10-26 — Temp folders of killed jobs no longer stay in RAM

- Branch / commits: `fix/temp-cleanup`.
- Goal: cancel and crash left the pipeline work folder behind — 854 MB of
  extracted audio and chunks in `/dev/shm` (i.e. RAM) after one cancelled
  episode — and the test suite copied ~485 MB of repository per test into
  `/tmp`, which on the reference machine is also tmpfs.
- Done: `utils/temp_cleanup.py` (`temp_base`, `stale_dirs`, `sweep`,
  `sweep_summary`, `directory_size`) removes only `$TMPDIR/TranscriberPro/vid_*`
  folders, with an age filter; the sweep runs at startup of `web.main` and
  `core.queue_runner` (nothing can be running) and right after a job ends
  `cancelled`/`failed` in `JobManager._run_one` (one job at a time, so nothing
  in use can be deleted). `linux_tests/pytest.ini` pins
  `--basetemp=/var/tmp/tp-pytest` (disk, and pytest clears it each run, so no
  accumulation); the `full` fixture became session-scoped and ignores `.tools`
  and `samples`, so the 485 MB copy happens once instead of once per test.
- Tests and results: `linux_tests/test_temp_cleanup.py` (11: orphan removal,
  age filter, missing base, files vs folders, summary, size, manager sweeping
  after a failure and not after a success, plus guards on the pytest basetemp
  and the session-scoped fixture). Suite: all green. Measured on the reference
  machine: 854 MB of orphan chunks and 7.7 GB of pytest copies removed by hand
  before the fix (RAM in use 11 GiB -> 2.4 GiB, available 18 -> 27 GiB); after
  the fix one suite run leaves 7.7 MB in `/var/tmp` and `/tmp` stays empty.
- Decisions / ADRs: no ADR. The sweep is deliberately conservative: only our
  prefix, only the age filter, only when no job can be running. The
  `/dev/shm/u1000-Shm_*` segments leaked by killed GPU processes (150 orphans,
  1.3 GB) are **left alone**: they belong to the graphics driver (some are in
  use by running applications) and are freed at reboot.
- Known issues: the age filter is not used at the manager sweep (it removes
  every `vid_*` right after a failure) — safe because the queue runs one job at
  a time, but it would need revisiting if the manager ever runs jobs
  concurrently.
- Next step: keep an eye on `/dev/shm` growth after cancelled jobs; the
  container runs will need the same behaviour inside the image.

## 2026-10-26 — WebUI: system status on the landing page, token removed (Step 10)

- Branch / commits: `feat/webui-system-status`.
- Goal: make the state of the machine visible where the work starts, and run
  the UI without a token on a private network while keeping the mechanism.
- Done: `_system_status()` in `web/app.py` (backend stamp, GPU verdict from
  `utils/backend_preflight.py`, torch/HIP/CUDA/ctranslate2 versions, device
  count, `TMPDIR` with free space) exposed in `/api/status` and rendered by
  `_status.html` as a "System" card with two conditional alerts — GPU not
  usable (with the `./install.sh --verify-only` remedy) and "No authentication";
  `web/main.py` gains `--no-auth` / `TP_WEB_NO_AUTH=1`, which serves without a
  token on any interface, prints a warning at startup and no longer refuses the
  bind; `/login` redirects to `/` when no token is configured; `--no-auth` in
  `web/README.md`, SPEC §3/§7/§8 and `docs/STATUS.md`.
- Tests and results: `test_web_ui.py` +4 (system card with backend/versions/work
  dir, GPU-problem alert with the remedy, no-auth warning plus `/login`
  redirect, `/api/status` payload). Suite: 720 passed, 11 skipped, 0 failed.
- Decisions / ADRs: no ADR. The token stays in the code (it can be re-enabled
  with one environment variable) but the reference deployment runs with
  `--no-auth` behind Twingate; the warning is part of the page, not a hidden
  note, because without auth anyone reaching the port can queue jobs.
- Known issues: `/api/status` runs the cached preflight probe, so the first
  request after five minutes can take a couple of seconds; the "System" card
  shows the discrete GPU only (the iGPU appears in `/api/status`).
- Next step: merge the three backend branches, push, and re-run one episode to
  confirm the UI status and the preflight agree with a real job.

## 2026-10-26 — Runtime preflight: a GPU job no longer starts on a CPU venv

- Branch / commits: `feat/gpu-preflight`.
- Goal: close the second half of the ADR-007 problem — the installer now refuses
  a wrong backend, but nothing stopped a job from starting on a venv that had
  been changed by hand afterwards.
- Done: `utils/backend_preflight.py` reads `venv/.tp-backend`, probes the real
  libraries in a subprocess (torch version, HIP/CUDA runtime,
  `cuda.is_available()`, device count, ctranslate2 device count), caches the
  answer for five minutes and turns it into a verdict plus a remedy sentence;
  `JobManager` accepts a `preflight(job)` hook and fails the job before spawning
  the pipeline; `web.main` prints the backend banner at startup and passes the
  check, `core.queue_runner` does the same for the CLI; new job override
  `allow_cpu` (checkbox "Allow CPU" in the add form) lets a single job skip the
  check on purpose; `install.sh --verify-only` re-checks an existing venv and
  rewrites the stamp without installing anything (the remedy when a stamp is
  missing), and the stamp now records ctranslate2 by importing it after torch.
- Tests and results: `linux_tests/test_backend_preflight.py` (11: stamp parsing,
  healthy/missing/wrong-runtime reports, cache, `allow_cpu`, `use_gpu=false`, the
  manager failing the job without calling the runner, override sanitising) and
  two installer tests for `--verify-only`. Suite: 714 passed, 11 skipped, 0
  failed. On the reference machine `--verify-only` writes `backend=rocm`,
  `torch=2.10.0+rocm7.0`, `ctranslate2=4.8.4`, and the banner reads
  `rocm: torch 2.10.0+rocm7.0 (7.0.51831), device 2, ctranslate2 4.8.4`.
- Decisions / ADRs: ADR-007 extended in practice. The probe is a subprocess
  because the web server must not import torch; the cache keeps a ten-file queue
  at one probe. A job that fails the preflight is `failed` with the reason in
  `error` and in the job log — the same shape the UI already renders.
- Known issues: the preflight checks `use_gpu` from the config, not the
  per-engine requirement (a job that would only translate also fails when the
  GPU is missing); `utils/backend_preflight.py` has no CLI of its own, it is
  used through the queue.
- Next step: landing page with the system status and removal of the WebUI token.

## 2026-10-26 — Installer: automatic backend choice with deny-by-default (ADR-007)

- Branch / commits: `feat/backend-auto`.
- Goal: make it impossible to end up with a venv whose backend does not match
  the hardware — the accident that turned a 27-minute GPU job into a CPU job
  without a single error.
- Done: `install.sh` rewritten around a backend decision: `--backend=auto|cuda|rocm`
  (`auto` is the default, `--gpu-backend` kept as an alias), `--force-backend`
  for cross-builds and tests; `--no-gpu` and the `cpu`/`vulkan` branches removed;
  the AMD decision uses `utils/gpu_detect.py` (`path=rocm` and `/dev/kfd`
  accessible) and refuses RDNA2/`rocm_override`, older families, missing devices
  and unknown hardware with an explanation; explicit mismatch refuses; a
  post-install verification imports torch/ctranslate2 and checks the runtime
  before declaring success, writing `venv/.tp-backend` only then; a venv stamped
  with another backend refuses to be replaced without `--force-backend`;
  `--with-models` reads VRAM from the detector instead of nvidia-smi; the GGUF
  downloader no longer receives `--no-gpu`. `docker/compose.yaml` loses the
  `cpu` service and `docker/Dockerfile` accepts only `rocm|cuda`.
  `docs/adr/ADR-007-supported-backends.md` records the policy, and
  `docs/SUPPORT_MATRIX.md` moves CPU/Vulkan/older-AMD to "not supported".
- Tests and results: `linux_tests/test_install_backend.py` (11 new: retired
  backends refused, unknown value refused, `auto` with no hardware stops before
  touching the venv, `auto` picks cuda, RDNA2 and older families refused,
  explicit mismatch refused, `--force-backend` allowed, stamp mismatch refuses
  without pip, same stamp proceeds, no `--no-gpu`/`NOGPU` left in the script);
  `test_install_retry.py` +2 (stamp written with backend and requirements,
  failed verification aborts and leaves no stamp) and adapted to
  `--backend=cuda --force-backend`; `test_amd_rocm_f6.py` now asserts the
  retired backends are rejected; `test_docker.py` expects two services.
- Decisions / ADRs: ADR-007. `auto` is authoritative instead of advisory, and
  the detection is backed by a real import check so a wrong heuristic cannot
  produce a "successful" wrong install. The pipeline keeps its internal
  `cuda -> cpu` fallback; the job-level refusal arrives with the runtime
  preflight (next branch).
- Known issues: the ROCm Docker image installs `requirements-rocm.txt` but not
  the `ctranslate2` ROCm wheel (the Step 8 build is still unvalidated); the
  `llama-cpp-python` Vulkan wheel for the ROCm backend is likewise only
  installed by `install.sh`, not by the image.
- Next step: runtime preflight (stamp vs reality, job refused when the GPU does
  not answer), then the landing page status and the removal of the WebUI token.

## 2026-10-26 — Session close: throughput measured, GPU verdict, docs sync

- Branch / commits: `docs/session-close` (this entry ships in the same commit).
- Goal: record what the session proved about performance, close the pending
  documentation drift and leave the tree ready for the next step.
- Done: `docs/STATUS.md` gains the measured throughput bullet (per-episode
  times, GPU occupancy, single-pass read), the current `last merge` and a
  "suite fully green" line; this entry; the two steps merged earlier today
  (`3dae384` WebUI Step 9/file picker, `d17f601` test isolation) are the only
  code changes of the session besides the ROCm environment repair.
- Tests and results: full suite on `development` after both merges, 689
  passed, 11 skipped, 0 failed (71 s). Runtime checks: `torch 2.10.0+rocm7.0`,
  `cuda True`, `ctranslate2 4.8.4`, `use_gpu=true`, picker served, HTML
  `Cache-Control: no-store`.
- Measurements (reference machine, one job at a time, AMD RX 9060 XT 16 GB):
  a 134-minute episode took 25 min; a 144-minute one took 27 min (1619.7 s per
  the pipeline clock) for 1968 cues; a third run sampled every 2 s showed the
  GPU at 94% average, 96% of samples at or above 80%, VRAM peak 7.5 GB and only
  51 MB of reads outside the extraction phase. Conclusion: the workload is
  GPU-bound, the media read is one sequential pass (~4% of the wall time) and
  staging a copy on the local disk would add I/O instead of saving time.
- Decisions / ADRs: no ADR. The pipeline chain (Demucs htdemucs, 20/10/25 s
  energy chunking with per-engine caps, Qwen3-ASR, punctuation, cleaner) stays
  untouched: it is the result of months of tuning on the hardest kind of
  material (music, audience, overlapping speech) and measured results are good.
  No quality A/B is planned until a human reference exists for the evaluation
  set; the benchmark's single synthetic clip is not a basis for model choices.
- Known issues: the reference evaluation set does not exist yet (a 10-minute
  hand-corrected slice would unlock WER-based comparisons). The cancel path
  still leaves the `TMPDIR` work folder behind, and the pipeline pre-loads
  Whisper even when the engine is Qwen3 (a `ctranslate2` without the GPU
  runtime fails a job that would never use it). The library scanner remains a
  separate service.
- Next step: container validation (Step 8 acceptance) on a host with a
  container daemon; then the two robustness items above.

## 2026-10-26 — Test isolation: the suite no longer destroys the GPU venv

- Branch / commits: `fix/install-test-isolation`.
- Goal: stop `pytest linux_tests` from reinstalling `requirements.txt` (torch
  CPU) into the working venv, which silently turned every job into a CPU job.
- Done: `install.sh` resolves the target venv with
  `VENV="${TP_INSTALL_VENV:-$ROOT/venv}"` and explains why in a comment; the
  `env` fixture of `linux_tests/test_install_retry.py` sets
  `TP_INSTALL_VENV` under `tmp_path`; three guard tests added (the override is
  honoured, the literal is present in `install.sh`, the fixture points away
  from `$ROOT/venv`).
- Tests and results: `test_install_retry.py` 20 passed — the two failures that
  had been documented as "local venv only" are gone, because they were caused
  by the real `pip install` that the test triggered. Full suite: **689 passed,
  11 skipped, 0 failed** (first fully green run), 71 s instead of 129 s.
  `torch 2.10.0+rocm7.0`, `cuda True`, `ctranslate2 4.8.4` still in place after
  the run.
- Decisions / ADRs: no ADR. The override is an installer knob, not a product
  setting: nothing else changes behaviour when the variable is absent. The
  guard tests check the literal in `install.sh` so a refactor cannot quietly
  remove the isolation.
- Known issues: other `install.sh` paths still write into `$ROOT`
  (`requirements-gui.txt` install, the local model download section) — they
  are out of the test's reach today but the same class of accident remains
  possible. The venv had already been downgraded once before this session, so
  the documented "known failure" was the symptom of this bug, not an
  environment quirk.
- Next step: re-queue the season (E02–E07) with the GPU validated, and record
  the real per-episode timings.

## 2026-10-26 — WebUI Step 9: file picker and multi-add

- Branch / commits: `feat/webui-picker`.
- Goal: choose the media from the browser instead of typing an absolute path,
  and queue several files at once, without turning the WebUI into a library
  scanner.
- Done: `web/browse.py` (read-only lister: `VIDEO_EXTENSIONS`, `natural_key`,
  `has_subtitle`, `start_dir`, `resolve_dir`, `list_directory`, `MAX_ENTRIES`);
  API `GET /api/browse`; UI partial `GET /ui/browse` and `_picker.html`
  (roots, breadcrumb/up, folders, checkboxes, `SRT` badge, truncation notice);
  dashboard form gains the picker opened by `<details>`/`<summary>` so it needs
  no JavaScript at all, the `Skip files that already have a subtitle` checkbox
  and repeated `paths` fields; `POST /ui/jobs` queues one job
  per selected file (dedupe, per-path errors, `skip_existing`); new whitelisted
  config key `picker_start_dir` (`utils/config.py`, `web/config_schema.py`,
  `_settings.html` `dir` kind with the `/set/root/dir` placeholder); CSS for the
  picker and `[x-cloak]`.
- Tests and results: `linux_tests/test_web_picker.py` (14 tests: listing and
  folder-first order, hidden entries skipped, `SRT` badge, symlink escape
  dropped, path outside the roots / relative / file / missing rejected,
  `picker_start_dir` honoured and ignored when outside the roots, entry limit
  and `parent`, JSON API plus auth, multi-add, `skip_existing`, empty selection,
  mixed valid/invalid, settings round trip). Full suite: 684 passed,
  11 skipped, only the two known `test_install_retry.py` failures.
- Decisions / ADRs: no ADR. The picker lists only what the queue already
  accepts (`web/paths.py::is_allowed`), so there is one rule for both; no
  database, no recursion, no upload, no index — the non-goal "no library
  scanner" in the SPEC still holds. `has_subtitle` matches any `<stem>.*.srt`
  instead of a language suffix because the pipeline writes ISO 639-1. A start
  folder outside the roots is ignored rather than rejected: the setting cannot
  brick the picker. The panel is a native `<details>` element, not an Alpine
  toggle: a browser with stale cached HTML or without Alpine still opens the
  listing, and HTMX only fetches it. The panel is always visible (no toggle at
  all: the `<details>` version could be closed by one click and looked broken),
  and every
  non-static response now carries `Cache-Control: no-store` (`web/app.py`):
  a page cached before the deploy was showing a UI without the picker, and the
  server had no header to prevent it.
- Known issues: the picker does not probe the media (no ffprobe), so duration,
  embedded subtitle tracks and audio languages are not shown; the entry limit
  is a silent cap beyond the notice line. Two robustness items found while
  running a real file are still open: the temporary folder under `TMPDIR` is
  left behind when a job is cancelled (`SIGKILL` skips the pipeline `finally`),
  and the pipeline pre-loads Whisper even with
  `transcription_engine_mode=qwen3`, so a `ctranslate2` without the GPU runtime
  fails a job that would never use it. Environment note from the same session:
  the local venv had `torch 2.8.0+cpu`; it was reinstalled to
  `2.10.0+rocm7.0` plus the `ctranslate2` 4.8.4 ROCm wheel, which restored GPU
  processing (a 133-minute episode finished in 25 minutes).
- Next step: run the picker against the real library and queue the remaining
  episodes; then the two robustness items above and the container build
  (Step 8 acceptance).

## 2026-10-26 — Documentation: SPEC/API sync and the PROGRESS rule

- Branch / commits: `docs/spec-sync` (this entry ships in the same commit).
- Goal: close the documentation gaps found while checking the session, and make
  the progress log a hard requirement instead of a habit.
- Done: `AGENTS.md` Workflow gains the rule "every implementation step is
  recorded in `docs/PROGRESS.md` before its branch is merged, one entry per
  PR"; `docs/PROGRESS.md` header restates the rule and now lists every field;
  `docs/CONTRIBUTING.md` has rule 10 and a PR-readiness item; new guard
  `linux_tests/test_docs_progress.py` (7 tests: fields, newest-first order,
  heading format, rule stated in `AGENTS.md`/header, CONTRIBUTING link);
  retroactive entries for `docs/arch-sync` and `docs/status-close`; SPEC §7
  marked page by page and §6 completed with the OCR/glossary endpoints and the
  new parameters; `testing.md` lists the four new test modules.
- Tests and results: `test_docs_progress.py` 7 passed, docs index/links tests
  green, full `linux_tests` unchanged apart from the two known
  `test_install_retry.py` failures.
- Decisions / ADRs: the guard requires the full template only for entries dated
  2026-10-26 or later, because the log is append-only and older entries are not
  rewritten; SPEC §7 uses `done` / `not implemented` instead of a phase number
  once the phase is over.
- Known issues: the guard checks structure, not honesty; a step merged without
  its entry is only caught if someone runs the suite before the next merge.
- Next step: build and validate the container images on a host with a daemon
  (Step 8 acceptance), then the library scanner.

## 2026-10-26 — WebUI Step 8: container artifacts

- Branch / commits: `feat/docker`.
- Goal: ship the WebUI and the pipeline as one image per backend.
- Done: `docker/Dockerfile` (multi-stage, `ARG BACKEND`, no drivers, no
  weights, non-root `tp`, `/data` and `/models` volumes, healthcheck,
  `python -m web.main --host 0.0.0.0`); `docker/compose.yaml` (profiles
  `rocm`/`cuda`/`cpu`, AMD devices and groups, NVIDIA reservation, mandatory
  `TP_WEB_TOKEN`); `.dockerignore`; `docker/README.md`.
- Tests: `linux_tests/test_docker.py` (9 guard tests): one image per backend,
  unknown backend fails the build, no driver packages, no models/media in the
  image, no Qt, non-root plus healthcheck, dirs on volumes, compose wiring for
  AMD and NVIDIA, volumes for data/models/media, build context cleaned.
  `docker compose -f docker/compose.yaml --profile rocm config` renders (exit
  0) and refuses to render without `TP_WEB_TOKEN`.
- Decisions: images carry code and system tools only; no driver, no weights,
  no Qt; the token is mandatory in compose (`:?`) because the server binds
  `0.0.0.0`; media is mounted read-write because the SRT is written next to the
  video.
- Known issues: the images were **not built** here — `docker` daemon not
  reachable in this session and the rocm/cuda layers are several GB, so the
  acceptance "`docker compose up` produces the SRT" is still open. `cpu` image
  builds llama-cpp-python from source (slow) and is a smoke-test target only.
  `dashboard`/WebUI behind a TLS proxy is documented, not provided.
- Next step: build the three images on a host with a container daemon, run the
  rocm profile on the reference machine and record the result here.

## 2026-10-26 — Session close: STATUS handoff

- Branch / commits: `docs/status-close`; commit `f8b0f5c`, merged as `a4ce112`.
- Goal: make a cold start see Steps 4–8 as finished instead of "next: Step 4".
- Done: `docs/STATUS.md` rewritten around the new state (merge `4ef8397`,
  WebUI pages, GUI optional, containers), open items restated as open
  (container build validation, library scanner, glossary report generation,
  CSRF, positive OCR run).
- Tests and results: full `linux_tests` 663 passed, 11 skipped; only the two
  known `test_install_retry.py` failures, which also fail on the unmodified
  branch (checked with `git stash`).
- Decisions / ADRs: no ADR; the STATUS page stays the single place for "what
  works / what is next", the details live in PROGRESS.
- Known issues: this step added no PROGRESS entry at the time; it is recorded
  here retroactively (same day) because the rule was introduced afterwards.
- Next step: the documentation sync PR (SPEC/API and the PROGRESS rule).

## 2026-10-26 — WebUI Step 7: PyQt optional

- Branch / commits: `feat/pyqt-optional`.
- Goal: a default install without Qt (ADR-002).
- Done: `requirements-gui.txt` holds `PyQt6==6.10.2`, `PyQt6-Qt6`, `PyQt6_sip`;
  those pins removed from `requirements.txt` and `requirements-rocm.txt`
  (comment pointing at the new file); `main.py` imports Qt behind
  `try/except ImportError` and exits 2 with a message naming both
  `requirements-gui.txt` and `python -m web.main`; `install.sh --with-gui`
  installs the optional file, default installs do not.
- Tests: `linux_tests/test_gui_optional.py` (4 guard tests): no Qt pin in any
  default requirements file, Qt pinned in `requirements-gui.txt`, install
  script exposes the flag, `main.py` keeps the guarded import (AST check for an
  unguarded module-level import and for a `try` that catches `ImportError`).
  Simulated a missing Qt with `sys.modules['PyQt6'] = None`: `main.py` printed
  the message and exited 2. Full suite: 654 passed, same two pre-existing
  `test_install_retry.py` failures.
- Decisions: `onnxruntime` stays in the default requirements (it must be
  imported before Qt and is used by the VAD); the GUI entry point is kept
  working for users who install the extra file, not removed (removal happens
  after WebUI parity, ADR-002).
- Known issues: the Qt GUI is still present in the tree and imports `core.jobs`
  only; `README.md`/`CHANGELOG.md` (historical, Italian) still describe the
  GUI-first install and are not updated in this step.
- Next step: Step 8, Docker.

## 2026-10-26 — WebUI Step 6: glossary review, and the library scanner scoped out

- Branch / commits: `feat/webui-glossary`.
- Goal: review the per-show glossary candidates from the browser.
- Done: `web/glossary.py` (read-only view of
  `glossary_engine.build_glossary_candidates` reports plus a
  `<report>.decisions.json` written next to the report); API
  `/api/glossary/reports` (list, detail, decide by index); pages `/glossary`
  and `/glossary/{name}` with per-term decision, rendering and note; nav link.
- Tests: `linux_tests/test_web_glossary.py` (7 tests) on a fixture report:
  list/view, decision round trip, decisions file separate from the report,
  name traversal rejected, pages, login redirect, empty directory.
- Decisions: the web layer does **not** build reports. `build_full_report()`
  needs the show folder, an English reference track and the Qwen extractor
  (long GPU job), and `glossary_engine`'s CLI does not write the full report
  at all; the page shows the one-line Python call instead and reviewers only
  read and decide. Library scanner: **not implemented here**, it is a separate
  FastAPI + SQLite service (`library scanner per server- va su docker/`) with
  its own data model and a 1290-line Qt widget as the only reference; it needs
  real media to validate and a decision about where its database lives, so it
  stays a separate work item (see `docs/webui/PLAN.md`).
- Known issues: no CSRF token; reports must be produced and copied under
  `TP_DATA_DIR/glossary/` by hand; no bulk approve.
- Next step: Step 7, optional PyQt.

## 2026-10-26 — WebUI Step 5: OCR review

- Branch / commits: `feat/webui-ocr`.
- Goal: correct bitmap-subtitle OCR in the browser with the same data contract
  as the Qt dialog.
- Done: `core/ocr_review_job.py` (worker CLI, `ocr` and `writeback` modes,
  sidecar only); `web/ocr_review.py` (session store under `TP_DATA_DIR/ocr/`,
  atomic JSON, subprocess runner, image serving, text limits); API
  `/api/ocr/sessions` (create/list/detail/update event/image/write-back/
  delete); pages `/ocr` and `/ocr/{id}` with self-polling while the worker
  runs and a `flagged` filter; nav link, grid styles.
- Tests: `linux_tests/test_web_ocr.py` (8 tests) with a synchronous fake
  runner that writes the same files as the worker: lifecycle, validation
  (outside roots, missing file, relative path, bad language, unknown session,
  oversized text), pages, login redirect, image serving, and
  `build_events` -> `events_to_srt` on corrected text. Architecture guard
  tests still green (the worker lives in `core/`, so `web/` imports no domain
  module directly).
- Real validation: server on `127.0.0.1:8097`, real subprocess; a session on
  `samples/prova_amd_test.mp4` (no bitmap track) reached `failed` with
  "no PGS/VOBSUB bitmap subtitle track found" and the page showed it. A
  positive end-to-end OCR run needs bitmap media, which `samples/` does not
  contain yet.
- Decisions: the OCR worker is a domain CLI (`core/ocr_review_job.py`) like
  `core.pipeline_cli`, not a web module, so the layer rules hold; write-back
  is always a sidecar, never an in-place mux from the browser; sessions store
  one PNG per event instead of holding PIL images in memory.
- Known issues: no CSRF token; no real bitmap sample to validate a successful
  OCR + write-back; session files are not cleaned up automatically.
- Next step: Step 6, glossary and library pages.

## 2026-10-26 — WebUI Step 4: settings and history

- Branch / commits: `feat/webui-settings`.
- Goal: config editing and a history view from the browser, with no JSON
  access required.
- Done: `web/config_schema.py` (whitelist + value validation + secret
  masking, shared by API and UI); `GET /api/history` gains `status` and
  `limit`; `PUT /api/config` validates every value before `Config.set`;
  `GET /api/models` reads `MODEL_SPECS` without loading weights; new pages
  `/history` (filter, duration, output) and `/settings` (grouped form,
  write-only secrets, `clear:` checkbox, draft redisplay on error); nav links
  and fieldset/textarea styles.
- Tests: `test_web_api.py` +5 (history filter/limit, invalid values, secret
  clear, models registry), `test_web_ui.py` +6 (history page and filter,
  settings render and secret masking, save, validation error keeps nothing,
  secret never echoed, auth redirect). Full suite: 635 passed, 2 failed — the
  two `test_install_retry.py` failures are the documented local-venv issue and
  fail identically on the unmodified branch (verified with `git stash`).
- Real validation: server on `127.0.0.1:8098`, `TP_DATA_DIR=/tmp/tp-data`,
  token auth; `/settings` 200, config PUT accepted, invalid value 400,
  `/api/models` lists the registry; `samples/prova_amd_test.mp4` queued over
  HTTP and finished `done` in ~285 s with `prova_amd_test.it.srt`; history
  filter and page list the job. Server stopped afterwards.
- Decisions: one schema module for the API and the UI so the two write paths
  cannot drift; `allowed_media_roots` must be existing absolute directories;
  an empty secret field never overwrites, the `clear:` checkbox removes.
- Known issues: no CSRF token (SameSite=Lax only, as recorded in Step 3);
  history is in memory + `jobs.json`, not a separate archive.
- Next step: Step 5, OCR review page.

## 2026-10-26 — Architecture pages aligned with the code

- Branch / commits: `docs/arch-sync`; commit `e6c4780`, merged as `01b47e5`.
- Goal: remove the statements that contradicted the code after WebUI Steps 1–3.
- Done: `docs/architecture/README.md` (the `core -> gui` exception for
  `file_progress` is resolved, `web/`/`core/jobs` no longer labelled *target*),
  `layers.md`, `contracts.md` and `config.md` (no environment override for
  config keys, only `TP_DATA_DIR`/`TP_MODELS_DIR`), `events.md` (consumer is
  `core/jobs/progress.py`), `testing.md` (web UI/paths tests, legacy root
  `unittest` modules that `pytest linux_tests` does not collect), `web/README.md`
  (Step 3 UI present), `docs/README.md` (`CLAUDE_INTEGRATION.txt` indexed as
  historical Italian documentation, to be translated as separate work).
- Tests and results: docs index and link tests 10 passed.
- Decisions / ADRs: `CLAUDE_INTEGRATION.txt` is indexed, not translated, because
  a full translation is separate work (documentation rule, point 3).
- Known issues: the legacy root tests are documented, not moved; they need the
  GUI removal step.
- Next step: WebUI Step 4, settings and history.

## 2026-10-25 — Documentation sync (handoff)

- Branch / commits: `docs/progress-sync`; commit `92c2580`, merged as `31bd740`.
- Goal: make a cold start unambiguous.
- Done: commit/merge hashes for WebUI Steps 1–3 in `PROGRESS` and `PLAN`;
  `STATUS` updated with the last merge and the WebUI start command.
- Tests: docs index and link tests (10 passed).
- Next step: Step 4, settings and history.

## 2026-10-25 — WebUI MVP (Step 3)

- Branch / commits: `feat/webui-mvp`; commit `ba9ba99`, merged as `a9c0975`.
- Goal: browser interface for dashboard, queue, logs.
- Done: Jinja2 templates (`base`, `index`, `_status`, `_queue`, `login`),
  HTMX + Alpine vendored locally, `web/ui.py` routes (page, queue/status
  partials, add/cancel/remove, login/logout), cookie session auth, CSP and
  security headers, static CSS/JS.
- Tests: 6 UI tests (render, static + headers, form add, invalid path, login
  flow, open-redirect); real smoke test: 303 without cookie, login, form add,
  SSE events (created/status/log), job done in ~78 s with SRT.
- Decisions: Alpine used for the logs panel; token stored in an HttpOnly
  cookie for browser sessions; CSP allows `unsafe-eval` for Alpine expressions
  (no inline scripts); media roots and token still from env/config.
- Known issues: no settings/history/OCR/glossary pages yet; no CSRF token
  beyond SameSite=Lax; logs panel is per job only.
- Next step: Step 4, settings and history.

## 2026-10-25 — Web API (WebUI Step 2)

- Branch / commits: `feat/web-api`; commit `66c426e`, merged as `cb962cc`.
- Goal: expose the shared job queue over HTTP with auth, path validation and SSE.
- Done: `web/` (FastAPI factory, entry point, auth, paths, SSE bridge);
  `TP_DATA_DIR`/`TP_MODELS_DIR`; manager `keep_alive` mode; whitelisted
  config API with masked secrets; requirements-web.txt; web/README.md.
- Tests: 16 unit tests (paths, API with fake runner, SSE bridge, env dirs);
  real smoke test on 127.0.0.1:8099: auth 401/200, real job completed in ~78 s
  with SRT and history, second job cancelled via HTTP in ~2 s.
- Decisions: token required on non-loopback; token accepted as query param for
  SSE only; media roots from `TP_MEDIA_ROOTS` or config, else home.
- Known issues: no UI yet; no login page (token only); job step detail is the
  next UI step.
- Next step: Step 3, WebUI MVP.

## 2026-10-25 — Job service extracted (`core/jobs`)

- Branch / commits: **deviation** — the branch `feat/jobs-service` was not
  created and the work landed directly on `development` as `e87e8ae`
  (already pushed; published history is not rewritten). Future steps use
  feature branches. Documentation correction: `54a1913`.
- Goal: one implementation of the queue, shared by CLI and (later) WebUI.
- Done: `core/jobs/` with `Job`, `ProcessRunner`, `JobManager`, `EventHub`,
  atomic persistence, legacy status snapshot; `core/queue_runner.py` is now a
  thin client; `FileProgress` moved to `core/jobs/progress.py` with a shim in
  `gui/file_progress.py`; boundary allowlist for `core -> gui` is now empty.
- Tests: `linux_tests/test_jobs_manager.py` (8 tests, fake runner); headless
  queue on a real sample (71 s, status schema and SRT correct).
- Decisions: manager persists only when a path is given (the CLI keeps its own
  `--status` file); Qt worker untouched until WebUI parity. Process note: a
  feature branch must be created **before** the first commit.
- Known issues: GUI still has its own queue; API not started.
- Next step: Step 2, HTTP API.

## 2026-10-25 — WebUI specification and agent entry point

- Branch / commits: `docs/webui-spec` (this branch).
- Goal: make `AGENTS.md` the single entry point, record the project state and
  write the WebUI specification and step plan.
- Done: `AGENTS.md` now has project description, reading order, repository
  map, workflow; added `docs/STATUS.md`, `docs/PROGRESS.md`,
  `docs/README.md`, `docs/webui/SPEC.md`, `docs/webui/PLAN.md`; guard test
  `linux_tests/test_docs_index.py`.
- Tests: `test_docs_index.py` and the existing docs link tests.
- Decisions: WebUI binds `0.0.0.0` with a required token; path-only input in
  v1; HTMX + Alpine, no Node build; Qt GUI frozen; OCR review at Step 5.
- Known issues: service layer and API not started.
- Next step: Step 1, extract `core/jobs/`.

## 2026-10-25 — Two lines: legacy master and development

- Branch / commits: `docs/development-strategy`, merged as `a71ddc4`.
- Goal: record that `master` is the legacy line maintained outside this
  workflow and `development` is the product line, with a possible future
  repository split.
- Done: ADR-006; `docs/CONTRIBUTING.md` updated (branch model, merge strategy,
  releases).
- Tests: docs link tests.
- Decisions: no `development` → `master` merges for now; master changes are
  merged into development; split deferred.
- Next step: WebUI specification.

## 2026-10-25 — Benchmarks and results in the repository

- Branch / commits: `bench/asr-translation`, merged as `0bbab20`.
- Goal: measure ASR and translation engines on the AMD machine and keep the
  results in git, sanitized.
- Done: `bench/` harness (ASR, translation, HTTP engines, NLLB-FT, hardware
  fingerprint, sanitized export); `docs/benchmarks/2026-10-25/`.
- Tests: bench unit tests, guard tests.
- Results: Whisper WER 0.000; Qwen3 WER 0.0037; TranslateGemma GGUF balanced;
  NLLB-FT best under 8 GB; gemma4 best chrF but slow; gpt-oss fast but
  11.5 GB; LFM rejected.
- Known issues: single synthetic clip; HTTP cold/warm difference; NLLB-FT
  non-commercial license.
- Next step: none for the harness; WebUI specification.

## 2026-10-25 — Architecture baseline

- Branch / commits: `docs/architecture-baseline`, merged as `0bbab20` (same
  merge as the benchmarks, separate history below it).
- Goal: define layers, contracts, runtime/platform split and guard rails.
- Done: `docs/architecture/`, ADR-001…005, `docs/SUPPORT_MATRIX.md`,
  `docs/CONTRIBUTING.md`, PR template, guard tests
  (`test_architecture_boundaries.py`, `test_events_schema.py`,
  `test_docs_links.py`), `utils/events.py` `step` event documented.
- Tests: 11 guard tests green; full suite green except the two `install_retry`
  tests caused by the local venv (proven green in a clean worktree).
- Next step: benchmarks.

## 2026-10-24 — AMD validation and fixes

- Branch / commits: `test/amd-rocm-validazione`, merged into master as
  `1.34.34` (legacy line).
- Goal: make the stack work on Linux + AMD ROCm.
- Done: Python 3.12 via uv in `.tools/`; system deps; ROCm install; fixes:
  `torchaudio.info` → `soundfile.info`, ctranslate2 bootstrap before torch
  (Linux), NLLB `device_map={"": 0}` on ROCm, translation success gate
  (`translation_max_untranslated_pct`, fatal GPU errors, audit before writing);
  `docs/VALIDAZIONE_AMD_2026-10-24.md`.
- Tests: full suite; AMD smoke test; pipeline on the sample (Whisper 98.8%,
  Qwen3 99.5% similarity at the time).
- Known issues: GUI skipped (no display); Windows untested.
- Next step: architecture baseline.
