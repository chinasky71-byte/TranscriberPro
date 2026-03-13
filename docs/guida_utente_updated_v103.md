# 📖 Guida Utente - Transcriber Pro v1.0.3

## Indice

1. [Introduzione](#introduzione)
2. [Interfaccia Grafica](#interfaccia-grafica)
3. [Workflow Elaborazione](#workflow-elaborazione)
4. [Upload OpenSubtitles](#upload-opensubtitles) ⭐ **NUOVO v1.0.3**
5. [Configurazione Avanzata](#configurazione-avanzata)
6. [Tips & Tricks](#tips--tricks)
7. [Troubleshooting](#troubleshooting)

---

## Introduzione

**Transcriber Pro** è un'applicazione desktop avanzata per la trascrizione e traduzione automatica di video utilizzando modelli di AI all'avanguardia.

### Funzionalità Principali

- 🎤 **Trascrizione AI** - Faster-Whisper large-v3 (99+ lingue)
- 🌍 **Traduzione Neurale** - NLLB-200 3.3B (200 lingue → Italiano)
- 🎵 **Separazione Vocale** - Demucs per audio pulito
- 🌐 **Upload Automatico** - OpenSubtitles.org REST API ⭐ **NUOVO**
- 📊 **Metadata TMDB/IMDb** - Ricerca automatica informazioni film
- 🖥️ **GUI Moderna** - Interfaccia intuitiva con monitoraggio risorse

---

## Interfaccia Grafica

### Layout Principale

```
┌─────────────────────────────────────────────────────────┐
│  [🎬 Transcriber Pro v1.0.3]                  [_ □ X] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────┐  ┌──────────────────────────────┐ │
│  │                 │  │  Coda di Elaborazione        │ │
│  │   Anteprima     │  │  ┌──────────────────────────┐│ │
│  │     Video       │  │  │ 🎬 Movie1.mkv           ││ │
│  │                 │  │  │ 🎬 Movie2.mp4           ││ │
│  │   (Poster)      │  │  │ 🎬 Movie3.avi           ││ │
│  │                 │  │  └──────────────────────────┘│ │
│  └─────────────────┘  │                              │ │
│                       │  [➕ Aggiungi]  [📁 Cartella]│ │
│  ┌─────────────────┐  │  [🗑️ Svuota]   [▶️ Avvia]   │ │
│  │ Risorse Sistema │  └──────────────────────────────┘ │
│  │ CPU:  45%       │                                   │
│  │ RAM:  6.2/12GB  │  ┌──────────────────────────────┐ │
│  │ GPU:  85%       │  │ Log Elaborazione             │ │
│  │ VRAM: 8.1/12GB  │  │ ⏳ Trascrizione in corso...  │ │
│  └─────────────────┘  │ ✅ Completato: movie1.it.srt │ │
│                       └──────────────────────────────┘ │
│  [⚙️ Settings]  [📤 OpenSubtitles: ON] [🌐 Network] │
└─────────────────────────────────────────────────────────┘
```

### Elementi Interfaccia

#### Pannello Sinistro
- **Anteprima Video** - Poster TMDB del file selezionato
- **Monitor Risorse** - Utilizzo CPU, RAM, GPU, VRAM in tempo reale
- **Stato Rete** - Download/Upload speed

#### Pannello Centrale
- **Coda Elaborazione** - Lista file video da processare
- **Pulsanti Azione:**
  - `➕ Aggiungi File` - Seleziona file singoli
  - `📁 Aggiungi Cartella` - Elabora intera directory
  - `🗑️ Svuota Coda` - Rimuovi tutti i file
  - `▶️ Avvia` - Inizia elaborazione
  - `⏸️ Pausa` - Pausa temporanea
  - `⏹️ Annulla` - Termina elaborazione

#### Pannello Destro
- **Log Elaborazione** - Output dettagliato processo
- **Progress Bar** - Avanzamento elaborazione

#### Barra Inferiore
- **Settings** - Configurazione applicazione
- **OpenSubtitles Toggle** ⭐ **NUOVO** - Abilita/disabilita upload
- **Network Status** - Stato connessione

---

## Workflow Elaborazione

### Passo 1: Aggiungere File

**Metodo A: Drag & Drop**
```
1. Trascina file/cartelle → Finestra applicazione
2. ✅ File aggiunti automaticamente alla coda
```

**Metodo B: Pulsante File**
```
1. Click [➕ Aggiungi File]
2. Seleziona file video (MKV, MP4, AVI, etc.)
3. ✅ File aggiunti alla coda
```

**Metodo C: Cartella Intera**
```
1. Click [📁 Aggiungi Cartella]
2. Seleziona directory
3. ✅ Tutti i video nella cartella aggiunti
```

---

### Passo 2: Avviare Elaborazione

```
1. Click [▶️ Avvia]
2. ⏳ Elaborazione inizia automaticamente
3. 👀 Monitora progress in tempo reale
```

---

### Passo 3: Pipeline Automatica

Per ogni video, Transcriber Pro esegue:

#### **Step 1: Estrazione Audio** 🎵
```
🔍 Analisi tracce audio video...
📊 Trovate 3 tracce audio
  ✅ Traccia 1: ENG (Selezionata)
  ℹ️ Traccia 2: ITA (Commentary)
  ℹ️ Traccia 3: SPA
🎵 Estrazione traccia audio...
✅ Audio estratto: temp_audio.wav
```

#### **Step 2: Separazione Vocale** 🎤
```
⏳ Caricamento Demucs htdemucs...
✅ Modello Demucs caricato
🎵 Separazione vocale da background...
  Pipeline: STANDARD (file 45 minuti)
  Chunks: 135 (20s ciascuno)
  Progress: [████████████████████] 100%
✅ Vocali isolati: vocals.wav
```

#### **Step 3: Trascrizione Whisper** 📝
```
⏳ Caricamento Faster-Whisper large-v3...
✅ Modello caricato (GPU, int8_float16)
🎤 Trascrizione in corso...
  Lingua rilevata: eng (confidenza: 0.98)
  VAD: ATTIVO
  Beam size: 7
  Progress: [████████████████████] 100%
  Segmenti: 1596
✅ Trascrizione completata
```

#### **Step 4: Pulizia Sottotitoli** 🧹
```
🧹 Pulizia sottotitoli...
  ✅ Rimossi duplicati
  ✅ Fissati overlap temporali
  ✅ Normalizzati caratteri speciali
✅ Pulizia completata
```

#### **Step 5: Traduzione** 🌍
```
🌍 Traduzione ENG → ITA
⏳ Caricamento NLLB-200 3.3B...
✅ Modello caricato (GPU, float16)
📊 Batch processing: 1596 segmenti
  Batch size: 24
  Num beams: 7
  Progress: [████████████████████] 100%
✅ Traduzione completata
```

#### **Step 6: Salvataggio** 💾
```
💾 Salvataggio sottotitoli...
✅ File salvato: Movie.2024.1080p.it.srt
📍 Percorso: C:\Videos\Movie.2024.1080p.it.srt
```

#### **Step 7: Upload OpenSubtitles** 📤 ⭐ **NUOVO**
```
========================================
📤 UPLOAD OPENSUBTITLES
========================================
🔐 Autenticazione REST API...
✅ Login riuscito

🔍 Ricerca metadata...
  → TMDB: The Matrix (1999)
  → IMDb ID: tt0133093
✅ Metadata completi

🔍 Verifica duplicati...
✅ Nessun duplicato trovato

📤 Upload in corso...
✅ Upload completato!
   ID: 9876543210
   URL: https://www.opensubtitles.org/it/subtitles/9876543210

🏆 Grazie per contribuire a OpenSubtitles!
========================================
```

---

## Upload OpenSubtitles

### Configurazione (Prima Volta)

**⚠️ Importante:** L'upload è **opzionale** ma raccomandato per contribuire alla community!

#### Step 1: Crea Account OpenSubtitles

1. Vai su https://www.opensubtitles.org/en/newuser
2. Registrati (gratuito)
3. **Verifica email** (obbligatorio)

#### Step 2: Ottieni API Key (per REST)

1. Login su https://www.opensubtitles.com
2. Vai su https://www.opensubtitles.com/consumers
3. Click "Create Consumer"
4. Compila:
   - **App Name:** Transcriber Pro
   - **Purpose:** Personal use
5. **Copia API Key** (salvala in luogo sicuro!)

#### Step 3: Configura Credenziali

**Crea file di configurazione:**

**Windows:**
```
C:\Users\TUO_USERNAME\.transcriberpro\opensubtitles_credentials.json
```

**Linux/Mac:**
```
~/.transcriberpro/opensubtitles_credentials.json
```

**Contenuto:**
```json
{
    "username": "tuo_username",
    "password": "tua_password",
    "api_key": "TUA_API_KEY_QUI",
    "auto_upload": true
}
```

#### Step 4: Riavvia Applicazione

```
1. Chiudi Transcriber Pro
2. Riapri
3. ✅ Credenziali caricate automaticamente
```

#### Step 5: Verifica Setup

```bash
# Da terminale
python verify_opensubtitles_setup.py
```

**Output atteso:**
```
🎉 TUTTO OK! Sistema configurato correttamente.
```

---

### Uso Upload

#### Upload Automatico (Default)

Se `auto_upload: true`:

```
1. ▶️ Elabora video normalmente
2. ⏳ Pipeline completa (trascrizione + traduzione)
3. 📤 Upload automatico a fine elaborazione
4. ✅ Conferma in log: "Upload completato!"
```

**Non devi fare nulla!** 🎉

#### Toggle Upload On/Off

**Dalla GUI:**

```
1. Guarda barra inferiore
2. Click [📤 OpenSubtitles: ON/OFF]
3. ✅ Stato cambiato
```

**Dal Config:**

Edita `~/.transcriberpro/config.json`:

```json
{
    "opensubtitles_upload_enabled": false
}
```

#### Disabilitare Auto-Upload

Se vuoi **decidere manualmente** per ogni file:

In `opensubtitles_credentials.json`:

```json
{
    ...
    "auto_upload": false
}
```

**⚠️ Note:** Upload manuale disponibile in v1.1.0+

---

### Verifica Duplicati

**Automatica!** Transcriber Pro verifica sempre se i sottotitoli esistono già:

```
🔍 Verifica duplicati...
  Video hash: 8f7e9c2d1a3b4e5f
  Lingua: ita
  
ℹ️ Sottotitoli già presenti!
  ID esistente: 1234567890
  → Upload saltato (evitato duplicato)
```

**Vantaggi:**
- ✅ Risparmia banda
- ✅ Rispetta ToS OpenSubtitles
- ✅ Evita spam database

---

### Metadata Automatici

Transcriber Pro arricchisce i sottotitoli con metadata:

**Ricerca Automatica:**
```
🔍 Ricerca metadata: The Matrix (1999).mkv
  → Query TMDB: "The Matrix 1999"
  → Match trovato: The Matrix (1999)
  → IMDb ID: tt0133093
  → Rating: 8.7/10
  → Genre: Sci-Fi, Action
✅ Metadata completi
```

**Dati Inviati:**
- IMDb ID
- Lingua sottotitoli (ISO 639-2)
- Release name
- Video hash
- Video size
- Subtitle format (SRT)
- Comments ("Generated by Transcriber Pro")

**Risultato:**
I tuoi sottotitoli saranno facilmente trovabili su OpenSubtitles!

---

### Limiti Upload

**Account Gratuito:**
- 10 upload/giorno
- 200 query/giorno

**Se superi limite:**
```
❌ Rate limit exceeded
   Riprova tra: 12h 34m
```

**Soluzione:**
- Attendi 24h
- Considera account VIP (opzionale)

---

### FAQ Upload

**Q: I sottotitoli sono pubblici?**

Sì, OpenSubtitles è un database pubblico community-driven.

**Q: Posso eliminare sottotitoli caricati?**

Sì, login su OpenSubtitles → My Subtitles → Delete

**Q: Devo pagare?**

No, servizio completamente gratuito (VIP opzionale per limiti più alti)

**Q: Cosa succede se fallisce?**

Upload non blocca elaborazione. Puoi ricaricare manualmente.

**Q: Posso disabilitare permanentemente?**

Sì, elimina file `opensubtitles_credentials.json`

📚 **Guida Completa:** [GUIDA_OPENSUBTITLES_REST_API.md](GUIDA_OPENSUBTITLES_REST_API.md)

---

## Configurazione Avanzata

### File Configurazione

**Percorso:**
```
~/.transcriberpro/config.json
```

### Opzioni Principali

#### Generale

```json
{
    "use_gpu": true,
    "language": "auto",
    "shutdown_after_processing": false
}
```

#### Trascrizione

```json
{
    "transcription_method": "faster-whisper",
    "whisper_model": "large-v3",
    "whisper_device": "auto",
    "whisper_compute_type": "auto"
}
```

**Modelli disponibili:**
- `tiny` - Veloce, meno accurato (1GB VRAM)
- `base` - Bilanciato (1GB VRAM)
- `small` - Buono (2GB VRAM)
- `medium` - Molto buono (5GB VRAM)
- `large-v3` - **Migliore** (10GB VRAM) ⭐ **Raccomandato**

#### OpenSubtitles ⭐ **NUOVO**

```json
{
    "opensubtitles_upload_enabled": true,
    "opensubtitles_auto_upload": true,
    "opensubtitles_check_duplicates": true,
    "opensubtitles_preferred_implementation": "rest",
    "opensubtitles_api_key": "YOUR_API_KEY"
}
```

---

## Tips & Tricks

### 🚀 Massimizzare Prestazioni

**1. Chiudi applicazioni GPU-intensive**
```
- Browser con molti tab
- Giochi
- Editor video
```

**2. Monitora risorse**
```
👀 Guarda pannello risorse
⚠️ Se VRAM > 95% → Riduci batch size
```

**3. Usa SSD**
```
✅ File temporanei su SSD = +30% velocità
```

### 🎯 Migliorare Accuratezza

**1. Qualità audio**
```
✅ Audio bitrate ≥ 128 kbps
✅ No video over-compressi
```

**2. Lingua chiara**
```
✅ Audio senza musica forte funziona meglio
✅ Demucs aiuta, ma non fa miracoli
```

**3. Nome file corretto**
```
✅ Movie.Title.(YEAR).1080p.mkv
   → Metadata TMDB accurati

❌ asdasd.mkv
   → Metadata non trovati
```

### 📂 Organizzazione File

**Struttura consigliata:**
```
Videos/
├── Movies/
│   ├── The.Matrix.(1999)/
│   │   ├── The.Matrix.(1999).1080p.mkv
│   │   └── The.Matrix.(1999).1080p.it.srt  ← Generato
│   └── Inception.(2010)/
│       ├── Inception.(2010).1080p.mkv
│       └── Inception.(2010).1080p.it.srt   ← Generato
└── TV.Shows/
    └── Breaking.Bad/
        └── Season.01/
            ├── S01E01.mkv
            ├── S01E01.it.srt  ← Generato
            ...
```

### ⚡ Batch Processing

**Per molti file:**

```
1. [📁 Aggiungi Cartella] → Seleziona directory
2. ✅ Tutti i file aggiunti
3. [▶️ Avvia]
4. ☕ Vai a prendere un caffè
5. 🎉 Tutti i sottotitoli pronti!
```

**Stima tempi:**
- Film 2h: ~30-60 minuti
- Episodio TV 45min: ~15-30 minuti
- *Tempi su RTX 3060 12GB*

---

## Troubleshooting

### Video Non Elaborato

**Checklist:**
- [ ] Formato supportato? (MKV, MP4, AVI, MOV, WMV)
- [ ] File corrotto? (Prova con VLC)
- [ ] Spazio disco? (Serve ~2x dimensione video liberi)
- [ ] Permessi file? (Leggi/scrivi ok?)

### Errore GPU

**Sintomi:**
```
❌ CUDA out of memory
```

**Soluzioni:**
1. Chiudi altre app GPU
2. Riavvia Transcriber Pro
3. Se persiste → Usa CPU (più lento)

### Trascrizione Imprecisa

**Cause comuni:**
1. Audio di bassa qualità
2. Musica/rumore forte
3. Lingua non supportata bene

**Soluzioni:**
- Usa video con audio migliore
- Demucs aiuta con audio rumoroso
- Verifica lingua supportata da Whisper

### Upload Fallito

**Errore comune:**
```
❌ Autenticazione fallita
```

**Fix:**
```bash
# 1. Verifica credenziali
cat ~/.transcriberpro/opensubtitles_credentials.json

# 2. Test setup
python verify_opensubtitles_setup.py

# 3. Rigenera API Key se necessario
https://www.opensubtitles.com/consumers
```

📚 **Troubleshooting Completo:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 🆘 Supporto

### Hai bisogno di aiuto?

1. **Controlla questa guida**
2. **Leggi [TROUBLESHOOTING.md](TROUBLESHOOTING.md)**
3. **Verifica [FAQ](#faq-upload)**
4. **Apri issue su GitHub**

### Report Bug

GitHub: https://github.com/chinasky71-byte/Transcriptor-Pro/issues

**Includi sempre:**
- Versione Transcriber Pro
- Sistema operativo
- Log completo errore
- Steps per riprodurre

---

## 📚 Guide Aggiuntive

- 📦 [Guida Installazione](GUIDA_INSTALLAZIONE.md)
- 🌐 [Guida OpenSubtitles REST API](GUIDA_OPENSUBTITLES_REST_API.md) ⭐ **NUOVO**
- 🏗️ [Architettura](ARCHITETTURA.md)
- 🐛 [Troubleshooting](TROUBLESHOOTING.md)

---

<div align="center">

**Buon lavoro con Transcriber Pro!** 🎬🎤🌍

**Made with ❤️ for subtitle enthusiasts**

[← README](../README.md) | [Installazione →](GUIDA_INSTALLAZIONE.md) | [Troubleshooting →](TROUBLESHOOTING.md)

</div>
