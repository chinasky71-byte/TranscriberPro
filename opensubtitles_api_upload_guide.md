# OpenSubtitles REST API — Guida Completa per l'Upload di Sottotitoli

> **Scopo:** Documento di riferimento per un'IA che deve debuggare un'app che usa le API REST di OpenSubtitles per caricare sottotitoli di un film. Contiene tutti i dettagli tecnici senza eccezioni.

---

## 1. Panoramica Generale

### URL Base
```
https://api.opensubtitles.com/api/v1
```

> **IMPORTANTE:** Dopo il login, la risposta contiene un campo `base_url` che potrebbe essere diverso (es. `vip-api.opensubtitles.com` per gli utenti VIP). **Tutte le richieste successive devono usare questo `base_url` restituito dal login**, non quello hardcoded.

### Autenticazione — Due livelli

| Header | Tipo | Quando serve |
|---|---|---|
| `Api-Key: YOUR_API_KEY` | Obbligatorio su tutti gli endpoint | Sempre |
| `Authorization: Bearer YOUR_TOKEN` | JWT ricevuto dal `/login` | Endpoint protetti (upload, download, logout, user info) |

### Header Obbligatori su ogni richiesta

```http
Api-Key: YOUR_API_KEY
User-Agent: NomeApp v1.0.0
Content-Type: application/json      (solo per POST con body)
Accept: application/json
```

Il formato `User-Agent` deve essere `AppName vX.Y.Z`. **Non usare stringhe generiche** — OpenSubtitles le può rifiutare o limitare.

### Best Practices Generali
- Parametri GET in ordine **alfabetico** e **lowercase** → migliora il caching CDN ed evita redirect
- Seguire sempre i redirect HTTP (`--location` in curl)
- Non inserire spazi nell'URL: usare `+` invece di `%20` nei valori query
- Rimuovere sempre gli **zero iniziali** dagli ID numerici (IMDB, TMDB, ecc.)

---

## 2. Endpoint `/api/v1/login`

L'upload richiede obbligatoriamente un token JWT. **Il login deve precedere qualsiasi upload.**

### Richiesta
```http
POST /api/v1/login
```

**Headers:**
```http
Api-Key: YOUR_API_KEY
User-Agent: MyApp v1.0.0
Content-Type: application/json
Accept: application/json
```

**Body JSON:**
```json
{
  "username": "tuo_username",
  "password": "tua_password"
}
```

### Risposta 200 OK
```json
{
  "user": {
    "allowed_downloads": 100,
    "allowed_translations": 5,
    "level": "Sub leecher",
    "user_id": 66,
    "ext_installed": false,
    "vip": false
  },
  "base_url": "api.opensubtitles.com",
  "token": "eyJ0eXAiOiJKV1QiLCJ...",
  "status": 200
}
```

### ⚠️ Note Critiche sul Login
- **Rate limit: 1 request/secondo.** Non fare login ripetuti — può portare a blocchi temporanei.
- Il `base_url` nella risposta è il hostname da usare per tutte le chiamate successive di quella sessione.
- Il `token` è il JWT da inserire in `Authorization: Bearer <token>` per tutti gli endpoint protetti.
- Se ricevi `401`, **non ritentare immediatamente** con le stesse credenziali.
- Il login è un'operazione computazionalmente costosa per il server: minimizzare le chiamate, riusare il token finché valido.

### cURL di Esempio
```bash
curl --request POST \
  --url https://api.opensubtitles.com/api/v1/login \
  --header 'Api-Key: YOUR_API_KEY' \
  --header 'User-Agent: MyApp v1.0.0' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json' \
  --data '{
    "username": "testuser",
    "password": "testpassword"
  }'
```

### Codici di Errore Login
| Codice | Significato |
|---|---|
| `200` | Login OK, token generato |
| `401` | Username o password errati |
| `403` | Account sospeso o API key errata |
| `429` | Rate limit superato |

---

## 3. Calcolo del Moviehash (Hash del File Video)

Il `moviehash` è **fondamentale** per l'upload: permette al database di associare il sottotitolo al file video esatto. **Va calcolato dal file video, non dal sottotitolo.**

### Algoritmo OpenSubtitles Hash

L'hash è una stringa esadecimale di **esattamente 16 caratteri** (`^[a-f0-9]{16}$`).

L'algoritmo:
1. Prendi i primi **64 KB** del file video (64 × 1024 = 65536 byte)
2. Prendi gli ultimi **64 KB** del file video
3. Somma tutti i valori come interi a 64-bit (little-endian, unsigned) di questi chunk da 8 byte
4. Aggiungi anche la **dimensione totale del file in byte** (come intero a 64-bit)
5. Il risultato finale, modulo 2^64, formattato come esadecimale a 16 cifre = il moviehash

### Implementazione Python
```python
import struct
import os

def compute_moviehash(filepath):
    """Calcola il moviehash OpenSubtitles di un file video."""
    filesize = os.path.getsize(filepath)
    longlongformat = '<q'  # little-endian signed 64-bit
    bytesize = struct.calcsize(longlongformat)
    
    with open(filepath, 'rb') as f:
        file_hash = filesize
        
        # Controlla che il file sia abbastanza grande
        if filesize < 65536 * 2:
            raise ValueError(f"File troppo piccolo per calcolare l'hash: {filesize} byte")
        
        # Leggi i primi 64 KB
        for _ in range(65536 // bytesize):
            buffer = f.read(bytesize)
            (l_value,) = struct.unpack(longlongformat, buffer)
            file_hash += l_value
            file_hash &= 0xFFFFFFFFFFFFFFFF  # mantieni a 64-bit
        
        # Leggi gli ultimi 64 KB
        f.seek(max(0, filesize - 65536), 0)
        for _ in range(65536 // bytesize):
            buffer = f.read(bytesize)
            (l_value,) = struct.unpack(longlongformat, buffer)
            file_hash += l_value
            file_hash &= 0xFFFFFFFFFFFFFFFF
    
    returnedhash = "%016x" % file_hash
    return returnedhash

# Uso:
# hash = compute_moviehash("/path/to/movie.mkv")
# print(hash)  # es: "8e245d9679d31e12"
```

### Implementazione Node.js
```javascript
const fs = require('fs');

function computeMoviehash(filepath) {
  const stats = fs.statSync(filepath);
  const filesize = BigInt(stats.size);
  const chunkSize = 65536; // 64 KB
  const buf = Buffer.alloc(chunkSize);
  
  let hash = filesize;
  
  const fd = fs.openSync(filepath, 'r');
  
  // Primi 64 KB
  fs.readSync(fd, buf, 0, chunkSize, 0);
  for (let i = 0; i < chunkSize; i += 8) {
    hash = (hash + buf.readBigInt64LE(i)) & 0xFFFFFFFFFFFFFFFFn;
  }
  
  // Ultimi 64 KB
  fs.readSync(fd, buf, 0, chunkSize, stats.size - chunkSize);
  for (let i = 0; i < chunkSize; i += 8) {
    hash = (hash + buf.readBigInt64LE(i)) & 0xFFFFFFFFFFFFFFFFn;
  }
  
  fs.closeSync(fd);
  return hash.toString(16).padStart(16, '0');
}
```

---

## 4. Ricerca del `feature_id` (ID del Film)

Prima di fare l'upload, è necessario conoscere il `feature_id` OpenSubtitles del film (o l'`imdb_id`). Usa l'endpoint `/api/v1/features` per trovarlo.

### Richiesta
```http
GET /api/v1/features?imdb_id=133093
```
oppure
```http
GET /api/v1/features?query=the+matrix&type=movie
```

**Headers:**
```http
Api-Key: YOUR_API_KEY
User-Agent: MyApp v1.0.0
Accept: application/json
```

### Parametri Query

| Parametro | Tipo | Descrizione |
|---|---|---|
| `feature_id` | integer | ID OpenSubtitles specifico |
| `imdb_id` | string | IMDB ID senza `tt` e senza zeri iniziali |
| `tmdb_id` | string | TMDB ID |
| `query` | string | Ricerca testuale (min 3 caratteri, lowercase) |
| `type` | string | `movie`, `tvshow`, `episode`, `all` |
| `year` | integer | Anno (solo con `query`) |

### Risposta 200 OK
```json
{
  "data": [
    {
      "id": "514811",
      "type": "feature",
      "attributes": {
        "feature_id": "514811",
        "feature_type": "Movie",
        "title": "the matrix",
        "original_title": "The Matrix",
        "year": "1999",
        "imdb_id": 133093,
        "tmdb_id": 603,
        "title_aka": ["Matrix", "La Matrice", ...],
        "url": "https://www.opensubtitles.com/en/movies/1999-the-matrix",
        "img_url": "https://s9.opensubtitles.com/features/...",
        "subtitles_count": 3500,
        "subtitles_counts": {
          "en": 450,
          "it": 120
        }
      }
    }
  ]
}
```

> **Nota:** L'`imdb_id` nella risposta è un numero intero (es. `133093`), non la stringa `tt0133093`.

---

## 5. Endpoint `/api/v1/upload` — Upload del Sottotitolo

Questo è l'endpoint principale per caricare un nuovo sottotitolo.

### Richiesta
```http
POST /api/v1/upload
```

**Headers:**
```http
Api-Key: YOUR_API_KEY
Authorization: Bearer YOUR_JWT_TOKEN
User-Agent: MyApp v1.0.0
Content-Type: application/json
Accept: application/json
```

### Struttura del Body JSON

```json
{
  "base_subtitle_id": null,
  "subtitles": [
    {
      "sub_to_movie": {
        "movie_hash": "8e245d9679d31e12",
        "movie_byte_size": "129994823",
        "movie_fps": "23.976",
        "movie_time_ms": null,
        "movie_filename": "The.Matrix.1999.720p.BluRay.x264.mkv"
      },
      "sub_content": "BASE64_GZIP_ENCODED_SUBTITLE_CONTENT",
      "sub_hash": "md5_hash_of_subtitle_file",
      "sub_language_id": "en",
      "sub_filename": "The.Matrix.1999.720p.BluRay.x264.eng.srt",
      "comments": "Sync perfetto con la release 720p BluRay",
      "hearing_impaired": false,
      "foreign_parts_only": false,
      "high_definition": true
    }
  ],
  "baseinfo": {
    "idmovieimdb": "133093",
    "sublanguageid": "eng",
    "moviereleasename": "The.Matrix.1999.720p.BluRay.x264",
    "subauthorcomment": "Commento opzionale dell'autore",
    "hearingimpaired": 0,
    "highDefinition": 1,
    "automatictranslation": 0,
    "foreignpartsonly": 0,
    "fromtrusted": 0
  }
}
```

### Campi del Body — Dettaglio Completo

#### Oggetto `sub_to_movie` (informazioni sul file video)

| Campo | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `movie_hash` | string | **Sì** | Hash a 16 hex del file video (vedi sezione 3) |
| `movie_byte_size` | string | **Sì** | Dimensione del file video in byte (come stringa) |
| `movie_fps` | string | No | FPS del video (es. `"23.976"`, `"25"`) |
| `movie_time_ms` | integer/null | No | Durata in millisecondi (opzionale) |
| `movie_filename` | string | No | Nome del file video (con estensione) |

#### Campi diretti del sottotitolo

| Campo | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `sub_content` | string | **Sì** | Contenuto del sottotitolo: **compresso con gzip** e poi **codificato in Base64** |
| `sub_hash` | string | **Sì** | Hash MD5 del file di sottotitolo originale (non compresso) |
| `sub_language_id` | string | **Sì** | Codice lingua ISO 639-1 a 2 lettere (es. `"en"`, `"it"`, `"fr"`) |
| `sub_filename` | string | **Sì** | Nome del file sottotitolo con estensione (es. `"movie.eng.srt"`) |
| `comments` | string | No | Commento visibile agli utenti |
| `hearing_impaired` | boolean | No | `true` se è per non udenti (HI/SDH) |
| `foreign_parts_only` | boolean | No | `true` se copre solo le parti in lingua straniera |
| `high_definition` | boolean | No | `true` se il sottotitolo è per una release HD |

#### Oggetto `baseinfo` (metadati del film)

| Campo | Tipo | Obbligatorio | Descrizione |
|---|---|---|---|
| `idmovieimdb` | string | **Sì** (o `feature_id`) | IMDB ID senza `tt` e senza zeri iniziali |
| `sublanguageid` | string | **Sì** | Codice lingua ISO 639-2/B a 3 lettere (es. `"eng"`, `"ita"`, `"fra"`) |
| `moviereleasename` | string | No | Nome della release (es. `"Movie.2023.1080p.BluRay.x264-GROUP"`) |
| `subauthorcomment` | string | No | Commento dell'autore |
| `hearingimpaired` | integer | No | `0` o `1` |
| `highDefinition` | integer | No | `0` o `1` |
| `automatictranslation` | integer | No | `0` o `1` (default `0`) |
| `foreignpartsonly` | integer | No | `0` o `1` |

> **Nota sui codici lingua:** `sub_language_id` usa ISO 639-1 (2 lettere: `en`), mentre `sublanguageid` in `baseinfo` usa ISO 639-2/B (3 lettere: `eng`). Sono formati **diversi** per lo stesso campo lingua — attenzione!

---

## 6. Come Preparare `sub_content` (Gzip + Base64)

Il contenuto del file di sottotitolo deve essere:
1. Letto come testo/bytes
2. Compresso con **gzip**
3. Codificato in **Base64**

### Python
```python
import gzip
import base64
import hashlib

def prepare_subtitle_for_upload(subtitle_filepath):
    """Legge un .srt/.vtt, lo gzippa e lo codifica in base64."""
    with open(subtitle_filepath, 'rb') as f:
        raw_content = f.read()
    
    # Calcola MD5 del file originale (non compresso)
    sub_hash = hashlib.md5(raw_content).hexdigest()
    
    # Comprimi con gzip
    compressed = gzip.compress(raw_content)
    
    # Codifica in base64
    encoded = base64.b64encode(compressed).decode('utf-8')
    
    return encoded, sub_hash

# Uso:
# sub_content, sub_hash = prepare_subtitle_for_upload("/path/to/subtitle.srt")
```

### Node.js
```javascript
const fs = require('fs');
const zlib = require('zlib');
const crypto = require('crypto');

function prepareSubtitleForUpload(subtitlePath) {
  const rawContent = fs.readFileSync(subtitlePath);
  
  // MD5 del file originale
  const subHash = crypto.createHash('md5').update(rawContent).digest('hex');
  
  // Gzip + Base64
  const compressed = zlib.gzipSync(rawContent);
  const encoded = compressed.toString('base64');
  
  return { subContent: encoded, subHash };
}
```

---

## 7. Esempio Completo di Upload — Python

```python
import os
import gzip
import base64
import hashlib
import struct
import requests

API_KEY = "YOUR_API_KEY"
USERNAME = "your_username"
PASSWORD = "your_password"

def compute_moviehash(filepath):
    filesize = os.path.getsize(filepath)
    longlongformat = '<q'
    bytesize = struct.calcsize(longlongformat)
    with open(filepath, 'rb') as f:
        file_hash = filesize
        for _ in range(65536 // bytesize):
            buf = f.read(bytesize)
            (val,) = struct.unpack(longlongformat, buf)
            file_hash = (file_hash + val) & 0xFFFFFFFFFFFFFFFF
        f.seek(max(0, filesize - 65536))
        for _ in range(65536 // bytesize):
            buf = f.read(bytesize)
            (val,) = struct.unpack(longlongformat, buf)
            file_hash = (file_hash + val) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % file_hash

def login(api_key, username, password):
    resp = requests.post(
        "https://api.opensubtitles.com/api/v1/login",
        headers={
            "Api-Key": api_key,
            "User-Agent": "MyApp v1.0.0",
            "Content-Type": "application/json"
        },
        json={"username": username, "password": password}
    )
    resp.raise_for_status()
    data = resp.json()
    return data["token"], data["base_url"]

def upload_subtitle(token, base_url, api_key,
                    video_path, subtitle_path,
                    imdb_id, language_2="en", language_3="eng",
                    release_name="", comments="",
                    hearing_impaired=False, hd=True):
    
    # 1. Calcola hash e dimensione del video
    movie_hash = compute_moviehash(video_path)
    movie_byte_size = str(os.path.getsize(video_path))
    movie_filename = os.path.basename(video_path)
    
    # 2. Prepara il sottotitolo
    with open(subtitle_path, 'rb') as f:
        raw = f.read()
    sub_hash = hashlib.md5(raw).hexdigest()
    compressed = gzip.compress(raw)
    sub_content = base64.b64encode(compressed).decode('utf-8')
    sub_filename = os.path.basename(subtitle_path)
    
    # 3. Costruisci il body
    body = {
        "base_subtitle_id": None,
        "subtitles": [
            {
                "sub_to_movie": {
                    "movie_hash": movie_hash,
                    "movie_byte_size": movie_byte_size,
                    "movie_fps": None,
                    "movie_time_ms": None,
                    "movie_filename": movie_filename
                },
                "sub_content": sub_content,
                "sub_hash": sub_hash,
                "sub_language_id": language_2,
                "sub_filename": sub_filename,
                "comments": comments,
                "hearing_impaired": hearing_impaired,
                "foreign_parts_only": False,
                "high_definition": hd
            }
        ],
        "baseinfo": {
            "idmovieimdb": str(imdb_id),
            "sublanguageid": language_3,
            "moviereleasename": release_name,
            "subauthorcomment": comments,
            "hearingimpaired": 1 if hearing_impaired else 0,
            "highDefinition": 1 if hd else 0,
            "automatictranslation": 0,
            "foreignpartsonly": 0,
            "fromtrusted": 0
        }
    }
    
    # 4. Esegui l'upload
    resp = requests.post(
        f"https://{base_url}/api/v1/upload",
        headers={
            "Api-Key": api_key,
            "Authorization": f"Bearer {token}",
            "User-Agent": "MyApp v1.0.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        json=body
    )
    
    return resp.status_code, resp.json()

# ---- ESECUZIONE ----
token, base_url = login(API_KEY, USERNAME, PASSWORD)

status, result = upload_subtitle(
    token=token,
    base_url=base_url,
    api_key=API_KEY,
    video_path="/path/to/TheMatrix.1999.mkv",
    subtitle_path="/path/to/TheMatrix.1999.en.srt",
    imdb_id="133093",       # senza "tt"
    language_2="en",        # ISO 639-1
    language_3="eng",       # ISO 639-2/B
    release_name="The.Matrix.1999.720p.BluRay.x264",
    comments="Sincronizzato manualmente",
    hearing_impaired=False,
    hd=True
)

print(f"Status: {status}")
print(f"Result: {result}")
```

---

## 8. Risposta dell'Upload

### 200 OK — Upload Riuscito
```json
{
  "data": {
    "subtitle": {
      "subtitle_id": "10234567",
      "language": "en",
      "upload_date": "2025-03-15T10:30:00Z",
      "url": "https://www.opensubtitles.com/en/subtitles/10234567"
    }
  },
  "message": "Subtitle uploaded successfully"
}
```

### 208 Already Reported — Sottotitolo Già Presente
```json
{
  "data": {
    "subtitle": {
      "subtitle_id": "9876543"
    }
  },
  "message": "Subtitle already in database"
}
```
Questo non è un errore! Significa che il sottotitolo (identificato dall'hash MD5) è già nel database. Il `subtitle_id` restituito è quello del sottotitolo già esistente.

---

## 9. Codici di Errore dell'Upload

| Codice HTTP | Significato | Cosa fare |
|---|---|---|
| `200` | Upload riuscito | ✅ |
| `208` | Sottotitolo già presente nel DB | Considerarlo un successo parziale; usare l'`subtitle_id` restituito |
| `400` | Bad Request — parametri mancanti o malformati | Controllare il body JSON, i campi obbligatori, la codifica base64 |
| `401` | Unauthorized — API key mancante/invalida o token scaduto | Rifare il login e ottenere un nuovo token |
| `403` | Forbidden — utente non ha i permessi per l'upload | Verificare il livello dell'account; alcuni tipi di upload richiedono account verificati |
| `406` | Not Acceptable — header `Accept` mancante o non supportato | Aggiungere `Accept: application/json` |
| `415` | Unsupported Media Type | Verificare `Content-Type: application/json` |
| `422` | Unprocessable Entity — dati semanticamente errati | L'hash del sottotitolo non corrisponde, o `sub_content` non è base64 valido |
| `429` | Too Many Requests — rate limit superato | Attendere e riprovare con backoff esponenziale |
| `500` | Internal Server Error | Problema lato server; riprovare dopo qualche secondo |

---

## 10. Endpoint `/api/v1/logout`

Dopo l'upload, invalidare il token è buona pratica.

```http
DELETE /api/v1/logout
```

**Headers:**
```http
Api-Key: YOUR_API_KEY
Authorization: Bearer YOUR_JWT_TOKEN
User-Agent: MyApp v1.0.0
```

**Risposta 200:**
```json
{
  "message": "token successfully destroyed",
  "status": 200
}
```

---

## 11. Endpoint Utili per il Debug

### Verifica informazioni utente e quota

```http
GET /api/v1/infos/user
```

**Headers:**
```http
Api-Key: YOUR_API_KEY
Authorization: Bearer YOUR_JWT_TOKEN
User-Agent: MyApp v1.0.0
Accept: application/json
```

**Risposta:**
```json
{
  "data": {
    "allowed_downloads": 100,
    "level": "Sub leecher",
    "user_id": 66,
    "ext_installed": false,
    "vip": false,
    "downloads_count": 5,
    "remaining_downloads": 95
  }
}
```

### Parse del nome file video (Guessit)

Utile per estrarre automaticamente metadati dal nome del file.

```http
GET /api/v1/utilities/guessit?filename=The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv
```

**Risposta:**
```json
{
  "title": "The Matrix",
  "year": 1999,
  "season": null,
  "episode": null,
  "screen_size": "1080p",
  "source": "BluRay",
  "video_codec": "H.264",
  "release_group": "GROUP",
  "type": "movie"
}
```

---

## 12. Flusso Completo — Diagramma

```
1. LOGIN
   POST /api/v1/login
   → Ottieni: token JWT + base_url
          ↓
2. TROVARE IL FILM
   GET /api/v1/features?imdb_id=XXXXX
   → Ottieni: feature_id, imdb_id confermato
          ↓
3. PREPARARE IL FILE SOTTOTITOLO
   - Leggi il file .srt/.vtt
   - Calcola MD5 → sub_hash
   - Gzip → Base64 → sub_content
          ↓
4. PREPARARE I DATI VIDEO
   - Calcola moviehash (64KB inizio + 64KB fine + filesize)
   - Ottieni filesize in byte
          ↓
5. UPLOAD
   POST /api/v1/upload
   Headers: Api-Key + Authorization: Bearer <token>
   Body: { subtitles: [...], baseinfo: {...} }
   → Risposta: 200 (successo) o 208 (già presente)
          ↓
6. LOGOUT (opzionale ma consigliato)
   DELETE /api/v1/logout
```

---

## 13. Checklist Debug — Errori Comuni

| Problema | Causa Probabile | Soluzione |
|---|---|---|
| `401` sull'upload | Token scaduto o non inviato | Rifare login; verificare header `Authorization: Bearer ...` |
| `400` "missing parameters" | Campi obbligatori mancanti | Verificare: `sub_content`, `sub_hash`, `sub_language_id`, `sub_filename`, `idmovieimdb` |
| `400` o `422` sul `sub_content` | Base64 non valido o non gzippato | Verificare che il processo sia: bytes → gzip.compress() → base64.b64encode() → decode('utf-8') |
| `208` sempre | Hash MD5 del sottotitolo già nel DB | Non è un bug — il sottotitolo esiste già |
| `406` | Header `Accept` mancante | Aggiungere `Accept: application/json` |
| Upload va a buon fine ma non compare nella ricerca | Cache del DB | Normale ritardo fino a qualche ora; non riuploadare |
| Lingua sbagliata nel risultato | Confusione tra ISO 639-1 e 639-2 | `sub_language_id` = 2 lettere (`en`); `sublanguageid` in baseinfo = 3 lettere (`eng`) |
| `movie_hash` invalido | File video troppo piccolo o algoritmo sbagliato | Verificare che il file sia > 128 KB; ricontrollare l'algoritmo (little-endian, 64-bit, chunk da 64 KB) |
| Token non funziona dopo il login | `base_url` sbagliato | Usare il `base_url` restituito dal login, non hardcoded |

---

## 14. Tabella Codici Lingua

I codici più comuni per l'Europa:

| Lingua | ISO 639-1 (`sub_language_id`) | ISO 639-2/B (`sublanguageid`) |
|---|---|---|
| Italiano | `it` | `ita` |
| Inglese | `en` | `eng` |
| Francese | `fr` | `fra` |
| Spagnolo | `es` | `spa` |
| Tedesco | `de` | `ger` |
| Portoghese (BR) | `pt-BR` | `pob` |
| Greco | `el` | `ell` |
| Russo | `ru` | `rus` |
| Arabo | `ar` | `ara` |
| Cinese (simp.) | `zh-CN` | `chi` |
| Giapponese | `ja` | `jpn` |

> **Nota importante:** Per il portoghese brasiliano usare `pt-BR` (non `pt`) nel campo ISO 639-1.

---

## 15. Riferimenti

- **Documentazione ufficiale (Stoplight):** https://opensubtitles.stoplight.io/docs/opensubtitles-api/
- **API Base URL:** `https://api.opensubtitles.com/api/v1`
- **VIP API Base URL:** `https://vip-api.opensubtitles.com/api/v1` (solo se restituito dal login)
- **Forum sviluppatori:** https://forum.opensubtitles.org/viewforum.php?f=8
- **Registrazione account:** https://www.opensubtitles.com/
- **Ottenere API Key:** Profilo utente → sezione "API Consumers"

---

*Documento generato il 15 marzo 2026. La documentazione API potrebbe aggiornarsi — verificare sempre su opensubtitles.stoplight.io per eventuali modifiche.*
