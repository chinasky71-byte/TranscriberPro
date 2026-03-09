# Installation Guide - Transcriber Pro

> **Supported OS:** Windows 10/11 (64-bit), Linux (Ubuntu 22.04+)
> **Estimated time:** 20-40 minutes

---

## System Requirements

### Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA with ≥4 GB VRAM | RTX 3080 / RTX 4070+ (≥10 GB VRAM) |
| RAM | 12 GB | 32 GB |
| Storage | 20 GB free | SSD with 50+ GB free |
| CPU | Any quad-core | Intel i7/i9 or AMD Ryzen 7/9 |

> **Note:** GPU is required for local transcription and translation models. Cloud engines (Claude API, OpenAI) work without a GPU but require an internet connection.

### Software

| Component | Required Version |
|-----------|----------------|
| Python | **3.11** (required) |
| CUDA Toolkit | **12.6** |
| cuDNN | 9.x (compatible with CUDA 12.6) |
| FFmpeg | 6.0+ |

---

## Installation Steps

### Step 1: Python 3.11

Download from [python.org](https://www.python.org/downloads/release/python-3119/).

**Windows:** check **"Add Python to PATH"** during installation.

```bash
python --version
# Expected: Python 3.11.x
```

### Step 2: CUDA 12.6 and cuDNN

1. Download [CUDA Toolkit 12.6](https://developer.nvidia.com/cuda-downloads) from NVIDIA
2. Install using the guided installer
3. Download and install [cuDNN 9.x](https://developer.nvidia.com/cudnn) compatible with CUDA 12.6

```bash
nvcc --version
# Expected: Cuda compilation tools, release 12.6
```

### Step 3: FFmpeg

**Windows:**
```bash
winget install ffmpeg
```
Or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin` folder to PATH manually.

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

```bash
ffmpeg -version
# Should show version 6.0+
```

### Step 4: Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/TranscriberPro.git
cd TranscriberPro
```

### Step 5: Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** This installs PyTorch 2.8+cu126. If your CUDA version differs, install PyTorch manually from [pytorch.org/get-started](https://pytorch.org/get-started/locally/).

### Step 7: First Launch

```bash
python main.py
```

Verify the app starts without errors and detects your GPU (shown in the info panel at the bottom).

---

## Credentials Configuration

All credentials are configured through the GUI in **Settings** — no manual file editing required.

### TMDB API Key (movie/series metadata)

1. Go to [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)
2. Create an application (free, instant approval for personal use)
3. Copy the **API Key (v3 auth)**
4. Transcriber Pro: **Settings → API Keys → TMDB API Key**

### OMDB API Key (metadata fallback)

1. Go to [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx)
2. Register for the free key (1000 req/day)
3. Transcriber Pro: **Settings → API Keys → OMDB API Key**

### Claude API Key (cloud translation, optional)

1. Go to [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys → Create Key
2. Transcriber Pro: **Settings → Translation Model → Claude API → enter API Key**

Requires a paid Anthropic plan. Estimated cost: ~$0.15–0.25 per movie.

### OpenAI API Key (alternative cloud translation, optional)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → Create new secret key
2. Transcriber Pro: **Settings → Translation Model → OpenAI → enter API Key**

### HuggingFace Token (Aya-23-8B model, optional)

Required only to use the Aya-23-8B local translation model (~16 GB download).

1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token (Read type)
2. Transcriber Pro: **Settings → Translation Model → HuggingFace Token**

### OpenSubtitles (subtitle upload, optional)

1. Create a free account at [opensubtitles.com](https://www.opensubtitles.com)
2. Get an API Key at [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers)
3. Transcriber Pro: **Settings → OpenSubtitles** → enter username, password, API Key

---

## Project Structure

```
TranscriberPro/
├── main.py                          # Entry point
├── requirements.txt                 # Python dependencies
├── core/
│   ├── transcriber.py               # Transcription engine (Faster-Whisper)
│   ├── translator.py                # Translation engines (NLLB, Aya, Claude, OpenAI)
│   └── pipeline.py                  # Workflow orchestration
├── gui/                             # PyQt6 graphical interface
├── utils/
│   ├── config.py                    # Singleton configuration manager
│   ├── opensubtitles_rest_uploader.py
│   └── tmdb_client.py
├── NLLB_Tranined/                   # Fine-tuned NLLB model config (no weights)
└── docs/                            # Documentation
```

AI models are downloaded automatically on first use to:
```
~/.cache/huggingface/    # HuggingFace models (NLLB, Aya)
~/.cache/whisper/        # Faster-Whisper models
```

User configuration is stored in:
```
~/.transcriberpro/config.json
```

---

## Troubleshooting

### "ModuleNotFoundError" on startup

```bash
# Make sure you're in the virtual environment
pip install -r requirements.txt
```

### GPU not detected / CUDA unavailable

```bash
python -c "import torch; print(torch.cuda.is_available())"
# False = CUDA not properly configured
```

Solutions:
1. Check CUDA version: `nvcc --version`
2. Reinstall PyTorch from [pytorch.org](https://pytorch.org) selecting CUDA 12.6
3. Update NVIDIA drivers to the latest version

### "FFmpeg not found"

Verify FFmpeg is in PATH: `ffmpeg -version`

**Windows:** add FFmpeg's `bin` folder to system environment variables (PATH).

### Errors during `pip install -r requirements.txt`

On Windows, some packages may require Visual C++ Build Tools:
```
https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
