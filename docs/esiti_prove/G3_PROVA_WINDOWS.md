# G3 (parte 1: OCR e profilo): prova su Windows (sessione locale)

Branch da provare: **`refactor/g3-prova`** = master (1.34.39) + le PR #44 (Revisione OCR) e #45 (Profilo di trascrizione), già unite fra loro; la suite Linux passa (881 test). Non unire nulla a master: l'esito va riferito al proprietario. File di prova: vedi `docs/G3_DATI_OCR.md` (MKV con PGS in `Desktop\g3_prova_dati\ocr`).

Dove sta cosa nella GUI:
- **Profilo**: Impostazioni → scheda «Trascrizione» (motore, stile dialoghi). Le schede dei profili sono nascoste di proposito (`SHOW_PROFILE_CARDS = False`): non provarle.
- **OCR**: Library Scanner → azione OCR su un video con sottotitoli bitmap; Impostazioni → scheda OCR (strategia: Revisione mirata / Solo automatico; write-back mux o sidecar; lingua; soglia).

## 0. Preparazione
1. Clone NUOVO di `refactor/g3-prova` (o aggiorna il clone G2 portandolo su questo branch) e un worktree di master per i confronti. Interprete: venv di produzione solo come eseguibile (cartella di lavoro e `PYTHONPATH` sul clone), senza modificare la produzione.
2. **Isola i dati** per le prove senza modelli: `$env:USERPROFILE = "C:\tp_prova_home_g3"; $env:HOME = $env:USERPROFILE` (cartella vuota; per l'OCR serve Tesseract, che è un programma di sistema, non nella home).
3. L'OCR scrive accanto al video / rimuxa nell'MKV: lavora SOLO sulle copie in `Desktop\g3_prova_dati\ocr`, mai sugli originali; prima di ogni prova di write-back fai una copia fresca del file.

## 1. Automatica
`python -m pytest linux_tests -q` in un solo processo, home isolata, nessuna esclusione. Riporta passati/falliti/saltati e confronta con master (attesi solo i fallimenti ambientali noti). Test di G3: `test_ocr_review_characterization.py`, `test_ocr_worker_characterization.py`, `test_profile_dialog_characterization.py`. Il run intero NON deve crashare (0xC0000409).

## 2. Manuale, GUI vera, senza modelli di trascrizione
Profilo:
1. Impostazioni → Trascrizione: la tendina del motore ha 4 voci (Auto, Canary, Qwen3, Faster-Whisper) nell'ordine di master; scegli ciascuna e riavvia: la scelta resta. «Stile dialoghi»: spunta/togli e riavvia: resta. Nessuna scheda di profilo visibile. Confronto con master identico.
OCR (con gli estratti MKV+PGS, Tesseract e tessdata ita/eng):
2. **Revisione mirata** su un PGS in italiano: si apre la finestra di revisione; elenco con pallini (verde/giallo/rosso), «#N» e testo, contatore «totale / da rivedere», immagine del bitmap, riga con timecode e confidenza. Prova: filtro «solo dubbi», Precedente/Successivo, Invio (salva e salta al prossimo dubbio), «Verificato» (compare ✓ e il contatore scende), pulsante corsivo con e senza selezione (`<i>…</i>`), modifica del testo, ridimensiona la finestra (l'immagine si adatta), «Fine».
3. Dopo «Fine»: il write-back (mux nell'MKV o `.srt` accanto al video, secondo l'impostazione) produce il risultato come su master: stesso SRT (stesso SHA256 su stesso input e stesse correzioni) e, in modalità mux, la traccia aggiunta nell'MKV.
4. **Solo automatico** su un PGS italiano: nessuna finestra di revisione, esito e file come su master.
5. PGS **non italiano** (inglese): il ramo traduce automaticamente (serve il motore di traduzione: se non disponibile, il file deve fallire con lo stesso messaggio di master; non lanciare download di modelli senza dirlo).
6. **Annulla** durante l'OCR (stop dalla coda/scanner): il worker si ferma, nessun tesseract/python orfano in Task Manager.
7. Casi di errore: file senza sottotitoli bitmap (messaggio «formato non supportato» come master), lingua senza tessdata (file saltato, messaggio «lingua non supportata»).

## 3. Riferire
Per ogni punto: OK / differenza (testo o schermata) rispetto a master; allega pytest. Se trovi una differenza NON correggere il codice.
