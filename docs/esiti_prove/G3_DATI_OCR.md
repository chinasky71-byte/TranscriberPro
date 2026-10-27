# G3: dati di prova per la revisione OCR (sottotitoli bitmap)

Estratti brevi (~4 minuti, copia dei flussi senza ricodifica, dal minuto 10) di tre MKV della libreria del proprietario. Restano solo sul PC, in `Desktop\g3_prova_dati\ocr` (video e `.sup` NON sono nel repository). Gli originali non sono stati modificati.

## File
| File (nome nel PC) | Durata | Dimensione | Tracce sottotitoli (ordine nell'estratto) |
|---|---|---|---|
| `shrek_estratto.mkv` | 251 s | 86 MB | 0: PGS eng; 1: SubRip it |
| `cinderella_man_estratto.mkv` | 248 s | 47 MB | 0: SubRip ita (forced); 1: **VobSub** ita; 2: **VobSub** eng; 3: PGS ita; 4: PGS eng |
| `blue_warmest_color_estratto.mkv` | 246 s | 77 MB | 0: PGS ita; 1: PGS eng; 2: PGS ita (SDH) |

Copertura richiesta: (a) PGS inglese: Shrek, Cinderella Man (e Blue Is the Warmest Color); (b) PGS italiano: Cinderella Man, Blue Is the Warmest Color; (c) piu' tracce PGS: Cinderella Man (2) e Blue Is the Warmest Color (3, di cui una SDH); VobSub (dvd_subtitle): Cinderella Man (ita ed eng). Ogni estratto ha 1 traccia video e 1 audio (copiate).

## Controllo degli estratti
Creati con `ffmpeg -ss 600 -t 240 -i <originale> -map 0:v:0 -map 0:a:0 -map 0:s -c copy` (`-ss` prima di `-i`). Verifica: ffprobe conferma le tracce sopra; per ogni traccia PGS l'estrazione `-f sup` produce un file > 0 byte e ci sono pacchetti nell'intervallo, quindi i sottotitoli non sono vuoti ne' sfasati fuori finestra.

| Estratto | Traccia | .sup (byte) | Pacchetti |
|---|---|---|---|
| shrek | PGS eng | 1.254.783 | 109 |
| cinderella_man | PGS ita | 667.309 | 83 |
| cinderella_man | PGS eng | 705.476 | 87 |
| cinderella_man | VobSub ita | - | 42 |
| cinderella_man | VobSub eng | - | 44 |
| blue_warmest_color | PGS ita | 781.819 | 74 |
| blue_warmest_color | PGS eng | 1.038.003 | 98 |
| blue_warmest_color | PGS ita (SDH) | 799.103 | 78 |

## Strumenti (nessuno mancante)
- `ffmpeg`/`ffprobe` 8.0 (build gyan.dev), `tesseract` 5.5.0 (20241111), `mkvmerge` v99.0 e `mkvextract`: tutti raggiungibili nel PATH (shim Scoop).
- Tesseract, lingue installate (`--list-langs`): deu, eng, fra, ita, nld, por, spa: **ita ed eng presenti**.
- Nulla e' stato installato.
