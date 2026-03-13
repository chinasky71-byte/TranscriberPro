# 🚀 OpenSubtitles Quick Start - 5 Minuti

## Setup Ultra-Rapido

Vuoi contribuire alla community OpenSubtitles? Segui questi 5 semplici passaggi!

---

## ⚡ Setup in 5 Passi

### 1️⃣ Crea Account (2 minuti)

```
👉 https://www.opensubtitles.org/en/newuser
```

- Compila form registrazione
- **Verifica email** (controlla spam!)
- ✅ Account attivo

---

### 2️⃣ Ottieni API Key (1 minuto)

```
👉 https://www.opensubtitles.com/consumers
```

1. **Login** con account appena creato
2. Click **"Create Consumer"**
3. Compila:
   - **App Name:** `Transcriber Pro`
   - **Purpose:** `Personal use`
4. Click **"Create"**
5. **Copia API Key** (⚠️ Appare una sola volta!)

---

### 3️⃣ Crea File Credenziali (1 minuto)

**Windows:**

Apri **Notepad** e salva come:
```
C:\Users\TUO_USERNAME\.transcriberpro\opensubtitles_credentials.json
```

**Linux/Mac:**

Apri **editor** e salva come:
```
~/.transcriberpro/opensubtitles_credentials.json
```

**Contenuto file:**

```json
{
    "username": "tuo_username",
    "password": "tua_password",
    "api_key": "TUA_API_KEY_COPIATA",
    "auto_upload": true
}
```

**Sostituisci:**
- `tuo_username` → Il tuo username OpenSubtitles
- `tua_password` → La tua password
- `TUA_API_KEY_COPIATA` → L'API Key del passo 2

**Esempio reale:**

```json
{
    "username": "mario_rossi",
    "password": "MiaPassword123!",
    "api_key": "eY8xK2pN5mQ9sT4wV7zA1bC3fD6gH0jL",
    "auto_upload": true
}
```

---

### 4️⃣ Riavvia Transcriber Pro (10 secondi)

```
1. Chiudi applicazione
2. Riapri
3. ✅ Credenziali caricate automaticamente
```

---

### 5️⃣ Verifica Setup (30 secondi)

**Opzione A: Da Terminale**

```bash
# Windows (PowerShell)
cd C:\Users\TUO_USERNAME\Desktop\Transcriber_Pro
python verify_opensubtitles_setup.py

# Linux/Mac
cd ~/Transcriber_Pro
python verify_opensubtitles_setup.py
```

**Output OK:**
```
🎉 TUTTO OK! Sistema configurato correttamente.
```

**Output Errore:**
```
❌ [Dettaglio errore]
```
→ Controlla username/password/API key

---

**Opzione B: Prova Elaborazione**

```
1. Aggiungi un video
2. Click [▶️ Avvia]
3. Aspetta fine elaborazione
4. Guarda log:
   ✅ "Upload completato su OpenSubtitles!"
```

---

## ✅ Fatto!

Ora ogni volta che elabori un video:

```
🎬 Video elaborato
  → 📝 Sottotitoli generati
  → 📤 Upload automatico OpenSubtitles
  → 🎉 Contribuisci alla community!
```

**Nessuna azione richiesta!** 🚀

---

## 🎛️ Opzioni Aggiuntive

### Disabilitare Upload

**Temporaneo (dalla GUI):**
```
Click [📤 OpenSubtitles: ON] → Diventa OFF
```

**Permanente (config):**

Edita `opensubtitles_credentials.json`:
```json
{
    ...
    "auto_upload": false
}
```

---

### Scegliere Implementazione

**REST (Moderno - Default):**
```json
{
    ...
    "api_key": "YOUR_API_KEY"
}
```

**XML-RPC (Legacy - No API Key):**

Rimuovi `api_key` dal file:
```json
{
    "username": "tuo_username",
    "password": "tua_password",
    "auto_upload": true
}
```

E configura in `~/.transcriberpro/config.json`:
```json
{
    "opensubtitles_preferred_implementation": "xmlrpc"
}
```

---

## 🐛 Problemi Comuni

### "Autenticazione fallita"

**Causa:** Username o password errati

**Fix:**
1. Login manuale su https://www.opensubtitles.org
2. Se funziona → Verifica credenziali in file JSON
3. Se non funziona → Reset password

---

### "API Key non valida"

**Causa:** API Key errata o scaduta

**Fix:**
1. Vai su https://www.opensubtitles.com/consumers
2. Verifica Consumer attivo
3. Se scaduto → Crea nuovo Consumer
4. Copia nuova API Key
5. Aggiorna file JSON

---

### "File credenziali non trovato"

**Causa:** Path file errato

**Fix:**

**Windows:** Assicurati di salvare in:
```
C:\Users\TUO_USERNAME\.transcriberpro\opensubtitles_credentials.json
```

**Nota:** `.transcriberpro` inizia con punto!

**Linux/Mac:** Assicurati di salvare in:
```
~/.transcriberpro/opensubtitles_credentials.json
```

**Nota:** `~` = home directory

---

### "Rate limit exceeded"

**Causa:** Troppi upload in un giorno

**Limiti:**
- Account Free: 10 upload/giorno

**Fix:**
- Attendi 24h
- Oppure: Account VIP (opzionale, a pagamento)

---

## 📚 Guide Complete

Vuoi sapere di più?

- 🌐 [Guida Completa OpenSubtitles REST API](GUIDA_OPENSUBTITLES_REST_API.md)
- 📖 [Guida Utente Generale](GUIDA_UTENTE.md)
- 🐛 [Troubleshooting](TROUBLESHOOTING.md)

---

## 🆘 Serve Aiuto?

1. **Esegui verifica:**
   ```bash
   python verify_opensubtitles_setup.py
   ```

2. **Leggi output errore**

3. **Cerca soluzione** in questa guida

4. **Ancora bloccato?**
   - GitHub Issues: https://github.com/chinasky71-byte/Transcriptor-Pro/issues

---

<div align="center">

**Setup completato! Buon upload!** 📤🎉

**Grazie per contribuire a OpenSubtitles!** ❤️

[← Torna alla Guida Utente](GUIDA_UTENTE.md)

</div>
