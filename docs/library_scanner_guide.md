# Library Scanner — Guida Completa

## Indice

1. [Cos'è il Library Scanner](#cosè-il-library-scanner)
2. [Architettura](#architettura)
3. [Prerequisiti](#prerequisiti)
4. [Installazione con Docker](#installazione-con-docker)
5. [Configurazione docker-compose.yml](#configurazione-docker-composeyml)
6. [Adattamento ad altre macchine](#adattamento-ad-altre-macchine)
7. [Primo avvio e accesso web](#primo-avvio-e-accesso-web)
8. [Web Dashboard](#web-dashboard)
9. [Configurare Transcriber Pro](#configurare-transcriber-pro)
10. [Scansione automatica](#scansione-automatica)
11. [API Reference](#api-reference)
12. [Troubleshooting](#troubleshooting)

---

## Cos'è il Library Scanner

Il **Library Scanner** è un servizio Docker self-hosted che scansiona le tue directory multimediali (film e serie TV), rileva i video privi di sottotitoli in italiano, e li rende disponibili in Transcriber Pro per l'elaborazione in batch.

**Flusso di lavoro:**

```
Server Linux/NAS con Docker
         ↓
Library Scanner scansiona le cartelle media ogni 24h
         ↓
Identifica video senza sottotitoli italiani
(controlla sia file .srt esterni sia tracce embedded)
         ↓
REST API espone la lista dei video mancanti
         ↓
Transcriber Pro (Windows) si connette via HTTP
         ↓
L'utente vede la lista e importa i video con un click
```

**Cosa rileva:**
- File `.srt` / `.ass` / `.sub` esterni con tag lingua italiana (`.it.srt`, `.ita.srt`, etc.)
- Tracce subtitle embedded in MKV/MP4 con lingua `ita` / `it` / `italian` (via ffprobe)

---

## Architettura

```
┌─────────────────────────────────────────────────────┐
│              Docker Container (Linux)               │
│                                                     │
│  ┌──────────────┐    ┌──────────────┐               │
│  │  FastAPI     │    │  APScheduler │               │
│  │  REST API    │    │  (scan ogni  │               │
│  │  :6680       │    │   24 ore)    │               │
│  └──────┬───────┘    └──────┬───────┘               │
│         │                  │                        │
│  ┌──────▼──────────────────▼───────┐               │
│  │         SQLite Database         │               │
│  │  (VideoFile, ScanDirectory,     │               │
│  │   ScanLog, SystemConfig)        │               │
│  └─────────────────────────────────┘               │
│                                                     │
│  Volumi montati (read-only):                        │
│    /mnt/movies  →  /srv/dischi/MOVIES              │
│    /mnt/tvshows →  /srv/dischi/TV SHOWS            │
│                                                     │
└─────────────────────────────────────────────────────┘
               ↑ HTTP :6680
┌──────────────────────────────────┐
│  Transcriber Pro (Windows)       │
│  LibraryScannerWidget (PyQt6)    │
│  → GET /api/videos               │
│  → GET /api/stats                │
└──────────────────────────────────┘
```

**Componenti principali:**

| File | Ruolo |
|------|-------|
| `api/main.py` | FastAPI REST API + web dashboard |
| `scanner.py` | Logica di scansione delle directory |
| `subtitle_checker.py` | Rilevamento sottotitoli (ffprobe + regex) |
| `scheduler.py` | Scansione automatica periodica |
| `auth.py` | Autenticazione (API key + sessioni web) |
| `models.py` | Modelli SQLAlchemy (SQLite) |
| `config.py` | Variabili d'ambiente |

---

## Prerequisiti

### Sul server (Linux / NAS)

- **Docker Engine** 20.10+ e **Docker Compose** v2
- Accesso alla rete locale (porta 6680 raggiungibile dal PC Windows)
- Cartelle media montate/accessibili dal server

### Sul PC Windows (Transcriber Pro)

- Transcriber Pro installato e funzionante
- Connessione alla stessa rete locale del server

---

## Installazione con Docker

### Step 1: Copiare i file sul server

Copia la cartella `library_scanner/` sul server Linux, ad esempio in:

```
/opt/library-scanner/
```

La struttura deve essere:

```
/opt/library-scanner/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── library_scanner/
    ├── __init__.py
    ├── api/
    │   └── main.py
    ├── auth.py
    ├── config.py
    ├── database.py
    ├── models.py
    ├── scanner.py
    ├── scheduler.py
    └── subtitle_checker.py
```

### Step 2: Creare la directory dati

```bash
mkdir -p /opt/library-scanner/data/db
mkdir -p /opt/library-scanner/data/logs
```

### Step 3: Configurare docker-compose.yml

Vedi la sezione successiva per le modifiche necessarie.

### Step 4: Build e avvio

```bash
cd /opt/library-scanner
docker compose up -d --build
```

Verifica che il container sia avviato:

```bash
docker compose ps
docker compose logs -f
```

Il servizio è pronto quando nei log appare:

```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:6680
INFO:     Application startup complete.
```

---

## Configurazione docker-compose.yml

Il file `docker-compose.yml` deve essere adattato alla propria macchina. Ecco la struttura completa con spiegazione di ogni sezione modificabile:

```yaml
services:
  library-scanner:
    build: .
    container_name: library-scanner
    restart: unless-stopped

    ports:
      # [PORTA_HOST]:[PORTA_CONTAINER]
      # Modifica solo la parte sinistra se la 6680 è già occupata
      - "6680:6680"

    volumes:
      # Dati persistenti (DB + log) — NON modificare la parte destra
      - ./data:/app/data

      # ============================================================
      # DIRECTORY MEDIA — DA ADATTARE ALLA PROPRIA MACCHINA
      # Formato: "[percorso_linux_reale]:[percorso_container]:ro"
      # Il :ro rende il mount read-only (consigliato per sicurezza)
      # ============================================================

      # Esempio: cartella film
      - "/srv/dischi/DISCO2/MOVIES:/mnt/movies:ro"

      # Esempio: seconda cartella film
      - "/srv/dischi/FILM_2:/mnt/film2:ro"

      # Esempio: cartella serie TV
      - "/srv/dischi/TV SHOWS:/mnt/tvshows:ro"

      # Aggiungi qui tutte le directory media necessarie

    environment:
      # Timezone del server
      - TZ=Europe/Rome

      # Percorsi interni al container — NON modificare
      - SCANNER_DB_PATH=/app/data/db/library_scanner.db
      - SCANNER_LOG_PATH=/app/data/logs
      - SCANNER_PORT=6680

      # ============================================================
      # OPZIONALE: Credenziali personalizzate
      # Se non specificati, vengono generati automaticamente
      # ============================================================

      # - SCANNER_ADMIN_USER=admin
      # - SCANNER_ADMIN_PASSWORD=la_tua_password
      # - SCANNER_API_KEY=la_tua_api_key

      # ============================================================
      # OPZIONALE: Parametri di scansione
      # ============================================================

      # Intervallo scansione automatica (ore, default: 24)
      # - SCANNER_INTERVAL_HOURS=24

      # Dimensione minima file video in MB (default: 50)
      # - SCANNER_MIN_FILE_MB=50

      # Ore silenziose: non avvia scan tra START e END (-1 = disabilitato)
      # - SCANNER_QUIET_START=23
      # - SCANNER_QUIET_END=6

    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Adattamento ad altre macchine

### 1. Percorsi delle directory media

Questa è la modifica principale. Ogni macchina ha percorsi diversi.

**Caso tipico:** media su un disco montato in `/mnt` o `/srv`

```yaml
volumes:
  - "./data:/app/data"
  - "/mnt/storage/Movies:/mnt/movies:ro"
  - "/mnt/storage/Series:/mnt/tvshows:ro"
```

**Caso NAS Synology:** percorsi tipo `/volume1/`

```yaml
volumes:
  - "./data:/app/data"
  - "/volume1/video/Films:/mnt/movies:ro"
  - "/volume1/video/Series:/mnt/tvshows:ro"
```

**Caso NAS QNAP:** percorsi tipo `/share/`

```yaml
volumes:
  - "./data:/app/data"
  - "/share/Multimedia/Films:/mnt/movies:ro"
  - "/share/Multimedia/Series:/mnt/tvshows:ro"
```

**Caso media su SMB/NFS già montati:**

```yaml
volumes:
  - "./data:/app/data"
  - "/mnt/nas/films:/mnt/movies:ro"
  - "/mnt/nas/tvshows:/mnt/tvshows:ro"
```

> **Importante:** il percorso a destra del `:` (dentro il container) puoi sceglierlo liberamente, ma deve essere registrato nel database come **Linux Path** della directory (vedi sezione Web Dashboard). La parte a sinistra deve esistere sul server host.

---

### 2. Porta di rete

Se la porta `6680` è già usata sul server:

```yaml
ports:
  - "8080:6680"   # Usa 8080 sul host, rimane 6680 nel container
```

Ricordati poi di aggiornare l'URL in Transcriber Pro:
```
http://192.168.1.18:8080
```

---

### 3. Windows path per l'accesso da Transcriber Pro

Il Library Scanner memorizza sia il **percorso Linux** (dentro il container) sia il **percorso Windows** corrispondente (per permettere a Transcriber Pro di aprire/processare i file).

Quando aggiungi una directory dalla web dashboard, specifica entrambi:

| Campo | Esempio |
|-------|---------|
| **Linux Path** | `/mnt/movies` |
| **Windows Path** | `\\192.168.1.18\movies` oppure `Z:\movies` |

Il **Windows Path** è il percorso UNC (rete) o mappato con cui il PC Windows raggiunge la stessa cartella. Transcriber Pro userà questo percorso per elaborare i file.

---

### 4. Timezone

Modifica `TZ` con la tua timezone:

```yaml
environment:
  - TZ=Europe/Rome       # Italia
  - TZ=Europe/London     # UK
  - TZ=America/New_York  # USA Est
```

Lista completa: [en.wikipedia.org/wiki/List_of_tz_database_time_zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

---

## Primo avvio e accesso web

### Ottenere le credenziali generate automaticamente

Al primo avvio, il container genera automaticamente password e API key. Recuperale dai log:

```bash
docker compose logs library-scanner | grep -E "password|api.key|API.Key" -i
```

Oppure entra nel container:

```bash
docker exec -it library-scanner python -c "
from library_scanner.database import get_db
from library_scanner.models import SystemConfig
with get_db() as db:
    for k in ['admin_password_hash', 'api_key']:
        r = db.query(SystemConfig).filter_by(key=k).first()
        print(k, ':', r.value if r else 'non trovato')
"
```

> **Consiglio:** imposta credenziali personalizzate tramite variabili d'ambiente in `docker-compose.yml` per evitare di doverle recuperare.

### Accesso al web dashboard

Apri nel browser (dal PC Windows o da qualsiasi device in rete):

```
http://[IP_SERVER]:6680
```

Es: `http://192.168.1.18:6680`

Login con `admin` / `[password generata o impostata]`.

---

## Web Dashboard

### Sezione: Directories

Gestisce le cartelle da scansionare.

**Aggiungere una directory:**

1. Clicca **"Add Directory"**
2. Compila i campi:

| Campo | Descrizione | Esempio |
|-------|-------------|---------|
| **Label** | Nome descrittivo | `Film 4K` |
| **Linux Path** | Percorso nel container | `/mnt/movies` |
| **Windows Path** | Percorso UNC per il client | `\\192.168.1.18\movies` |
| **Media Type** | `movie` o `tvshow` | `movie` |
| **Recursive** | Scansiona sottocartelle | ✅ abilitato |
| **Enabled** | Abilita la scansione | ✅ abilitato |

> Il **Linux Path** deve corrispondere esattamente al mount point definito in `docker-compose.yml`.

---

### Sezione: Videos

Lista di tutti i video rilevati, filtrabili per:
- **Tipo**: Film / Serie TV / Tutti
- **Stato**: Solo senza sottotitoli / Tutti
- **Ricerca**: per nome file

Ogni voce mostra: nome file, tipo, dimensione, giorni senza sottotitoli, data primo rilevamento.

---

### Sezione: Scan

**Avvio manuale scansione:**

Clicca **"Start Scan"** per avviare immediatamente una scansione di tutte le directory abilitate.

**Progresso:**
- Mostra directory corrente, file trovati, file aggiornati, errori
- La scansione può essere annullata con **"Cancel Scan"**

**Storico scansioni:**
- Ogni scansione viene registrata con: data/ora, durata, file trovati/aggiornati, errori

---

### Sezione: Settings / Security

- **Change Password**: cambia la password admin
- **Regenerate API Key**: genera una nuova API key (attenzione: invalida quella vecchia — aggiorna Transcriber Pro)

---

## Configurare Transcriber Pro

### Step 1: Recupera l'API Key

Dal web dashboard: **Settings → Security → API Key** (la trovi visualizzata)

Oppure via API:
```
GET http://[IP]:6680/api/security/api-key
Header: X-API-Key: [api_key_corrente]
```

### Step 2: Configura in Transcriber Pro

In **Settings → Library Scanner**:

| Campo | Valore |
|-------|--------|
| **Server URL** | `http://192.168.1.18:6680` |
| **API Key** | La key generata dal server |

Clicca **Save**. Il widget Library Scanner nella finestra principale si attiverà con un indicatore verde di connessione.

### Step 3: Utilizzo nel workflow

1. Nella finestra principale, espandi il pannello **Library Scanner** (clic sul triangolo ▶)
2. Attendi il caricamento della lista video
3. Filtra per tipo (Film / Serie TV) o cerca per nome
4. Clicca **➕** su un singolo video per importarlo nella coda
5. Oppure clicca **"Import All Filtered"** per importare tutto ciò che è visibile
6. I video vengono aggiunti alla lista di elaborazione → avvia Trascrizione come al solito

Il widget si aggiorna automaticamente ogni 5 minuti quando è espanso.

---

## Scansione automatica

Il server esegue una scansione automatica ogni **24 ore** (configurabile).

### Cambiare l'intervallo

In `docker-compose.yml`:

```yaml
environment:
  - SCANNER_INTERVAL_HOURS=12    # Ogni 12 ore
```

### Ore silenziose (quiet hours)

Evita scansioni automatiche durante la notte (o qualsiasi orario):

```yaml
environment:
  - SCANNER_QUIET_START=23   # Non avviare scan dopo le 23:00
  - SCANNER_QUIET_END=7      # Riprendere dalle 07:00
```

Funziona anche per range che attraversano la mezzanotte (es: 23→6).

Se una scansione era già in corso quando inizia la finestra silenziosa, viene completata normalmente — le ore silenziose impediscono solo l'**avvio** di nuove scansioni.

### Verifica scheduler

Dalla web dashboard vai su **Scan → Scheduler Status** per vedere:
- Stato (running/stopped)
- Intervallo impostato
- Data e ora della prossima scansione

---

## API Reference

Tutte le richieste (tranne `/health`) richiedono l'header:

```
X-API-Key: [la_tua_api_key]
```

### Endpoints principali

#### GET /health
Healthcheck Docker — non richiede autenticazione.
```json
{"status": "ok"}
```

#### GET /api/stats
Statistiche della libreria.
```json
{
  "total_files": 150,
  "with_subs": 95,
  "without_subs": 55,
  "total_size_gb": 250.5,
  "directories": [
    {"label": "Movies", "total": 80, "without_subs": 25, "enabled": true}
  ],
  "last_scan": {
    "started_at": "2025-03-09T14:00:00",
    "status": "completed",
    "duration_seconds": 180
  }
}
```

#### GET /api/videos
Lista video, con filtri opzionali.

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `no_subs_only` | bool | `true` | Solo video senza sottotitoli italiani |
| `media_type` | string | — | `movie` o `tvshow` (ometti per tutti) |
| `search` | string | — | Filtro per nome file |
| `sort_by` | string | `first_seen` | `first_seen`, `filename`, `file_size` |
| `sort_order` | string | `desc` | `asc` o `desc` |
| `limit` | int | `100` | Risultati per pagina (max 1000) |
| `offset` | int | `0` | Offset per paginazione |

Esempio risposta:
```json
{
  "total": 55,
  "count": 50,
  "offset": 0,
  "limit": 100,
  "videos": [
    {
      "id": 1,
      "filename": "The.Movie.2024.1080p.mkv",
      "windows_path": "\\\\192.168.1.18\\movies\\The.Movie.2024.1080p.mkv",
      "linux_path": "/mnt/movies/The.Movie.2024.1080p.mkv",
      "file_size_mb": 2150.5,
      "media_type": "movie",
      "has_italian_srt": false,
      "has_italian_embedded": false,
      "days_without_subs": 45,
      "first_seen": "2025-01-23T10:30:00"
    }
  ]
}
```

#### POST /api/scan/start
Avvia una scansione manuale immediatamente.
```json
{"message": "Scan started"}
```

#### GET /api/scan/status
Stato della scansione corrente.
```json
{
  "is_running": true,
  "current_directory": "/mnt/movies",
  "files_found": 45,
  "files_new": 3,
  "errors": 0
}
```

#### GET /api/directories
Lista delle directory configurate.

#### POST /api/directories
Aggiungi una directory.
```json
{
  "label": "Film 4K",
  "linux_path": "/mnt/4k",
  "windows_path": "\\\\192.168.1.18\\4k",
  "media_type": "movie",
  "recursive": true,
  "enabled": true
}
```

---

## Troubleshooting

### Il container non si avvia

```bash
docker compose logs library-scanner
```

**Causa comune:** percorso di un volume non esistente sul server host.

```
Error response from daemon: invalid mount config: bind source path does not exist
```

**Soluzione:** verifica che tutti i percorsi nella sezione `volumes:` esistano sul server host:
```bash
ls /srv/dischi/MOVIES/
```

---

### Il container si avvia ma la web dashboard non è raggiungibile

**Verifica:**
```bash
# Controlla che la porta sia in ascolto
docker compose ps
# Deve mostrare: 0.0.0.0:6680->6680/tcp

# Testa in locale sul server
curl http://localhost:6680/health
```

**Causa comune:** firewall del server che blocca la porta 6680.

```bash
# Ubuntu/Debian con ufw
sudo ufw allow 6680/tcp

# CentOS/RHEL con firewalld
sudo firewall-cmd --add-port=6680/tcp --permanent
sudo firewall-cmd --reload
```

---

### Transcriber Pro mostra "Connection failed"

1. Verifica che il container sia avviato: `docker compose ps`
2. Verifica che l'IP del server sia corretto nelle Settings di Transcriber Pro
3. Testa la connessione manualmente dal PC Windows:
   ```
   curl http://192.168.1.18:6680/health
   ```
4. Verifica che l'API key sia corretta (copia/incolla senza spazi)

---

### La scansione non trova file video

**Verifica che il volume sia montato correttamente:**

```bash
docker exec library-scanner ls /mnt/movies/
```

Se il comando non mostra i tuoi file, il volume non è montato correttamente.

**Verifica che la directory sia configurata nel database:**

Dal web dashboard → Directories: la directory `/mnt/movies` deve essere presente e abilitata.

---

### File non rilevati come "senza sottotitoli" (falsi negativi)

Il sistema cerca sottotitoli italiani in questo modo:

**File esterni:** cerca file con pattern `.it.srt`, `.ita.srt`, `.it.sdh.srt`, `.ita.cc.srt`, etc. nella stessa cartella del video.

**Tracce embedded:** usa ffprobe per leggere i metadati del file. Verifica che ffprobe funzioni:

```bash
docker exec library-scanner ffprobe -version
docker exec library-scanner ffprobe -v quiet -print_format json -show_streams "/mnt/movies/Film.mkv" 2>/dev/null | grep -i lang
```

---

### Aggiornare il container (nuova versione)

```bash
cd /opt/library-scanner
git pull  # o copia i nuovi file manualmente
docker compose down
docker compose up -d --build
```

I dati nel database sono persistenti (nella cartella `./data/`) e non vengono persi.

---

### Reset completo (incluso database)

```bash
docker compose down
rm -rf ./data/db/library_scanner.db
docker compose up -d
```

Attenzione: questo cancella tutte le directory configurate e la cronologia delle scansioni. Le credenziali vengono rigenerate.

---

## Riferimento variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `SCANNER_HOST` | `0.0.0.0` | Indirizzo di bind |
| `SCANNER_PORT` | `6680` | Porta di ascolto |
| `SCANNER_DB_PATH` | `/app/data/db/library_scanner.db` | Percorso database SQLite |
| `SCANNER_LOG_PATH` | `/app/data/logs` | Cartella log |
| `SCANNER_ADMIN_USER` | `admin` | Username admin web dashboard |
| `SCANNER_ADMIN_PASSWORD` | *(generata)* | Password admin |
| `SCANNER_API_KEY` | *(generata)* | API key per Transcriber Pro |
| `SCANNER_SESSION_HOURS` | `24` | Durata sessione web (ore) |
| `SCANNER_RATE_LIMIT` | `5` | Tentativi login prima del blocco |
| `SCANNER_RATE_WINDOW` | `300` | Finestra rate limit (secondi) |
| `SCANNER_INTERVAL_HOURS` | `24` | Intervallo scansione automatica |
| `SCANNER_MIN_FILE_MB` | `50` | Dimensione minima file video |
| `SCANNER_MAX_FFPROBE` | `4` | Thread paralleli per ffprobe |
| `SCANNER_QUIET_START` | `-1` | Inizio ore silenziose (-1 = disabilitato) |
| `SCANNER_QUIET_END` | `-1` | Fine ore silenziose |
| `TZ` | `UTC` | Timezone |

---

*Transcriber Pro — Library Scanner v1.0*
