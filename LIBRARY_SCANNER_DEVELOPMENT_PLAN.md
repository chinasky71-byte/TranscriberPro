# LIBRARY SCANNER - PIANO DI SVILUPPO

## INFORMAZIONI GENERALI

### Hardware Target
- **Server Linux:** Intel N95, 16GB RAM, Debian headless, 5 dischi USB 3.2
- **Client Windows:** Intel 12700KF, 12GB RAM, RTX 3060, Windows 11

### Stack Tecnologico
- **Server:** Python 3.10+, FastAPI, SQLite, Watchdog, ffprobe
- **Client:** PyQt6, requests, integrazione Transcriber Pro

### Note Implementative
- Ogni step fornisce codice completo e funzionante
- Non creare README, markdown o documenti istruzioni salvo questo
- Testare ogni step prima di passare al successivo
- Priorità: completare server prima del client

---

## STEP 1: DATABASE E MODELLI BASE

### Obiettivo
Creare la struttura database SQLite con tutti i modelli e le operazioni CRUD base.

### File da Creare
```
library_scanner/
├── __init__.py
├── database.py          # Gestione connessione e inizializzazione
├── models.py            # Modelli SQLAlchemy/dataclass
└── config.py            # Configurazione globale
```

### Specifiche Tecniche

**Database Schema:**
```sql
-- Tabella video_files
- id (INTEGER PRIMARY KEY)
- path_linux (TEXT, INDEXED, UNIQUE)
- path_windows (TEXT)
- filename (TEXT)
- file_size (INTEGER)
- date_created (DATETIME)
- date_modified (DATETIME)
- last_checked (DATETIME)
- has_italian_subs (BOOLEAN)
- has_embedded_subs (BOOLEAN)
- has_external_subs (BOOLEAN)
- days_without_subs (INTEGER, INDEXED)
- video_format (TEXT)
- video_duration (INTEGER)

-- Tabella scan_directories
- id (INTEGER PRIMARY KEY)
- linux_path (TEXT, UNIQUE)
- windows_path (TEXT)
- enabled (BOOLEAN DEFAULT TRUE)
- recursive (BOOLEAN DEFAULT TRUE)
- file_extensions (TEXT DEFAULT 'mp4,mkv,avi,mov,wmv,flv,webm')

-- Tabella configuration
- key (TEXT PRIMARY KEY)
- value (TEXT)
- value_type (TEXT)  # 'int', 'bool', 'string', 'json'

-- Tabella scan_history
- id (INTEGER PRIMARY KEY)
- scan_start (DATETIME)
- scan_end (DATETIME)
- files_scanned (INTEGER)
- files_added (INTEGER)
- files_updated (INTEGER)
- errors (INTEGER)
```

**Configurazioni Default:**
- scan_interval_days: 7
- days_threshold_no_subs: 1
- web_port: 6680
- max_concurrent_ffprobe: 4
- subtitle_patterns: ["*_ita.srt", "*_italian.srt", "*.it.srt", "*.ita.sub", "*.it.sub"]
- min_file_size_mb: 50
- excluded_patterns: ["*/sample/*", "*/extras/*", "*/.tmp/*"]

### Deliverables
- Database SQLite funzionante con schema completo
- Funzioni CRUD per tutte le tabelle
- Script di inizializzazione database
- Inserimento configurazioni default

### Test di Verifica
```python
# Test da eseguire:
1. Creare database
2. Inserire 10 video di test
3. Inserire 3 directory di scansione
4. Leggere/modificare configurazioni
5. Query su video senza sottotitoli
6. Verificare indici e performance
```

### Criteri di Completamento
- [ ] Database creato correttamente
- [ ] Tutte le tabelle con campi corretti
- [ ] CRUD funzionante per ogni tabella
- [ ] Query ottimizzate con indici
- [ ] Configurazioni inizializzate

---

## STEP 2: SCANNER FILESYSTEM BASE

### Obiettivo
Implementare lo scanner che esplora le directory configurate e identifica i file video.

### File da Creare
```
library_scanner/
├── scanner.py           # Core scanner filesystem
└── file_utils.py        # Utility per path, size, date
```

### Specifiche Tecniche

**Scanner Features:**
- Scansione ricorsiva directory configurate
- Filtro per estensioni video
- Esclusione pattern (sample, extras, temp)
- Filtro dimensione minima file
- Estrazione metadati file (size, dates)
- Calcolo path Windows da path Linux (mapping)
- Gestione errori (permessi, file corrotti)
- Progress callback per UI futura

**Logica Path Mapping:**
```python
# Esempio:
Linux:   /mnt/disk1/Movies/Film.mkv
Windows: \\NAS\Movies\Film.mkv

# Configurazione directory:
linux_path: /mnt/disk1/Movies
windows_path: \\NAS\Movies
```

**Ottimizzazioni:**
- Skip file già nel database se stessa data modifica
- Batch insert database (ogni 100 file)
- Logging dettagliato operazioni
- Gestione dischi USB lenti (timeout read)

### Deliverables
- Scanner filesystem completo
- Path mapping Linux/Windows
- Inserimento file nel database
- Gestione errori robusta

### Test di Verifica
```python
# Test da eseguire:
1. Aggiungere directory di test con 100+ file video
2. Eseguire scansione completa
3. Verificare tutti i file nel database
4. Verificare path Windows corretti
5. Testare con file di varie dimensioni
6. Testare esclusione pattern
7. Verificare performance (tempo scansione)
```

### Criteri di Completamento
- [ ] Scansione completa directory funzionante
- [ ] Path mapping corretto Linux/Windows
- [ ] File inseriti nel database con metadati
- [ ] Pattern esclusione applicati
- [ ] Performance accettabili (<1 sec per 100 file)
- [ ] Logging dettagliato

---

## STEP 3: VERIFICA SOTTOTITOLI (ESTERNI + EMBEDDED)

### Obiettivo
Implementare la logica di verifica sottotitoli italiani sia esterni che embedded tramite ffprobe.

### File da Creare
```
library_scanner/
├── subtitle_checker.py  # Verifica sottotitoli
└── ffprobe_wrapper.py   # Wrapper per ffprobe
```

### Specifiche Tecniche

**Verifica Sottotitoli Esterni:**
- Pattern da cercare (configurabili):
  - `filename_ita.srt`, `filename_italian.srt`
  - `filename.it.srt`, `filename.ita.srt`
  - `filename_ita.sub`, `filename.it.sub`
  - `filename_ita.ass`, `filename.it.ass`
- Case-insensitive
- Stessa directory del video
- Può avere stesso nome o nome_ita

**Verifica Sottotitoli Embedded:**
```bash
# Comando ffprobe:
ffprobe -v error -select_streams s -show_entries stream=index,codec_name:stream_tags=language -of json "video.mkv"

# Output atteso:
{
  "streams": [
    {
      "index": 2,
      "codec_name": "subrip",
      "tags": {
        "language": "ita"
      }
    }
  ]
}
```

**Lingue Italiane da Riconoscere:**
- `ita`, `it`, `italian`, `italiano`

**Logica Decisionale:**
```
has_external_subs = True se trovato file esterno
has_embedded_subs = True se ffprobe trova stream italiano
has_italian_subs = has_external_subs OR has_embedded_subs
```

**Ottimizzazioni:**
- Timeout ffprobe 10 secondi
- Pool di processi paralleli (max_concurrent_ffprobe)
- Cache risultati per evitare ricontrolli inutili
- Gestione errori ffprobe (file corrotti, codec non supportati)

**Calcolo days_without_subs:**
```python
if has_italian_subs:
    days_without_subs = 0
else:
    days_without_subs = (datetime.now() - file_date_created).days
```

### Deliverables
- Checker sottotitoli esterni completo
- Wrapper ffprobe per embedded
- Logica combinata verifica
- Update database con risultati
- Gestione errori robusta

### Test di Verifica
```python
# Preparare test set:
1. Video con .srt esterno italiano
2. Video con .srt esterno inglese
3. Video con sottotitoli embedded italiani
4. Video con sottotitoli embedded multipli (eng+ita)
5. Video senza sottotitoli
6. Video con file corrotto
7. File MKV complesso (10+ stream)

# Verificare:
- Tutti i casi rilevati correttamente
- Performance ffprobe accettabili
- Gestione errori senza crash
- Database aggiornato correttamente
```

### Criteri di Completamento
- [ ] Rilevamento sottotitoli esterni funzionante
- [ ] ffprobe wrapper operativo
- [ ] Rilevamento embedded funzionante
- [ ] Logica combinata corretta
- [ ] Database aggiornato con flags corretti
- [ ] days_without_subs calcolato correttamente
- [ ] Performance <2 sec per video (medio)
- [ ] Gestione errori robusta

---

## STEP 4: API REST CORE

### Obiettivo
Implementare il server FastAPI con tutti gli endpoint REST necessari per il client.

### File da Creare
```
library_scanner/
├── api/
│   ├── __init__.py
│   ├── main.py          # FastAPI app
│   ├── routes.py        # Endpoints
│   ├── schemas.py       # Pydantic models
│   └── dependencies.py  # Auth, DB session
└── server.py            # Entry point server
```

### Specifiche Tecniche

**Endpoints da Implementare:**

```python
# Videos
GET  /api/videos?days_min=7&limit=100&offset=0
     # Lista video senza sottotitoli italiani
     # Filtri: days_min, limit, offset, order_by
     # Response: {total: int, items: [VideoResponse]}

GET  /api/videos/{id}
     # Dettaglio singolo video
     # Response: VideoResponse completo

POST /api/videos/{id}/recheck
     # Forza ricontrollo sottotitoli
     # Response: VideoResponse aggiornato

# Configuration
GET  /api/config
     # Tutte le configurazioni
     # Response: {key: value}

POST /api/config
     # Aggiorna configurazioni
     # Body: {key: value}
     # Response: {updated: [keys]}

GET  /api/config/{key}
     # Singola configurazione
     # Response: {key: string, value: any}

# Directories
GET  /api/directories
     # Lista directory scansionate
     # Response: [DirectoryResponse]

POST /api/directories
     # Aggiungi directory
     # Body: {linux_path, windows_path, enabled, recursive}
     # Response: DirectoryResponse

PUT  /api/directories/{id}
     # Aggiorna directory
     # Response: DirectoryResponse

DELETE /api/directories/{id}
     # Rimuovi directory
     # Response: {deleted: bool}

# Scan
GET  /api/scan/status
     # Stato scansione corrente
     # Response: {running: bool, progress: int, current_file: str}

POST /api/scan/start
     # Avvia scansione manuale
     # Response: {started: bool, scan_id: int}

GET  /api/scan/history?limit=10
     # Storico scansioni
     # Response: [ScanHistoryResponse]

# Stats
GET  /api/stats
     # Statistiche generali
     # Response: {
     #   total_videos: int,
     #   videos_no_subs: int,
     #   videos_external_subs: int,
     #   videos_embedded_subs: int,
     #   total_size_gb: float,
     #   oldest_no_subs_days: int
     # }

# Health
GET  /api/health
     # Health check
     # Response: {status: "ok", version: "1.0.0"}
```

**Pydantic Models:**
```python
class VideoResponse(BaseModel):
    id: int
    path_windows: str
    filename: str
    file_size: int
    date_created: datetime
    has_italian_subs: bool
    has_external_subs: bool
    has_embedded_subs: bool
    days_without_subs: int
    video_format: str
    video_duration: Optional[int]

class DirectoryResponse(BaseModel):
    id: int
    linux_path: str
    windows_path: str
    enabled: bool
    recursive: bool
    file_extensions: str

class ScanHistoryResponse(BaseModel):
    id: int
    scan_start: datetime
    scan_end: Optional[datetime]
    files_scanned: int
    files_added: int
    files_updated: int
    errors: int
```

**Features:**
- CORS configurabile (per web UI)
- Logging richieste
- Error handling JSON
- Validazione input Pydantic
- Pagination per liste lunghe
- Rate limiting opzionale (futuro)
- Health check per monitoring

**Configurazione Server:**
```python
# server.py
uvicorn.run(
    "library_scanner.api.main:app",
    host="0.0.0.0",
    port=6680,  # da config
    reload=False,  # production
    log_level="info"
)
```

### Deliverables
- FastAPI app completa
- Tutti gli endpoint implementati
- Pydantic schemas validazione
- Error handling robusto
- Logging richieste

### Test di Verifica
```bash
# Test con curl/httpie:
1. GET /api/health
2. GET /api/videos?days_min=7&limit=10
3. GET /api/videos/1
4. POST /api/videos/1/recheck
5. GET /api/config
6. POST /api/config (update scan_interval_days)
7. GET /api/directories
8. POST /api/directories (add test dir)
9. GET /api/scan/status
10. POST /api/scan/start
11. GET /api/stats

# Verificare:
- Response JSON corretti
- Status code appropriati
- Error handling (404, 400, 500)
- Performance (<100ms per query semplice)
```

### Criteri di Completamento
- [ ] Server FastAPI avviabile
- [ ] Tutti gli endpoint rispondono
- [ ] Validazione Pydantic funzionante
- [ ] Error handling robusto
- [ ] Logging configurato
- [ ] CORS abilitato
- [ ] Performance accettabili
- [ ] Documentazione OpenAPI (/docs)

---

## STEP 5: WATCHDOG REAL-TIME MONITORING

### Obiettivo
Implementare il monitoraggio real-time del filesystem con inotify/watchdog per aggiornamenti automatici.

### File da Creare
```
library_scanner/
├── watcher.py           # Watchdog observer
└── event_handler.py     # Gestione eventi filesystem
```

### Specifiche Tecniche

**Eventi da Monitorare:**
- `FileCreatedEvent`: nuovo video aggiunto
- `FileModifiedEvent`: video modificato (possibile aggiunta subs)
- `FileDeletedEvent`: video eliminato
- `FileMovedEvent`: video spostato/rinominato

**Logica Eventi:**

```python
# FileCreatedEvent
if is_video_file(path):
    - Aggiungi al database
    - Verifica sottotitoli
    - Log: "Nuovo video rilevato: {path}"

if is_subtitle_file(path):
    - Trova video correlato
    - Ricontrolla sottotitoli video
    - Log: "Sottotitoli aggiunti: {path}"

# FileModifiedEvent
if is_subtitle_file(path):
    - Trova video correlato
    - Ricontrolla sottotitoli
    
if is_video_file(path):
    - Verifica se date_modified cambiata
    - Ricontrolla sottotitoli (potrebbe essere embed aggiunto)

# FileDeletedEvent
if is_video_file(path):
    - Rimuovi dal database
    - Log: "Video eliminato: {path}"

if is_subtitle_file(path):
    - Trova video correlato
    - Ricontrolla sottotitoli
    - Log: "Sottotitoli eliminati: {path}"

# FileMovedEvent
if is_video_file(src_path):
    - Aggiorna path nel database
    - Ricontrolla sottotitoli (nuova posizione)
```

**Ottimizzazioni:**
- Debouncing: aspetta 2 secondi prima di processare (evita eventi duplicati)
- Queue eventi: processa in batch ogni 5 secondi
- Skip eventi su path temporanei (.tmp, .part)
- Limita profondità ricorsione (max 10 livelli)
- Thread separato per processamento eventi
- Graceful shutdown

**Gestione Multi-Disco USB:**
- Observer separato per ogni directory configurata
- Gestione disconnessione disco (try/except)
- Riconnessione automatica quando disco torna disponibile
- Log warning se disco non accessibile

### Deliverables
- Watchdog observer funzionante
- Event handler per tutti i tipi evento
- Integrazione con database e subtitle_checker
- Queue eventi con batch processing
- Gestione errori disconnessione dischi

### Test di Verifica
```python
# Test da eseguire:
1. Avviare watcher
2. Copiare video nella directory monitorata
   → Verificare inserimento automatico database
3. Aggiungere file .srt a video esistente
   → Verificare update has_external_subs
4. Eliminare video
   → Verificare rimozione da database
5. Rinominare video
   → Verificare update path database
6. Copiare 100 file rapidamente
   → Verificare debouncing e batch processing
7. Scollegare USB e ricollegare
   → Verificare gestione errori e recovery
```

### Criteri di Completamento
- [ ] Watcher avviabile e in background
- [ ] Tutti gli eventi gestiti correttamente
- [ ] Database aggiornato in real-time
- [ ] Debouncing funzionante
- [ ] Batch processing efficiente
- [ ] Gestione errori dischi USB
- [ ] Performance accettabili (CPU <5%)
- [ ] Logging dettagliato eventi

---

## STEP 6: WEB UI - CONFIGURAZIONE

### Obiettivo
Creare interfaccia web per configurazione server (porta 6680).

### File da Creare
```
library_scanner/
├── web/
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css
│   │   └── js/
│   │       └── app.js
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── directories.html
│       ├── config.html
│       └── logs.html
└── api/web_routes.py    # Routes per web UI
```

### Specifiche Tecniche

**Pagine da Implementare:**

**1. Dashboard (/) - Home**
```html
Layout:
- Header: logo, nav menu, status indicator
- Stats cards:
  - Totale video
  - Video senza sottotitoli
  - Ultimo scan
  - Disk space used
- Chart: video senza subs per giorni (7, 14, 30, 60, 90+)
- Tabella: ultimi 10 video aggiunti
- Bottone: "Avvia Scansione Manuale"
```

**2. Directory (/directories)**
```html
Layout:
- Tabella directory configurate:
  Colonne: Linux Path | Windows Path | Enabled | Recursive | Extensions | Actions
- Form aggiungi directory:
  - Input: linux_path (text, required)
  - Input: windows_path (text, required)
  - Checkbox: enabled (default true)
  - Checkbox: recursive (default true)
  - Input: file_extensions (text, default from config)
  - Bottone: Test Path (verifica accessibilità)
  - Bottone: Aggiungi
- Actions per ogni riga:
  - Edit (modal)
  - Delete (conferma)
  - Test (verifica accessibilità)
```

**3. Configurazione (/config)**
```html
Layout:
- Form configurazione:
  
  Scanner Settings:
  - scan_interval_days (number, min 1)
  - days_threshold_no_subs (number, min 0)
  - min_file_size_mb (number, min 1)
  - max_concurrent_ffprobe (number, 1-8)
  
  Scheduling:
  - blackout_start_hour (select 0-23)
  - blackout_end_hour (select 0-23)
  
  Subtitle Patterns:
  - subtitle_patterns (textarea, one per line)
  - excluded_patterns (textarea, one per line)
  
  Server:
  - web_port (number, 1024-65535)
  - log_level (select: DEBUG, INFO, WARNING, ERROR)
  
  Advanced:
  - enable_watchdog (checkbox)
  - database_backup_enabled (checkbox)
  
- Bottoni:
  - Save All
  - Reset to Defaults
  - Test Configuration
```

**4. Logs (/logs)**
```html
Layout:
- Filtri:
  - Level (select: ALL, DEBUG, INFO, WARNING, ERROR)
  - Date range (date picker)
  - Search (text)
- Tabella logs:
  Colonne: Timestamp | Level | Module | Message
  - Auto-refresh ogni 10 secondi
  - Pagination (50 per pagina)
- Download logs (button)
```

**5. Scan History (/scan-history)**
```html
Layout:
- Tabella scan history:
  Colonne: Start | End | Duration | Files Scanned | Added | Updated | Errors
  - Ordinabile per colonna
  - Dettaglio errori in modal
- Chart: scansioni nel tempo (ultimi 30 giorni)
```

**Tech Stack UI:**
- **HTML5 + Jinja2** templating
- **CSS puro** (no framework): flexbox/grid, responsive
- **Vanilla JavaScript** (no jQuery): fetch API, DOM manipulation
- **Chart.js** per grafici (CDN)
- **Alpine.js** opzionale per reattività (leggero, 15KB)

**Features UI:**
- Responsive design (mobile-friendly)
- Toast notifications (success/error)
- Loading indicators
- Form validation client-side
- Conferme per azioni distruttive
- Dark mode (opzionale)

**API Integration:**
```javascript
// Esempio fetch
async function loadStats() {
    const response = await fetch('/api/stats');
    const data = await response.json();
    updateStatsCards(data);
}

async function startScan() {
    const response = await fetch('/api/scan/start', {
        method: 'POST'
    });
    const data = await response.json();
    showToast(data.started ? 'Scansione avviata' : 'Errore', 
              data.started ? 'success' : 'error');
}
```

### Deliverables
- Web UI completa con tutte le pagine
- CSS responsive
- JavaScript per interazioni
- Integrazione con API REST
- Form validation
- Error handling UI

### Test di Verifica
```bash
# Test da browser:
1. Accedere a http://server:6680
2. Navigare tutte le pagine
3. Dashboard: verificare stats e grafico
4. Directories: aggiungere, modificare, eliminare
5. Config: modificare valori e salvare
6. Logs: filtrare e visualizzare
7. Scan History: visualizzare storico
8. Avviare scansione manuale da dashboard
9. Testare responsiveness (mobile)
10. Testare con più browser (Chrome, Firefox)

# Verificare:
- UI fluida senza lag
- Toast notifications funzionanti
- Form validation corretta
- API calls funzionanti
- Nessun errore console JavaScript
```

### Criteri di Completamento
- [ ] Tutte le pagine accessibili
- [ ] UI responsive e moderna
- [ ] Form funzionanti e validati
- [ ] Integrazione API completa
- [ ] Toast notifications operative
- [ ] Chart.js grafici visualizzati
- [ ] Logging UI funzionante
- [ ] Nessun errore JavaScript console

---

## STEP 7: SCHEDULER E SCANSIONI AUTOMATICHE

### Obiettivo
Implementare lo scheduler per scansioni automatiche periodiche con gestione blackout hours.

### File da Creare
```
library_scanner/
├── scheduler.py         # APScheduler setup
└── tasks.py             # Task scansioni periodiche
```

### Specifiche Tecniche

**Scheduler Features:**
- **Scansione Completa Periodica:**
  - Intervallo: configurabile (default 7 giorni)
  - Tipo: full scan di tutte le directory
  - Aggiorna database completo
  
- **Scansione Verificativa Giornaliera:**
  - Ogni 24h alle 03:00 (configurabile)
  - Solo video già nel database
  - Ricontrolla has_italian_subs
  - Update days_without_subs
  
- **Cleanup Database:**
  - Ogni settimana
  - Rimuove record di file non più esistenti
  - Ottimizza database (VACUUM)

**Blackout Hours:**
```python
# Configurazione:
blackout_start_hour: 8    # Non scannerizzare dalle 08:00
blackout_end_hour: 22     # fino alle 22:00

# Logica:
if current_hour >= blackout_start and current_hour < blackout_end:
    skip_scan()
    log("Scan skipped: blackout hours")
    reschedule_after_blackout()
```

**Task Priorità:**
```python
Priority Queue:
1. Real-time events (watchdog)      # Immediate
2. Manual scan requests             # High
3. Verificativa giornaliera         # Medium
4. Scansione completa periodica     # Low
5. Cleanup database                 # Low
```

**Gestione Sovrapposizione:**
- Se scan in corso, skippa successivo
- Lock file per evitare scansioni duplicate
- Kill graceful se nuovo scan manual richiesto

**APScheduler Configuration:**
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

# Scansione completa ogni N giorni
scheduler.add_job(
    full_scan,
    trigger=IntervalTrigger(days=scan_interval_days),
    id='full_scan',
    replace_existing=True
)

# Verificativa giornaliera alle 03:00
scheduler.add_job(
    verify_scan,
    trigger=CronTrigger(hour=3, minute=0),
    id='verify_scan',
    replace_existing=True
)

# Cleanup settimanale domenica 02:00
scheduler.add_job(
    cleanup_database,
    trigger=CronTrigger(day_of_week='sun', hour=2, minute=0),
    id='cleanup',
    replace_existing=True
)

scheduler.start()
```

**Progress Tracking:**
```python
class ScanProgress:
    running: bool = False
    total_files: int = 0
    processed_files: int = 0
    current_file: str = ""
    scan_id: int = 0
    start_time: datetime
    errors: List[str] = []
    
    @property
    def progress_percent(self) -> int:
        return (processed_files / total_files * 100) if total_files else 0
```

**Logging Avanzato:**
```python
Logs per scan:
- Scan started: {scan_id}, type: {full/verify/cleanup}
- Progress: {percent}% ({processed}/{total})
- Current file: {path}
- Errors encountered: {error_msg}
- Scan completed: duration {duration}, files added {added}, updated {updated}
- Scan failed: {error}
```

### Deliverables
- Scheduler APScheduler configurato
- Task scansioni periodiche
- Blackout hours implementato
- Progress tracking
- Lock per evitare sovrapposizioni
- Logging dettagliato

### Test di Verifica
```python
# Test da eseguire:
1. Avviare scheduler
2. Forzare scansione completa
   → Verificare esecuzione e log
3. Configurare blackout hours corrente
   → Verificare skip scan
4. Avviare due scan manuali simultanei
   → Verificare lock funzionante
5. Modificare scan_interval_days a 1 minuto
   → Verificare esecuzione periodica
6. Verificare progress tracking via API
7. Simulare crash durante scan
   → Verificare recovery e cleanup
8. Eseguire cleanup database
   → Verificare rimozione orphan records

# Verificare:
- Scheduler non blocca thread principale
- Scansioni eseguite agli orari corretti
- Blackout hours rispettati
- Lock previene sovrapposizioni
- Progress tracking accurato
- Graceful shutdown
```

### Criteri di Completamento
- [ ] Scheduler avviabile e in background
- [ ] Scansioni periodiche funzionanti
- [ ] Blackout hours implementato
- [ ] Lock sovrapposizioni operativo
- [ ] Progress tracking via API
- [ ] Cleanup database funzionante
- [ ] Logging completo
- [ ] Graceful shutdown
- [ ] Riconfigurazione runtime

---

## STEP 8: SYSTEMD SERVICE E DEPLOYMENT SERVER

### Obiettivo
Creare script deployment, systemd service e configurazione per produzione.

### File da Creare
```
library_scanner/
├── deployment/
│   ├── install.sh           # Script installazione
│   ├── library-scanner.service  # Systemd unit file
│   ├── config.example.json  # Config template
│   └── backup.sh            # Script backup database
├── requirements.txt         # Dipendenze Python
└── setup.py                 # Package setup
```

### Specifiche Tecniche

**requirements.txt:**
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sqlalchemy>=2.0.0
pydantic>=2.4.0
watchdog>=3.0.0
apscheduler>=3.10.0
jinja2>=3.1.0
aiofiles>=23.0.0
python-multipart>=0.0.6
```

**systemd Service File:**
```ini
[Unit]
Description=Library Scanner Video Service
After=network.target

[Service]
Type=simple
User=libraryscanner
Group=libraryscanner
WorkingDirectory=/opt/library-scanner
Environment="PYTHONPATH=/opt/library-scanner"
ExecStart=/opt/library-scanner/venv/bin/python -m library_scanner.server
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**install.sh Script:**
```bash
#!/bin/bash
# 1. Creare utente libraryscanner
# 2. Installare dipendenze sistema (python3, ffmpeg)
# 3. Creare venv Python
# 4. Installare requirements
# 5. Creare directory /opt/library-scanner
# 6. Copiare file applicazione
# 7. Creare directory dati /var/lib/library-scanner
# 8. Inizializzare database
# 9. Copiare systemd service
# 10. Abilitare e avviare service
# 11. Configurare firewall (porta 6680)
```

**backup.sh Script:**
```bash
#!/bin/bash
# 1. Stop service
# 2. Backup database SQLite
# 3. Backup configurazione
# 4. Compress con timestamp
# 5. Cleanup old backups (keep last 7)
# 6. Start service
# 7. Log operazione
```

**Configurazione Produzione:**
```json
{
  "database_path": "/var/lib/library-scanner/library.db",
  "log_path": "/var/log/library-scanner",
  "log_level": "INFO",
  "web_port": 6680,
  "max_workers": 4,
  "enable_cors": false,
  "scan_interval_days": 7,
  "enable_watchdog": true,
  "backup_enabled": true,
  "backup_retention_days": 30
}
```

**Directory Structure Finale:**
```
/opt/library-scanner/              # Applicazione
/var/lib/library-scanner/          # Database e dati
/var/log/library-scanner/          # Logs
/etc/library-scanner/              # Configurazione
/opt/library-scanner/backups/      # Backup database
```

**Health Check e Monitoring:**
```python
# Endpoint health avanzato
GET /api/health
Response:
{
  "status": "ok",
  "version": "1.0.0",
  "uptime_seconds": 86400,
  "database_size_mb": 45.2,
  "total_videos": 1523,
  "watchdog_running": true,
  "scheduler_running": true,
  "last_scan": "2025-01-10T03:00:00Z",
  "disk_usage": {
    "/mnt/disk1": "450GB / 2TB",
    "/mnt/disk2": "1.2TB / 4TB"
  }
}
```

**Security Hardening:**
- Utente dedicato senza shell
- Permission files 600 (database)
- Permission directory 700 (dati)
- Firewall rule per porta 6680
- Log rotation (logrotate)
- Fail2ban opzionale (rate limiting)

### Deliverables
- Script installazione completo
- Systemd service file
- Requirements.txt
- Script backup automatico
- Documentazione deployment
- Health check avanzato

### Test di Verifica
```bash
# Test installazione:
1. Eseguire install.sh su Debian fresh
2. Verificare service attivo:
   systemctl status library-scanner
3. Verificare log:
   journalctl -u library-scanner -f
4. Accedere a http://server:6680
5. Verificare health check:
   curl http://server:6680/api/health
6. Eseguire backup.sh
7. Simulare crash e verificare restart automatico
8. Testare aggiornamento (stop, update, start)

# Verificare:
- Service si avvia al boot
- Restart automatico dopo crash
- Backup funzionante
- Log rotation attivo
- Performance stabili nel tempo
- Nessun memory leak
```

### Criteri di Completamento
- [ ] Script installazione funzionante
- [ ] Service systemd operativo
- [ ] Auto-restart dopo crash
- [ ] Backup automatico configurato
- [ ] Log rotation attivo
- [ ] Health check completo
- [ ] Security hardening applicato
- [ ] Firewall configurato
- [ ] Documentazione deployment chiara

---

## STEP 9: TESTING COMPLETO E STRESS TEST SERVER

### Obiettivo
Eseguire testing completo del server con scenari reali e stress test.

### Test Suite da Implementare

**Test Funzionali:**
```python
tests/
├── test_database.py         # CRUD operations
├── test_scanner.py          # Filesystem scanning
├── test_subtitle_checker.py # Subtitle detection
├── test_api.py              # API endpoints
├── test_watcher.py          # Real-time monitoring
├── test_scheduler.py        # Scheduled tasks
└── test_integration.py      # End-to-end tests
```

**Scenari Test da Validare:**

**1. Scenario: Prima Installazione**
```
- Database vuoto
- Nessuna directory configurata
- Configurazione default
→ Aggiungere directory
→ Avviare prima scansione
→ Verificare popolamento database
→ Verificare sottotitoli rilevati
```

**2. Scenario: Libreria Grande (10,000+ video)**
```
- Preparare dataset 10,000 video misti
- Eseguire full scan
→ Tempo completamento < 3 ore
→ Memory usage < 2GB
→ CPU usage medio < 50%
→ Tutti i file nel database
→ Sottotitoli verificati correttamente
```

**3. Scenario: Real-time Events Storm**
```
- Copiare 500 file video simultaneamente
- Aggiungere 200 file .srt
- Eliminare 100 video
→ Watchdog gestisce tutti gli eventi
→ Nessun evento perso
→ Database consistente
→ Nessun crash
```

**4. Scenario: Dischi USB Multipli**
```
- 5 dischi USB configurati
- Scollegare disco durante scan
- Ricollegare disco
→ Gestione errori graceful
→ Recovery automatico
→ Logging appropriato
→ Continue scan altri dischi
```

**5. Scenario: API Load Test**
```bash
# Apache Bench test
ab -n 1000 -c 10 http://server:6680/api/videos?days_min=7

→ Tutte le request completate
→ Tempo risposta medio < 100ms
→ Nessun errore 500
→ Memory stabile
```

**6. Scenario: Long Running (7 giorni)**
```
- Avviare server
- Lasciare in esecuzione 7 giorni
- Monitorare metriche
→ Nessun memory leak
→ Database size stabile
→ CPU usage normale
→ Nessun crash
→ Scheduler esegue correttamente
```

**7. Scenario: Concurrent Operations**
```
- Scansione in corso
- 10 client API simultanei
- Watchdog attivo
- Scheduler triggera task
→ Tutte le operazioni completate
→ Database locks gestiti
→ Nessun deadlock
→ Performance degradation < 20%
```

**Performance Benchmarks Target:**
- Scansione: 100 file/minuto (con ffprobe)
- API response: < 100ms (95 percentile)
- Memory usage: < 500MB (idle), < 2GB (scanning)
- CPU usage: < 10% (idle), < 60% (scanning)
- Database size: ~50KB per 1000 video

**Metriche da Monitorare:**
```python
# Script monitoring
import psutil
import time

while True:
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk_io = psutil.disk_io_counters()
    
    log(f"CPU: {cpu}%, RAM: {mem.percent}%, Disk Read: {disk_io.read_bytes}")
    time.sleep(60)
```

### Deliverables
- Test suite completa
- Script stress test
- Script monitoring
- Report performance
- Lista issue trovati e risolti

### Criteri di Completamento
- [ ] Tutti i test funzionali passano
- [ ] Stress test completati con successo
- [ ] Performance benchmarks raggiunti
- [ ] Nessun memory leak rilevato
- [ ] Long running test (7 giorni) OK
- [ ] Concurrent operations stabili
- [ ] Documentazione test completa

---

## STEP 10: WIDGET CLIENT TRANSCRIBER PRO

### Obiettivo
Implementare widget PyQt6 in Transcriber Pro per interfacciarsi con il server.

### File da Creare/Modificare
```
transcriber_pro/
├── ui/
│   └── library_scanner_widget.py   # Widget principale
├── utils/
│   └── library_scanner_client.py   # Client API
└── main_window.py                  # Integrazione widget
```

### Specifiche Tecniche

**Widget UI Layout:**
```
┌─────────────────────────────────────────────────┐
│ Library Scanner                    [●] Connected │
│                                                   │
│ Server: 192.168.1.100:6680          [⟳ Refresh] │
├─────────────────────────────────────────────────┤
│ Filtri:                                          │
│ Giorni senza subs: [≥7 ▼]  Ordina: [Giorni ▼]  │
│ Cerca: [_____________]              [🔍]         │
├─────────────────────────────────────────────────┤
│ ☑ Nome File              │ Giorni │ Dimensione  │
│ ☑ Film_2024.mkv          │   15   │ 4.2 GB     │
│ ☑ Serie_S01E01.mkv       │   30   │ 1.8 GB     │
│ ☐ Documentario.mp4       │    7   │ 950 MB     │
│ ...                                              │
│                                    152 totali    │
├─────────────────────────────────────────────────┤
│ [☑ Seleziona tutto]  [Aggiungi 2 alla coda]     │
└─────────────────────────────────────────────────┘
```

**Widget Features:**

**1. Header:**
- **Toggle Enable/Disable**: QCheckBox per attivare/disattivare funzionalità
- **Connection Indicator**: QLabel con colore (verde=ok, rosso=offline)
- **Server Address**: QLineEdit configurabile (salvato in QSettings)
- **Refresh Button**: QPushButton per aggiornamento manuale

**2. Filtri:**
- **Giorni Dropdown**: QComboBox [≥7, ≥14, ≥30, ≥60, ≥90, Tutti, Custom]
- **Sort Dropdown**: QComboBox [Giorni (desc), Nome, Data aggiunta, Dimensione]
- **Search Box**: QLineEdit con QTimer per debounce (500ms)
- **Applicazione filtri**: automatica on change

**3. Tabella Video:**
- **QTableWidget** con colonne:
  - Checkbox (select)
  - Nome File (string, sortable)
  - Giorni senza subs (int, sortable)
  - Dimensione (string formatted, sortable)
  - Path (nascosto in tooltip)
- **Multi-selection**: Ctrl+Click, Shift+Click
- **Double-click**: mostra dialog dettagli video
- **Context menu** (right-click):
  - "Aggiungi alla coda"
  - "Apri cartella"
  - "Escludi da lista"
  - "Ricontrolla sottotitoli"

**4. Footer:**
- **Select All Checkbox**: seleziona/deseleziona tutti
- **Counter**: "X selezionati / Y totali"
- **Add Button**: "Aggiungi X alla coda" (disabilitato se nessuno selezionato)
- **Progress Bar**: durante import files
- **Status Label**: "Ultimo aggiornamento: 10:35"

**5. Settings Dialog:**
```
┌─────────────────────────────────────┐
│ Library Scanner Settings            │
├─────────────────────────────────────┤
│ Server:                             │
│ IP/Hostname: [192.168.1.100]        │
│ Port: [6680]                        │
│ [Test Connection]                   │
│                                     │
│ Comportamento:                      │
│ ☑ Auto-refresh ogni: [5] minuti    │
│ ☑ Conferma prima di aggiungere >20 │
│ ☐ Aggiungi in cima alla coda       │
│                                     │
│ Profilo predefinito:                │
│ [Standard ▼]                        │
│                                     │
│ [Salva]  [Annulla]                  │
└─────────────────────────────────────┘
```

**Client API Class:**
```python
class LibraryScannerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.timeout = 10
    
    def test_connection(self) -> bool:
        """Test server health"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/health",
                timeout=self.timeout
            )
            return response.status_code == 200
        except:
            return False
    
    def get_videos(self, 
                   days_min: int = 7, 
                   limit: int = 1000, 
                   offset: int = 0,
                   search: str = "") -> Dict:
        """Get videos without subs"""
        params = {
            "days_min": days_min,
            "limit": limit,
            "offset": offset
        }
        if search:
            params["search"] = search
        
        response = self.session.get(
            f"{self.base_url}/api/videos",
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def recheck_video(self, video_id: int) -> Dict:
        """Force recheck video subtitles"""
        response = self.session.post(
            f"{self.base_url}/api/videos/{video_id}/recheck",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def get_stats(self) -> Dict:
        """Get server stats"""
        response = self.session.get(
            f"{self.base_url}/api/stats",
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
```

**Integration con Transcriber Pro:**
```python
# In main_window.py
def add_files_from_library_scanner(self, file_paths: List[str]):
    """Add files from library scanner to queue"""
    # Usa profilo configurato o default
    profile = self.settings.value("library_scanner/profile", "Standard")
    
    for path in file_paths:
        # Verifica file esistente
        if not os.path.exists(path):
            self.show_error(f"File non trovato: {path}")
            continue
        
        # Aggiungi alla coda esistente
        self.add_to_queue(path, profile)
    
    self.statusBar().showMessage(
        f"Aggiunti {len(file_paths)} file alla coda"
    )
```

**Threading:**
- **Worker Thread** per API calls (no freeze UI)
- **QTimer** per auto-refresh periodico
- **Signals/Slots** per comunicazione thread-safe

**Error Handling:**
```python
# Scenari da gestire:
1. Server offline → Mostra indicatore rosso, disabilita funzioni
2. Timeout request → QMessageBox con retry
3. Errore API (500) → Log e mostra errore user
4. File non esistente → Warning e skip
5. Network error → Auto-retry con backoff exponential
```

### Deliverables
- Widget Library Scanner completo
- Client API funzionante
- Settings dialog configurazione
- Integrazione Transcriber Pro
- Threading corretto
- Error handling robusto

### Test di Verifica
```python
# Test da eseguire:
1. Aprire Transcriber Pro
2. Navigare a widget Library Scanner
3. Configurare server address
4. Test connection → verde
5. Refresh lista video
6. Applicare filtri vari
7. Selezionare 5 video
8. Aggiungi alla coda
   → Verificare in coda Transcriber Pro
9. Double-click video → dialog dettagli
10. Right-click → "Apri cartella"
11. Disabilitare widget → verificare disabilitazione
12. Staccare server → indicatore rosso
13. Riattivare server → auto-reconnect

# Verificare:
- UI responsive (no freeze)
- API calls in background
- Errori gestiti gracefully
- Settings persistenti
- Integration seamless con TP
```

### Criteri di Completamento
- [ ] Widget UI completo e funzionante
- [ ] Client API operativo
- [ ] Settings persistenti (QSettings)
- [ ] Threading corretto (no freeze)
- [ ] Error handling completo
- [ ] Connection indicator funzionante
- [ ] Auto-refresh configurabile
- [ ] Filtri e sort operativi
- [ ] Multi-selection funzionante
- [ ] Integration con coda TP OK
- [ ] Context menu implementato
- [ ] Dialog dettagli video

---

## STEP 11: INTEGRAZIONE FINALE E TESTING END-TO-END

### Obiettivo
Testing completo dell'integrazione client-server in scenari reali d'uso.

### Test End-to-End da Eseguire

**Test 1: Setup Iniziale Completo**
```
Scenario: Primo utilizzo sistema completo

1. Server Linux:
   - Installazione da zero
   - Configurazione directory (5 dischi USB)
   - Avvio prima scansione completa
   - Verifica web UI accessibile
   - Check logs per errori

2. Client Windows:
   - Aprire Transcriber Pro
   - Configurare Library Scanner widget
   - Test connection con server
   - Verifica lista video popolata

3. Workflow:
   - Selezionare 10 video da widget
   - Aggiungi a coda Transcriber Pro
   - Processare 2-3 video
   - Verificare sottotitoli generati
   - Verificare server aggiorna database
   → Video scompaiono da lista scanner

Criteri successo:
✓ Installazione server senza errori
✓ Scansione completa libreria grande
✓ Client connesso e funzionante
✓ Video processati correttamente
✓ Database sincronizzato
```

**Test 2: Operazioni Real-Time**
```
Scenario: Monitoraggio real-time filesystem

1. Server in esecuzione con watchdog attivo
2. Client connesso e lista aperta

3. Azioni:
   - Copiare 5 nuovi video su disco
   → Attendere 5-10 secondi
   → Refresh client
   → Verificare nuovi video in lista
   
   - Aggiungere .srt a 2 video esistenti
   → Attendere 5-10 secondi
   → Refresh client
   → Verificare video rimossi da lista
   
   - Eliminare 1 video
   → Verificare rimozione da database

Criteri successo:
✓ Watchdog rileva tutti gli eventi
✓ Database aggiornato in real-time
✓ Client vede cambiamenti dopo refresh
✓ Nessun file fantasma nel database
```

**Test 3: Resilienza e Recovery**
```
Scenario: Gestione errori e disconnessioni

1. Avviare processamento 3 video da client

2. Durante processamento:
   - Scollegare disco USB server
   → Verificare log errori
   → Verificare server continua
   
   - Ricollegare disco
   → Verificare recovery automatico
   → Verificare riconnessione watchdog

3. Client disconnesso:
   - Spegnere server
   → Client mostra indicatore rosso
   → Tentativo operazione → errore graceful
   
   - Riaccendere server
   → Client auto-reconnect dopo N secondi
   → Funzionalità ripristinate

Criteri successo:
✓ Nessun crash su errori
✓ Recovery automatico funzionante
✓ Logging dettagliato errori
✓ Client gestisce disconnessioni
```

**Test 4: Performance e Scalabilità**
```
Scenario: Libreria molto grande

Setup:
- 20,000+ video su 5 dischi
- Mix di file con/senza sottotitoli
- Client con lista filtrata

Test:
1. Scansione completa iniziale
   → Tempo: max 5 ore
   → Memory: max 2GB
   → CPU: max 70% medio

2. Client filtra "giorni ≥ 30"
   → Response time: < 2 secondi
   → UI responsive

3. Seleziona 100 video e aggiungi
   → Import completato < 10 secondi
   → Tutti i file in coda TP

4. API concurrent (5 client)
   → Tutte le request OK
   → Nessun timeout
   → Database non locked

Criteri successo:
✓ Performance entro limiti accettabili
✓ Nessun bottleneck critico
✓ Scalabilità verificata
✓ Concurrent access OK
```

**Test 5: Scheduler e Automazione**
```
Scenario: Funzionamento automatico 24/7

1. Configurare:
   - Scan completo ogni 7 giorni
   - Verificativa giornaliera ore 03:00
   - Blackout hours: 09:00-22:00
   - Cleanup settimanale

2. Lasciare in esecuzione 10 giorni

3. Monitorare:
   - Scan eseguiti agli orari corretti
   - Blackout hours rispettati
   - Database incrementale corretto
   - Nessun memory leak
   - Log senza errori critici

Criteri successo:
✓ Tutti gli scheduled task eseguiti
✓ Blackout hours rispettati
✓ Nessun crash o restart
✓ Memory e CPU stabili
✓ Database consistente
```

**Test 6: Workflow Utente Tipico**
```
Scenario: Uso quotidiano sistema

Mattina:
1. Utente apre Transcriber Pro
2. Widget Library Scanner: 15 nuovi video
3. Seleziona tutti
4. Aggiungi a coda
5. Avvia processamento batch
6. Lascia in esecuzione

Pomeriggio:
1. Check progress Transcriber Pro
2. Alcuni video completati
3. Aggiungi altri 5 video manualmente a TP
4. Copia 3 nuovi film su NAS

Sera:
1. Refresh Library Scanner widget
2. 3 nuovi video apparsi
3. Nota: video processati mattina NON in lista
4. Aggiungi 3 nuovi alla coda
5. Chiude Transcriber Pro

Criteri successo:
✓ Workflow fluido e intuitivo
✓ Nessuna confusione o frustrazione
✓ Sincronizzazione database accurata
✓ Performance costanti tutto il giorno
```

### Metriche Finali da Validare

**Performance:**
- [ ] Scansione: ≥80 file/minuto con ffprobe
- [ ] API latency p95: <150ms
- [ ] Client UI: nessun freeze >500ms
- [ ] Memory leak test: nessun incremento dopo 7 giorni
- [ ] CPU idle: <15%

**Affidabilità:**
- [ ] Uptime server: 99.9% (10 giorni test)
- [ ] Zero data loss (crash recovery)
- [ ] Error rate API: <0.1%
- [ ] Watchdog events: 100% rilevati

**Usabilità:**
- [ ] Setup iniziale: <15 minuti
- [ ] Learning curve: <5 minuti per utente
- [ ] Operazioni comuni: <3 click
- [ ] Feedback immediato: <1 secondo

### Documentazione Finale

Creare (solo se richiesto esplicitamente):
- User guide setup server
- User guide configurazione client
- Troubleshooting common issues
- API documentation (OpenAPI/Swagger)

### Deliverables Finali
- Sistema completo funzionante
- Tutti i test E2E passati
- Performance benchmarks raggiunti
- Zero bug critici
- Codice pulito e commentato
- Repository git con tag v1.0.0

### Criteri di Completamento Progetto
- [ ] Tutti gli step precedenti completati
- [ ] Test E2E tutti passed
- [ ] Performance target raggiunti
- [ ] Nessun bug critico aperto
- [ ] Documentazione minima presente
- [ ] Server production-ready
- [ ] Client integrato in Transcriber Pro
- [ ] Sistema testato in produzione reale

---

## NOTE IMPLEMENTATIVE GENERALI

### Regole di Sviluppo

1. **Codice Completo**
   - Ogni step fornisce file completi, mai frammenti
   - Nessun "// TODO" o placeholders
   - Codice testato e funzionante

2. **No Documentazione Extra**
   - NO README per ogni step
   - NO CHANGELOG
   - NO file markdown di istruzioni
   - SOLO questo documento pianificazione

3. **Testing Rigoroso**
   - Testare ogni step prima del successivo
   - Non procedere con bug noti
   - Logging dettagliato per debug

4. **Git Workflow**
   - Commit dopo ogni step completato
   - Branch: main (produzione)
   - Tag version per milestone

5. **Priorità Qualità**
   - Performance ottimizzate
   - Error handling completo
   - Codice pulito e leggibile
   - Type hints Python ovunque

### Hardware Considerations

**Server (Intel N95, 16GB RAM):**
- CPU limitata: ottimizzare concurrent operations
- USB 3.2: attenzione I/O bottleneck
- Headless: logging essenziale per debug

**Client (12700KF, 12GB RAM):**
- Potente: nessun limite performance
- Threading aggressivo OK
- UI ricca senza problemi

### Modifiche Rispetto a Specifica Iniziale

Nessuna. Implementazione completa come richiesto:
- ✓ Sottotitoli embedded verificati (ffprobe)
- ✓ Client/Server architettura
- ✓ Web UI porta 6680
- ✓ Real-time monitoring (watchdog)
- ✓ Database incrementale
- ✓ Path mapping Linux/Windows
- ✓ Widget Transcriber Pro integrato

### Timeline Realistica

- Step 1-3: 3 giorni (database, scanner, subtitles)
- Step 4-5: 3 giorni (API, watchdog)
- Step 6-7: 3 giorni (web UI, scheduler)
- Step 8-9: 2 giorni (deployment, testing server)
- Step 10-11: 3 giorni (client, integration)

**Totale: ~14 giorni effettivi di sviluppo**

### Supporto Futuro

Dopo completamento v1.0.0, possibili enhancement:
- Notifiche Discord/Telegram
- Support altri formati sottotitoli (vtt, sbv)
- Machine learning per predizione sottotitoli
- Multi-utente con autenticazione
- Mobile app companion
- Statistics dashboard avanzate

---

## PROSSIMI PASSI

**Per iniziare sviluppo:**

```
Dire: "Inizia Step 1"
```

**Per continuare dopo interruzione:**

```
Dire: "Continua Step X" (dove X = ultimo step completato)
```

**Per informazioni su step specifico:**

```
Dire: "Dettagli Step X"
```

---

**FINE PIANO DI SVILUPPO - v1.0**
