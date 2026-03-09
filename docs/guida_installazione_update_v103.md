# 📝 Aggiornamento GUIDA_INSTALLAZIONE.md - v1.0.3

## Sezione da Aggiungere: Configurazione OpenSubtitles

Inserisci questa sezione **dopo** il capitolo "Verifica Installazione" e **prima** di "Primo Avvio".

---

## 🌐 Configurazione OpenSubtitles (Opzionale)

### Perché Configurare OpenSubtitles?

**Vantaggi:**
- ✅ Contribuisci alla community mondiale dei sottotitoli
- ✅ Upload automatico dopo ogni elaborazione
- ✅ I tuoi sottotitoli saranno disponibili per milioni di utenti
- ✅ Metadata TMDB/IMDb automatici per massima visibilità

**⚠️ Completamente Opzionale:**
- L'app funziona perfettamente anche senza OpenSubtitles
- Puoi configurarlo in qualsiasi momento
- Puoi disabilitarlo quando vuoi

---

### Prerequisiti

Prima di iniziare, assicurati di avere:

- [x] Transcriber Pro v1.0.3+ installato
- [x] Connessione internet attiva
- [x] 5 minuti di tempo
- [x] Email valida (per registrazione)

---

### Step 1: Registrazione OpenSubtitles

**1.1 Vai sulla pagina di registrazione:**

```
https://www.opensubtitles.org/en/newuser
```

**1.2 Compila il form:**

- **Username:** Scegli un username unico
- **Email:** La tua email (verrà verificata)
- **Password:** Password sicura
- **Repeat Password:** Ripeti password

**1.3 Conferma registrazione:**

1. Click **"Register"**
2. Controlla email (anche spam!)
3. Click sul link di verifica
4. ✅ Account attivato

---

### Step 2: Ottenere API Key (REST)

**⭐ Nuovo in v1.0.3:** REST API richiede API Key

**2.1 Login su OpenSubtitles:**

```
https://www.opensubtitles.com/login
```

**2.2 Vai alla pagina Consumers:**

```
https://www.opensubtitles.com/consumers
```

**2.3 Crea nuovo Consumer:**

1. Click **"Create Consumer"**
2. Compila form:
   - **App Name:** `Transcriber Pro`
   - **Description:** `Personal video transcription tool`
   - **Purpose:** Seleziona `Personal use`
3. Click **"Create"**

**2.4 Salva API Key:**

⚠️ **IMPORTANTE:** L'API Key appare **UNA SOLA VOLTA**!

```
Copia e salva la chiave in un posto sicuro!
Esempio: eY8xK2pN5mQ9sT4wV7zA1bC3fD6gH0jL
```

**💡 Tip:** Usa un password manager per salvare l'API Key

---

### Step 3: Creare File Credenziali

#### Opzione A: File JSON (Raccomandato) ⭐

**3.1 Crea directory configurazione:**

**Windows (PowerShell):**
```powershell
# Crea directory se non esiste
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.transcriberpro"

# Verifica creazione
Test-Path "$env:USERPROFILE\.transcriberpro"
# Output: True
```

**Linux/Mac:**
```bash
# Crea directory
mkdir -p ~/.transcriberpro

# Verifica
ls -la ~/.transcriberpro
```

**3.2 Crea file JSON:**

**Windows (Notepad):**

1. Apri **Notepad**
2. Copia questo template:

```json
{
    "username": "TUO_USERNAME",
    "password": "TUA_PASSWORD",
    "api_key": "TUA_API_KEY_QUI",
    "auto_upload": true
}
```

3. **Sostituisci** i valori:
   - `TUO_USERNAME` → Il tuo username OpenSubtitles
   - `TUA_PASSWORD` → La tua password
   - `TUA_API_KEY_QUI` → L'API Key dal Step 2

4. **Salva come:**
   - Nome file: `opensubtitles_credentials.json`
   - Tipo: **Tutti i file** (non .txt!)
   - Percorso: `C:\Users\TUO_USERNAME\.transcriberpro\`

**Esempio file completo:**

```json
{
    "username": "mario_rossi",
    "password": "MiaPassword123!",
    "api_key": "eY8xK2pN5mQ9sT4wV7zA1bC3fD6gH0jL",
    "auto_upload": true
}
```

**Linux/Mac:**

```bash
# Crea file con editor
nano ~/.transcriberpro/opensubtitles_credentials.json

# Incolla template sopra
# CTRL+O per salvare
# CTRL+X per uscire

# Verifica file
cat ~/.transcriberpro/opensubtitles_credentials.json
```

---

#### Opzione B: File TXT (Semplice)

**⚠️ Limitazioni:** Solo XML-RPC, no REST API

**Windows:**

1. Notepad → Nuovo file
2. Scrivi **2 righe**:
   ```
   tuo_username
   tua_password
   ```
3. Salva come:
   - Nome: `opensubtitles_credentials.txt`
   - Percorso: `C:\Users\TUO_USERNAME\.transcriberpro\`

**Linux/Mac:**

```bash
# Crea file
cat > ~/.transcriberpro/opensubtitles_credentials.txt << EOF
tuo_username
tua_password
EOF

# Verifica
cat ~/.transcriberpro/opensubtitles_credentials.txt
```

---

### Step 4: Configurare Preferenze

**4.1 Verifica/Crea config principale:**

**File:** `~/.transcriberpro/config.json`

**Windows:** `C:\Users\TUO_USERNAME\.transcriberpro\config.json`

**Se non esiste, verrà creato automaticamente al primo avvio.**

**4.2 Opzioni OpenSubtitles nel config:**

```json
{
    "opensubtitles_upload_enabled": true,
    "opensubtitles_auto_upload": true,
    "opensubtitles_check_duplicates": true,
    "opensubtitles_preferred_implementation": "rest",
    "opensubtitles_api_key": ""
}
```

**Parametri:**

- `upload_enabled` - Abilita/disabilita upload globalmente
- `auto_upload` - Upload automatico al termine elaborazione
- `check_duplicates` - Verifica se sottotitoli esistono già
- `preferred_implementation` - `"rest"` (moderno) o `"xmlrpc"` (legacy)
- `api_key` - Lascia vuoto (letto da credentials.json)

**💡 Note:**
- Non serve editare il config manualmente
- I valori di default vanno bene per la maggior parte degli utenti
- Le credenziali vengono lette dal file `opensubtitles_credentials.json`

---

### Step 5: Verifica Setup

**5.1 Esegui script di verifica:**

```bash
# Windows (PowerShell)
cd C:\Users\TUO_USERNAME\Desktop\Transcriber_Pro
python verify_opensubtitles_setup.py

# Linux/Mac
cd ~/Transcriber_Pro
python verify_opensubtitles_setup.py
```

**5.2 Output atteso (tutto OK):**

```
======================================================================
  🔍 VERIFICA SETUP OPENSUBTITLES UPLOAD
======================================================================

======================================================================
  🔍 VERIFICA DIPENDENZE
======================================================================
  ✅ xmlrpc.client       [Standard Library]
  ✅ hashlib             [Standard Library]
  ...

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

======================================================================
  🔑 TEST AUTENTICAZIONE
======================================================================
  ✅ Login riuscito
     Token: [GENERATO]

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

**5.3 Se ci sono errori:**

```
❌ Autenticazione fallita

Possibili cause:
  • Username o password errati
  • Account non attivato (verifica email)
  • API Key mancante o errata
```

**Fix:**
1. Verifica username/password su https://www.opensubtitles.org/login
2. Controlla API Key su https://www.opensubtitles.com/consumers
3. Verifica file `opensubtitles_credentials.json`
4. Ri-esegui verifica

---

### Step 6: Test Upload

**6.1 Avvia Transcriber Pro:**

```bash
# Windows
python main.py

# Linux/Mac
python main.py
```

**6.2 Elabora un video di test:**

1. Aggiungi un video breve (es. 5 minuti)
2. Click **[▶️ Avvia]**
3. Attendi completamento elaborazione
4. Controlla log:

```
========================================
📤 UPLOAD OPENSUBTITLES
========================================
🔐 Autenticazione REST API...
✅ Login riuscito

🔍 Ricerca metadata...
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

**✅ Se vedi questo → Setup completato con successo!**

---

### Troubleshooting Setup

#### File non trovato

**Errore:**
```
⚠️ File credenziali non trovato
```

**Verifica percorsi:**

**Windows:**
```powershell
# Verifica esistenza file
Test-Path "$env:USERPROFILE\.transcriberpro\opensubtitles_credentials.json"

# Se False → Crea file
```

**Linux/Mac:**
```bash
# Verifica esistenza
ls ~/.transcriberpro/opensubtitles_credentials.json

# Se non esiste → Crea file
```

---

#### Formato JSON non valido

**Errore:**
```
❌ JSON decode error
```

**Causa:** Sintassi JSON errata

**Fix:**

1. Valida JSON su: https://jsonlint.com
2. Copia template da questa guida
3. Verifica virgole e parentesi
4. **No commenti** nel file JSON!

**JSON Corretto:**
```json
{
    "username": "mario",
    "password": "pass123",
    "api_key": "abc123xyz",
    "auto_upload": true
}
```

**JSON Errato:**
```json
{
    "username": "mario",
    "password": "pass123"  # Errore: manca virgola
    "api_key": "abc123xyz",
    "auto_upload": true,  # Errore: virgola finale
}
```

---

#### Autenticazione fallita

**Errore:**
```
❌ Login failed: Invalid credentials
```

**Checklist:**
1. [ ] Username corretto?
2. [ ] Password corretta?
3. [ ] Account attivato via email?
4. [ ] API Key valida (per REST)?

**Test manuale:**

1. Login su https://www.opensubtitles.org
2. Se funziona → Problema è nel file JSON
3. Se non funziona → Reset password

---

#### API Key non valida

**Errore:**
```
❌ Invalid API Key
```

**Fix:**

1. Vai su https://www.opensubtitles.com/consumers
2. Verifica Consumer attivo
3. Se scaduto/eliminato → Crea nuovo Consumer
4. Copia nuova API Key
5. Aggiorna file `opensubtitles_credentials.json`
6. Riavvia Transcriber Pro

---

### Disabilitare OpenSubtitles

Se vuoi disabilitare temporaneamente:

**Opzione 1: Toggle GUI**
```
Click [📤 OpenSubtitles: ON] → Diventa OFF
```

**Opzione 2: Config file**

Edita `~/.transcriberpro/config.json`:
```json
{
    "opensubtitles_upload_enabled": false
}
```

**Opzione 3: Elimina credenziali**

**Windows:**
```powershell
Remove-Item "$env:USERPROFILE\.transcriberpro\opensubtitles_credentials.json"
```

**Linux/Mac:**
```bash
rm ~/.transcriberpro/opensubtitles_credentials.json
```

---

### Guide Aggiuntive

Per saperne di più su OpenSubtitles:

- 🚀 [Quick Start (5 minuti)](OPENSUBTITLES_QUICKSTART.md)
- 🌐 [Guida Completa REST API](GUIDA_OPENSUBTITLES_REST_API.md)
- 📖 [Guida Utente - Sezione Upload](GUIDA_UTENTE.md#upload-opensubtitles)
- 🐛 [Troubleshooting Completo](TROUBLESHOOTING.md)

---

## ✅ Configurazione Completata!

**Recap:**
- ✅ Account OpenSubtitles creato
- ✅ API Key ottenuta
- ✅ File credenziali configurato
- ✅ Setup verificato
- ✅ Test upload riuscito

**Adesso:**
- 🎬 Elabora video normalmente
- 📤 Upload automatico al termine
- 🌍 Contribuisci alla community!

---

**Continua con:** [Primo Avvio →](#primo-avvio)

---

<div align="center">

**Grazie per contribuire a OpenSubtitles!** ❤️🌍

</div>
