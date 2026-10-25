# Extension guide

Recipes for the common changes. Each recipe lists what to touch and what to
leave alone.

## 1. Add an ASR engine

1. Create `core/engines/my_engine.py` implementing
   `core/engines/base_engine.py::TranscriptionEngine`:
   `is_available()`, `supports_language()`, `load()`, `unload()`,
   `transcribe_chunks()`.
2. Register it in `core/engine_router.py` (availability, language support,
   planning order).
3. Emit the usual events (`phase`, `bar`) through `utils/events.py`.
4. Add tests: availability with missing deps, language support, router
   fallback to faster-whisper.
5. Update `docs/architecture/domain.md` and the engine table in the README.

Never load two engines at once. The router owns the lifecycle.

## 2. Add a translator

1. Subclass `core/translator.py::BaseTranslator` and implement
   `translate_file()` and `cleanup()`.
2. Add the model key to `Config.VALID_TRANSLATION_MODELS` and to the factory.
3. Honour the success criterion: use
   `_translation_exceeds_error_budget()` and return `False` when coverage is
   insufficient; never report success for a file left in the source language.
4. Add i18n keys in both English and Italian (`utils/translations.py`);
   the i18n test enforces parity.
5. Document the model, VRAM requirements and generation parameters.

## 3. Add an LLM model (`ModelSpec`)

1. Add an entry to `MODEL_SPECS` in
   `core/llm_subtitle_translator/engine.py`: `model_id`, label, generation
   parameters, loader, context window, VRAM notes.
2. If it has a GGUF path, add it to the GGUF directory layout and to
   `path_router.py` thresholds.
3. Verify the prompt format (chat template) and the output parser; a
   general-purpose model needs an adapter, not only a path.
4. Measure: quality versus the current default, time per block, peak VRAM.
   A model that does not beat the default on the reference sample is rejected.
5. Update `docs/architecture/runtime.md` (VRAM thresholds) and the model table.

## 4. Add a GPU backend

1. Extend `Caps` and `RuntimeProfile` with the new capability.
2. Implement detection in `utils/gpu_detect.py` and policy in `runtime/`.
3. Add the bootstrap hooks (initialization order, environment variables) in
   `runtime/`, never in `core/`.
4. Add the requirements file (`requirements-<backend>.txt`) and a Dockerfile
   target.
5. Add a guard test asserting the backend is not referenced from `core/`.
6. Update `docs/SUPPORT_MATRIX.md` with the support tier and what was tested.

## 5. Add a WebUI page

1. Add API endpoints in `web/` (JSON, explicit status codes) and an SSE event
   if the page needs live updates.
2. Add the static page (HTMX partial or full page) and navigation.
3. Reuse the service layer; never call `core.pipeline` directly from a request
   handler.
4. Validate input (paths, enums) and return errors that do not leak secrets.
5. Add API tests with a fake `JobManager` and a link/route test.
6. Document the endpoint in the OpenAPI-generated docs and in `domain.md` if
   it changes the user-visible workflow.

## 6. Add a platform service

1. Extend the `Platform` protocol in `contracts.md`.
2. Implement it in `platform_services/<os>.py`; default to a no-op elsewhere.
3. Add a fake for tests and a test per implementation where possible.
4. Remove the old inline OS check and its allowlist entry.
