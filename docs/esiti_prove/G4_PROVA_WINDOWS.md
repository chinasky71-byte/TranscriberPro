# G4: prova su Windows (sessione locale) — Library Scanner

Branch da provare: **`refactor/g4-prova`** = master (1.34.40) + PR #48 (client HTTP), #49 (righe/filtri/badge), #50 (import in coda, conversione ASS, Superpower, OCR), già unite fra loro; suite Linux: 1045 test. Non unire nulla a master: l'esito va riferito al cloud.

## Regole
- **Il server Library Scanner vero si tocca SOLO in lettura** (GET `/api/stats` e `/api/videos`, mai POST: la notifica e la conversione ASS cambiano lo stato del server). La chiave API resta nel `config.json` locale: non stamparla, non scriverla nei rapporti.
- Tutto il resto contro il **finto server** `linux_tests/run_fake_scanner.py` (in locale, 127.0.0.1) con una home isolata (`$env:USERPROFILE = "C:\tp_prova_home_g4"; $env:HOME = ...`) e il config della home isolata puntato al finto (`library_scanner_url = http://127.0.0.1:<porta>`, `library_scanner_api_key = KEY`).
- L'OCR e il write-back lavorano SOLO su copie dei tre estratti di `Desktop\g3_prova_dati\ocr` (cartella di lavoro `Desktop\g4_prova_dati\lavoro`); imposta `ocr_writeback = sidecar` nel config isolato, così nessun MKV viene rimuxato in place.
- Controllo del computer (mouse/tastiera, screenshot) autorizzato come da `PROTOCOL.md`.

## 1. Automatica
`python -m pytest linux_tests -q` in un solo processo, home isolata, nessuna esclusione; confronta con master (attesi solo gli 8 ambientali; nessun crash). Test di G4: `test_library_scanner_*`.

## 2. Server vero, SOLA LETTURA (G4a)
Con uno script che usa i worker veri (`LibraryScannerWorker`, Qt offscreen) su G4 e su master, con il config vero SOLO per URL e chiave (leggi i valori da codice, non stamparli): richieste `both` e `videos` con filtro tipo e con ricerca di una parola; confronta i JSON di risposta e i segnali (stessi totali, stessi video, stesso ordine, stesso numero di righe). Riporta solo conteggi, non nomi di file. Caso errore: URL sbagliato → stesso messaggio «Server non raggiungibile».

## 3. Finto server + GUI vera (G4b, G4c)
Costruisci `routes.json` con 8-10 video finti (nomi con `ITA`/`ENG`, tipi film/serie, giorni 3…100, formati pgs/vobsub/mixed/None, due ASS, un PGS con testo ITA, `windows_path` che puntano alle COPIE in `lavoro`), avvia `python linux_tests/run_fake_scanner.py routes.json` e apri l'app (isolata) → Library Scanner. Per ogni punto confronta con master (screenshot affiancati, pixel per pixel dove possibile):
1. Tabella: nomi, tipo, giorni con colori (>14 ambra, >30 rosa), badge PGS/VOB/MIX/ASS, pulsanti «+», tooltip; ordinamento cliccando le intestazioni (giorni numerico).
2. Filtri: tipo, giorni, formato (PGS, VOBSUB, ASS/SSA, No SRT), ricerca (attesa 500 ms e ricarica); statistiche e pallino di connessione (verde/rosso se fermi il finto).
3. Import: «+» singolo, «Importa filtrati» (solo righe visibili), file già in coda con ✓; mappa percorsi (config `library_scanner_path_map` su Windows vuota: prova anche con una regola `V:\=C:\...` finta); file in lavorazione non reimportato.
4. Badge ASS: clic → il finto riceve `POST /api/subtitles/convert/start` col corpo corretto; messaggi di esito identici a master (200 / server fermo / 500).
5. Dopo un file elaborato (notifica): il finto riceve `POST /api/videos/notify-subtitle` con il percorso lato server.

## 4. OCR dal Library Scanner (G4d)
6. Clic sul badge PGS di una riga (copia) → OCR immediato con la strategia configurata (prova `review` con la finestra di revisione e `auto`), sidecar `.it.srt` con lo stesso SHA256 di master; stato nella coda dei lavori OCR (in coda → in corso → completato) e riga ✓.
7. **Superpower**: conferma, GET `/api/subtitles/list` (parametri `issue_type=bitmap&limit=500`), batch sui tre estratti in sequenza, avanzamento «OCR batch n/m», riepilogo finale; stesso SRT di master; a fine batch lista ricaricata.
8. Pipeline di trascrizione attiva (`is_processing`): l'OCR viene accodato come differito e parte a fine elaborazione. Se non riproducibile a mano, copri con lo script (non inventare).
9. Annulla/chiusura durante l'OCR: nessun processo tesseract/python orfano.

## 5. Riferire
Per ogni punto OK / differenza (testo o schermata) rispetto a master; pytest; nessuna chiave o nome di file reale nel rapporto. Se trovi una differenza NON correggere il codice.
