# Configuration

`utils/config.py` is a process-wide singleton. It merges defaults with
`~/.transcriberpro/config.json` and exposes typed accessors.

## Precedence

```
defaults (Config.DEFAULTS)  <  config.json  <  per-job in-memory overlay
```

- Per-job overrides (`utils/job_overrides.py`) are applied with
  `Config.set_overlay()` and are **never written to disk**.
- There are **no environment overrides for config keys**: only the directory
  roots `TP_DATA_DIR` and `TP_MODELS_DIR` are read from the environment.
- `TP_DATA_DIR` (config/logs/jobs root, default `~/.transcriberpro`) and
  `TP_MODELS_DIR` (model cache, default `<project>/models`) are read at import
  time; `web.main` sets them before importing config. Containers rely on them.

## Important keys

| Key | Default | Meaning |
|---|---|---|
| `transcription_engine_mode` | `auto` | `auto \| canary \| qwen3 \| faster-whisper` |
| `whisper_model` | `large-v3` | default Whisper model |
| `target_language` | `ita` | subtitle target language |
| `translation_model` | `translategemma-12b-gguf` | one engine (ADR-009); every historical value is mapped onto it on read |
| `llm_translator_model` | `translategemma-12b` | key in `MODEL_SPECS` |
| `llm_translator_gguf_quant` | `Q4_K_M` | `Q4_K_M \| Q3_K_M \| IQ3_M` |
| `llm_translator_gguf_dir` | `` (empty) | GGUF directory, empty means `models/translategemma-12b-gguf` |
| `llm_translator_gguf_parallel` | `4` | parallel sequences, i.e. the KV-cache size |
| `translation_max_untranslated_pct` | `80` | translation fails above this share of untranslated blocks |
| `use_gpu` | `true` | allow GPU execution |
| `enable_diarization` | `false` | pyannote diarization |
| `dialogue_style_enabled` | `true` | Netflix dialogue formatting (implies diarization) |
| `gender_correction_enabled` | `false` | audio-driven gender correction |
| `punctuation_restore_mode` | `auto` | punctuation restoration for engines that need it |
| `model_cache_cleanup_enabled` | `true` | purge unused model caches after a queue |
| `opensubtitles_upload_enabled` | `true` | upload finished subtitles |
| `mux_subtitle_into_video` | `false` | mux the SRT into the MKV |
| `replace_mislabeled_italian_track` | `true` | replace a mistagged Italian track |

Model path keys: `nllb_model_path`, `nllb_finetuned_model_path` (bench only),
`llm_translator_gguf_dir`, `llm_translator_model_path` (legacy alias for the
GGUF directory, written by the frozen Qt dialog), `gender_correction_model_path`.

## Per-job override keys

Only these keys can be overridden for a single file
(`utils/job_overrides.py`):

`target_language` (only `ita` since ADR-009), `force_audio_transcription`,
`gender_correction_enabled`, `mux_subtitle_into_video`,
`opensubtitles_upload_enabled`.

## Secrets and local endpoints

The config file may contain:

- `huggingface_token`
- `opensubtitles_username`, `opensubtitles_password`, `opensubtitles_api_key`
- `opensubtitles_xmlrpc_username`, `opensubtitles_xmlrpc_password`
- `library_scanner_api_key`
- `library_scanner_url` — a LAN address, not a credential, but just as
  environment-specific: it belongs to the installation, not to the repository

**No default value in `utils/config.py` is a secret or an address.** Both
`library_scanner_url` and `library_scanner_api_key` default to the empty string;
the scanner UI reports "config missing" until they are set, which is the honest
state for a fresh install. Set them in `TP_DATA_DIR/config.json` or in the WebUI
settings (the key is write-only there).

History: until 2026-10-27 those two defaults carried a real API key and a
private LAN address, committed with `1ab14ab` ("Sync production"). Removing
them from the working tree does not remove them from git history, so **that key
must be considered compromised and rotated on the scanner service**. Never paste
it back into a tracked file.

Rules:
- never commit them, never log them, never return them from an API;
- the web API exposes only `is_set` flags and accepts write-only updates;
- keep the config file readable by the owner only (`chmod 600`);
- `claude_api_key` and `openai_api_key` are gone with the cloud engines
  (ADR-009); an old config that still has them is harmless, nothing reads them.

## Migration

`Config._merge_defaults` adds new defaults on load. Unknown keys are preserved.
Do not rename keys without a migration; older configs must keep working.
