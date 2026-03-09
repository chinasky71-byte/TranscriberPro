# Architettura Tecnica - Transcriber Pro

> **Documento per:** Developer, Contributor, Advanced Users

---

## Panoramica

Transcriber Pro è organizzato in tre layer principali:

```
┌─────────────────────────────────────────┐
│           PRESENTATION LAYER            │
│         (PyQt6 GUI — gui/)              │
├─────────────────────────────────────────┤
│             CORE LAYER                  │
│   (Transcription, Translation, Pipeline)│
├─────────────────────────────────────────┤
│            UTILS LAYER                  │
│  (Config, TMDB, OpenSubtitles, Library) │
└─────────────────────────────────────────┘
```

---

## Struttura Directory

```
TranscriberPro/
├── main.py                              # Punto di ingresso, bootstrap Qt
├── core/
│   ├── transcriber.py                   # Motore Faster-Whisper
│   ├── translator.py                    # Factory + implementazioni traduzione
│   └── pipeline.py                      # Orchestratore del workflow completo
├── gui/
│   ├── main_window.py                   # Finestra principale
│   ├── settings_dialog.py               # Dialog impostazioni
│   ├── translation_model_dialog.py      # Selezione motore traduzione + API keys
│   └── workers.py                       # QThread worker per elaborazione async
├── utils/
│   ├── config.py                        # Singleton configurazione
│   ├── tmdb_client.py                   # Client TMDB API
│   ├── omdb_client.py                   # Client OMDB API (fallback)
│   ├── subtitle_uploader_interface.py   # Interfaccia astratta uploader
│   ├── opensubtitles_rest_uploader.py   # Implementazione REST OpenSubtitles
│   ├── opensubtitles_xmlrpc_uploader.py # Implementazione legacy XML-RPC
│   └── library_scanner_client.py        # Client Library Scanner (Plex/Jellyfin)
└── NLLB_Tranined/                       # Configurazione modello NLLB finetuned
    └── *.json                           # Config tokenizer e modello (no pesi)
```

---

## Core Layer

### `core/transcriber.py` — Motore di Trascrizione

Wrappa **Faster-Whisper** (implementazione CTranslate2 di Whisper).

**Classi principali:**
- `WhisperTranscriber` — gestisce caricare/scaricare il modello, trascrivere audio

**Modelli supportati:** `small`, `medium`, `large-v3`

**Profili di trascrizione** (configurati da `Config`):

| Profilo | Modello | VAD | Beam Size |
|---------|---------|-----|-----------|
| Fast | small | Sì | 1 |
| Balanced | medium | Sì | 3 |
| Quality | large-v3 | Sì | 5 |
| Maximum | large-v3 | No | 10 |
| Batch | medium | Sì | 3 |

Il modello viene caricato in memoria GPU tramite CUDA 12.6 / cuDNN 9.x.

---

### `core/translator.py` — Motori di Traduzione

Implementa un **Factory Pattern** per i motori di traduzione.

**Funzione factory:**
```python
def create_translator(engine: str, config: Config) -> BaseTranslator
```

**Motori disponibili:**

| Engine string | Classe | Tipo | Note |
|---------------|--------|------|------|
| `nllb` | `NLLBTranslator` | Locale (GPU) | NLLB-200-3.3B |
| `nllb_finetuned` | `NLLBFinetunedTranslator` | Locale (GPU) | Da NLLB_Tranined/ |
| `aya` | `AyaTranslator` | Locale (GPU) | Aya-23-8B, richiede HF token |
| `claude` | `ClaudeTranslator` | Cloud API | Sonnet 4.6, richiede API key |
| `openai` | `OpenAITranslator` | Cloud API | GPT-4o-mini, richiede API key |

Tutti i traduttori implementano l'interfaccia:
```python
class BaseTranslator:
    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str: ...
    def translate_batch(self, texts: list[str], ...) -> list[str]: ...
```

**Batch Processing:**
I traduttori locali processano i sottotitoli in batch per massimizzare il throughput GPU. Il batch size è adattivo in base alla VRAM disponibile (vedi `docs/adaptive_batch_readme_it.md`).

Claude API e OpenAI usano batch di 4 sottotitoli per chiamata API.

---

### `core/pipeline.py` — Orchestrazione

Coordina l'intero workflow:

```
Input Video
    ↓
Estrazione Audio (FFmpeg)
    ↓
Trascrizione (Faster-Whisper)
    ↓
Ricerca Metadata (TMDB → OMDB fallback)
    ↓
Traduzione (motore selezionato)
    ↓
Scrittura file .srt / .LANG.srt
    ↓
Upload OpenSubtitles (se abilitato)
    ↓
Notifica Library Scanner (se configurato)
```

---

## Utils Layer

### `utils/config.py` — Configurazione Singleton

Classe `Config` — singleton globale che gestisce tutta la configurazione.

**Storage:** `~/.transcriberpro/config.json`

**Chiavi principali:**

```python
{
    # Traduzione
    "translation_model": "nllb",         # nllb | nllb_finetuned | aya | claude | openai
    "target_language": "it",
    "claude_api_key": "",
    "openai_api_key": "",
    "huggingface_token": "",

    # Trascrizione
    "transcription_profile": "balanced", # fast | balanced | quality | maximum | batch
    "whisper_language": "auto",

    # Metadata
    "tmdb_api_key": "",
    "omdb_api_key": "",

    # OpenSubtitles
    "opensubtitles_username": "",
    "opensubtitles_password": "",
    "opensubtitles_api_key": "",
    "opensubtitles_auto_upload": false,
    "opensubtitles_check_duplicates": true,

    # Library Scanner
    "library_scanner_url": "",
    "library_scanner_api_key": "",
}
```

Accesso thread-safe con lock interno. Lettura/scrittura su disco ad ogni modifica.

---

### `utils/subtitle_uploader_interface.py` — Pattern Uploader

Interfaccia astratta con factory per i due uploader OpenSubtitles:

```python
class SubtitleUploaderInterface(ABC):
    @abstractmethod
    def upload(self, subtitle_path, video_path, language, imdb_id) -> bool: ...

    @abstractmethod
    def check_duplicate(self, video_hash, language) -> bool: ...
```

**Implementazioni:**
- `OpenSubtitlesRESTUploader` — REST API moderna (default)
- `OpenSubtitlesXMLRPCUploader` — Legacy XML-RPC (fallback)

La factory seleziona automaticamente REST se l'API key è presente, altrimenti XML-RPC.

---

### `utils/library_scanner_client.py` — Library Scanner

Client HTTP per notificare server Library Scanner (Plex/Jellyfin/Emby) dell'aggiornamento dei sottotitoli.

Configurabile in **Settings → Library Scanner**.

---

## Presentation Layer (GUI)

Basato su **PyQt6 6.6.1**.

- L'elaborazione avviene in `QThread` worker per non bloccare la UI
- I progressi vengono comunicati via **Qt signals/slots**
- Le impostazioni vengono lette/scritte tramite `Config` (singleton condiviso)

**Dialog principali:**
- `SettingsDialog` — impostazioni generali, API keys, OpenSubtitles, Library Scanner
- `TranslationModelDialog` — scelta motore traduzione, configurazione API keys cloud, HuggingFace token

---

## Stack Tecnologico

| Componente | Tecnologia | Versione |
|------------|-----------|---------|
| GUI | PyQt6 | 6.6.1 |
| Trascrizione | Faster-Whisper | 1.0.3 |
| Deep Learning | PyTorch | 2.8+cu126 |
| Accelerazione | CUDA | 12.6 |
| Traduzione locale | Transformers (HuggingFace) | 4.57+ |
| Traduzione cloud 1 | Anthropic SDK | ≥0.39 |
| Traduzione cloud 2 | OpenAI SDK | ≥1.0 |
| Audio processing | FFmpeg | 6.0+ |
| Metadata | TMDB API v3 / OMDB API | — |
| Upload subtitle | OpenSubtitles REST API v1 | — |
| Python | CPython | 3.11 |

---

## Flusso Dati — Traduzione con Contesto TMDB

Quando si usa **Claude API** o **OpenAI**, il traduttore riceve anche la sinossi TMDB:

```
SRT file + sinossi TMDB
         ↓
Batch di 4 sottotitoli
         ↓
Prompt strutturato con contesto
         ↓
Claude/OpenAI API call
         ↓
Sottotitoli tradotti con terminologia coerente
```

Questo garantisce coerenza nella traduzione di nomi di personaggi, luoghi e terminologia specifica del contenuto.

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
