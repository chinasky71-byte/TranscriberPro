# Transcriber Pro

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt)
![License](https://img.shields.io/badge/License-MIT-green)
![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?logo=nvidia)
![Version](https://img.shields.io/badge/Version-1.3.7-orange)

AI-powered desktop application for automatic subtitle transcription and translation from video files.

---

## What It Does

Transcriber Pro takes any video file, extracts or transcribes its audio using Faster-Whisper (OpenAI speech recognition), then translates the resulting subtitles into Italian (or other languages) using local AI models or cloud APIs. The output is a clean `.srt` subtitle file, optionally uploaded to OpenSubtitles automatically.

**No subscription. No cloud dependency for local models. Runs entirely on your GPU.**

---

## Features

- **Automatic transcription** via Faster-Whisper `large-v3` (99 languages, VAD filter)
- **Multiple translation engines**: NLLB-200, Aya-23-8B, Claude API, OpenAI GPT-4o-mini
- **Vocal separation** via Meta Demucs — isolates speech before transcription for better accuracy
- **Intelligent chunking** — splits audio at silence points for accurate timestamp alignment
- **TMDB/OMDB metadata** — auto-fetches film synopsis for context-aware translation; robust title parsing with HTML entity decoding and release-tag stripping
- **OpenSubtitles upload** — REST API integration with duplicate detection
- **Library Scanner** — integrates with self-hosted Plex/Jellyfin servers; real-time DB update on subtitle creation; Italian audio detection via explicit filename tags (ITA, NUiTA, ENG, NUEnG, MULTI, etc.)
- **Transcription profiles** — Fast / Balanced / Quality / Maximum / Batch presets
- **Real-time resource monitor** — GPU/CPU/RAM usage during processing
- **GPU memory management** — sequential model loading/unloading to fit 6–12 GB VRAM
- **Embedded subtitle extraction** — skips transcription if subtitles already exist in the container; bitmap-only (PGS/VOBSUB) streams are automatically skipped
- **IT/EN interface** — full Italian/English UI; language selector in General Settings (🔧); auto-detects system locale
- **Immediate stop with confirmation** — Stop button shows a confirmation dialog; on confirm, kills active FFmpeg/Demucs/Whisper processes within seconds and cleans up temp files automatically
- **Gender correction (experimental)** — LLM-based post-translation fix for Italian grammatical gender errors, using TMDB cast context; runs in isolated subprocess

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | NVIDIA 6 GB VRAM | NVIDIA RTX 3060 12 GB |
| **RAM** | 12 GB | 16 GB+ |
| **Storage** | SSD (models + temp files) | NVMe SSD |
| **OS** | Windows 10/11 | Windows 11 |

> CPU-only mode is supported but ~10x slower. GPU is strongly recommended.

---

## Software Requirements

- **Python** 3.11
- **CUDA** 12.6 + cuDNN
- **FFmpeg** 6.0+ (must be in PATH)
- **Git** (for cloning)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/TranscriberPro.git
cd TranscriberPro

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

> PyTorch with CUDA is listed in `requirements.txt`. If you need a different CUDA version, install PyTorch manually from https://pytorch.org/get-started/locally/

---

## Credentials Configuration

All credentials are entered through the application GUI — no config files to edit manually.

| Credential | Where to enter in the app | How to obtain | Enables |
|---|---|---|---|
| **Claude API Key** | Settings → Translation Model → Claude | [console.anthropic.com](https://console.anthropic.com) → API Keys | Claude Sonnet translation (best quality) |
| **OpenAI API Key** | Settings → Translation Model → OpenAI | [platform.openai.com](https://platform.openai.com) → API Keys | GPT-4o-mini translation |
| **HuggingFace Token** | Settings → Models → HuggingFace Token | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | Download Aya-23-8B (gated model) |
| **OpenSubtitles Username** | Settings → OpenSubtitles | [opensubtitles.com](https://www.opensubtitles.com) (free) | Subtitle upload |
| **OpenSubtitles Password** | Settings → OpenSubtitles | opensubtitles.com | Subtitle upload |
| **OpenSubtitles API Key** | Settings → OpenSubtitles | [opensubtitles.com/en/api](https://www.opensubtitles.com/en/api) | REST API upload |
| **TMDB API Key** | Settings → Metadata → TMDB | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) (free) | Film/series metadata for translation context |
| **OMDB API Key** | Settings → Metadata → OMDB | [omdbapi.com/apikey](http://www.omdbapi.com/apikey.aspx) (free tier) | IMDb metadata fallback |
| **Library Scanner API Key** | Settings → Library → API Key | Your self-hosted server | Plex/Jellyfin library scanning |

All credentials are optional except for the translation model you choose to use. Local models (NLLB, Aya) require no API keys.

---

## Basic Usage

1. **Add video files** — drag and drop or use the file picker
2. **Select transcription profile** — Balanced is recommended for most cases
3. **Choose translation engine** — NLLB (fast, local) or Claude (best quality, cloud API)
4. **Click Start** — the pipeline runs automatically:
   - Vocal separation (Demucs)
   - Audio chunking at silence points
   - Transcription (Faster-Whisper)
   - Translation
   - SRT file saved next to the video
   - Optional upload to OpenSubtitles

---

## Supported Models

| Model | Type | Size | VRAM | Quality | Speed |
|-------|------|------|------|---------|-------|
| Faster-Whisper large-v3 | Transcription | 1.5B params | ~4 GB | ★★★★★ | ★★★★☆ |
| NLLB-200-3.3B | Translation (local) | 3.3B params | ~5 GB | ★★★☆☆ | ★★★★★ |
| NLLB-200 fine-tuned | Translation (local) | 3.3B params | ~5 GB | ★★★★☆ | ★★★★★ |
| Aya-23-8B | Translation (local) | 8B params | ~8 GB | ★★★★☆ | ★★★☆☆ |
| Claude Sonnet (API) | Translation (cloud) | — | 0 GB | ★★★★★ | ★★★★☆ |
| GPT-4o-mini (API) | Translation (cloud) | — | 0 GB | ★★★★☆ | ★★★★★ |
| Qwen2.5-14B GGUF | Gender correction (local) | 14B params | ~8.4 GB | ★★★☆☆ | ★★★☆☆ |

Models are loaded and unloaded sequentially to fit within available VRAM. Demucs, Whisper, and the translation model never run simultaneously.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                     │
│                      (PyQt6 GUI)                         │
│   MainWindow · ResourceMonitor · ProfileDialog           │
└────────────────────────┬────────────────────────────────┘
                         │ Qt Signals/Slots
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   CORE PROCESSING LAYER                  │
│             ProcessingPipeline (orchestrator)            │
│   SubtitleExtractor · AudioProcessor · Transcriber       │
│   Translator (NLLB / Aya / Claude / OpenAI)              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   UTILS / DATA LAYER                     │
│   Config · TMDBClient · IMDbClient · OpenSubtitles       │
│   FileHandler · Logger · ResourceMonitor                 │
└─────────────────────────────────────────────────────────┘
```

---

## Performance Benchmarks

Tested on: i7-12700KF · 12 GB RAM · RTX 3060 12 GB · NVMe SSD

| Content | Duration | GPU | CPU | Speedup |
|---------|----------|-----|-----|---------|
| Short clip | 5 min | 45 sec | 7 min | 9.3x |
| TV episode | 45 min | 7 min | 67 min | 9.5x |
| Movie | 2h 15min | 20 min | 3h 22min | 10.1x |
| Long documentary | 4h | 38 min | 6h 12min | 9.8x |

**Average: ~10x speedup with GPU vs CPU-only mode.**

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push and open a Pull Request

Please open an issue first for major changes to discuss the approach.

---

## License

This project is licensed under the MIT License.

---

## Changelog

### v1.3.7
- **Local model cache** — all AI models (Whisper, NLLB, Aya, wav2vec2, pyannote, Demucs) now download into `models/.cache/` inside the project folder instead of `~/.cache/huggingface/`. Single bootstrap module sets `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE`, `TORCH_HOME` env vars before any torch/transformers/HF import; faster-whisper gets `download_root=` explicitly since it doesn't honor `HF_HOME` reliably
- **Auto cache cleanup post-pipeline** — non-Italian models are removed from cache at the end of each file's processing to save disk space. Whitelist: wav2vec2-italian, faster-whisper-large-v3, NLLB fine-tuned (already local), Qwen GGUF (already local). Removed: NLLB-200 base, Aya-23-8B, wav2vec2 en/fr/es/generic, pyannote, Demucs htdemucs. Re-download is automatic and silent if a removed model is needed again. Windows mmap lock handled with retry+sleep
- **Force audio transcription option** — new checkbox in Translation Model settings to bypass embedded subtitle extraction and always transcribe from audio. Useful when embedded subs are low quality

### v1.3.6
- **Gender correction settings UI** — GGUF model selector with VRAM guidance table (8GB/12GB/16GB+), file browser, enable/disable toggle

### v1.3.5
- **Gender Correction (EXPERIMENTAL)** — new STEP 6.5: LLM-based grammatical gender correction for Italian subtitles using Qwen2.5-14B GGUF via llama-cpp-python. Runs in an isolated subprocess with fresh CUDA context for maximum VRAM availability. Integrates TMDB cast info for character gender context. Includes progress bar with ETA. *This feature is experimental — quality depends on the LLM model and corrections should be reviewed manually.*
- **VRAM cleanup fix** — fixed 3.2 GB VRAM stuck after NLLB translator cleanup. Root cause: cuBLAS persistent workspaces prevented PyTorch caching allocator from releasing memory segments. Fix: `torch._C._cuda_clearCublasWorkspaces()` + accelerate hook removal + explicit `.to('cpu')` before model deletion
- **Encoding fix** — fixed `UnicodeDecodeError` in subtitle extractor and audio track selector on Windows when video filenames contain non-ASCII characters (was defaulting to cp1252 instead of UTF-8)

### v1.3.1
- **OOM prevention** — adaptive batch size ceiling based on real-time VRAM availability; fatigue tracking across batch files

### v1.3.0
- **Immediate stop with confirmation** — Stop button now shows a confirmation dialog; pressing Yes kills all active FFmpeg/Demucs/Whisper subprocesses within 2–3 seconds via `pipeline.cancel()` propagation; temp files are cleaned up automatically by the existing `finally` block
- **TMDB parser fix** — double HTML entity decoding (`&amp;#039;` → `&#039;` → `'`) for edge-case titles
- **Log noise reduction** — demoted it-IT/en-US fallback messages from `warning`/`info` to `debug`

### v1.2.0
- Full IT/EN interface with auto locale detection and language selector in General Settings
- Library Scanner: Italian audio tag detection (ITA, NUiTA, ENG, MULTI…); real-time DB update on subtitle creation
- TMDB parser: HTML entity decoding, robust release-tag stripping
- WhisperX forced alignment support (word-level timestamps)
- Embedded subtitle extraction: bitmap-only streams (PGS/VOBSUB) auto-skipped

### v1.1.0
- Speaker diarization via pyannote.audio (optional, requires HuggingFace token)
- Adaptive batch size manager for VRAM-aware translation
- Subtitle formatter with professional dialogue style
- OpenSubtitles REST API upload with duplicate detection

### v1.0.0
- Initial release: Faster-Whisper transcription, NLLB/Aya/Claude/OpenAI translation, Demucs vocal separation, TMDB metadata, OpenSubtitles upload

---

## Acknowledgements

- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2-optimized Whisper
- [WhisperX](https://github.com/m-bain/whisperX) — forced alignment and word-level timestamps pipeline
- [NLLB-200](https://huggingface.co/facebook/nllb-200-3.3B) — Meta No Language Left Behind
- [Aya-23-8B](https://huggingface.co/CohereForAI/aya-23-8B) — Cohere multilingual model
- [Demucs](https://github.com/facebookresearch/demucs) — Meta source separation
- [OpenSubtitles](https://www.opensubtitles.com) — Subtitle database and API
- [jonatasgrosman](https://huggingface.co/jonatasgrosman) — wav2vec2-large-xlsr-53 alignment models (Italian, English, French, Spanish)
- [facebook/wav2vec2-large-xlsr-53](https://huggingface.co/facebook/wav2vec2-large-xlsr-53) — multilingual fallback alignment model
