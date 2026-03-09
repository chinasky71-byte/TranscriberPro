# 🛠️ Transcriber Pro - Guida Installazione Dettagliata

> **Versione:** 1.0  
> **OS Supportati:** Windows 10/11, Ubuntu 20.04+, Debian 11+, Fedora 35+  
> **Tempo stimato:** 15-30 minuti

---

## 📑 Indice

- [Prerequisiti](#prerequisiti)
- [Installazione Windows](#installazione-windows)
- [Installazione Linux](#installazione-linux)
- [Configurazione Post-Installazione](#configurazione-post-installazione)
- [Verifica Installazione](#verifica-installazione)
- [Abilitazione Features Opzionali](#abilitazione-features-opzionali)
- [Troubleshooting Installazione](#troubleshooting-installazione)

---

## 📋 Prerequisiti

### Hardware Raccomandato

| Componente | Minimo | Raccomandato | Ottimale |
|------------|--------|--------------|----------|
| **CPU** | Intel i5-8400 / Ryzen 5 2600 | Intel i7-12700KF / Ryzen 7 5800X | Intel i9-13900K / Ryzen 9 7950X |
| **RAM** | 8 GB | 12 GB | 16-32 GB |
| **GPU** | GTX 1060 6GB | RTX 3060 12GB | RTX 4090 24GB |
| **Storage** | 10 GB HDD | 50 GB SSD | 100+ GB NVMe |

### Software Base

#### Windows

- **OS:** Windows 10 (build 19041+) o Windows 11
- **Python:** 3.8, 3.9, 3.10 o 3.11 ([Download](https://www.python.org/downloads/))
- **CUDA Toolkit:** 11.8 o 12.1 (solo per GPU NVIDIA) ([Download](https://developer.nvidia.com/cuda-downloads))
- **Driver GPU:** Aggiornati all'ultima versione ([NVIDIA](https://www.nvidia.com/Download/index.aspx))

#### Linux

- **OS:** Ubuntu 20.04+, Debian 11+, Fedora 35+
- **Python:** 3.8-3.11
- **CUDA Toolkit:** 11.8+ (solo per GPU NVIDIA)
- **Build essentials:** gcc, g++, make

### Verifica Prerequisiti

**Python:**
```bash
python --version
# Output atteso: Python 3.8.x - 3.11.x
```

**CUDA (opzionale, solo GPU NVIDIA):**
```bash
nvcc --version
# Output atteso: release 11.8 o superiore
```

**Driver GPU:**
```bash
nvidia-smi
# Output atteso: info GPU, driver version, CUDA version
```

---

## 💻 Installazione Windows

### Opzione 1: Installazione Automatica (Raccomandata)

**1. Scarica il Progetto**

```powershell
# Metodo A: Git (se installato)
git clone https://github.com/yourusername/transcriber-pro.git
cd transcriber-pro

# Metodo B: Download ZIP
# 1. Vai su: https://github.com/yourusername/transcriber-pro
# 2. Click "Code" → "Download ZIP"
# 3. Estrai in C:\transcriber-pro
# 4. Apri PowerShell nella cartella
```

**2. Esegui Script Automatico**

```batch
# Doppio click su:
setup_windows.bat

# Oppure da CMD/PowerShell:
.\setup_windows.bat
```

**3. Segui le Istruzioni**

Lo script automaticamente:
- ✅ Verifica Python
- ✅ Rileva GPU NVIDIA
- ✅ Crea virtual environment
- ✅ Installa PyTorch (CPU o CUDA)
- ✅ Installa tutte le dipendenze
- ✅ Configura directories

**4. Fine!**

Al termine vedrai:
```
============================================================================
                INSTALLAZIONE COMPLETATA!
============================================================================

Transcriber Pro è pronto per l'uso!

AVVIO APPLICAZIONE:
   - Doppio click su: Lancia Transcriptor.bat
   - Oppure: python main.py
```

### Opzione 2: Installazione Manuale

**1. Installa Python**

- Scarica da [python.org](https://www.python.org/downloads/)
- **IMPORTANTE:** Durante installazione, ✅ seleziona "Add Python to PATH"
- Verifica: `python --version`

**2. Installa CUDA Toolkit (solo GPU)**

- Scarica da [NVIDIA CUDA](https://developer.nvidia.com/cuda-downloads)
- Versione raccomandata: 11.8 o 12.1
- Installa con opzioni di default
- Verifica: `nvcc --version`

**3. Crea Virtual Environment**

```powershell
cd C:\path\to\transcriber-pro
python -m venv venv
```

**4. Attiva Virtual Environment**

```powershell
# PowerShell
.\venv\Scripts\Activate.ps1

# CMD
.\venv\Scripts\activate.bat

# Vedrai (venv) nel prompt
```

**5. Installa PyTorch**

```powershell
# Con GPU NVIDIA (CUDA 11.8)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Senza GPU (CPU-only)
pip install torch torchvision torchaudio
```

**6. Installa Dipendenze**

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

**7. Crea Directory Config**

```powershell
mkdir %USERPROFILE%\.transcriberpro
```

---

## 🐧 Installazione Linux

### Opzione 1: Installazione Automatica (Raccomandata)

**1. Scarica il Progetto**

```bash
# Git clone
git clone https://github.com/yourusername/transcriber-pro.git
cd transcriber-pro
```

**2. Rendi Eseguibile lo Script**

```bash
chmod +x setup_linux.sh
```

**3. Esegui Script Automatico**

```bash
./setup_linux.sh
```

Lo script installerà automaticamente:
- ✅ Dipendenze sistema (ffmpeg, build-essential, etc.)
- ✅ Virtual environment Python
- ✅ PyTorch (GPU o CPU)
- ✅ Tutte le dipendenze progetto
- ✅ Configurazione directories

**4. Fine!**

Al termine:
```
============================================================================
                INSTALLAZIONE COMPLETATA!
============================================================================

AVVIO APPLICAZIONE:
   ./run_transcriber.sh
   
   oppure:
   source venv/bin/activate && python main.py
```

### Opzione 2: Installazione Manuale

#### Ubuntu/Debian

**1. Installa Dipendenze Sistema**

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    ffmpeg \
    libsndfile1 \
    portaudio19-dev \
    build-essential \
    git
```

**2. Installa CUDA Toolkit (solo GPU)**

```bash
# Ubuntu 22.04 - CUDA 11.8
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-11-8

# Aggiungi a PATH
echo 'export PATH=/usr/local/cuda-11.8/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

**3. Crea Virtual Environment**

```bash
cd ~/transcriber-pro
python3 -m venv venv
source venv/bin/activate
```

**4. Installa PyTorch**

```bash
# Con GPU (CUDA 11.8)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# CPU-only
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**5. Installa Dipendenze**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**6. Crea Directory Config**

```bash
mkdir -p ~/.transcriberpro
```

#### Fedora/RHEL

**1. Installa Dipendenze Sistema**

```bash
sudo dnf install -y \
    python3 \
    python3-pip \
    python3-devel \
    ffmpeg \
    libsndfile \
    portaudio-devel \
    gcc \
    gcc-c++ \
    git
```

**2-6. Come Ubuntu** (usa gli stessi comandi Python/pip)

---

## ⚙️ Configurazione Post-Installazione

### 1. Configurazione Base

Il file `~/.transcriberpro/config.json` viene creato automaticamente.

**Modifica (opzionale):**

```bash
# Windows
notepad %USERPROFILE%\.transcriberpro\config.json

# Linux
nano ~/.transcriberpro/config.json
```

**Contenuto di default:**
```json
{
  "use_gpu": true,
  "language": "auto",
  "shutdown_after_processing": false,
  "opensubtitles": {
    "upload_enabled": false,
    "auto_upload": false,
    "check_duplicates": true
  }
}
```

### 2. TMDB API Key (Opzionale - Raccomandata)

**Perché serve:**
- ✅ Metadata automatici film/serie
- ✅ IMDb ID per upload OpenSubtitles
- ✅ Matching intelligente titoli

**Setup:**

1. **Registrati su TMDB**
   - Vai su: [themoviedb.org/signup](https://www.themoviedb.org/signup)
   - Crea account gratuito

2. **Richiedi API Key**
   - Vai su: [Settings → API](https://www.themoviedb.org/settings/api)
   - Click "Request an API Key"
   - Seleziona "Developer"
   - Compila form (descrizione: "Personal use - Transcriber Pro")

3. **Salva API Key**

   **Windows:**
   ```powershell
   echo "your_api_key_here" > %USERPROFILE%\.transcriberpro\tmdb_api_key.txt
   ```

   **Linux:**
   ```bash
   echo "your_api_key_here" > ~/.transcriberpro/tmdb_api_key.txt
   ```

4. **Riavvia applicazione**

### 3. OpenSubtitles Credentials (Opzionale)

**Solo se vuoi upload automatico su OpenSubtitles.org**

**Setup:**

1. **Registrati su OpenSubtitles**
   - Vai su: [opensubtitles.org/en/newuser](https://www.opensubtitles.org/en/newuser)
   - Crea account gratuito
   - **Nota:** Usa password diversa da altri servizi (API usa MD5 legacy)

2. **Crea File Credenziali**

   **Windows:**
   ```powershell
   notepad %USERPROFILE%\.transcriberpro\opensubtitles_credentials.json
   ```

   **Linux:**
   ```bash
   nano ~/.transcriberpro/opensubtitles_credentials.json
   ```

3. **Inserisci Credenziali**

   ```json
   {
     "username": "your_opensubtitles_username",
     "password": "your_opensubtitles_password",
     "auto_upload": false
   }
   ```

4. **Abilita Upload in Config**

   Modifica `config.json`:
   ```json
   {
     ...
     "opensubtitles": {
       "upload_enabled": true,
       "auto_upload": false,
       "check_duplicates": true
     }
   }
   ```

5. **Riavvia applicazione**

---

## ✅ Verifica Installazione

### Test Rapido

**1. Avvia Applicazione**

```bash
# Windows
python main.py

# Linux
./run_transcriber.sh
```

**2. Verifica Splash Screen**

Dovrebbe apparire uno splash screen "Transcriber Pro" per 2-3 secondi.

**3. Verifica Finestra Principale**

Dovrebbe aprirsi la GUI con:
- Pannello coda elaborazione (sinistra)
- Pannello anteprima (destra)
- Monitor risorse (basso)
- Controlli elaborazione (basso)

### Test Componenti

**Test PyQt6:**
```bash
python -c "from PyQt6.QtWidgets import QApplication; print('✓ PyQt6 OK')"
```

**Test PyTorch:**
```bash
python -c "import torch; print('✓ PyTorch version:', torch.__version__)"
```

**Test CUDA (se GPU):**
```bash
python -c "import torch; print('✓ CUDA available:', torch.cuda.is_available()); print('✓ GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

**Test Faster-Whisper:**
```bash
python -c "from faster_whisper import WhisperModel; print('✓ Faster-Whisper OK')"
```

**Test Transformers (NLLB):**
```bash
python -c "from transformers import AutoTokenizer; print('✓ Transformers OK')"
```

**Test Demucs:**
```bash
python -c "import demucs; print('✓ Demucs OK')"
```

### Test File Processing

**Test con video corto:**

1. Prepara un video di test (1-2 minuti)
2. Aggiungi alla coda
3. Avvia elaborazione
4. Verifica output `.it.srt`

**Log atteso:**
```
✓ Video caricato: test.mp4
✓ Rilevamento sottotitoli: 0 trovati
✓ Trascrizione avviata...
✓ Separazione vocale (Demucs)
✓ Chunking: 8 chunks creati
✓ Trascrizione Whisper: 8/8 chunks
✓ Pulizia sottotitoli
✓ Traduzione: eng → ita
✓ File salvato: test.it.srt
```

---

## 🎛️ Abilitazione Features Opzionali

### Feature 1: Upload OpenSubtitles

**Prerequisiti:**
- ✅ Account OpenSubtitles.org
- ✅ File `opensubtitles_credentials.json` configurato
- ✅ Connessione internet

**Test:**
```bash
# Windows
python scripts\verify_opensubtitles_setup.py

# Linux
python scripts/verify_opensubtitles_setup.py
```

**Output atteso:**
```
✓ Dipendenze Python OK
✓ Moduli Progetto OK
✓ Credenziali configurate
✓ Test Autenticazione OK
✓ TUTTO OK! Sistema pronto per upload
```

### Feature 2: Metadata TMDB

**Prerequisiti:**
- ✅ File `tmdb_api_key.txt` con API key valida
- ✅ Connessione internet

**Test:**
```bash
python -c "from utils.tmdb_client import get_tmdb_client; client = get_tmdb_client(); result = client.search_movie('Matrix', 1999); print('✓ TMDB OK:', result['title'] if result else 'API key non valida')"
```

### Feature 3: Accelerazione GPU

**Prerequisiti:**
- ✅ GPU NVIDIA
- ✅ Driver aggiornati
- ✅ CUDA Toolkit installato
- ✅ PyTorch con supporto CUDA

**Test:**
```bash
python -c "
import torch
if torch.cuda.is_available():
    print('✓ GPU:', torch.cuda.get_device_name(0))
    print('✓ VRAM:', torch.cuda.get_device_properties(0).total_memory // 1024**3, 'GB')
    print('✓ CUDA version:', torch.version.cuda)
else:
    print('✗ CUDA non disponibile')
"
```

---

## 🔧 Troubleshooting Installazione

### Problema: Python non trovato

**Windows:**
```powershell
# Verifica installazione
where python

# Se non trova:
# 1. Reinstalla Python da python.org
# 2. Seleziona "Add Python to PATH"
# 3. Riavvia CMD/PowerShell
```

**Linux:**
```bash
# Verifica installazione
which python3

# Se non trova:
sudo apt install python3  # Ubuntu/Debian
sudo dnf install python3  # Fedora
```

### Problema: pip non funziona

**Soluzione:**
```bash
# Upgrade pip
python -m pip install --upgrade pip

# Se pip non installato:
python -m ensurepip --upgrade

# Linux: usa pip3
pip3 install --upgrade pip
```

### Problema: "ERROR: Could not build wheels for..."

**Causa:** Mancano build tools

**Windows:**
- Installa [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
- Seleziona "Desktop development with C++"

**Linux:**
```bash
# Ubuntu/Debian
sudo apt install build-essential python3-dev

# Fedora
sudo dnf install gcc gcc-c++ python3-devel
```

### Problema: PyTorch non rileva GPU

**Checklist:**

1. **Driver NVIDIA aggiornati?**
   ```bash
   nvidia-smi
   ```
   Se errore, aggiorna driver da [nvidia.com](https://www.nvidia.com/Download/index.aspx)

2. **CUDA Toolkit installato?**
   ```bash
   nvcc --version
   ```
   Se errore, installa CUDA Toolkit 11.8+

3. **PyTorch compilato per CUDA?**
   ```bash
   python -c "import torch; print(torch.version.cuda)"
   ```
   Se `None`, reinstalla PyTorch:
   ```bash
   pip uninstall torch torchvision torchaudio
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
   ```

### Problema: "ModuleNotFoundError: No module named 'PyQt6'"

**Causa:** Virtual environment non attivo

**Soluzione:**
```bash
# Windows
.\venv\Scripts\activate

# Linux
source venv/bin/activate

# Poi reinstalla
pip install -r requirements.txt
```

### Problema: FFmpeg non trovato

**Windows:**
```powershell
# Verifica PATH
where ffmpeg

# Se non trova:
# 1. Download da: https://www.gyan.dev/ffmpeg/builds/
# 2. Estrai in C:\ffmpeg
# 3. Aggiungi C:\ffmpeg\bin al PATH di sistema
# 4. Riavvia CMD
```

**Linux:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Verifica
ffmpeg -version
```

### Problema: Errore "Permission denied"

**Linux:**
```bash
# Script non eseguibile
chmod +x setup_linux.sh
chmod +x run_transcriber.sh

# Directory senza permessi
sudo chown -R $USER:$USER ~/.transcriberpro
chmod -R 755 ~/.transcriberpro
```

**Windows:**
```powershell
# Esegui PowerShell come Amministratore
# Abilita esecuzione script
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Problema: Installazione lentissima

**Causa:** Download modelli AI grandi (10+ GB)

**Soluzioni:**
1. **Usa connessione stabile** (no Wi-Fi debole)
2. **Aumenta timeout pip:**
   ```bash
   pip install --timeout=1000 -r requirements.txt
   ```
3. **Installa in più step:**
   ```bash
   pip install torch torchvision torchaudio
   pip install transformers
   pip install demucs
   pip install faster-whisper
   pip install -r requirements.txt
   ```

---

## 📞 Supporto Installazione

**Se i problemi persistono:**

1. **Controlla Log:**
   ```bash
   # Cerca errori specifici in:
   %USERPROFILE%\.transcriberpro\logs\  # Windows
   ~/.transcriberpro/logs/               # Linux
   ```

2. **Crea Issue GitHub:**
   - Vai su: [GitHub Issues](https://github.com/yourusername/transcriber-pro/issues)
   - Include:
     - OS e versione
     - Output di `python --version`
     - Output di `pip list`
     - Log errore completo

3. **Community Support:**
   - [GitHub Discussions](https://github.com/yourusername/transcriber-pro/discussions)
   - Tag: `installation`, `windows` o `linux`

---

## ✨ Installazione Completata!

**Prossimi passi:**

1. ✅ [Leggi la Guida Utente](GUIDA_UTENTE.md)
2. ✅ Configura TMDB API (opzionale)
3. ✅ Configura OpenSubtitles (opzionale)
4. ✅ Testa con un video corto
5. ✅ Enjoy! 🎬

---

<div align="center">

**Benvenuto in Transcriber Pro! 🚀**

</div>
