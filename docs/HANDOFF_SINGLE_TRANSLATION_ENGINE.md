# Handoff — one translation engine (ADR-009)

Resume point for the work that turns translation into a single engine:
**TranslateGemma-12B GGUF, English→Italian only, no alternatives, no automatic
fallbacks**. Written to be usable from a cold start: the next session should not
need to re-derive anything.

- Updated: 2026-10-27 (session in progress)
- Branch: `feat/single-translation-engine`, from `origin/development` (`c5b856d`)
- Suite at every commit: `pytest linux_tests -q` → **802 passed, 15 skipped**

## Hard constraints for this branch

1. **Do not touch `gui/`.** The Qt interface is frozen (ADR-002). Everything it
   calls must keep existing: `utils/config.py` keeps the legacy cloud-API
   getters/setters/validators and the three legacy defaults for exactly that
   reason (commit `fe749cc`). Verify with:
   `git diff --stat origin/development -- gui/` → must stay empty.
2. Every user-visible string goes through `tr()` and must be added to **three**
   places: `utils/translations.py` (`en` table and `it` table) and
   `linux_tests/i18n_it_originals.json` (only for keys that are already there;
   a brand-new key may be absent from the manifest).
3. `requirements.txt` and `requirements-rocm.txt` are compared by
   `linux_tests/test_amd_rocm_f6.py`: a package removed from one must be removed
   from the other.
4. Commits: one per step, message states cause and evidence. Documentation in
   English.

## Done (committed)

| Commit | Step | What |
|---|---|---|
| `8906970` | 1 | Non-English source refused in `core/pipeline.py` STEP 6 and `core/ocr_auto.py`; `route_non_english_away_from_llm()` deleted; `test_translation_routing.py` replaced by `linux_tests/test_translation_refusal.py` |
| `bf549f2` | 2 | `core/subtitle_synchronizer.py` timing-only: `_LocalQwenMatcher`, `_step2_translate_anchors`, `_step3_match_subtitles`, `_step1_whisper_fallback`, prompt/JSON helpers, `sync_engine`, `sync_llm_window_size`, `sync_qwen_model_path` and 26 `sy_*` strings removed (1942 → 1062 lines) |
| `4ca8f8a` | 3 | Cloud engines removed: `ClaudeTranslator`, `OpenAITranslator`, `utils/opensubtitles_ai_translator.py`, `core/llm_subtitle_translator/hallucination_guard.py`, `claude_api_key`/`openai_api_key`/`openai_model` from WebUI and requirements, 23 i18n strings per language |
| `fe749cc` | 3b | The cloud-API config methods restored as **legacy** for the frozen Qt dialog (it called them); static check over every `config.<method>()` in `gui/` reports 0 missing |

Not yet touched on this branch: `docs/adr/ADR-009-*.md` (still to write),
`docs/STATUS.md`, `docs/PROGRESS.md` (one entry per PR, at the end).

### State recorded while step 4 was starting

- Working tree: clean except this document and its row in `docs/README.md`.
- **Step 4 has not been applied yet.** A first attempt used a temporary script
  outside the repository (`/tmp/tp_step4_reservoir.py`) with text-anchored
  deletions; it stopped on a mismatch (the reservoir counter line is shared by
  the NLLB and the LLM branch, so it must be removed with a `count == 2`
  replacement, not a single-match one) and, by construction, wrote nothing.
  Re-run the same deletion with that fix, or delete the blocks with the editor.
- Nothing about step 4 has been committed, so `git reset --hard` would return
  to `fe749cc` (steps 1-3b) without losing work.

## Remaining steps

### 4. L3 reservoir (next)

Remove the last "second model" fallback. Blocks that survive L1 (tolerant
unmask) and L2 (retranslation without masking) stay in English and are counted
by the audit; the job-level gate (`translation_max_untranslated_pct`, 80) is
unchanged.

- `core/translator.py`: delete `RESERVOIR_*`, `RESERVOIR_DEFAULT`,
  `_reservoir_engine_choice`, `_reservoir_via_nllb`, `_reservoir_translate`,
  `_reservoir_fanout`, and both call sites (one in the NLLB branch, one in the
  LLM branch, each followed by a `tl_counter_reservoir_l3` counter).
- delete `core/fallback_translate_cli.py`.
- `utils/config.py`: drop `reservoir_engine`, `fallback_translator_model_path`,
  `get_reservoir_engine`, `set_reservoir_engine`,
  `get_fallback_translator_model_path`, `get_fallback_translator_model`.
- `linux_tests/test_i18n_texts.py` parametrises `core.fallback_translate_cli`:
  remove it from the list or the test fails.
- `test_translation_success_gate.py` (root, not in the suite) monkeypatches
  `_reservoir_translate`; update together with the deletion.
- i18n: `tl_reservoir_*`, `tl_distinct_sentences_blocks_to_the*`,
  `tl_warning_blocks_to_the_reservoir*`, `tl_blocks_confirmed_identical_to_the`,
  `tl_counter_reservoir_l3`, `fb_*` (three files as in constraint 2).

### 5. Quant policy

`utils/translator_path_select.py` → `utils/gguf_quant.py` keeping only
`QUANT_WEIGHTS_GIB`, `QUANT_PREFERENCE`, `normalize_quant()`, `gguf_need_gib()`
and the VRAM constants; `choose_translator_path`, `PathChoice`, `AUTO_QUANTS`
and the bf16/nf4 thresholds go. Delete `core/llm_subtitle_translator/path_router.py`
and resolve the file in `gguf_engine.py`, raising one explicit error that names
the directory and the `.gguf` files found. `engine.py` keeps one `ModelSpec` and
loses `SubtitleLLMEngine` (the transformers bf16/NF4/LoRA loader).
`core/translator.py::LLMSubtitleTranslator._acquire_engine` calls the GGUF
resolver and never returns `None` (`_translate_via_nllb_ft` disappears).
Config: `llm_translator_gguf_quant` default `Q4_K_M` (no `auto`), drop
`llm_translator_gguf_enabled`, `_before_nf4`, `_nf4_min_free_gb`,
`_q4_min_free_gb`, `_iq3_min_free_gb`. `utils/gguf_download.py` and
`scripts_manutenzione/gguf_convert.py` reference the old module/constants:
update both. Tests: delete `linux_tests/test_translator_path_select.py` and the
router half of `test_gguf_engine.py`, update `test_gguf_download.py`.

### 6. Target language

`utils/job_overrides.py::LANGUAGES` and `web/ui.py::LANGUAGES` → `('ita',)`;
the engine keeps refusing anything else (`tl_this_engine_only_possibly`
message is `tl_this_engine_only_produces_italian`); also collapse
`VALID_TRANSLATION_MODELS` to the single value `translategemma-12b-gguf` with
`LEGACY_TRANSLATION_MODELS` mapping every old value (`nllb`, `nllb_finetuned`,
`aya`, `llm`, `claude`, `openai`, `opensubtitles`) onto it with a log line, drop
the per-job `translation_model` override, the WebUI engine `<select>`, and
`_NOMI_MOTORE` / `get_translation_model_info()`.

### 7. Unavailable engine

`core/backend_preflight.py`: `check_translation_ready(config)` → file exists,
`llama_cpp` importable, GPU-side llama.cpp usable, free VRAM ≥
`gguf_need_gib(quant)`; returns `(ok, remedy)`. Call it from
`core/pipeline.py` STEP 0 so a missing/broken engine costs seconds, not a whole
transcription. New test proves no translator is constructed and the job ends
failed.

## Close-out (after the seven)

1. `docs/adr/ADR-009-single-translation-engine.md` + row in `docs/README.md`
   (ADR table at the bottom of the "Decisions" section).
2. `docs/STATUS.md` translation line, open items, known issues;
   `docs/PROGRESS.md` entry (branch, commits, goal, files, tests, decisions,
   known issues, next step — enforced by `test_docs_progress.py`).
3. `docs/architecture/{config,runtime,extension-guide,testing}.md` and
   `docs/benchmarks/README.md` (mark the 2026-10-25 multi-engine table
   historical, new reproduce command).
4. End-to-end: English clip (expect ≈ WER 0.41 / chrF 0.76 / ~9 GB / ~15 s,
   i.e. the `llm` row of `docs/benchmarks/2026-10-25/translation/summary.md`),
   plus a French clip to prove the refusal; export a new run under
   `docs/benchmarks/`.
5. `--no-ff` merge into `development`, delete the branch.

## Open items that need the owner

- **Secret in the repository (pre-existing)**: `utils/config.py` has
  `'library_scanner_api_key': 'IDu_…'` as a default value — looks like a real
  key committed to git. The privacy rule forbids it; replacing it with `''`
  plus a note on where the value lives is the fix, but it is the owner's call.
- **Uncommitted leftovers from `docs/cleanup-after-whisper`** (comments in
  `core/pipeline.py` and a docstring in `utils/cache_bootstrap.py`) are in
  `git stash@{0}`; they are not part of this branch.
