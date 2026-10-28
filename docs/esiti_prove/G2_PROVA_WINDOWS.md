# G2: prova su Windows (sessione locale)

Branch da provare: **`refactor/g2-prova`** = master (1.34.38 + test POSIX) + le due PR di G2 (#41 Sync SRT, e Glossario), già unite fra loro; la suite Linux passa (845 test). Non unire nulla a master: l'esito va riferito al proprietario.

Il Glossario richiede `venv_glossary` e una GPU (il canale Qwen è opzionale); il Sync completo richiede i modelli (Whisper/NLLB/LLM) e la GPU. Le prove sotto sono divise per **cosa serve**.

## 0. Preparazione
1. Clone NUOVO di `refactor/g2-prova` in una cartella di prova (non la produzione). Interprete: quello del venv di produzione, solo come eseguibile (cartella di lavoro e `PYTHONPATH` sul clone). Per il Glossario il clone non ha `venv_glossary`: collegalo copiando/puntando a quello di produzione SOLO se serve (vedi punto 4), senza modificare la produzione.
2. **Isola i dati**: `$env:USERPROFILE = "C:\tp_prova_home"; $env:HOME = $env:USERPROFILE` (cartella vuota) in ogni finestra di prova. Home vuota = nessuna cache modelli: per i test senza modelli non serve; se compare un download, interrompi e riferiscilo.
3. Niente modelli/GPU nei punti 1-2.

## 1. Automatica
`python -m pytest linux_tests -q` con le stesse esclusioni di G1 (non servono più: i due test POSIX ora sono saltati da soli). Riporta passati/falliti/saltati e confrontali con master (worktree a parte). Test di G2: `test_sync_*_characterization.py`, `test_sync_batch_plan.py`, `test_glossary_*_characterization.py`.

## 2. Manuale, senza modelli (GUI vera)
Sync (Strumenti → Sincronizza SRT):
1. Scheda **Coda**: scegli due cartelle (video e SRT) con 3-4 coppie finte (nomi tipo `Serie.S01E01.mkv` / `Serie.S01E01.it.srt`, un video senza SRT, un SRT orfano). «Abbina»: stessa tabella di master (video, output `.synced.it.srt`, stato Pronta / Da controllare / Senza SRT / Duplicato), riepilogo corretto. Cambia l'SRT di una riga, togli/metti la spunta, forza un duplicato: stati e riepilogo come su master. Opzione «sottocartelle».
2. «Avvia» sulla coda con i modelli assenti: le coppie falliscono ma la coda prosegue, ogni riga passa da «In corso» a «Fallita», riepilogo finale (riuscite/fallite/non eseguite). **Annulla** a metà: nessun processo python/ffmpeg orfano, righe rimaste «Saltata».
3. Chiudi la finestra mentre la coda gira: si chiude senza blocchi e senza processi orfani; la coda principale e il Glossario restano bloccati finché il sync è attivo (e si sbloccano dopo).
4. Scheda **Singolo**: video + SRT inesistenti → messaggi di errore come su master.
Glossario (Strumenti → Glossario per show):
5. Scegli una cartella show tipo `Plex\Show\Season 2`: il nome proposto è «Show», non «Season 2». Con cartella già pulita e con una cartella film.
6. «Risolvi TMDB»: senza chiave TMDB messaggio «non trovato» come su master; con la tua chiave, il titolo viene risolto.
7. Senza `venv_glossary` (clone nuovo): avviso rosso in alto; «Avvia» → stato «Fallito: venv_glossary non trovato…» senza crash. «Annulla» e chiusura della finestra a vuoto.

## 3. Manuale, con modelli e GPU (la produzione aggiornata, dopo l'ok del proprietario)
Solo dopo aver copiato in produzione i file di G2 (elenco nel rapporto/PR), con backup come per G1:
8. Sync singolo reale su un episodio con SRT esterno: progresso, log, file `.synced.it.srt` identico a quello prodotto da master (stessa durata e stesso numero di righe).
9. Sync coda reale con 2 coppie, una annullata a metà.
10. Glossario reale su uno show piccolo (cartella con episodi e SRT): gate, avanzamento, schede dei termini, approvazione e «Salva» → glossario scritto; annulla a metà: nessun processo Qwen orfano (controlla in Task Manager), file temporanei ripuliti.

## 4. Riferire
Per ogni punto: OK / differenza (testo o schermata). Allega pytest. Se trovi una differenza NON correggere il codice: descrivila.
