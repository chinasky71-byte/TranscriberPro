# 🔧 Troubleshooting - Risoluzione Problemi Comuni

> **Versione:** 1.0  
> **Ultima modifica:** Ottobre 2025

---

## 📑 Indice

- [Problemi di Installazione](#problemi-di-installazione)
- [Problemi GPU/CUDA](#problemi-gpucuda)
- [Problemi di Elaborazione](#problemi-di-elaborazione)
- [Problemi di Qualità Output](#problemi-di-qualità-output)
- [Problemi OpenSubtitles](#problemi-opensubtitles)
- [Problemi Performance](#problemi-performance)
- [Errori Comuni](#errori-comuni)

---

## 🛠️ Problemi di Installazione

### ❌ Errore: "Python non trovato"

**Sintomo:**
```
'python' is not recognized as an internal or external command
```

**Causa:** Python non in PATH di sistema

**Soluzione Windows:**
1. Reinstalla Python da [python.org](https://www.python.org/downloads/)
2. ✅ **IMPORTANTE:** Seleziona "Add Python to PATH" durante installazione
3. Riavvia terminale/PowerShell
4. Verifica: `python --version`

**Soluzione Linux:**
```bash
# Usa python3
python3 --version

# Crea alias (opzionale)
echo "alias python=python3" >> ~/.bashrc
source ~/.bashrc
```

---

### ❌ Errore: "No module named 'PyQt6'"

**Sintomo:**
```python
ModuleNotFoundError: No module named 'PyQt6'
```

**Causa:** Virtual environment non attivo o dipendenze non installate

**Soluzione:**

**Windows:**
```powershell
# 1. Attiva venv
.\venv\Scripts\activate

# 2. Verifica venv attivo (vedrai "(venv)" nel prompt)
# 3. Reinstalla dipendenze
pip install -r requirements.txt
```

**Linux:**
```bash
# 1. Attiva venv
source venv/bin/activate

# 2. Reinstalla dipendenze
pip install -r requirements.txt
```

---

### ❌ Errore: "Could not build wheels for..."

**Sintomo:**
```
ERROR: Could not build wheels for numpy/soundfile/...
```

**Causa:** Mancano compilatori C/C++

**Soluzione Windows:**
1. Installa [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
2. Durante installazione, seleziona: **"Desktop development with C++"**
3. Riavvia sistema
4. Riprova installazione

**Soluzione Linux:**
```bash
# Ubuntu/Debian
sudo apt install build-essential python3-dev

# Fedora/RHEL
sudo dnf groupinstall "Development Tools"
sudo dnf install python3-devel
```

---

## 🎮 Problemi GPU/CUDA

### ❌ GPU non rilevata (CUDA not available)

**Sintomo:**
```python
>>> import torch
>>> torch.cuda.is_available()
False  # ❌ Dovrebbe essere True
```

**Diagnosi completa:**

```python
import torch

print("PyTorch version:", torch.__version__)
print("CUDA compiled:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print("VRAM:", torch.cuda.get_device_properties(0).total_memory // 1024**3, "GB")
```

**Possibili cause e soluzioni:**

#### 1️⃣ Driver NVIDIA non installato/obsoleto

**Verifica:**
```bash
nvidia-smi
```

**Soluzione:**
- Aggiorna driver da [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx)
- Versione minima raccomandata: 520.xx+

#### 2️⃣ CUDA Toolkit non installato

**Verifica:**
```bash
nvcc --version
```

**Soluzione:**
- Installa CUDA Toolkit 11.8 o 12.1
- [Download CUDA](https://developer.nvidia.com/cuda-downloads)

#### 3️⃣ PyTorch installato senza CUDA

**Verifica:**
```python
import torch
print(torch.version.cuda)  # Se None → PyTorch CPU-only
```

**Soluzione:**
```bash
# Disinstalla PyTorch CPU
pip uninstall torch torchvision torchaudio

# Reinstalla con CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

#### 4️⃣ Versione CUDA mismatch

**Verifica compatibilità:**
```bash
# CUDA Toolkit installato
nvcc --version

# CUDA supportato da PyTorch
python -c "import torch; print(torch.version.cuda)"

# Driver CUDA version
nvidia-smi  # Guarda "CUDA Version" in alto a destra
```

**Regola:** PyTorch CUDA version ≤ Driver CUDA version

**Soluzione:** Installa PyTorch compatibile con il tuo CUDA Toolkit

---

### ❌ Errore: "CUDA out of memory"

**Sintomo:**
```
RuntimeError: CUDA out of memory. Tried to allocate X.XX GiB
```

**Soluzioni immediate:**

1. **Chiudi altre applicazioni GPU:**
   ```bash
   # Verifica processi GPU
   nvidia-smi
   
   # Chiudi browser, giochi, altre app AI
   ```

2. **Riduci batch size:**
   
   Modifica `core/translator.py`:
   ```python
   # Prima
   self.batch_size = 8
   
   # Dopo (per GPU 6-8GB)
   self.batch_size = 4
   ```

3. **Usa modalità CPU fallback:**
   
   Modifica `config.json`:
   ```json
   {
     "use_gpu": false
   }
   ```

4. **Upgrade GPU o RAM:**
   - GPU minima raccomandata: RTX 3060 12GB
   - Alternative: RTX 4060 Ti 16GB, RTX 4080

---

## 🎬 Problemi di Elaborazione

### ❌ Video non elaborato (stuck/frozen)

**Sintomo:**
- Progresso bloccato al X%
- Log mostra ultimo messaggio da minuti/ore
- Applicazione non risponde

**Diagnosi:**

1. **Controlla log dettagliato:**
   ```
   Windows: %USERPROFILE%\.transcriberpro\logs\transcriber.log
   Linux: ~/.transcriberpro/logs/transcriber.log
   ```

2. **Controlla risorse:**
   - RAM piena? (Chiudi altre app)
   - Disco pieno? (Libera spazio)
   - GPU OOM? (Vedi sezione CUDA)

**Soluzioni:**

#### Caso 1: File video corrotto

**Verifica:**
```bash
# Testa con VLC
vlc video.mp4

# Verifica integrità FFmpeg
ffmpeg -v error -i video.mp4 -f null -
```

**Soluzione:**
- Ri-scarica il video
- Converti in formato stabile: `ffmpeg -i input.mkv -c copy output.mp4`

#### Caso 2: Formato non supportato

**Verifica codec:**
```bash
ffprobe -v error -show_entries stream=codec_name -of default=noprint_wrappers=1 video.mp4
```

**Soluzione:**
```bash
# Converti in H.264 + AAC (universale)
ffmpeg -i input.mkv -c:v libx264 -c:a aac output.mp4
```

#### Caso 3: File troppo grande

**Sintomo:** Video >50GB si blocca

**Soluzione:**
```bash
# Riduci dimensione mantenendo qualità
ffmpeg -i large_video.mkv -c:v libx265 -crf 23 -c:a copy smaller_video.mp4
```

---

### ❌ Elaborazione lentissima (molto più di 1x video duration)

**Sintomo:**
- Video 2h → 10+ ore di elaborazione
- GPU usage: 0-10% (dovrebbe essere 70-90%)

**Diagnosi:**

```python
# Test velocità GPU
python -c "
import torch
import time

if torch.cuda.is_available():
    device = 'cuda'
    x = torch.randn(10000, 10000).to(device)
    start = time.time()
    y = torch.matmul(x, x)
    torch.cuda.synchronize()
    print(f'GPU compute time: {time.time()-start:.2f}s')
    print('Expected: <1s. If >5s → problema GPU')
"
```

**Possibili cause:**

1. **CPU fallback attivo (no GPU)**
   - Verifica: `torch.cuda.is_available()` → deve essere `True`
   - Soluzione: Vedi sezione GPU/CUDA

2. **Thermal throttling GPU**
   ```bash
   # Monitora temperatura
   nvidia-smi -l 1
   
   # Se >85°C → problema raffreddamento
   ```
   Soluzione: Migliora ventilazione, pulisci polvere, riduci overclock

3. **Power limit GPU troppo basso**
   ```bash
   # Verifica power usage
   nvidia-smi --query-gpu=power.draw,power.limit --format=csv
   ```
   Soluzione: Aumenta power limit (MSI Afterburner / nvidia-smi)

---

## 📝 Problemi di Qualità Output

### ❌ Trascrizione imprecisa/sbagliata

**Sintomo:**
- Parole sbagliate
- Frasi senza senso
- Lingua rilevata male

**Soluzioni:**

#### 1. Audio di bassa qualità

**Verifica bitrate audio:**
```bash
ffprobe -v error -select_streams a:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 video.mp4
```

**Raccomandato:** ≥128 kbps

**Soluzione:**
- Usa fonte video migliore (BluRay > Web-DL > HDTV)
- Pre-processa audio:
  ```bash
  ffmpeg -i input.mp4 -vn -ar 16000 -ac 1 -ab 192k audio.wav
  ```

#### 2. Lingua non rilevata correttamente

**Esempio:** Audio italiano → trascritto come spagnolo

**Soluzione temporanea:**

Modifica `core/pipeline.py` (riga ~420):
```python
# Forza lingua manualmente
transcribe_lang = 'it'  # Invece di auto-detect
```

**Soluzione permanente (prossima versione):**
- GUI per selezione manuale lingua

#### 3. Musica/rumori coprono dialoghi

**Sintomo:** Demucs non separa bene voce da background

**Verifica separazione:**
- Controlla file temporaneo `*_vocals.wav` in temp folder
- Ascolta con VLC

**Soluzioni:**
- Aumento volume dialoghi pre-processing:
  ```bash
  ffmpeg -i input.mp4 -af "volume=2.0" louder.mp4
  ```
- Per casi estremi: usa software dedicated come iZotope RX

---

### ❌ Traduzione scadente

**Sintomo:**
- Traduzione letterale/robotica
- Context perso
- Nomi propri tradotti erroneamente

**Soluzioni:**

1. **Batch size troppo piccolo** (perde contesto)
   
   Modifica `core/translator.py`:
   ```python
   self.batch_size = 12  # Aumenta da 6 a 12 (se hai VRAM)
   ```

2. **Modello NLLB troppo piccolo**
   
   Modifica `core/translator.py`:
   ```python
   # Cambia modello (richiede più VRAM)
   model_name = "facebook/nllb-200-3.3B"  # Migliore qualità
   ```

3. **Post-editing manuale**
   - Per sottotitoli critici, revisiona output `.srt`
   - Tool consigliato: [Subtitle Edit](https://www.nikse.dk/subtitleedit)

---

## ☁️ Problemi OpenSubtitles

### ❌ Upload fallisce: "Authentication failed"

**Sintomo:**
```
ERROR: OpenSubtitles authentication failed
```

**Soluzioni:**

1. **Credenziali errate**
   
   Verifica file: `~/.transcriberpro/opensubtitles_credentials.json`
   ```json
   {
     "username": "correct_username",
     "password": "correct_password"
   }
   ```

2. **Account non attivo**
   - Login su [opensubtitles.org](https://www.opensubtitles.org)
   - Conferma email se non fatto

3. **IP bannato (troppi tentativi)**
   - Attendi 15-30 minuti
   - Usa VPN se problema persiste

---

### ❌ Upload fallisce: "Duplicate subtitle"

**Sintomo:**
```
WARNING: Subtitle already exists in database
```

**Causa:** Sottotitolo già presente (stesso hash video)

**Comportamento corretto:** Il software DEVE skippare upload duplicati

**Soluzione:** 
- Se vuoi forzare upload, modifica leggermente il file video (ri-encode)
- Oppure modifica `.srt` manualmente prima di upload

---

### ❌ Nessun IMDb ID trovato

**Sintomo:**
```
WARNING: No IMDb ID found for video
```

**Causa:** TMDB non trova il film/serie

**Soluzioni:**

1. **Rinomina file correttamente:**
   ```
   GIUSTO:
   The.Matrix.1999.1080p.BluRay.mkv
   Breaking.Bad.S01E01.720p.WEB-DL.mkv
   
   SBAGLIATO:
   movie.mkv
   video1.avi
   ```

2. **Aggiungi TMDB API key** (se non fatto):
   - Crea: `~/.transcriberpro/tmdb_api_key.txt`
   - Ottieni key: [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)

3. **Ricerca manuale IMDb ID:**
   - Cerca su [imdb.com](https://www.imdb.com)
   - Copia ID dalla URL (es: `tt0133093`)
   - Modifica `core/pipeline.py` temporaneamente per forzarlo

---

## ⚡ Problemi Performance

### ❌ RAM piena (sistema lento/crash)

**Sintomo:**
- Sistema lentissimo
- App crashano
- Errore: "MemoryError"

**Diagnosi:**
```python
# Monitor RAM real-time
python -c "
import psutil
import time
while True:
    ram = psutil.virtual_memory()
    print(f'RAM: {ram.percent}% ({ram.used//1024**3}/{ram.total//1024**3} GB)')
    time.sleep(2)
"
```

**Soluzioni:**

1. **Chiudi applicazioni non essenziali**
   - Browser (Chrome/Firefox mangiano RAM)
   - Altri software pesanti

2. **Processa video più corti**
   - Split video lunghi:
     ```bash
     ffmpeg -i long_video.mp4 -t 3600 -c copy part1.mp4
     ffmpeg -i long_video.mp4 -ss 3600 -c copy part2.mp4
     ```

3. **Aumenta RAM fisica**
   - Minimo: 12 GB
   - Raccomandato: 16-32 GB

---

### ❌ Disco pieno durante elaborazione

**Sintomo:**
```
OSError: [Errno 28] No space left on device
```

**Causa:** File temporanei Demucs/Whisper occupano molto spazio

**Spazio richiesto:** ~3-5x dimensione video

**Soluzioni:**

1. **Libera spazio disco:**
   ```bash
   # Elimina file temp vecchi
   Windows: del /q %TEMP%\*
   Linux: rm -rf /tmp/*
   
   # Pulisci cache Python
   pip cache purge
   ```

2. **Cambia directory temp** (su disco più capiente):
   
   Modifica `utils/file_handler.py`:
   ```python
   TEMP_DIR = Path("D:/transcriber_temp")  # Disco con più spazio
   ```

3. **Cleanup automatico dopo elaborazione:**
   - Già implementato, ma verifica in `core/pipeline.py`

---

## ❗ Errori Comuni

### 🔴 "AttributeError: module 'torch' has no attribute 'cuda'"

**Causa:** PyTorch CPU installato invece di CUDA

**Soluzione:**
```bash
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

---

### 🔴 "ImportError: DLL load failed while importing ..."

**Causa Windows:** Visual C++ Redistributable mancante

**Soluzione:**
- Installa [VC++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
- Versioni: 2015-2022 (x64)

---

### 🔴 "ffmpeg: command not found"

**Soluzione Windows:**
1. Download: [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/)
2. Estrai in `C:\ffmpeg`
3. Aggiungi `C:\ffmpeg\bin` al PATH
4. Riavvia terminale

**Soluzione Linux:**
```bash
sudo apt install ffmpeg  # Ubuntu/Debian
sudo dnf install ffmpeg  # Fedora
```

---

### 🔴 "RuntimeError: PytorchStreamReader failed reading zip archive"

**Causa:** Modello corrotto durante download

**Soluzione:**
```bash
# Elimina cache modelli
Windows: rmdir /s %USERPROFILE%\.cache\huggingface
Linux: rm -rf ~/.cache/huggingface

# Rilancia app (ri-scaricherà modelli)
python main.py
```

---

## 📞 Supporto Avanzato

**Se nessuna soluzione funziona:**

1. **Raccogli informazioni sistema:**
   ```bash
   python -c "
   import sys, torch, platform
   print('Python:', sys.version)
   print('OS:', platform.platform())
   print('PyTorch:', torch.__version__)
   print('CUDA:', torch.cuda.is_available())
   "
   ```

2. **Raccogli log completo:**
   ```bash
   # Copia file log
   Windows: type %USERPROFILE%\.transcriberpro\logs\transcriber.log
   Linux: cat ~/.transcriberpro/logs/transcriber.log
   ```

3. **Crea Issue GitHub:**
   - [github.com/youruser/transcriber-pro/issues](https://github.com/youruser/transcriber-pro/issues)
   - Includi: OS, Python version, GPU model, log errore completo

4. **Community:**
   - [GitHub Discussions](https://github.com/youruser/transcriber-pro/discussions)
   - Discord/Telegram (se disponibili)

---

<div align="center">

**Buona risoluzione! 🔧✨**

*Se hai risolto un problema non listato qui, contribuisci aprendo una Pull Request!*

</div>
