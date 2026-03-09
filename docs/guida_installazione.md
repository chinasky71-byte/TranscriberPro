# Guida all'Installazione - Transcriber Pro

> **OS Supportati:** Windows 10/11 (64-bit), Linux (Ubuntu 22.04+)
> **Tempo stimato:** 20-40 minuti

---

## Requisiti di Sistema

### Hardware

| Componente | Minimo | Consigliato |
|------------|--------|-------------|
| GPU | NVIDIA con ≥4 GB VRAM | RTX 3080 / RTX 4070+ (≥10 GB VRAM) |
| RAM | 12 GB | 32 GB |
| Storage | 20 GB liberi | SSD con 50+ GB liberi |
| CPU | Qualsiasi quad-core | Intel i7/i9 o AMD Ryzen 7/9 |

> **Nota:** La GPU è necessaria per i modelli di trascrizione e traduzione locale. I motori cloud (Claude API, OpenAI) operano senza GPU ma richiedono connessione internet.

### Software

| Componente | Versione richiesta |
|------------|-------------------|
| Python | **3.11** (obbligatorio) |
| CUDA Toolkit | **12.6** |
| cuDNN | 9.x (compatibile con CUDA 12.6) |
| FFmpeg | 6.0+ |

---

## Installazione Passo per Passo

### Step 1: Python 3.11

Scarica da [python.org](https://www.python.org/downloads/release/python-3119/).

**Windows:** durante l'installazione, spunta **"Add Python to PATH"**.

```bash
python --version
# Output atteso: Python 3.11.x
```

### Step 2: CUDA 12.6 e cuDNN

1. Scarica [CUDA Toolkit 12.6](https://developer.nvidia.com/cuda-downloads)
2. Installa con la procedura guidata NVIDIA
3. Scarica e installa [cuDNN 9.x](https://developer.nvidia.com/cudnn) compatibile

```bash
nvcc --version
# Output atteso: Cuda compilation tools, release 12.6
```

### Step 3: FFmpeg

**Windows:**
```bash
winget install ffmpeg
```
Oppure scarica da [ffmpeg.org](https://ffmpeg.org/download.html) e aggiungi la cartella `bin` al PATH.

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

```bash
ffmpeg -version
# Deve mostrare versione 6.0+
```

### Step 4: Clonare il Repository

```bash
git clone https://github.com/YOUR_USERNAME/TranscriberPro.git
cd TranscriberPro
```

### Step 5: Ambiente Virtuale

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### Step 6: Dipendenze Python

```bash
pip install -r requirements.txt
```

> **Nota:** L'installazione include PyTorch 2.8+cu126. Se la tua versione CUDA è diversa, installa PyTorch manualmente da [pytorch.org/get-started](https://pytorch.org/get-started/locally/).

### Step 7: Primo Avvio

```bash
python main.py
```

Verifica che l'applicazione si avvii senza errori e che la GPU sia rilevata (mostrata nel pannello info in basso).

---

## Configurazione Credenziali

Tutte le credenziali si configurano dall'interfaccia grafica in **Settings**. Non è necessario modificare file di configurazione manualmente.

### TMDB API Key (metadata film/serie)

1. Vai su [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)
2. Crea un'applicazione (gratuita, approvazione immediata per uso personale)
3. Copia la **API Key (v3 auth)**
4. Transcriber Pro: **Settings → API Keys → TMDB API Key**

### OMDB API Key (fallback metadata)

1. Vai su [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx)
2. Registrati per la chiave gratuita (1000 req/giorno)
3. Transcriber Pro: **Settings → API Keys → OMDB API Key**

### Claude API Key (traduzione cloud, opzionale)

1. Vai su [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys → Create Key
2. Transcriber Pro: **Settings → Translation Model → Claude API → inserisci API Key**

Richiede un piano a pagamento Anthropic. Costo stimato: ~$0.15–0.25 per film.

### OpenAI API Key (traduzione cloud alternativa, opzionale)

1. Vai su [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → Create new secret key
2. Transcriber Pro: **Settings → Translation Model → OpenAI → inserisci API Key**

### HuggingFace Token (modello Aya-23-8B, opzionale)

Necessario solo per usare il motore Aya-23-8B (traduzione locale avanzata, ~16 GB download).

1. Vai su [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token (tipo Read)
2. Transcriber Pro: **Settings → Translation Model → HuggingFace Token**

### OpenSubtitles (upload sottotitoli, opzionale)

1. Crea account gratuito su [opensubtitles.com](https://www.opensubtitles.com)
2. Ottieni API Key su [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers)
3. Transcriber Pro: **Settings → OpenSubtitles** → inserisci username, password, API Key

---

## Struttura Directory

```
TranscriberPro/
├── main.py                          # Punto di ingresso
├── requirements.txt                 # Dipendenze Python
├── core/
│   ├── transcriber.py               # Motore trascrizione (Faster-Whisper)
│   ├── translator.py                # Motori traduzione (NLLB, Aya, Claude, OpenAI)
│   └── pipeline.py                  # Orchestrazione workflow
├── gui/                             # Interfaccia grafica PyQt6
├── utils/
│   ├── config.py                    # Gestione configurazione singleton
│   ├── opensubtitles_rest_uploader.py
│   └── tmdb_client.py
├── NLLB_Tranined/                   # Config modello NLLB finetuned (no pesi)
└── docs/                            # Documentazione
```

I modelli AI vengono scaricati automaticamente alla prima esecuzione in:
```
~/.cache/huggingface/    # Modelli HuggingFace (NLLB, Aya)
~/.cache/whisper/        # Modelli Faster-Whisper
```

La configurazione utente viene salvata in:
```
~/.transcriberpro/config.json
```

---

## Troubleshooting

### "ModuleNotFoundError" all'avvio

```bash
# Assicurarsi di essere nell'ambiente virtuale
pip install -r requirements.txt
```

### GPU non rilevata / CUDA non disponibile

```bash
python -c "import torch; print(torch.cuda.is_available())"
# False = CUDA non configurata correttamente
```

Soluzioni:
1. Verifica versione CUDA: `nvcc --version`
2. Reinstalla PyTorch da [pytorch.org](https://pytorch.org) scegliendo CUDA 12.6
3. Aggiorna i driver NVIDIA all'ultima versione

### "FFmpeg not found"

Verifica che FFmpeg sia nel PATH: `ffmpeg -version`

**Windows:** aggiungi la cartella `bin` di FFmpeg nelle variabili d'ambiente di sistema.

### Errori durante `pip install -r requirements.txt`

Su Windows potrebbe servire Visual C++ Build Tools:
```
https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
