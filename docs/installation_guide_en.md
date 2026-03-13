# 🚀 Installation Guide - IA Transcriber Pro

## 📖 Table of Contents

- [System Requirements](#system-requirements)
- [Quick Start](#quick-start)
- [Detailed Installation](#detailed-installation)
- [GPU Setup (CUDA)](#gpu-setup-cuda)
- [First Run](#first-run)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Optional Optimizations](#optional-optimizations)
- [Upgrading](#upgrading)

---

## 💻 System Requirements

### Minimum Requirements

| Component | Minimum | Recommended | Optimal |
|-----------|---------|-------------|---------|
| **OS** | Windows 10, macOS 10.15, Ubuntu 20.04 | Windows 11, macOS 12+, Ubuntu 22.04 | Any modern 64-bit OS |
| **CPU** | 4 cores, 2.0 GHz | 8 cores, 3.0 GHz | 12+ cores, 3.5+ GHz |
| **RAM** | 8 GB | 16 GB | 32 GB+ |
| **Storage** | 10 GB free | 50 GB free | 100 GB+ SSD |
| **GPU** | None (CPU only) | NVIDIA GPU, 6GB VRAM | NVIDIA GPU, 12GB+ VRAM |
| **Python** | 3.8+ | 3.10+ | 3.11+ |

### GPU Support

**NVIDIA GPUs** (CUDA-enabled):
- ✅ **Recommended**: RTX 3060 (12GB), RTX 4060 Ti (16GB), RTX 4070+
- ✅ **Minimum**: GTX 1660 (6GB), RTX 2060 (6GB)
- ✅ **Optimal**: RTX 4080 (16GB), RTX 4090 (24GB)

**AMD/Apple Silicon**:
- ⚠️ Limited support (CPU mode recommended)
- Apple M1/M2/M3: Use CPU mode (still very fast)

### Software Requirements

- **Python**: 3.8 - 3.11 (3.10 recommended)
- **FFmpeg**: Latest stable version
- **CUDA Toolkit**: 11.8 or 12.1 (for GPU support)
- **Git**: For cloning repository

---

## ⚡ Quick Start

### Windows (PowerShell)

```powershell
# 1. Clone repository
git clone https://github.com/yourusername/ia-transcriber-pro.git
cd ia-transcriber-pro

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run application
python main.py
```

### Linux/macOS (Terminal)

```bash
# 1. Clone repository
git clone https://github.com/yourusername/ia-transcriber-pro.git
cd ia-transcriber-pro

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run application
python main.py
```

---

## 📦 Detailed Installation

### Step 1: Install Python

#### Windows

**Option A: Official Python.org (Recommended)**

1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run installer
3. ✅ **IMPORTANT**: Check "Add Python to PATH"
4. Choose "Customize installation"
5. Ensure "pip" is selected
6. Click "Install"

**Option B: Microsoft Store**

1. Open Microsoft Store
2. Search "Python 3.11"
3. Click "Install"

**Verify Installation:**

```powershell
python --version
# Should output: Python 3.11.x

pip --version
# Should output: pip 23.x.x
```

#### Linux

**Ubuntu/Debian:**

```bash
# Update package list
sudo apt update

# Install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip

# Verify
python3.11 --version
```

**Fedora/RHEL:**

```bash
sudo dnf install python3.11 python3-pip
```

**Arch Linux:**

```bash
sudo pacman -S python python-pip
```

#### macOS

**Option A: Homebrew (Recommended)**

```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.11

# Verify
python3 --version
```

**Option B: Official Installer**

1. Download from [python.org](https://www.python.org/downloads/macos/)
2. Run .pkg installer
3. Follow installation wizard

### Step 2: Install FFmpeg

FFmpeg is required for audio/video processing.

#### Windows

**Option A: Chocolatey (Recommended)**

```powershell
# Install Chocolatey if not present
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install FFmpeg
choco install ffmpeg
```

**Option B: Manual Installation**

1. Download from [ffmpeg.org](https://ffmpeg.org/download.html#build-windows)
2. Extract to `C:\ffmpeg`
3. Add to PATH:
   - Open "Environment Variables"
   - Edit "Path" variable
   - Add `C:\ffmpeg\bin`
4. Restart terminal

**Verify:**

```powershell
ffmpeg -version
```

#### Linux

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install ffmpeg
```

**Fedora:**

```bash
sudo dnf install ffmpeg
```

**Arch Linux:**

```bash
sudo pacman -S ffmpeg
```

**Verify:**

```bash
ffmpeg -version
```

#### macOS

```bash
# Using Homebrew
brew install ffmpeg

# Verify
ffmpeg -version
```

### Step 3: Clone Repository

```bash
# Using HTTPS
git clone https://github.com/yourusername/ia-transcriber-pro.git

# OR using SSH
git clone git@github.com:yourusername/ia-transcriber-pro.git

# Navigate to directory
cd ia-transcriber-pro
```

### Step 4: Create Virtual Environment

Virtual environments isolate project dependencies.

#### Windows

```powershell
# Create venv
python -m venv venv

# Activate
.\venv\Scripts\Activate.ps1

# If you get execution policy error:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

#### Linux/macOS

```bash
# Create venv
python3 -m venv venv

# Activate
source venv/bin/activate
```

**Verify Activation:**

Your prompt should show `(venv)` prefix:

```
(venv) C:\Users\YourName\ia-transcriber-pro>
```

### Step 5: Install Python Dependencies

```bash
# Upgrade pip first (recommended)
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# This will install:
# - PyTorch (with CUDA support if available)
# - Whisper / faster-whisper
# - PySide6 (GUI)
# - OpenCV, Pillow (image processing)
# - Other dependencies
```

**Installation may take 5-15 minutes** depending on your internet connection.

---

## 🎮 GPU Setup (CUDA)

For maximum performance with NVIDIA GPUs, install CUDA support.

### Check GPU Compatibility

```python
# Run this Python script to check
python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('CUDA Version:', torch.version.cuda if torch.cuda.is_available() else 'N/A')"
```

### Install CUDA Toolkit

#### Windows

**Option A: NVIDIA Installer (Recommended)**

1. Visit [NVIDIA CUDA Downloads](https://developer.nvidia.com/cuda-downloads)
2. Select:
   - Operating System: Windows
   - Architecture: x86_64
   - Version: 10/11
   - Installer Type: exe (network)
3. Download and run installer
4. Follow installation wizard
5. Restart computer

**Option B: Conda (Alternative)**

```bash
conda install pytorch torchvision torchaudio pytorch-cuda=11.8 -c pytorch -c nvidia
```

#### Linux

**Ubuntu/Debian:**

```bash
# Add NVIDIA repository
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update

# Install CUDA
sudo apt-get install cuda-toolkit-11-8

# Add to PATH (add to ~/.bashrc)
export PATH=/usr/local/cuda-11.8/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH

# Reload
source ~/.bashrc
```

**Verify CUDA:**

```bash
nvcc --version
nvidia-smi
```

### Install PyTorch with CUDA

If `requirements.txt` installed CPU-only PyTorch, reinstall with CUDA:

```bash
# Uninstall CPU version
pip uninstall torch torchvision torchaudio

# Install CUDA 11.8 version
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# OR CUDA 12.1 version
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Verify GPU Support:**

```python
python -c "import torch; print('GPU Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU'); print('CUDA Available:', torch.cuda.is_available())"
```

Expected output:

```
GPU Name: NVIDIA GeForce RTX 3060
CUDA Available: True
```

---

## 🎬 First Run

### Launch Application

```bash
# Ensure virtual environment is activated
# You should see (venv) in your prompt

python main.py
```

**What happens on first run:**

1. ✅ Configuration files created in `~/.transcriberpro/`
2. ✅ Log directory created
3. ✅ Whisper model downloaded (2-6 GB depending on size)
4. ✅ GUI window appears

### Download Whisper Models

Models are downloaded automatically on first use, but you can pre-download:

```bash
# Via Python
python -c "import whisper; whisper.load_model('base')"
python -c "import whisper; whisper.load_model('medium')"

# Models are cached in:
# Windows: C:\Users\YourName\.cache\whisper
# Linux/Mac: ~/.cache/whisper
```

**Model Sizes:**

| Model | Size | VRAM | Speed | Quality |
|-------|------|------|-------|---------|
| tiny | 75 MB | 1 GB | ~32x | Basic |
| base | 142 MB | 1 GB | ~16x | Good |
| small | 466 MB | 2 GB | ~6x | Better |
| medium | 1.5 GB | 5 GB | ~2x | Great |
| large-v2 | 2.9 GB | 10 GB | ~1x | Excellent |
| large-v3 | 2.9 GB | 10 GB | ~1x | Best |

### Test Transcription

1. Click **"Open Video"** button
2. Select a short video/audio file (1-2 minutes recommended for first test)
3. Choose model (start with **medium** for balance)
4. Click **"Start Transcription"**
5. Wait for completion
6. Check output in same folder as input file

---

## ⚙️ Configuration

### Configuration File Location

- **Windows**: `C:\Users\YourName\.transcriberpro\config\settings.json`
- **Linux/Mac**: `~/.transcriberpro/config/settings.json`

### Basic Configuration

Edit `settings.json`:

```json
{
  "transcription": {
    "model": "medium",
    "device": "cuda",
    "language": "auto",
    "task": "transcribe",
    "vad_enabled": true,
    "adaptive_batch": {
      "enabled": true,
      "initial_size": "auto"
    }
  },
  "output": {
    "format": "srt",
    "directory": "auto",
    "overwrite": false
  },
  "opensubtitles": {
    "enabled": false,
    "username": "",
    "password": "",
    "user_agent": ""
  }
}
```

### Key Settings

| Setting | Options | Description |
|---------|---------|-------------|
| `model` | tiny, base, small, medium, large-v2, large-v3 | Whisper model size |
| `device` | cuda, cpu, auto | Processing device |
| `language` | auto, en, it, es, fr, etc. | Source language (auto = detect) |
| `task` | transcribe, translate | Transcribe or translate to English |
| `vad_enabled` | true, false | Voice Activity Detection |

### Recommended Settings

**For Speed:**
```json
{
  "model": "small",
  "device": "cuda",
  "vad_enabled": true,
  "adaptive_batch": {"enabled": true}
}
```

**For Quality:**
```json
{
  "model": "large-v3",
  "device": "cuda",
  "vad_enabled": true,
  "adaptive_batch": {"enabled": true}
}
```

**For CPU (No GPU):**
```json
{
  "model": "base",
  "device": "cpu",
  "vad_enabled": true,
  "adaptive_batch": {"enabled": false}
}
```

---

## 🔧 Troubleshooting

### Common Issues

#### 1. "Python is not recognized as an internal or external command"

**Problem:** Python not in PATH

**Solution (Windows):**

```powershell
# Find Python location
where python

# Add to PATH manually:
# 1. Win+R → sysdm.cpl → Advanced → Environment Variables
# 2. Edit "Path"
# 3. Add Python directory (e.g., C:\Users\YourName\AppData\Local\Programs\Python\Python311)
```

#### 2. "No module named 'torch'"

**Problem:** Dependencies not installed or wrong venv

**Solution:**

```bash
# Ensure venv is activated (should see (venv) in prompt)
# Windows:
.\venv\Scripts\Activate.ps1

# Linux/Mac:
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

#### 3. "CUDA out of memory"

**Problem:** GPU VRAM exhausted

**Solutions:**

```json
// Option 1: Reduce batch size
{
  "adaptive_batch": {
    "enabled": true,
    "max_size": 8
  }
}

// Option 2: Use smaller model
{
  "model": "medium"  // instead of large
}

// Option 3: Use CPU
{
  "device": "cpu"
}
```

#### 4. "FFmpeg not found"

**Problem:** FFmpeg not installed or not in PATH

**Solution:**

```bash
# Test FFmpeg
ffmpeg -version

# If error, reinstall:
# Windows: choco install ffmpeg
# Linux: sudo apt install ffmpeg
# Mac: brew install ffmpeg
```

#### 5. Application crashes on startup

**Problem:** Corrupted configuration or incompatible dependencies

**Solution:**

```bash
# Delete configuration
# Windows:
Remove-Item -Recurse -Force "$env:USERPROFILE\.transcriberpro"

# Linux/Mac:
rm -rf ~/.transcriberpro

# Reinstall dependencies
pip uninstall -r requirements.txt -y
pip install -r requirements.txt

# Restart application
python main.py
```

#### 6. Slow transcription even with GPU

**Problem:** Using CPU instead of GPU

**Check:**

```python
python -c "import torch; print('Using GPU:', torch.cuda.is_available())"
```

**If False:**

1. Verify CUDA installation: `nvidia-smi`
2. Reinstall PyTorch with CUDA: 
   ```bash
   pip uninstall torch
   pip install torch --index-url https://download.pytorch.org/whl/cu118
   ```
3. Check settings.json: `"device": "cuda"` not `"cpu"`

#### 7. "Permission denied" errors

**Linux/Mac:**

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Or run with sudo if needed
sudo python main.py
```

**Windows:**

Run PowerShell/CMD as Administrator

#### 8. GUI doesn't appear

**Problem:** Display/Qt issues

**Solution:**

```bash
# Reinstall GUI dependencies
pip uninstall PySide6
pip install PySide6

# Try running in compatibility mode (Windows)
# Right-click main.py → Properties → Compatibility → Run as admin
```

### Debug Mode

Enable detailed logging:

```bash
# Set environment variable
# Windows:
$env:TRANSCRIBER_DEBUG=1
python main.py

# Linux/Mac:
TRANSCRIBER_DEBUG=1 python main.py
```

Logs saved to: `~/.transcriberpro/logs/`

### Getting Help

1. **Check Logs**: `~/.transcriberpro/logs/transcriber_YYYYMMDD_HHMMSS.log`
2. **GitHub Issues**: [github.com/yourrepo/issues](https://github.com/)
3. **Documentation**: Check `docs/` folder
4. **Community**: Join Discord/Forum (link in README)

---

## 🚀 Optional Optimizations

### 1. Install faster-whisper

For 2-4x faster transcription:

```bash
pip install faster-whisper
```

Application will automatically use it if available.

### 2. NVIDIA cuDNN (for even faster performance)

1. Download from [NVIDIA cuDNN](https://developer.nvidia.com/cudnn)
2. Extract to CUDA directory
3. Restart application

### 3. Optimize Windows for Performance

```powershell
# Disable Windows Defender real-time scanning for project folder
Add-MpPreference -ExclusionPath "C:\path\to\ia-transcriber-pro"

# Set power plan to High Performance
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
```

### 4. Linux Performance Tweaks

```bash
# Increase file descriptor limit
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Disable CPU throttling
sudo cpupower frequency-set -g performance
```

### 5. Use SSD for Cache

Move Whisper cache to SSD for faster model loading:

```bash
# Windows:
$env:WHISPER_CACHE_DIR="D:\whisper_cache"  # Replace D: with your SSD

# Linux/Mac:
export WHISPER_CACHE_DIR="/path/to/ssd/whisper_cache"
# Add to ~/.bashrc or ~/.zshrc for persistence
```

---

## 🔄 Upgrading

### Update Application

```bash
# Navigate to project directory
cd ia-transcriber-pro

# Pull latest changes
git pull origin main

# Activate virtual environment
# Windows:
.\venv\Scripts\Activate.ps1
# Linux/Mac:
source venv/bin/activate

# Update dependencies
pip install --upgrade -r requirements.txt

# Run application
python main.py
```

### Update Python Packages Only

```bash
pip install --upgrade -r requirements.txt
```

### Major Version Upgrade

For major releases, clean installation recommended:

```bash
# Backup your settings
# Windows:
Copy-Item -Recurse "$env:USERPROFILE\.transcriberpro" "$env:USERPROFILE\.transcriberpro_backup"

# Linux/Mac:
cp -r ~/.transcriberpro ~/.transcriberpro_backup

# Delete old installation
cd ..
Remove-Item -Recurse -Force ia-transcriber-pro  # Windows
# rm -rf ia-transcriber-pro  # Linux/Mac

# Fresh install (follow installation steps)
git clone https://github.com/yourusername/ia-transcriber-pro.git
cd ia-transcriber-pro
python -m venv venv
# ... continue installation steps
```

---

## 📝 Post-Installation Checklist

- [ ] Python 3.10+ installed and in PATH
- [ ] FFmpeg installed and working (`ffmpeg -version`)
- [ ] Git installed (optional, for updates)
- [ ] CUDA Toolkit installed (for GPU support)
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip list` shows all packages)
- [ ] GPU detected (if applicable): `torch.cuda.is_available() == True`
- [ ] Configuration file created at `~/.transcriberpro/config/settings.json`
- [ ] Whisper model downloaded (at least `base` or `medium`)
- [ ] Test transcription completed successfully
- [ ] Logs directory exists and is writable
- [ ] (Optional) OpenSubtitles credentials configured

---

## 🎉 You're Ready!

Congratulations! IA Transcriber Pro is now installed and ready to use.

### Next Steps

1. **Read Documentation**
   - [Adaptive Batch Size Guide](ADAPTIVE_BATCH_README_EN.md)
   - [OpenSubtitles Integration](OPENSUBTITLES_README_EN.md)

2. **Try Your First Transcription**
   - Start with a short video (2-5 minutes)
   - Use `medium` model for balance
   - Check quality of output

3. **Optimize Settings**
   - Adjust batch size for your GPU
   - Enable/disable VAD based on your needs
   - Configure output format preferences

4. **Join Community**
   - Report bugs on GitHub
   - Share feedback
   - Request features

---

## 📞 Support

- **Documentation**: Check `docs/` folder
- **Issues**: [GitHub Issues](https://github.com/yourrepo/issues)
- **Email**: support@example.com
- **Discord**: [Join Server](https://discord.gg/example)

---

**Version**: 1.0.0  
**Last Updated**: October 2025  
**License**: MIT

---

**Happy Transcribing! 🎬✨**
