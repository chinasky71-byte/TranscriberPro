# G4: esito della prova su Windows (Library Scanner)

Branch provato: `refactor/g4-prova` (`dc75436` = master 1.34.40 + PR #48, #49, #50). Confronto con `master` (`f6c4e8a`) nello stesso ambiente. Nessuna modifica al codice, nessuna copia in produzione, nessun merge.
Dove ho lavorato: clone `Desktop\Transcriber_Pro_G4_prova`, worktree `Desktop\Transcriber_Pro_G4_master`, dati `Desktop\g4_prova_dati\lavoro` (copie degli estratti), home isolata `C:\tp_prova_home_g4`, interprete del venv di produzione (sola lettura). `ocr_writeback = sidecar`, finto server `linux_tests/run_fake_scanner.py` su 127.0.0.1. Nessuna chiave o nome di file reale in questo rapporto.

## 1. pytest (un solo processo, home isolata, nessuna esclusione)
| Ramo | Risultato |
|---|---|
| G4 | 1015 passati, 8 falliti, 28 saltati (87 s) |
| master | 919 passati, 8 falliti, 28 saltati (67 s) |

Gli 8 falliti sono gli stessi ambientali noti (test_amd_family x2, test_amd_rocm_f6, test_core_jobs_unit x3, test_queue_gui/runner_characterization::test_contratto_del_sottoprocesso), identici su entrambi; nessun crash.
**Prova inversa:** i 94 test `test_library_scanner_{actions,client,rows}_characterization` di G4 copiati temporaneamente nel worktree di master (poi rimossi) e lanciati contro il CODICE DI MASTER: 94/94 passano. Il comportamento osservabile di tabella, import, ASS, notifica, OCR, Superpower e client e' quindi lo stesso del vecchio codice.

## 2. Server vero, sola lettura (G4a)
`LibraryScannerWorker` vero (Qt offscreen), solo GET, config vero letto solo per URL e chiave (non stampati). G4 e master danno risposte **identiche** (hash dei JSON, conteggi, segnali, ordine) su: `both`, `stats`, `videos`, tipo `movie`, ricerca di una parola (con e senza tipo), filtro ASS/SSA (1 video), `both` + ASS. Il server ha oggi 0 video senza sottotitoli nel filtro predefinito (le richieste non banali sono quindi quelle ASS). Tipi non validi per il server (`series`, `film`, `tv`) -> «Errore HTTP: 422» identico; URL sbagliato -> «Server non raggiungibile: …» identico.

## 3. Finto server + GUI vera (G4b, G4c)
Eseguito sul ramo G4 con la GUI sullo schermo (mouse/tastiera simulati, screenshot):
| Punto | G4 |
|---|---|
| 1 Tabella: nomi, tipo, giorni con colori (ambra/rosa), badge PGS/VOB/MIX/ASS, pulsanti «+», ordinamento per Giorni (numerico) e per File | OK |
| 2 Statistiche «9 senza sub / 120 totali», pallino verde | OK (filtri tipo/giorni/formato: coperti dai 94 test, non ripetuti a mano) |
| 3 Import «+» singolo e «Importa tutti i filtrati»: righe con ✓, coda con i file «in coda» | OK |
| 4 Badge ASS: il finto riceve `POST /api/subtitles/convert/start` con corpo `{"video_ids": [7]}`; messaggio «Conversione avviata sul server per 1 file» | OK |
| 5 Dopo l'OCR: `POST /api/videos/notify-subtitle` con il percorso della copia | OK |
| 6 OCR immediato dal badge PGS, strategia `review`: finestra di revisione (37 eventi), «Fine revisione» -> sidecar `.it.srt`, «SRT scritto», job «completato», riga ✓ | OK |
| 7 Superpower: conferma, `GET /api/subtitles/list?issue_type=bitmap&limit=500`, batch in sequenza «OCR batch 1/2», riepilogo «Convertiti: 2 · Falliti: 0 (su 2)», lista ricaricata (`GET /api/stats` + `/api/videos`) | OK (2 file, non 3: vedi sotto) |
| 8 Pipeline attiva -> OCR differito | non riproducibile a mano: coperto dai test di caratterizzazione (94/94 su G4 e su master) |
| 9 Chiusura della finestra durante il batch Superpower («OCR batch 1/2 … Tesseract 100%») | OK: nessun processo tesseract/ffmpeg/mkvmerge/python orfano |

SHA256 degli SRT (primi 16 caratteri): OCR automatico di G4 (da GUI, Superpower) = OCR automatico di master (stesso `OcrWorker`, script offscreen): `Film.Uno…ITA` `10AFDC0058C9D1DD`, `Serie.Due…ENG` `49A4E126A0A62139`. Revisione (G4, GUI): `E12BD457AA4FDFB0`.

## 4. Differenze / osservazioni (nessuna corretta)
1. **Larghezza colonne della tabella non deterministica.** All'apertura del pannello, in alcune partenze la tabella mostra tutte le colonne (File, Tipo, Giorni, Sub, «+») e in altre solo la colonna «File» larga con barra di scorrimento orizzontale. Con master l'ho visto nelle 3 partenze fatte (sempre «solo File»); con G4 in 2 partenze su 4 (le prime due: colonne complete; le ultime due: «solo File»). Nelle due partenze affiancate subito una dopo l'altra master e G4 sono **identici al pixel** (ritaglio del pannello). Non posso quindi attribuirlo a G4 ne' a master; sembra dipendere dai tempi (ridimensionamento della colonna File al caricamento con pannello chiuso/aperto). Vale la pena verificarlo su master a parte.
2. **Contatore del filtro «Tutti (N)» nella coda** con N diverso dal numero di righe visibili (visto su G4: «Tutti (2)» con 5-6 elementi in lista dopo «Importa filtrati»; probabilmente lo stesso fenomeno del «File N/1» gia' segnalato). Non confrontato a mano su master (a causa del punto 1); i 94 test di caratterizzazione passano su entrambi.
3. **Confronto GUI completo su master non fatto:** a causa del punto 1 i clic a coordinate fisse sui badge non erano possibili sul master; il confronto e' stato sostituito da: prova inversa dei test di caratterizzazione su master (94/94), lettura del server vero identica, hash degli SRT identici.
4. Estratto con PGS + VobSub (cinderella): clic sul badge PGS in modalita' `review` -> messaggio «Codec dvd_subtitle non supportato dal ramo review (solo PGS; VOBSUB/DVD è fase 2)» e job in errore. Il messaggio proviene dal motore OCR (non modificato da G4); non confrontato a mano su master.
5. Superpower provato con 2 file (non 3): il terzo e' lo estratto con PGS inglese, la cui traduzione richiederebbe NLLB (nella home isolata non c'e' il modello e non e' consentito scaricare). Il finto server restituisce quindi 2 elementi.
6. Il valore predefinito di `library_scanner_api_key` in `utils/config.py` e' una chiave dall'aspetto reale presente nel repository pubblico (gia' segnalato): da ruotare. Non riportato qui.

Config/history veri (`~\.transcriberpro`) mai toccati: SHA256 invariati (`A758DA8F…`, `B7C1D43C…`). 0 processi di prova a fine lavoro; il server vero e' stato interrogato solo con GET.
