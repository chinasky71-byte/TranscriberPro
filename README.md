# Transcriber Pro

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt)
![License](https://img.shields.io/badge/License-MIT-green)
![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?logo=nvidia)
![Version](https://img.shields.io/badge/Version-1.0.3-orange)

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
- **TMDB/OMDB metadata** — auto-fetches film synopsis for context-aware translation
- **OpenSubtitles upload** — REST API integration with duplicate detection
- **Library Scanner** — integrates with self-hosted Plex/Jellyfin servers
- **Transcription profiles** — Fast / Balanced / Quality / Maximum / Batch presets
- **Real-time resource monitor** — GPU/CPU/RAM usage during processing
- **GPU memory management** — sequential model loading/unloading to fit 6–12 GB VRAM
- **Embedded subtitle extraction** — skips transcription if subtitles already exist in the container

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

## Acknowledgements

- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2-optimized Whisper
- [NLLB-200](https://huggingface.co/facebook/nllb-200-3.3B) — Meta No Language Left Behind
- [Aya-23-8B](https://huggingface.co/CohereForAI/aya-23-8B) — Cohere multilingual model
- [Demucs](https://github.com/facebookresearch/demucs) — Meta source separation
- [OpenSubtitles](https://www.opensubtitles.com) — Subtitle database and API
