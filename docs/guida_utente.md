# Guida Utente - Transcriber Pro

## Indice

1. [Panoramica](#panoramica)
2. [Interfaccia Principale](#interfaccia-principale)
3. [Workflow Base](#workflow-base)
4. [Trascrizione](#trascrizione)
5. [Profili di Trascrizione](#profili-di-trascrizione)
6. [Traduzione](#traduzione)
7. [Ricerca Metadata (TMDB/OMDB)](#ricerca-metadata-tmddomdb)
8. [Upload OpenSubtitles](#upload-opensubtitles)
9. [Library Scanner](#library-scanner)
10. [Impostazioni](#impostazioni)
11. [Output e File Generati](#output-e-file-generati)
12. [FAQ](#faq)

---

## Panoramica

**Transcriber Pro** è uno strumento desktop per la trascrizione automatica di video e la traduzione di sottotitoli, progettato per operare prevalentemente in locale con GPU NVIDIA.

**Funzionalità principali:**

- Trascrizione audio via **Faster-Whisper** (modelli small → large-v3)
- Traduzione sottotitoli con 5 motori intercambiabili (locale e cloud)
- Ricerca automatica metadata da **TMDB** e **OMDB**
- Upload automatico su **OpenSubtitles.org**
- Integrazione con **Library Scanner** (Plex/Jellyfin/Emby)
- Interfaccia grafica **PyQt6** con elaborazione in background

---

## Interfaccia Principale

L'interfaccia è divisa in tre aree:

### Pannello Sinistro — Lista File

- **Aggiungi File**: trascina video o usa il pulsante per selezionarli
- Formati supportati: MKV, MP4, AVI, MOV, WMV, M2TS, WEBM
- Ogni file mostra: nome, stato (In attesa / In elaborazione / Completato / Errore), progresso
- Click destro su un file per opzioni contestuali (rimuovi, apri cartella, etc.)

### Pannello Centrale — Log e Progresso

- Log in tempo reale dell'elaborazione corrente
- Barra di progresso globale e per singolo file
- Dettagli GPU/CPU usage durante l'elaborazione

### Pannello Destro — Metadata

- Dopo la ricerca TMDB/OMDB: titolo, anno, sinossi, poster
- I metadata vengono usati per migliorare la qualità della traduzione

---

## Workflow Base

Il flusso di lavoro tipico è:

```
1. Aggiungi file video
2. (Opzionale) Cerca metadata TMDB
3. Avvia Trascrizione → genera file .srt nella lingua originale
4. Avvia Traduzione → genera file .it.srt (o altra lingua target)
5. (Opzionale) Carica su OpenSubtitles
```

I file SRT vengono salvati nella stessa cartella del video sorgente.

---

## Trascrizione

### Avvio

1. Aggiungi uno o più file video alla lista
2. Seleziona il **Profilo di Trascrizione** (vedi sezione dedicata)
3. Clicca **"Avvia Trascrizione"**

### Modelli Whisper

Transcriber Pro usa **Faster-Whisper** con i seguenti modelli:

| Modello | VRAM | Qualità | Velocità |
|---------|------|---------|---------|
| `small` | ~1 GB | Base | Molto rapida |
| `medium` | ~3 GB | Buona | Rapida |
| `large-v3` | ~6 GB | Eccellente | Media |

Il modello viene scelto automaticamente in base al profilo selezionato.

### Rilevamento Lingua

La lingua del parlato viene rilevata automaticamente. Puoi forzarla manualmente in **Settings → Transcription → Language**.

### File di Output

La trascrizione genera un file `.srt` con lo stesso nome del video:

```
/percorso/video/Film.mkv   →   /percorso/video/Film.srt
```

---

## Profili di Trascrizione

I profili controllano il bilanciamento tra qualità, velocità e uso della GPU.

Selezionabili in **Settings → Transcription Profile** oppure nel menu a tendina nel pannello principale.

| Profilo | Modello Whisper | VAD | Beam Size | Uso consigliato |
|---------|----------------|-----|-----------|----------------|
| **Fast** | small | Sì | 1 | Test rapidi, contenuti brevi |
| **Balanced** | medium | Sì | 3 | Uso quotidiano bilanciato |
| **Quality** | large-v3 | Sì | 5 | Qualità superiore |
| **Maximum** | large-v3 | No | 10 | Massima precisione possibile |
| **Batch** | medium | Sì | 3 | Elaborazione in sequenza di file multipli |

**VAD (Voice Activity Detection)**: filtra i silenzi prima della trascrizione, riducendo i tempi e migliorando la qualità del risultato.

---

## Traduzione

### Avvio

1. Assicurati di avere file `.srt` nella lista (o che la trascrizione sia completata)
2. Seleziona il **motore di traduzione** in **Settings → Translation Model**
3. Clicca **"Avvia Traduzione"**

### Motori di Traduzione

Transcriber Pro supporta 5 motori intercambiabili:

#### NLLB-200 (Locale) — Default

- **Modello**: NLLB-200-3.3B (locale, gira su GPU)
- **Qualità**: Buona per la maggior parte delle lingue
- **Velocità**: Molto rapida (~5 min per film)
- **Costo**: Gratuito
- **Requisiti**: GPU NVIDIA con CUDA 12.6

#### NLLB Finetuned (Locale)

- **Modello**: NLLB finetuned su dati cinematografici
- **Qualità**: Migliore di NLLB standard per dialoghi audiovisivi
- **Velocità**: Simile a NLLB standard
- **Costo**: Gratuito
- **Requisiti**: GPU NVIDIA con CUDA 12.6

#### Aya-23-8B (Locale)

- **Modello**: Aya-23-8B (8 miliardi di parametri, locale)
- **Qualità**: Eccellente, comprensione contestuale avanzata
- **Velocità**: Più lenta (richiede GPU potente)
- **Costo**: Gratuito (dopo download)
- **Requisiti**: GPU con ≥10 GB VRAM; HuggingFace token per il download
- **Note**: Prima esecuzione richiede download ~16 GB da HuggingFace

#### Claude API (Cloud)

- **Modello**: Claude Sonnet 4.6 (cloud Anthropic)
- **Qualità**: Superiore, con comprensione del contesto e dello stile
- **Velocità**: Rapida (non usa GPU locale)
- **Costo**: ~$0.15–0.25 per film (richiede piano a pagamento Anthropic)
- **Requisiti**: Connessione internet, API key Anthropic
- **Vantaggio**: Usa automaticamente la sinossi TMDB per traduzioni più accurate

#### OpenAI GPT (Cloud)

- **Modello**: GPT-4o-mini (cloud OpenAI)
- **Qualità**: Ottima
- **Velocità**: Rapida (non usa GPU locale)
- **Costo**: ~$0.05–0.10 per film (richiede piano a pagamento OpenAI)
- **Requisiti**: Connessione internet, API key OpenAI

### Lingua di Destinazione

Selezionabile in **Settings → Translation → Target Language**.
Default: Italiano (`it`). Supporta 50+ lingue.

### File di Output

La traduzione genera un file `.LINGUA.srt`:

```
/percorso/video/Film.srt   →   /percorso/video/Film.it.srt
```

---

## Ricerca Metadata (TMDB/OMDB)

Transcriber Pro cerca automaticamente i metadata di film e serie TV per:

- Migliorare la qualità della traduzione (la sinossi viene usata come contesto)
- Ottenere l'IMDb ID per l'upload su OpenSubtitles
- Visualizzare poster e informazioni nel pannello laterale

### Come funziona

1. Seleziona un file nella lista
2. Clicca **"Cerca Metadata"** (o avviene automaticamente dopo la trascrizione)
3. Il titolo viene estratto dal nome del file e cercato su TMDB
4. I risultati vengono mostrati nel pannello destro

### Configurazione API Keys

In **Settings → API Keys**:

- **TMDB API Key**: necessaria per la ricerca metadata (prioritaria)
- **OMDB API Key**: usata come fallback se TMDB non trova risultati

### Naming Convention Consigliata

Per il rilevamento automatico migliore, rinomina i file video come:

```
Film Title (2024).mkv
Serie TV - S01E03 - Titolo Episodio.mkv
```

---

## Upload OpenSubtitles

Transcriber Pro può caricare automaticamente i sottotitoli generati su **OpenSubtitles.org**.

### Configurazione

In **Settings → OpenSubtitles**:

1. **Username**: il tuo username o email OpenSubtitles
2. **Password**: la tua password
3. **API Key**: ottenibile su [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers) (gratuita)
4. **Auto Upload**: abilita per caricare automaticamente al termine dell'elaborazione

### Verifica Duplicati

Prima di ogni upload, il sistema verifica automaticamente se i sottotitoli esistono già su OpenSubtitles tramite hash del video. Se trovati, l'upload viene saltato per evitare duplicati.

### Limiti Account Gratuito

- 10 upload/giorno
- 200 query/giorno

### Troubleshooting Upload

| Errore | Causa | Soluzione |
|--------|-------|-----------|
| Autenticazione fallita | Credenziali errate | Verifica username/password nelle Settings |
| API Key non valida | Key errata o scaduta | Rigenera su opensubtitles.com/consumers |
| Rate limit exceeded | Troppi upload | Attendi 24h |
| IMDb ID not found | Metadata mancanti | Cerca metadata TMDB prima dell'upload |

---

## Library Scanner

Transcriber Pro si integra con server di gestione librerie multimediali (Plex, Jellyfin, Emby) tramite un **Library Scanner** self-hosted.

### Configurazione

In **Settings → Library Scanner**:

- **Server URL**: indirizzo del server (es: `http://192.168.1.100:8080`)
- **API Key**: la chiave generata dal server Library Scanner

### Funzionalità

- Notifica al media server di aggiornare i metadata dopo la generazione dei sottotitoli
- Supporto per file in rete (NAS, condivisioni Samba)

---

## Impostazioni

Tutte le impostazioni si configurano da **Menu → Settings** e vengono salvate in:

```
~/.transcriberpro/config.json
```

Windows: `C:\Users\TUO_USERNAME\.transcriberpro\config.json`

### Sezioni Principali

| Sezione | Contenuto |
|---------|-----------|
| **Transcription** | Profilo, lingua, modello Whisper |
| **Translation Model** | Scelta motore, API keys (Claude/OpenAI), HuggingFace token |
| **API Keys** | TMDB API key, OMDB API key |
| **OpenSubtitles** | Credenziali, auto-upload, check duplicati |
| **Library Scanner** | URL server, API key |
| **Output** | Formato SRT, cartella output |

### Reset Impostazioni

Per ripristinare i default, elimina `~/.transcriberpro/config.json` e riavvia.

---

## Output e File Generati

| File | Contenuto |
|------|-----------|
| `Video.srt` | Trascrizione nella lingua originale |
| `Video.it.srt` | Traduzione in italiano |
| `Video.en.srt` | Traduzione in inglese (se richiesta) |

I log vengono salvati in `~/.transcriberpro/logs/transcriber.log`.

---

## FAQ

**Q: Posso usare Transcriber Pro senza GPU?**
A: La trascrizione e la traduzione locale richiedono GPU NVIDIA con CUDA. I motori cloud (Claude API, OpenAI) funzionano senza GPU ma richiedono connessione internet e hanno un costo per utilizzo.

**Q: Quanto tempo richiede la trascrizione?**
A: Dipende dal video e dal profilo. Con Quality su RTX 3080, un film di 2 ore richiede circa 15-20 minuti.

**Q: Posso elaborare più file contemporaneamente?**
A: Sì, aggiungi tutti i file e avvia. Vengono processati in sequenza automaticamente.

**Q: Come scarico il modello Aya-23-8B?**
A: Il download avviene automaticamente alla prima selezione del motore. Richiede un HuggingFace token (Settings → Translation Model) perché Aya-23-8B è un modello con accesso controllato.

**Q: La qualità di Claude API è davvero migliore?**
A: Sì, specialmente per dialoghi complessi, giochi di parole o terminologia specifica. Claude usa anche la sinossi TMDB come contesto aggiuntivo, migliorando nomi di personaggi e riferimenti narrativi.

**Q: I file SRT mantengono i timestamp originali?**
A: Sì, tutti i timestamp vengono preservati esattamente.

**Q: Come cambio la lingua di destinazione?**
A: Settings → Translation → Target Language. La scelta è persistente tra le sessioni.

**Q: Posso usare più motori per confrontare i risultati?**
A: Non automaticamente, ma puoi cambiare motore in Settings e ritradurre lo stesso file.

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
