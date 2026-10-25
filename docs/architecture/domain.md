# Domain and pipeline

The domain layer decides **what** to do. It receives facts (`Caps`,
`RuntimeProfile`) and configuration, and never inspects the OS or the GPU
runtime directly.

## Processing pipeline

`core/pipeline.py::ProcessingPipeline.process()` runs these steps:

| Step | What happens | Module |
|---|---|---|
| 0 | validation, metadata (TMDB/IMDb), temp dir | `pipeline.py`, `utils/tmdb_client.py` |
| 1 / 1b | embedded text subtitles, or OCR of PGS/VOBSUB bitmaps | `subtitle_extractor.py`, `ocr_auto.py`, `pgs_ocr.py`, `vobsub_ocr.py` |
| 2 | audio extraction | `audio_processor.py` |
| 2.5 | Whisper pre-load, before Demucs (GPU order constraint) | `engines/faster_whisper_engine.py` |
| 3 | Demucs vocal separation + chunking | `audio_processor.py` |
| 4 / 4.2 / 4.5 | transcription, forced alignment, diarization | `transcriber.py`, `engine_router.py`, `aligner.py`, `diarizer.py` |
| 5 | SRT cleanup and formatting | `subtitle_cleaner.py`, `subtitle_formatter.py` |
| 5.5 | unload ASR/Demucs to free VRAM | `pipeline.py` |
| 6 | translation | `translator.py`, `llm_subtitle_translator/` |
| 6.5 | gender correction (subprocess) | `gender_corrector*.py` |
| 7 | save `<video>.<lang>.srt` | `pipeline.py` |
| 8 | optional OpenSubtitles upload | `utils/opensubtitles_*` |
| 9 | remux/mux, finalisation | `pipeline.py` |

## Engine routing

`core/engine_router.py` selects the ASR engine from language and settings
(`auto`, `canary`, `qwen3`, `faster-whisper`), loads only one engine at a time,
and degrades to faster-whisper on any error. `LanguageNotAlignable` triggers a
single retry with the detected language.

## Translation routing

- `translation_model` selects the engine: `nllb`, `nllb_finetuned`, `llm`,
  `claude`, `openai`, `opensubtitles`.
- Non-English sources are routed away from TranslateGemma to fine-tuned NLLB.
- The LLM path chooses GGUF, NF4 or NLLB-FT from free VRAM (`path_router.py`).
- A translation is considered failed when the share of blocks left in the
  source language exceeds `translation_max_untranslated_pct` (default 80) or a
  fatal GPU error occurs (see `linux_tests/test_translation_success_gate.py`).

## Data flow

```
video ──► subtitle/OCR or audio ──► ASR ──► SRT (source)
     ──► clean/format ──► translate ──► gender ──► SRT (target)
     ──► sidecar or muxed track ──► optional upload
```

Structured progress is emitted on stdout as `@@TPEV@@` lines
(see [events.md](events.md)); the textual log remains the human record.

## Purity and side effects

- Pure logic: subtitle cleaning/formatting, timing alignment, glossary
  matching, text validation.
- Side effects: subprocesses, file writes, network, GPU. These live in
  infrastructure or runtime adapters, not in pure helpers.
- Cancellation is cooperative (`_cancelled` flags) and propagates from the job
  service to the subprocess tree.

## Error semantics

| Failure | Behaviour |
|---|---|
| ASR engine error | router falls back to faster-whisper |
| No chunks / unreadable audio | job fails, partial SRT preserved where possible |
| Translation below coverage threshold | job fails, source-language file kept |
| Fatal GPU error (HIP/CUDA/device) | translation aborts immediately, job fails |
| Optional features (upload, diarization, glossary) | skipped with a log line, job continues |
