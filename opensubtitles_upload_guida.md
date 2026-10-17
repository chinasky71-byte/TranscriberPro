# Upload sottotitoli su OpenSubtitles — guida riutilizzabile

Estratta e ripulita da un'implementazione funzionante e testata in produzione
(Transcriber Pro, upload reale riuscito verificato, IDSubtitle 14025912).
Il codice qui sotto è autonomo: non dipende da nessuna classe del progetto
di origine, si può incollare in qualunque tool Python nuovo.

## 0. Le due API — leggere prima di tutto

OpenSubtitles ha **due servizi distinti, con account e credenziali separate**:

| | opensubtitles.**org** | opensubtitles.**com** |
|---|---|---|
| Protocollo | XML-RPC | REST (v1) |
| Upload sottotitoli | **Funziona** | **Bloccato**: l'endpoint `POST /api/v1/subtitles/upload` risponde `403 uploads_not_enabled` per i consumer normali — va richiesta l'abilitazione esplicita a OpenSubtitles |
| Credenziali | username/password `.org` | username/password/API-key `.com` |

**Non sono intercambiabili**: stesso username non significa stessa password,
e le credenziali dell'uno non "sbloccano" l'altro. Se l'upload deve
funzionare oggi, **usare XML-RPC**. Questa guida copre solo quello.

## 1. User-Agent

```python
OPENSUBTITLES_USER_AGENT = "NomeTool v1.0.0"
```

La pagina di registrazione User-Agent (`opensubtitles.org/addons/new`) **non
esiste più dal 2022**: da allora qualunque stringa `"Nome vX.Y.Z"` viene
accettata. Non è mai la causa di un errore di login — se il login fallisce
è quasi sempre un problema di credenziali (vedi tabella errori in fondo).

## 2. Login

```python
import xmlrpc.client
import hashlib

XMLRPC_URL = "https://api.opensubtitles.org/xml-rpc"

server = xmlrpc.client.ServerProxy(XMLRPC_URL, allow_none=True)

def login(username: str, password: str, user_agent: str) -> str | None:
    password_hash = hashlib.md5(password.encode('utf-8')).hexdigest()
    response = server.LogIn(username, password_hash, 'en', user_agent)

    status = response.get('status', '')
    token = response.get('token')

    if token and status == '200 OK':
        return token

    if status == '401 Unauthorized':
        # Il token restituito con 401 è ANONIMO, non autentica nulla.
        # Causa quasi sempre: credenziali .com usate al posto di quelle .org
        # (sono account separati, vedi sezione 0).
        raise ValueError(f"Credenziali .org errate per '{username}'")

    raise ValueError(f"Login fallito: {status}")
```

## 3. L'hash del video (OSDB hash)

OpenSubtitles identifica il film non dal nome file ma da un hash a 64 bit
calcolato su dimensione + primi/ultimi 64KB del file. Serve per associare
il sottotitolo al film giusto nel loro database.

```python
import os
import struct
from pathlib import Path

def calculate_movie_hash(video_path: Path) -> tuple[str, int] | tuple[None, None]:
    """Ritorna (hash_hex, file_size_bytes). Il file dev'essere >= 128KB."""
    file_size = os.path.getsize(video_path)
    if file_size < 131072:
        return None, None

    hash_value = file_size

    with open(video_path, 'rb') as f:
        # Somma i primi 64KB come interi a 8 byte (little-endian, signed)
        for _ in range(8192):
            chunk = f.read(8)
            if len(chunk) < 8:
                break
            (value,) = struct.unpack('<q', chunk)
            hash_value += value
            hash_value &= 0xFFFFFFFFFFFFFFFF

        # Somma gli ultimi 64KB
        f.seek(max(0, file_size - 65536), 0)
        for _ in range(8192):
            chunk = f.read(8)
            if len(chunk) < 8:
                break
            (value,) = struct.unpack('<q', chunk)
            hash_value += value
            hash_value &= 0xFFFFFFFFFFFFFFFF

    return f"{hash_value:016x}", file_size
```

Questo è l'algoritmo standard "OSDB hash" (lo stesso usato da altri
strumenti che parlano con OpenSubtitles, non è specifico di questo
progetto) — se serve anche altrove, questa funzione è portabile così com'è.

## 4. Preparare il contenuto del sottotitolo — LA PARTE CON I GOTCHA REALI

Questo è il punto dove un'implementazione ingenua fallisce in modo
totalmente incomprensibile dai messaggi d'errore. Due problemi distinti,
**entrambi con la stessa causa radice**:

### 4a. zlib, NON gzip

```python
import zlib
import base64

def prepare_subtitle_content(subtitle_path: Path) -> tuple[str, bytes]:
    """Ritorna (subcontent_per_xmlrpc, contenuto_pulito_per_hash)."""
    with open(subtitle_path, 'rb') as f:
        raw = f.read()

    try:
        text = raw.decode('utf-8-sig')  # strip BOM se presente
    except UnicodeDecodeError:
        text = raw.decode('latin-1')

    content = text.encode('utf-8')

    # ⚠️ DEVE essere zlib (header 0x78), NON gzip (header 0x1f 0x8b).
    # La documentazione ufficiale OpenSubtitles chiama il campo "gzipped
    # base64 encoded", ma l'esempio XML che pubblicano è inequivocabilmente
    # zlib. Il server decomprime con l'equivalente di gzuncompress(): sul
    # contenitore gzip fallisce IN SILENZIO a stringa vuota.
    subcontent = base64.b64encode(zlib.compress(content, 9)).decode('ascii')

    return subcontent, content
```

**Sintomo se si sbaglia**: l'upload sembra riuscire a livello di chiamata
XML-RPC, ma il server torna contemporaneamente **due errori che sembrano
scollegati**:
- `403 SubHashes non corrispondono` — perché l'hash che hai calcolato è
  su testo vero, ma il server ha decompresso a stringa vuota e confronta
  con `md5('')`;
- `402 formato non valido` — perché `GetSubFormat('')` non riconosce
  niente in una stringa vuota.

**Sono lo stesso identico bug visto da due angolazioni diverse**, non due
problemi da risolvere separatamente. Se li vedete insieme, guardate qui
prima di ogni altra ipotesi.

### 4b. Niente doppia codifica Base64

`xmlrpc.client.Binary(...)` applica **un'altra** base64 sopra quella che
hai già fatto a mano. Il campo `subcontent` va passato come **stringa
Python normale** (il tipo XML-RPC `<string>`), non avvolto in `Binary`.

### 4c. L'hash del sottotitolo si calcola sul contenuto ripulito, non su quello grezzo

Se il vostro SRT contiene una riga di attribuzione/watermark (es. "Generato
con XYZ") **prima** del primo sottotitolo vero, OpenSubtitles la rifiuta
con `402 Invalid format`. Va rimossa PRIMA di comprimere e PRIMA di
calcolare l'hash — e l'hash deve essere calcolato sullo **stesso identico
contenuto** che viene inviato, altrimenti si ottiene di nuovo il
`403 SubHashes non corrispondono` di sopra:

```python
import re

def strip_credit_block(text: str, credit_patterns: list[str]) -> str:
    """Rimuove blocchi SRT promozionali e rinumera quelli restanti."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    blocks = re.split(r'\n{2,}', text.strip())
    kept = []
    for block in blocks:
        lines = block.strip().splitlines()
        block_text = ' '.join(lines[2:]).lower() if len(lines) >= 3 else ''
        if any(p in block_text for p in credit_patterns):
            continue  # scarta il blocco promozionale
        kept.append(block)

    # Rinumera i blocchi rimasti (i numeri devono essere sequenziali da 1)
    renumbered = []
    for i, block in enumerate(kept, start=1):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and '-->' in lines[1]:
            lines[0] = str(i)
        renumbered.append('\n'.join(lines))
    return '\n\n'.join(renumbered) + '\n'
```

## 5. Controllare se il sottotitolo esiste già (opzionale ma consigliato)

`UploadSubtitles` non deduplica da solo lato client: se caricate lo stesso
file due volte create due voci. `TryUploadSubtitles` fa il controllo prima
di spendere la chiamata di upload vera:

```python
def check_already_uploaded(token, movie_hash, movie_size, sub_hash,
                            subtitle_filename, video_filename,
                            imdb_id: str | None = None) -> bool:
    try_data = {
        'subhash': sub_hash,
        'subfilename': subtitle_filename,
        'moviehash': movie_hash,
        'moviebytesize': str(movie_size),
        'moviefilename': video_filename,
    }
    if imdb_id:
        try_data['movieimdbid'] = imdb_id.replace('tt', '')

    response = server.TryUploadSubtitles(token, [try_data])
    if response.get('status', '') != '200 OK':
        raise ValueError(f"Errore verifica: {response.get('status')}")

    return response.get('alreadyindb', 0) == 1
```

## 6. L'upload vero — struttura corretta della chiamata

Il punto più delicato: `UploadSubtitles` vuole un dizionario con **due
chiavi esatte**, `baseinfo` e `cd1` (cd2, cd3... per sottotitoli multi-CD,
irrilevante oggi). Sbagliare questa forma dà errori poco parlanti.

```python
def upload_subtitle(
    token: str,
    video_path: Path,
    subtitle_path: Path,
    imdb_id: str,              # formato "tt1234567"
    language_code_iso639_2: str,  # 3 lettere, es. "ita", "eng"
    release_name: str,
    username: str = '',
    comments: str = '',
    credit_patterns: list[str] = None,
) -> tuple[bool, str]:
    """Ritorna (successo, url_o_messaggio_errore)."""
    credit_patterns = credit_patterns or []

    movie_hash, movie_size = calculate_movie_hash(video_path)
    if not movie_hash:
        return False, "Impossibile calcolare l'hash del video"

    with open(subtitle_path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    cleaned = strip_credit_block(text, credit_patterns)
    stripped_bytes = cleaned.encode('utf-8')

    sub_hash = hashlib.md5(stripped_bytes).hexdigest()
    sub_content = base64.b64encode(zlib.compress(stripped_bytes, 9)).decode('ascii')

    imdb_numeric = imdb_id.replace('tt', '')

    # Step 1: evita duplicati
    if check_already_uploaded(token, movie_hash, movie_size, sub_hash,
                               subtitle_path.name, video_path.name, imdb_id):
        return True, "Sottotitolo già presente nel database"

    # Step 2: upload vero
    upload_struct = {
        'baseinfo': {
            'idmovieimdb': imdb_numeric,
            'sublanguageid': language_code_iso639_2,
            'moviereleasename': release_name,
            'movieaka': '',
            'subauthorcomment': comments or 'Uploaded via script',
            'subtranslator': username,
            'automatictranslation': '1',  # '1' se generato/tradotto da AI, '0' altrimenti
        },
        'cd1': {
            'subhash': sub_hash,
            'subfilename': subtitle_path.name,
            'moviehash': movie_hash,
            'moviebytesize': str(movie_size),
            'moviefilename': video_path.name,
            'subcontent': sub_content,   # stringa, MAI xmlrpc.client.Binary
        },
    }

    response = server.UploadSubtitles(token, upload_struct)
    status = response.get('status', '')

    if status == '200 OK':
        url = response.get('data', '')
        return True, (url if url else "Upload riuscito (nessun URL fornito)")

    return False, f"Upload fallito: {status}"
```

## 7. Logout

```python
def logout(token: str) -> None:
    try:
        server.LogOut(token)
    except Exception:
        pass  # il logout che fallisce non è mai un errore da propagare
```

## 8. Esempio completo, minimo, eseguibile

```python
import xmlrpc.client, hashlib, struct, os, base64, zlib, re
from pathlib import Path

USER_AGENT = "MioTool v1.0.0"
server = xmlrpc.client.ServerProxy("https://api.opensubtitles.org/xml-rpc", allow_none=True)

def main():
    token = login("mio_username_org", "mia_password_org", USER_AGENT)
    try:
        ok, msg = upload_subtitle(
            token=token,
            video_path=Path("Film.mkv"),
            subtitle_path=Path("Film.it.srt"),
            imdb_id="tt1234567",
            language_code_iso639_2="ita",
            release_name="Film.mkv",
            credit_patterns=["mio_watermark_da_rimuovere"],
        )
        print("OK" if ok else "ERRORE", msg)
    finally:
        logout(token)

if __name__ == '__main__':
    main()
```

## 9. Tabella errori — diagnosi rapida

| Errore | Causa reale (non quella apparente) |
|---|---|
| `401 Unauthorized` al login (con un token restituito comunque) | Credenziali `.com` usate al posto di quelle `.org` — token anonimo, non autentica nulla |
| `402 Invalid format` | Quasi sempre: il server ha decompresso a stringa vuota (vedi 4a — verificare zlib non gzip), oppure il file contiene un blocco di credit/watermark non rimosso |
| `403 SubHashes don't match` | Stessa causa di `402` sopra nella maggioranza dei casi: contenitore di compressione sbagliato, oppure l'hash è stato calcolato su un contenuto diverso da quello inviato (es. prima vs dopo lo strip del watermark) |
| `403 uploads_not_enabled` sulla REST API | Non è un bug vostro: l'endpoint upload della REST v1 è disabilitato di default per i consumer, serve richiedere l'abilitazione a OpenSubtitles. Usare XML-RPC nel frattempo |
| Login riesce ma l'upload fallisce silenziosamente | Controllare che `subcontent` sia una stringa Python semplice, non avvolta in `xmlrpc.client.Binary` (doppia codifica base64) |

## 10. Serie TV e anime: l'ID giusto e' quello dell'EPISODIO

Con XML-RPC il `baseinfo` di `UploadSubtitles` non ha campi per stagione ed episodio (nemmeno la REST, e la REST upload e' comunque
disabilitata di default): **la categorizzazione dipende solo da `idmovieimdb`**. Se si manda l'IMDb ID della *serie*, il
sottotitolo finisce sulla scheda della serie, senza stagione ne' episodio, e il sito lo mostra come "uncategorized".

- Serie normali: l'IMDb ID dell'episodio si ottiene da TMDB (`/tv/{id}/season/{s}/episode/{e}/external_ids`).
- Anime: TMDB di solito NON lo ha (Last Exile: vuoto per tutti gli episodi). Ripiego usato da TranscriberPro (v1.30.13): OMDb,
  cercando per **titolo** dell'episodio (nome TMDB en-US e titolo OMDb normalizzati, minuscolo e solo lettere/cifre, uguali e
  univoci), NON per numero di stagione: IMDb accorpa serie diverse sotto lo stesso ID (Last Exile 2003 e *Fam* 2011) e la
  numerazione non coincide con TMDB. Titoli generici ("Episode 11") e molto corti vanno scartati.
- Se l'ID dell'episodio non si trova, si resta sull'ID di serie: il sottotitolo e' valido ma non categorizzato. OpenSubtitles puo'
  non avere affatto le schede episodio di una serie (`GET /api/v1/features?query=...&type=episode`): in quel caso non c'e' nulla
  da fare lato client; dalla pagina del sottotitolo si puo' correggere a mano ("IMDB update / Edit").
- `GET /api/v1/features` accetta `imdb_id` e `query`+`type`; i parametri `parent_imdb_id`/`season_number` danno HTTP 400.

## Fonte

Estratto da un'implementazione reale, testata con upload riuscito
verificabile (IDSubtitle 14025912 su opensubtitles.org). I gotcha di
compressione (sezione 4) sono stati trovati per tentativi — non sono
documentati in modo chiaro nella documentazione ufficiale OpenSubtitles,
che descrive il campo come "gzipped" pur aspettandosi zlib.
