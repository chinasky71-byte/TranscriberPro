# ADR-009 — One translation engine: TranslateGemma-12B GGUF

- Status: accepted
- Date: 2026-10-27
- Supersedes: the multi-engine translation routing (`path_router.py`), the L3
  reservoir, and the cloud translation engines.

## Context

Translation had accumulated four families of engines and a routing layer:

- **NLLB-200** (base and fine-tuned) — the historical engine;
- **TranslateGemma-12B**, in three shapes: transformers bf16, transformers NF4
  (bitsandbytes) and GGUF on llama.cpp;
- **cloud engines**: Claude, OpenAI and the OpenSubtitles AI translator;
- an **L3 "reservoir"**: a second local model (NLLB-FT or Qwen, chosen at runtime)
  that received the blocks the primary engine had left in the source language,
  spawned as its own CLI process with its own timeout and fan-out.

Choosing between them was `utils/translator_path_select.py` (a pure policy) plus
`core/llm_subtitle_translator/path_router.py` (the facts: backend, free VRAM, GGUF
files present). Every branch ended in a *silent* substitute: an LLM that could not
run became NLLB-FT, a GGUF that did not load became NF4, a missing GGUF became the
transformers path, and a non-English source was routed to NLLB. The user saw a
finished subtitle and no indication of which model had produced it.

The measurements that closed the question:

- TranslateGemma-12B won the head-to-head comparison with NLLB-FT on film
  dialogue (MQM 2,06 vs 2,85 on Deadpool 2; 1,66 vs 2,38 on A Man Called Otto is
  the NLLB win, and the prompt work that followed changed it);
- the GGUF Q4_K_M is not inferior to NF4 with a 3-point margin and ~14× faster,
  and it is the only path on AMD/Vulkan where bitsandbytes does not exist;
- the reference library is English → Italian: the engine is trained on exactly
  that pair, and the Italian end-to-end round showed that the *translation* step
  is what WER punishes (59.76% on a translated source against 11.79% on a native
  one), not the choice of a second translator;
- the cloud engines were never part of a measured comparison and each added a
  key, a network dependency and a way to leak subtitles.

## Decision

**TranslateGemma-12B GGUF on llama.cpp is the only translation engine, English →
Italian only.** No alternatives, no automatic fallbacks.

- The GGUF file is **resolved, not chosen**: `gguf_engine.resolve_gguf_path()`
  returns the file for the configured quantization (`Q4_K_M` by default) or raises
  an error naming the directory and the `.gguf` files it found.
- The **quantization is a setting**, not a VRAM guess: `llm_translator_gguf_quant`
  (`Q4_K_M`, `Q3_K_M`, `IQ3_M`). `utils/gguf_quant.py` keeps the measured weights
  and `gguf_need_gib()`; nothing picks a quantization from free VRAM any more.
- **A non-English source is refused** in the pipeline and in OCR translation, with
  a message; the file keeps its original subtitles and the job is marked failed.
- **A missing engine fails the job in seconds**: `check_translation_ready()` runs
  at STEP 0 (file, llama.cpp, GPU offload) and again at STEP 6 (free VRAM against
  `gguf_need_gib`).
- The **L3 reservoir is gone**: what survives L1 (tolerant unmask) and L2
  (retranslation without masking) stays in the source language, is counted by the
  audit and is judged by `translation_max_untranslated_pct`, which is unchanged.

**Removed:** `core/llm_subtitle_translator/path_router.py`,
`utils/translator_path_select.py`, `core/fallback_translate_cli.py`, the reservoir
implementation and its config keys, `SubtitleLLMEngine` (the transformers bf16 /
NF4 / LoRA loader), `get_engine` / `unload_engine`, the cloud translators and their
requirements, the cloud API keys from the WebUI, and the config keys
`llm_translator_gguf_enabled`, `llm_translator_gguf_before_nf4`,
`llm_translator_nf4_min_free_gb`, `llm_translator_gguf_q4_min_free_gb`,
`llm_translator_gguf_iq3_min_free_gb`, `reservoir_engine`,
`fallback_translator_model_path`.

**Kept, replaced or re-homed:**

- one `ModelSpec` and `build_mt_messages()` in `engine.py` — the prompt is a
  property of the weights, not of the runtime;
- `translation_model` and `llm_translator_model` stay as keys for compatibility:
  every historical value (`nllb`, `nllb_finetuned`, `llm`, `aya`, `claude`,
  `openai`, `opensubtitles`) maps onto `translategemma-12b-gguf` on read, with a
  log line;
- `llm_translator_adapter` and `llm_translator_model_path` stay because the frozen
  Qt dialog writes them: the adapter is reported as not applied, the path counts
  as an alternative GGUF directory;
- `NLLBTranslator` / `NLLBFineTunedTranslator` stay in `core/translator.py`,
  reachable only from the `bench/` tools, which use them as a comparison arm.

## Consequences

- **One failure mode instead of four**: a job either translates with
  TranslateGemma or fails with a message that says what is missing. No subtitle is
  ever produced by a model the user did not configure.
- **The install is smaller and simpler**: no bitsandbytes, no peft, no
  transformers model download for translation (a 6,8 GiB GGUF replaces a 23 GiB
  bf16 checkpoint and an 8,4 GiB NF4 one), no cloud SDKs.
- **The WebUI is honest**: the target language is a single value, the engine
  selector is gone, and the quantization is a setting with three options.
- **What is lost**: a non-English source can no longer be translated at all, and
  neither can a source language the GGUF cannot handle. That is a declared limit,
  not a regression: the previous routing translated those files with a model that
  scored worse on this library.
- **Rollback**: `git revert` of the branch restores the routing, the reservoir and
  the cloud engines; the config keys of the old installs are still readable
  (they are ignored, not deleted from disk).

## Alternatives rejected

- **Keep the NLLB-FT fallback for non-GGUF setups**: it is what turned a
  configuration error into an invisible quality loss. If the GGUF is missing, the
  right answer is a failed job and a remedy.
- **Keep the router for machines with little VRAM**: the VRAM question is now
  "which of three files do I install", answered once at install time, not
  re-decided per file with a silent swap.
- **Keep NF4/bf16 for large cards**: no measurement shows them better than GGUF
  Q4_K_M, and they cost a 23 GiB download plus a transformers/bitsandbytes stack.
- **Keep the reservoir for the hard blocks**: measured, it recovered a handful of
  lines per episode at the price of a second model swap (1-2 minutes) and a whole
  CLI process; the remaining lines are now reported by the audit, which is what
  the reservoir was hiding.
- **Translate from any source language**: rejected on measurement (the French
  round showed that labelling French as English left it untranslated, and
  labelling it correctly made fluency worse), and the engine is trained on
  English → Italian.
