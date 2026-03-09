# Troubleshooting - Risoluzione Problemi

---

## Problemi di Installazione

### GPU non rilevata / CUDA non disponibile

```bash
python -c "import torch; print(torch.cuda.is_available())"
# Se stampa False, CUDA non è configurata correttamente
```

**Soluzioni:**
1. Verifica versione CUDA: `nvcc --version` (deve essere 12.6)
2. Verifica driver NVIDIA: aggiornali all'ultima versione
3. Reinstalla PyTorch da [pytorch.org](https://pytorch.org) selezionando CUDA 12.6:
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
   ```

---

### "ModuleNotFoundError" all'avvio

```bash
pip install -r requirements.txt
```

Se l'errore persiste su un singolo pacchetto:
```bash
pip install --upgrade <nome_pacchetto>
```

---

### FFmpeg non trovato

```bash
ffmpeg -version
# Se il comando non è trovato, FFmpeg non è nel PATH
```

**Windows:** aggiungi la cartella `bin` di FFmpeg alle variabili d'ambiente di sistema.

**Linux:**
```bash
sudo apt install ffmpeg
```

---

### Errori durante `pip install -r requirements.txt` (Windows)

Alcuni pacchetti richiedono il compilatore C++. Installa:
- [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

---

## Problemi di Trascrizione

### Trascrizione lenta / crash OOM (Out of Memory)

**Causa:** modello troppo grande per la VRAM disponibile.

**Soluzione:** usa un profilo più leggero in **Settings → Transcription Profile**:
- `Fast` (small, ~1 GB VRAM)
- `Balanced` (medium, ~3 GB VRAM)

---

### Testo trascritto nella lingua sbagliata

**Causa:** rilevamento automatico della lingua errato.

**Soluzione:** forza la lingua in **Settings → Transcription → Language** (es: `en`, `it`, `es`).

---

### Trascrizione con molti errori

**Cause possibili:**
- Audio di bassa qualità o con molto rumore di fondo
- Modello `small` o `medium` usato su contenuto difficile
- Accento forte o lingua mista

**Soluzioni:**
- Usa il profilo `Quality` o `Maximum`
- Migliora la qualità audio con pre-processing (riduzione rumore)
- Forza la lingua manualmente se è nota

---

## Problemi di Traduzione

### "GPU out of memory" durante la traduzione con NLLB o Aya

**Soluzione:**
1. Riduci il batch size in **Settings → Translation → Batch Size**
2. Chiudi altre applicazioni che usano la GPU
3. Usa un motore cloud (Claude API, OpenAI) che non usa la GPU locale

---

### Traduzione di bassa qualità

**Cause possibili:**
- Sottotitoli molto frammentati (frasi troppo corte)
- Lingua sorgente rilevata male
- Mancanza di contesto (metadata TMDB assenti)

**Soluzioni:**
- Verifica che i metadata TMDB siano caricati prima della traduzione
- Considera Claude API o OpenAI per qualità superiore con contesto
- Usa `nllb_finetuned` per contenuti audiovisivi

---

### Errore "libreria 'anthropic' non disponibile"

```bash
pip install anthropic
```

---

### Claude API: "API key non valida"

- Verifica che la key inizi con `sk-ant-`
- Verifica che sia attiva su [console.anthropic.com](https://console.anthropic.com)
- Controlla che non ci siano spazi extra durante il copia/incolla

---

### Claude API / OpenAI: "Rate limit exceeded"

Il sistema gestisce automaticamente i retry con exponential backoff. Se persiste:
- Attendi qualche minuto e riprova
- Verifica il tuo tier/quota nella console Anthropic o OpenAI

---

### Aya-23-8B: "HuggingFace authentication required"

Il modello Aya-23-8B è un modello "gated" su HuggingFace.

**Soluzione:**
1. Vai su [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Crea un token di tipo Read
3. Configuralo in **Settings → Translation Model → HuggingFace Token**

---

## Problemi OpenSubtitles

### "Autenticazione fallita"

1. Verifica username e password in **Settings → OpenSubtitles**
2. Testa il login manualmente su [opensubtitles.com](https://www.opensubtitles.com)
3. Verifica che l'account sia attivato (email di conferma)

---

### "API Key non valida"

1. Vai su [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers)
2. Verifica che il Consumer sia attivo
3. Se necessario, crea un nuovo Consumer e aggiorna la key nelle Settings

---

### "Rate limit exceeded" OpenSubtitles

Limiti account gratuito: 10 upload/giorno, 200 query/giorno.
- Attendi 24h
- Considera un account VIP per limiti più alti

---

### "IMDb ID not found" — upload saltato

**Causa:** non è stato possibile trovare il film/serie su TMDB/OMDB.

**Soluzioni:**
- Rinomina il file video includendo l'anno: `Film Title (2024).mkv`
- Cerca manualmente i metadata tramite il pulsante "Cerca Metadata" nella GUI

---

## Problemi di Configurazione

### Le impostazioni non vengono salvate

Verifica i permessi sulla cartella `~/.transcriberpro/`.

**Windows:**
```
C:\Users\TUO_USERNAME\.transcriberpro\
```

Se la cartella non esiste, viene creata automaticamente al primo avvio.

---

### Reset completo delle impostazioni

```bash
# Windows
del %USERPROFILE%\.transcriberpro\config.json

# Linux/Mac
rm ~/.transcriberpro/config.json
```

Riavvia l'applicazione: verrà creato un nuovo `config.json` con i valori di default.

---

## Problemi GPU / Performance

### Uso GPU basso durante la traduzione NLLB

**Causa normale:** i modelli NLLB sono più memory-bound che compute-bound su GPU moderne. Un utilizzo del 40-70% è normale.

---

### La GPU si surriscalda

- Verifica ventilazione del case
- Riduci il profilo di trascrizione (usa `Balanced` invece di `Maximum`)
- Controlla la temperatura GPU con GPU-Z o HWiNFO

---

## Supporto e Segnalazione Bug

Per segnalare un problema, apri una **Issue** su GitHub includendo:

1. Versione di Transcriber Pro
2. Sistema operativo e versione
3. GPU e driver NVIDIA
4. Log di errore completo (da `~/.transcriberpro/logs/transcriber.log`)
5. Passaggi per riprodurre il problema

**GitHub:** [https://github.com/YOUR_USERNAME/TranscriberPro/issues](https://github.com/YOUR_USERNAME/TranscriberPro/issues)

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
