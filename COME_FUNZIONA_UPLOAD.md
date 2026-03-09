# Come funziona l'upload su OpenSubtitles

Questo documento spiega il flusso interno dell'applicazione **OpenSubtitles Uploader v2.8.0** dalla ricezione dei file fino all'invio del sottotitolo al server.

---

## Stack tecnologico

| Componente | Ruolo |
|---|---|
| **NW.js** | Runtime desktop (Chromium + Node.js in un'unica app) |
| **opensubtitles-api** | Libreria npm che incapsula le chiamate XML-RPC a OpenSubtitles |
| **mediainfo-wrapper** | Estrae metadati tecnici dal file video |
| **detect-lang** | Rileva la lingua del sottotitolo analizzando il testo |
| **trakt.tv** | Cerca titoli e ID IMDB (rimpiazzo dell'API SearchMoviesOnIMDB ora deprecata) |
| **got** | Client HTTP usato internamente da opensubtitles-api |

---

## Flusso completo, passo dopo passo

### 1. Avvio e login

Al lancio dell'app (`app.js` → `Boot.load()`):

- Viene creato l'oggetto globale `OS` tramite `new openSubtitles({ useragent, ssl })`.
- Se le credenziali sono già salvate in `localStorage` (`os_user`, `os_pw`), il login è considerato valido se è avvenuto nelle ultime **7 giorni** (`isFresh`).
- Altrimenti viene chiamato `OsActions.refreshInfo()` → `OS.login()`, che apre una sessione XML-RPC con il server OpenSubtitles e restituisce un token.

Il login è **lazy**: non blocca l'interfaccia e viene ripetuto automaticamente prima di ogni operazione che richiede un token (hash, identify, upload).

---

### 2. Caricamento dei file (Drag & Drop o Browse)

Il file può essere trascinato nell'interfaccia o selezionato con il file browser.

**`DragDrop.analyzeDrop(files)`** (`dragdrop.js`):
- Scorre i file droppati e seleziona il **primo video** e il **primo sottotitolo** supportati.
- Formati video supportati: `.mkv`, `.mp4`, `.avi`, `.ts`, ecc. (lista completa in `files.js`).
- Formati sottotitolo supportati: `.srt`, `.sub`, `.smi`, `.txt`, `.ssa`, `.ass`, `.mpl`.

**`DragDrop.handleDrop(files)`**:
- Chiama `Interface.add_video(path)` e/o `Interface.add_subtitle(path)` in base ai file riconosciuti.

---

### 3. Elaborazione del file video (`Interface.add_video`)

Questa è la fase più articolata. Avviene in cascata di Promise:

#### 3a. Hash del video
```
OS.hash(file)
```
La libreria `opensubtitles-api` calcola due valori:
- **`moviehash`**: hash specifico OpenSubtitles, calcolato sui primi e ultimi 64 KB del file (algoritmo proprietario OS).
- **`moviebytesize`**: dimensione in byte del file.

Questi due valori identificano univocamente il video nel database di OpenSubtitles.

#### 3b. Identificazione automatica del film
```
OS.identify(file)
```
Invia l'hash a OpenSubtitles per trovare quale film/episodio corrisponde. Se trovato, restituisce titolo, anno, ID IMDB.

#### 3c. Metadati tecnici con MediaInfo
```
Files.mediainfo(file)
```
Lancia il binario `mediainfo` (tramite `mediainfo-wrapper`) sul file video ed estrae:
- **Durata** in millisecondi (`movietimems`)
- **Frame rate** (`moviefps`)
- **Numero di fotogrammi** (`movieframes`)
- **Risoluzione** (larghezza/altezza) — usata per rilevare se il video è HD (≥720p)

Questi dati vengono poi inseriti nel form e inviati insieme al sottotitolo.

#### 3d. Ricerca IMDB
Se `OS.identify` non ha trovato una corrispondenza, l'app prova con:
```
OS.api.GuessMovieFromString(token, [filename])
```
Se anche questo fallisce, il campo IMDB rimane vuoto (l'utente può cercarlo manualmente).

L'utente può anche cercare manualmente tramite il popup di ricerca, che ora usa **Trakt.tv** (la vecchia `SearchMoviesOnIMDB` di OpenSubtitles non funziona più dal maggio 2023):
```
TRAKT.search.text({ type: 'movie,show,episode', query: '...', limit: 25 })
```

---

### 4. Elaborazione del file sottotitolo (`Interface.add_subtitle`)

Quando viene caricato un sottotitolo:

1. **MD5 hash del file** → `OS.md5(file)` → campo `subhash`
2. **Rilevamento lingua** → `Files.detectSubLang()`:
   - Prima tenta con la libreria `detect-lang` (analisi del testo, soglia minima 25% di probabilità)
   - Fallback: cerca un codice lingua nell'estensione del nome file (es. `film.ita.srt`)
3. **Rilevamento traduzione automatica** → `Files.detectMachineTranslated()`: cerca parole chiave come "auto translated", "google translate", ecc. nel nome file e nel contenuto
4. **Rilevamento non udenti** → `Files.detectSoundDescriptions()`: conta le parentesi nel testo; se sono più di 10, segna come "hearing impaired"
5. **Rilevamento parti straniere** → `Files.detectForeignOnly()`: cerca "forced"/"foreign parts" nel nome file, oppure controlla se il file pesa meno di 5 KB

---

### 5. Verifica prima dell'upload (`OsActions.verify`)

Cliccando il pulsante Upload:

1. Controlla che il campo `#subtitle-file-path` non sia vuoto (obbligatorio).
2. Se manca l'ID IMDB, mostra un avviso (non bloccante): l'utente può scegliere di caricare lo stesso.
3. Se tutto è ok, chiama `OsActions.upload()`.

---

### 6. Upload (`OsActions.upload`)

Raccoglie tutti i dati dal form e chiama:

```javascript
OS.upload({
    path: '/percorso/video.mkv',       // percorso file video (per hash)
    subpath: '/percorso/sub.srt',      // percorso file sottotitolo
    sublanguageid: 'ita',              // codice lingua ISO 639-2
    imdbid: 'tt1234567',               // ID IMDB
    highdefinition: true,              // video HD
    hearingimpaired: false,            // per non udenti
    moviereleasename: 'Film.2020.BluRay', // nome release
    movieaka: '',                      // titolo alternativo
    moviefps: '23.976',               // frame rate
    movieframes: '123456',             // numero fotogrammi
    movietimems: '5400000',           // durata in ms
    automatictranslation: false,       // traduzione automatica
    foreignpartsonly: false,           // solo parti straniere
    subauthorcomment: '',              // commento autore
    subtranslator: ''                  // nome traduttore
})
```

Internamente, la libreria `opensubtitles-api` esegue due chiamate XML-RPC in sequenza:

1. **`TryUploadSubtitles`**: verifica se il sottotitolo è già nel database (stesso hash MD5 o stesso moviehash+filename). Il server risponde con `alreadyindb: 0` o `1`.
2. **`UploadSubtitles`** (solo se non già presente): invia il contenuto del file sottotitolo codificato in **Base64 + GZip**, insieme a tutti i metadati raccolti.

---

### 7. Gestione della risposta

| Risposta | Comportamento |
|---|---|
| `status: 200` + `alreadyindb: 0` | Upload riuscito, modale verde con link al sottotitolo |
| `status: 200` + `alreadyindb: 1` | Sottotitolo già presente; il server aggiunge solo l'hash e/o il nome file se mancavano |
| `503` / `ETIMEDOUT` | Server non raggiungibile, modale rosso con opzione "Riprova" |
| `506` | Server in manutenzione |
| `402` | Formato sottotitolo non valido (es. contiene URL pubblicitari) |

---

---

## Accesso alle API di OpenSubtitles

### Protocollo: XML-RPC

OpenSubtitles espone un'API basata su **XML-RPC** (non REST/JSON). Ogni chiamata è una richiesta HTTP POST con corpo XML verso uno di questi endpoint:

| Modalità | URL |
|---|---|
| HTTP (default) | `http://api.opensubtitles.org:80/xml-rpc` |
| HTTPS (SSL) | `https://api.opensubtitles.org:443/xml-rpc` |

La scelta tra i due è controllata dall'impostazione `localStorage.ssl` dell'app (attivabile dalle impostazioni). Il client XML-RPC è gestito dalla libreria npm `xmlrpc`, configurata in `node_modules/opensubtitles-api/lib/opensubtitles.js`.

```javascript
// Ogni metodo viene invocato con la stessa primitiva:
this.client.methodCall(methodName, [...args], callback)
```

---

### Autenticazione e gestione del token

#### 1. Chiamata `LogIn`

```xml-rpc
LogIn(username, password, language, useragent)
```

- **`username`** / **`password`**: credenziali inserite dall'utente (in chiaro nella chiamata, il protocollo XML-RPC non cifra il payload salvo HTTPS).
- **`language`**: fisso a `'en'`.
- **`useragent`**: stringa `"OpenSubtitles-Uploader v2.8.0"` — identificativo obbligatorio richiesto da OpenSubtitles per ogni client registrato.

Il server risponde con un **token di sessione** (stringa opaca) e dati utente (`IDUser`, `UserRank`, ecc.).

#### 2. Durata del token (TTL)

Il token viene cachato in memoria con un TTL di **15 minuti** (~895.000 ms):

```javascript
this.credentials.status.ttl = Date.now() + 895000
this.credentials.status.token = response.token
this.credentials.status.auth_as = this.credentials.username
```

Se una chiamata API viene fatta entro i 15 minuti dall'ultimo login, il token esistente viene riutilizzato senza rieseguire `LogIn`. Oltre i 15 minuti, il login viene ripetuto automaticamente.

#### 3. Refresh delle info utente (7 giorni)

Separato dal TTL del token, l'app salva in `localStorage`:
- `os_refreshed`: timestamp dell'ultimo aggiornamento delle info utente
- `os_rank`, `os_id`: rank e ID utente

Se `os_refreshed` è più vecchio di **7 giorni** (`604800000 ms`), al prossimo avvio viene rifatto `OS.login()` per aggiornare le informazioni, anche se le credenziali erano già memorizzate.

#### 4. Login in modalità portable

Se esiste il file `osu.json` nella stessa cartella dell'eseguibile, l'app è considerata **portable**: le impostazioni (incluse credenziali) vengono lette da quel file JSON all'avvio e riscritte alla chiusura, invece di usare il `localStorage` del browser.

```javascript
// All'avvio
const settings = require('../osu.json');
for (let s in settings) localStorage.setItem(s, settings[s]);

// Alla chiusura
fs.writeFileSync('./osu.json', JSON.stringify(localStorage));
```

---

### Metodi API utilizzati

| Metodo XML-RPC | Quando viene chiamato |
|---|---|
| `LogIn` | Avvio app, ogni 15 min, ogni operazione che richiede il token |
| `CheckMovieHash` | Dopo il calcolo dell'hash video, per identificare il film |
| `InsertMovieHash` | Se il film non è nel DB ma l'utente ha un file NFO con IMDB id |
| `GetIMDBMovieDetails` | Per recuperare titolo/anno da un ID IMDB |
| `GuessMovieFromString` | Fallback se `CheckMovieHash` non trova risultati |
| `TryUploadSubtitles` | Prima dell'upload: verifica se il sottotitolo esiste già |
| `UploadSubtitles` | Upload vero e proprio del sottotitolo |

> **Nota:** `SearchMoviesOnIMDB` era usata per la ricerca testuale di film, ma è **deprecata dal maggio 2023**. L'app ora usa Trakt.tv per questa funzione.

---

### Algoritmo dell'hash video (moviehash)

L'hash usato da OpenSubtitles **non è MD5 né SHA**, ma un algoritmo proprietario implementato in `lib/hash.js`:

1. Si legge la **dimensione del file** in byte (`file_size`).
2. Si leggono i **primi 64 KB** del file in un buffer.
3. Si leggono gli **ultimi 64 KB** del file in un buffer.
4. Si calcola un checksum a 64 bit **little-endian** sommando ogni blocco da 8 byte dei due buffer.
5. Il checksum finale è: `somma(file_size_hex, checksum_start, checksum_end)` in aritmetica a 64 bit con overflow.
6. Il risultato è una stringa esadecimale di 16 caratteri, zero-padded.

```
moviehash = pad16( hex64( file_size + Σ(chunk_start[8B]) + Σ(chunk_end[8B]) ) )
```

Questo hash, insieme alla dimensione del file (`moviebytesize`), identifica univocamente il video nel database di OpenSubtitles.

---

### Codifica del sottotitolo per l'upload

Il contenuto del file `.srt` (o altro formato) non viene inviato in chiaro. Prima dell'upload viene processato in `lib/hash.js → computeSubContent()`:

```
file .srt (binario)
    → zlib.deflate()     (compressione DEFLATE, equivalente a GZip senza header)
    → buffer.toString('base64')  (encoding Base64)
    → campo 'subcontent' nella chiamata UploadSubtitles
```

L'MD5 del file originale (non compresso) viene inviato separatamente nel campo `subhash` come verifica di integrità.

---

### Header HTTP e User-Agent

Ogni richiesta al server XML-RPC porta l'header:

```
User-Agent: opensubtitles-api v5.x.x
```

Questo è lo User-Agent della libreria npm, non dell'applicazione. L'User-Agent dell'applicazione (`OpenSubtitles-Uploader v2.8.0`) viene passato come **parametro** nella chiamata `LogIn`, non come header HTTP.

> OpenSubtitles richiede che ogni applicazione sia registrata con un User-Agent ufficiale. Usare uno User-Agent non approvato causa il rifiuto delle richieste.

---

## Schema riassuntivo

```
Utente trascina file
        │
        ▼
DragDrop.analyzeDrop()
  ├─ video? → Interface.add_video()
  │               ├─ OS.hash()          → moviehash + bytesize
  │               ├─ OS.identify()      → IMDB id (da hash)
  │               └─ Files.mediainfo()  → fps, frames, duration
  │
  └─ sub?   → Interface.add_subtitle()
                  ├─ OS.md5()           → subhash
                  ├─ detectSubLang()    → lingua
                  ├─ detectMachineTranslated()
                  ├─ detectSoundDescriptions()
                  └─ detectForeignOnly()

Utente clicca "Upload"
        │
        ▼
OsActions.verify()
        │
        ▼
OsActions.upload()
        │
        ▼
OS.upload() [opensubtitles-api]
  ├─ TryUploadSubtitles (XML-RPC)
  └─ UploadSubtitles    (XML-RPC) ← contenuto in Base64+GZip
        │
        ▼
Risposta server → modale con esito
```
