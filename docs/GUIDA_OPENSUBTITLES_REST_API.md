# 🌐 Guida OpenSubtitles REST API - v1.0.3

## Introduzione

A partire dalla versione 1.0.3, **Transcriber Pro** supporta l'upload automatico dei sottotitoli generati su **OpenSubtitles.org** tramite la moderna **REST API**.

### ✨ Novità v1.0.3

- 🌐 **REST API completa** per OpenSubtitles.com
- 🔐 **Gestione credenziali sicura** tramite file configurazione
- 🧪 **Test connessione GUI** integrato
- 🔑 **Supporto API Key** per autenticazione moderna
- ✅ **Verifica automatica duplicati** prima dell'upload
- 🎯 **Scelta implementazione** (REST o XML-RPC legacy)

---

## 📋 Requisiti

### 1. Account OpenSubtitles

- **Registrazione gratuita:** https://www.opensubtitles.org/en/newuser
- **Verifica email** necessaria per attivare l'account
- **Limite upload:** 10 sottotitoli/giorno (account gratuito)

### 2. API Key (per REST API)

**NUOVO in v1.0.3!** Per usare la REST API moderna:

1. Vai su: https://www.opensubtitles.com/consumers
2. Login con il tuo account
3. Clicca "**Create Consumer**"
4. Compila form:
   - **App Name:** Transcriber Pro
   - **Description:** Personal subtitle transcription tool
   - **Purpose:** Personal use
5. **Copia API Key** generata (la vedrai una sola volta!)

### 3. Software

- Python 3.8-3.11
- Transcriber Pro v1.0.3+
- Connessione internet attiva

---

## ⚙️ Configurazione

Ci sono **3 modi** per configurare le credenziali OpenSubtitles:

### Metodo 1: File JSON (Consigliato) ⭐

**Vantaggi:**
- ✅ Formato strutturato
- ✅ Supporta API Key REST
- ✅ Opzioni avanzate
- ✅ Facile da editare

**Procedura:**

1. Crea file di configurazione:

**Windows:**
```
C:\Users\TUO_USERNAME\.transcriberpro\opensubtitles_credentials.json
```

**Linux/Mac:**
```
~/.transcriberpro/opensubtitles_credentials.json
```

2. Contenuto del file:

```json
{
    "username": "tuo_username",
    "password": "tua_password",
    "api_key": "YOUR_API_KEY_HERE",
    "auto_upload": true
}
```

**Parametri:**
- `username` - Username o email OpenSubtitles (obbligatorio)
- `password` - Password account (obbligatorio)
- `api_key` - API Key per REST API (obbligatorio per REST)
- `auto_upload` - Upload automatico al termine elaborazione (opzionale, default: false)

3. **Riavvia** Transcriber Pro per caricare le credenziali

---

### Metodo 2: File TXT (Semplice)

**Vantaggi:**
- ✅ Semplicissimo da creare
- ✅ Nessun formato JSON da ricordare

**Limiti:**
- ❌ Solo XML-RPC (no REST API)
- ❌ No API Key
- ❌ No opzioni avanzate

**Procedura:**

1. Crea file:

**Windows:**
```
C:\Users\TUO_USERNAME\.transcriberpro\opensubtitles_credentials.txt
```

**Linux/Mac:**
```
~/.transcriberpro/opensubtitles_credentials.txt
```

2. Contenuto (due righe):

```
tuo_username
tua_password
```

**Importante:** Prima riga = username, seconda riga = password

3. **Riavvia** Transcriber Pro

---

### Metodo 3: Configurazione GUI (Futuro)

**Status:** 🚧 In sviluppo per v1.1.0

Permetterà di configurare tutto direttamente dall'interfaccia grafica senza editare file.

---

## 🎯 Scelta Implementazione API

Transcriber Pro supporta **2 implementazioni** per comunicare con OpenSubtitles:

### REST API (Moderno - Default v1.0.3) ⭐

**Vantaggi:**
- ✅ API moderna e performante
- ✅ Migliore sicurezza
- ✅ Rate limiting più alto
- ✅ Supporto futuro garantito
- ✅ Risposta JSON standard

**Requisiti:**
- API Key obbligatoria
- File JSON configurazione

**Configurazione:**

Nel file `config.json` (o automatico se usi JSON credentials):

```json
{
    "opensubtitles_preferred_implementation": "rest",
    "opensubtitles_api_key": "YOUR_API_KEY"
}
```

---

### XML-RPC (Legacy)

**Vantaggi:**
- ✅ Non richiede API Key
- ✅ Compatibile con file TXT

**Limiti:**
- ⚠️ API vecchia (deprecated)
- ⚠️ Potrebbe essere dismessa in futuro
- ⚠️ Rate limiting più basso

**Configurazione:**

Nel file `config.json`:

```json
{
    "opensubtitles_preferred_implementation": "xmlrpc"
}
```

**Raccomandazione:** Usa **REST API** per nuove installazioni!

---

## 🧪 Test Connessione

### Test da GUI

**Coming in v1.1.0:** Pulsante "Test Connessione" nell'interfaccia grafica.

### Test da Terminale

Usa lo script di verifica completo:

```bash
# Windows
cd C:\Users\TUO_USERNAME\Desktop\Transcriber_Pro
python verify_opensubtitles_setup.py

# Linux/Mac
cd ~/Transcriber_Pro
python verify_opensubtitles_setup.py
```

**Output atteso (tutto OK):**

```
======================================================================
  🔍 VERIFICA SETUP OPENSUBTITLES UPLOAD
======================================================================

======================================================================
  🔍 VERIFICA DIPENDENZE
======================================================================
  ✅ xmlrpc.client       [Standard Library]
  ✅ hashlib             [Standard Library]
  ✅ struct              [Standard Library]

======================================================================
  📦 VERIFICA MODULI PROGETTO
======================================================================
  ✅ utils.subtitle_uploader_interface
  ✅ utils.opensubtitles_rest_uploader
  ✅ utils.opensubtitles_xmlrpc_uploader

======================================================================
  🏭 FACTORY PATTERN
======================================================================
  ✅ REST uploader registrato
  ✅ XMLRPC uploader registrato

======================================================================
  🔐 VERIFICA CREDENZIALI
======================================================================
  ✅ File trovato: ~/.transcriberpro/opensubtitles_credentials.json
  ✅ Username: tuo_username
  ✅ Password: [NASCOSTA]
  ✅ API Key: [PRESENTE]

======================================================================
  🌐 TEST CONNETTIVITÀ RETE
======================================================================
  ✅ Connessione a api.opensubtitles.org riuscita
  ✅ Status Code: 200
  ✅ API raggiungibile

======================================================================
  🔑 TEST AUTENTICAZIONE
======================================================================
  ✅ Login riuscito
     Token: [GENERATO]
     User ID: 12345

======================================================================
  📊 RIEPILOGO
======================================================================
  ✅ OK       Dipendenze Python
  ✅ OK       Struttura File
  ✅ OK       Moduli Progetto
  ✅ OK       Factory Pattern
  ✅ OK       Connettività Rete
  ✅ OK       Configurazione Credenziali
  ✅ OK       Test Autenticazione

  Risultato: 7/7 check superati

  🎉 TUTTO OK! Il sistema è configurato correttamente.
  Puoi procedere con l'upload di sottotitoli.
```

---

## 🚀 Utilizzo

### Upload Automatico

Se `auto_upload: true` nel file credenziali:

1. **Elabora video** normalmente tramite GUI
2. **Al termine** della trascrizione/traduzione
3. **Upload automatico** su OpenSubtitles
4. **Verifica duplicati** automatica
5. **Conferma** in log: "✅ Sottotitoli caricati su OpenSubtitles"

### Upload Manuale

**Coming in v1.1.0:** Pulsante "Upload" nel contesto file.

---

## 🔍 Verifica Duplicati

Transcriber Pro **verifica automaticamente** se i sottotitoli esistono già prima dell'upload:

**Metodo verifica:**
1. **Calcolo hash video** (OpenSubtitles hash algorithm)
2. **Query API** per hash + lingua
3. **Se duplicato trovato** → Skip upload con log informativo
4. **Se nuovo** → Procede con upload

**Log esempio (duplicato trovato):**

```
ℹ️ Sottotitoli già presenti su OpenSubtitles
   Video: example_movie.mkv
   Lingua: it
   ID: 1234567
   → Upload saltato per evitare duplicato
```

**Disabilitare check:**

Nel `config.json`:

```json
{
    "opensubtitles_check_duplicates": false
}
```

**⚠️ Non raccomandato:** Potresti violare ToS di OpenSubtitles.

---

## 📊 Metadata Sottotitoli

Transcriber Pro invia automaticamente metadata completi:

### Metadata Obbligatori

- **IMDb ID** - Cercato automaticamente tramite TMDB
- **Lingua** - Rilevata automaticamente (ISO 639-2: "ita", "eng", etc.)
- **Release Name** - Nome file video (es: "Movie.2024.1080p.BluRay.x264")

### Metadata Opzionali

- **Video Hash** - Hash OpenSubtitles (per verifica duplicati)
- **Video Size** - Dimensione file in byte
- **Format** - Formato sottotitoli (default: "srt")
- **Comments** - "Generated by Transcriber Pro v1.0.3"

### Rilevamento Automatico

```
🔍 Ricerca metadata per: The Matrix (1999).mkv
  → TMDB: The Matrix (1999)
  → IMDb ID: tt0133093
  → Lingua: eng (rilevata da audio)
  → Release: The.Matrix.1999.1080p.BluRay.x264-GROUP
✅ Metadata completi
```

---

## ⚠️ Troubleshooting

### Errore: "Autenticazione fallita"

**Possibili cause:**
1. Username o password errati
2. Account non attivato (verifica email)
3. API Key mancante o errata (per REST)

**Soluzione:**
```bash
# 1. Verifica credenziali su web
https://www.opensubtitles.org/en/login

# 2. Controlla file configurazione
cat ~/.transcriberpro/opensubtitles_credentials.json

# 3. Testa autenticazione
python verify_opensubtitles_setup.py
```

---

### Errore: "API Key non valida"

**Causa:** API Key errata o scaduta

**Soluzione:**
1. Vai su https://www.opensubtitles.com/consumers
2. Verifica API Key attiva
3. Se scaduta, crea nuova Consumer
4. Aggiorna `opensubtitles_credentials.json`

---

### Errore: "Rate limit exceeded"

**Causa:** Troppi upload in poco tempo

**Limiti OpenSubtitles:**
- **Account Free:** 10 upload/giorno, 200 query/giorno
- **VIP:** Limiti più alti

**Soluzione:**
- Attendi 24h
- Considera account VIP se usi intensivamente

---

### Errore: "Duplicate subtitle"

**Causa:** Sottotitoli già presenti per questo video

**Comportamento:**
- Con `check_duplicates: true` → Skip automatico (nessun errore)
- Con `check_duplicates: false` → Upload fallisce

**Soluzione:**
- È normale! I sottotitoli esistono già
- Verifica su OpenSubtitles se vuoi vedere chi li ha caricati

---

### Errore: "IMDb ID not found"

**Causa:** Impossibile trovare IMDb ID per il video

**Soluzione:**
```bash
# Rinomina file video con anno
# Invece di: movie.mkv
# Usa: The Matrix (1999).mkv

# Oppure specifica manualmente IMDb ID (v1.1.0+)
```

---

### Connessione fallita

**Errore:**
```
❌ Errore connessione: [Errno 11001] getaddrinfo failed
```

**Possibili cause:**
1. Nessuna connessione internet
2. Firewall blocca api.opensubtitles.org
3. Proxy aziendale

**Soluzione:**

```bash
# Test connessione manuale
ping api.opensubtitles.org

# Test con curl
curl -I https://api.opensubtitles.com

# Se sei dietro proxy, configura:
# Windows
set HTTPS_PROXY=http://proxy:port

# Linux/Mac
export HTTPS_PROXY=http://proxy:port
```

---

## 🔐 Sicurezza

### Best Practices

1. ✅ **Usa file JSON** con permessi ristretti
   ```bash
   # Linux/Mac
   chmod 600 ~/.transcriberpro/opensubtitles_credentials.json
   ```

2. ✅ **Password unica** per OpenSubtitles

3. ✅ **NON committare** file credenziali su Git
   - Già escluso da `.gitignore`

4. ✅ **Backup sicuro** delle credenziali
   - Salva API Key in password manager

5. ✅ **Rigenera API Key** se compromessa
   - Vai su https://www.opensubtitles.com/consumers
   - Elimina vecchio Consumer
   - Crea nuovo Consumer

### Dove sono salvati i dati?

**File credenziali:**
```
~/.transcriberpro/opensubtitles_credentials.json  (locale)
```

**File config:**
```
~/.transcriberpro/config.json  (locale)
```

**⚠️ Le credenziali NON vengono mai:**
- Inviate a server terzi (solo OpenSubtitles)
- Loggate in chiaro
- Committate su repository
- Condivise con altri utenti

---

## 📈 Monitoraggio Upload

### Log Upload

Ogni upload genera log dettagliati:

```
========================================
📤 UPLOAD OPENSUBTITLES
========================================
Video: The Matrix (1999).mkv
IMDb ID: tt0133093
Lingua: ita
Release: The.Matrix.1999.1080p.BluRay.x264

🔐 Autenticazione...
✅ Login riuscito

🔍 Verifica duplicati...
✅ Nessun duplicato trovato

📤 Upload in corso...
  Dimensione: 125.4 KB
  Hash: 8f7e9c2d1a3b4e5f6g7h8i9j0k1l2m3n
  
✅ Upload completato con successo!
   ID Sottotitoli: 1234567890
   URL: https://www.opensubtitles.org/it/subtitles/1234567890

🏆 Grazie per contribuire a OpenSubtitles!
========================================
```

### Statistiche

**Coming in v1.1.0:** Dashboard statistiche upload.

---

## 🎓 FAQ

### Q: Devo pagare per OpenSubtitles?

**A:** No, l'account base è gratuito. Account VIP offre limiti più alti ma è opzionale.

### Q: Posso usare senza API Key?

**A:** Sì, usa XML-RPC (legacy) senza API Key. Ma REST è raccomandato.

### Q: I sottotitoli sono pubblici?

**A:** Sì, OpenSubtitles è un database pubblico. I tuoi sottotitoli saranno visibili a tutti.

### Q: Posso disabilitare upload?

**A:** Sì, in `config.json`:
```json
{
    "opensubtitles_upload_enabled": false
}
```

### Q: Come elimino sottotitoli caricati per errore?

**A:** Vai su OpenSubtitles.org → Login → My Subtitles → Delete

### Q: Posso caricare manualmente?

**A:** In v1.0.3 solo auto-upload. Upload manuale in v1.1.0.

### Q: Limiti di dimensione file?

**A:** OpenSubtitles: Max 5MB per file SRT (abbondante!)

### Q: Formati supportati?

**A:** Transcriber Pro genera solo SRT (formato standard).

---

## 🔄 Migrazione da v1.0.2

Se usavi Transcriber Pro v1.0.2 con OpenSubtitles:

### Cosa cambia?

1. **API Key richiesta** per REST
2. **File configurazione** con formato diverso
3. **Test connessione** disponibile

### Migrazione Step-by-Step

1. **Ottieni API Key:**
   ```
   https://www.opensubtitles.com/consumers
   ```

2. **Crea nuovo file JSON:**
   ```json
   {
       "username": "tuo_vecchio_username",
       "password": "tua_vecchia_password",
       "api_key": "NUOVA_API_KEY",
       "auto_upload": true
   }
   ```

3. **Salva in:**
   ```
   ~/.transcriberpro/opensubtitles_credentials.json
   ```

4. **Testa:**
   ```bash
   python verify_opensubtitles_setup.py
   ```

5. **Elimina vecchi file** (se presenti):
   ```bash
   rm ~/.transcriberpro/opensubtitles_credentials.txt
   ```

**Note:** XML-RPC continua a funzionare senza API Key per backward compatibility.

---

## 📚 Risorse Aggiuntive

### Link Utili

- **OpenSubtitles:** https://www.opensubtitles.org
- **API Documentation:** https://opensubtitles.stoplight.io
- **Consumers (API Keys):** https://www.opensubtitles.com/consumers
- **Support Forum:** https://forum.opensubtitles.org

### Script Utility

**Verifica setup completo:**
```bash
python verify_opensubtitles_setup.py
```

**Test autenticazione manuale:**
```bash
python test_auth_real.py
```

### Codice Sorgente

- `utils/opensubtitles_rest_uploader.py` - Implementazione REST
- `utils/opensubtitles_xmlrpc_uploader.py` - Implementazione legacy
- `utils/subtitle_uploader_interface.py` - Interfaccia astratta
- `utils/opensubtitles_config.py` - Gestione credenziali

---

## 🆘 Supporto

### Hai bisogno di aiuto?

1. **Controlla questa guida** per soluzioni comuni
2. **Esegui verifica setup:**
   ```bash
   python verify_opensubtitles_setup.py
   ```
3. **Controlla log** in `logs/transcriber.log`
4. **Apri issue** su GitHub con log completo

### Report Bug

GitHub Issues: https://github.com/chinasky71-byte/Transcriptor-Pro/issues

Includi sempre:
- Output `verify_opensubtitles_setup.py`
- Log completo errore
- Versione Transcriber Pro
- Sistema operativo

---

## 🎉 Contribuisci!

Aiutaci a migliorare la guida:

- **Hai trovato un errore?** → Apri PR
- **Manca qualcosa?** → Apri issue
- **Suggerimenti?** → GitHub Discussions

---

<div align="center">

**Grazie per usare Transcriber Pro!** 🎬

**Made with ❤️ for the subtitle community**

[← Torna alla Home](../README.md) | [Troubleshooting →](TROUBLESHOOTING.md) | [Guida Utente →](GUIDA_UTENTE.md)

</div>
