# G2: esito della prova su Windows, prima parte (27/10/2026)

Branch provato: `refactor/g2-prova` (HEAD `14e9666`), confrontato con un worktree di master `9892d96` (1.34.38 + PR #40). Nessun codice modificato, nessuna unione, produzione non toccata. La seconda parte (punti 8-10, con modelli e GPU) NON e' stata fatta: attende l'OK del proprietario.

## Ambiente
- Windows 11, RTX 3060. Interprete: venv di produzione solo come eseguibile (cartella di lavoro e `PYTHONPATH` sul clone).
- Dove ho lavorato: clone nuovo `Desktop\Transcriber_Pro_G2` e worktree `Desktop\Transcriber_Pro_G2_master`.
- Dati isolati: `USERPROFILE`/`HOME` (e `APPDATA`/`LOCALAPPDATA`) su `C:\tp_prova_home_g2` (nuova, vuota). Nessun dato vero usato. Nessun download di modelli comparso. Upload OpenSubtitles non toccato.
- La GUI e' stata pilotata con mouse/tastiera simulati e screenshot, con il PC libero (dopo una prima prova interrotta perche' il proprietario stava usando il PC).

## 1. pytest
| Albero | Passati | Falliti | Saltati |
|---|---|---|---|
| master `9892d96` | 737 | 8 | 28 |
| `refactor/g2-prova` | 799 + 14 | 10 | 26 |

- Nota: il branch NON contiene la PR #40 (e' basato su `1a74d6e`, non e' discendente di `9892d96`), quindi la checklist non e' esatta su "i due test POSIX si saltano da soli": `test_install_retry.py` non si raccoglie (`termios`) e `test_process_alive_posix` uccide pytest. Come in G1 li ho esclusi (`--ignore` dei due file) e ho lanciato i 14 test di `test_platform_compat.py` uno per uno: tutti passati.
- G2: la suite e' stata divisa in due blocchi (file fino a `test_glossary_*`/`test_history_service` / da `test_history_widget_characterization.py` in poi): 7 falliti + 3 falliti, 452 + 347 passati, 16 + 10 saltati.
- Fallimenti: gli 8 ambientali noti di master, piu' 2 nuovi, entrambi nei test e non nel codice:
  - `test_glossary_worker_characterization::test_run_ok`: il JSON atteso ha i percorsi con `\` non raddoppiati (diff `C:\\Users...` vs `C:\Users...`).
  - `test_sync_worker_characterization::test_successo`: il test si aspetta un insieme di variabili d'ambiente del sottoprocesso senza `PYTHONIOENCODING`, che su Windows viene aggiunto.
- **Differenza da segnalare:** lanciata in un solo run, la suite intera di G2 termina con crash nativo del processo (`0xC0000409`) al primo test di `test_history_widget_characterization.py` (3 prove su 3, anche con `-X faulthandler`, senza traceback). Il file da solo passa (8/8, due volte); nessun file precedente lo manda in crash in coppia con lui; i due blocchi eseguiti separatamente finiscono regolarmente. Sembra un problema cumulativo (Qt/thread) nella raccolta dei test di G2; su master e su G1 il run intero non si ferma. Non indagato oltre.

## 2. Manuale, GUI vera (punti 1-7)
Dati finti in `C:\tp_prova_home_g2\sync` (4 video + 1 in sottocartella, 6 SRT con un `.alt.it.srt`, un orfano) e `Plex\Show\Season 2`.

| # | Punto | Esito | Confronto con master |
|---|---|---|---|
| 1 | Sync, scheda Coda: abbinamento, stati, riepilogo, scelta SRT, spunte, duplicati, sottocartelle | **OK** | Stessa tabella e stesso riepilogo («4 coppie pronte, 0 da controllare, 1 video senza SRT, 2 SRT non abbinati»). Duplicato forzato: «OUTPUT DUPLICATO» su entrambe le righe, «1 coppie pronte». Togliere la spunta: riepilogo aggiornato. Abbinamento identico a master (anche la scelta di `E02.alt.it.srt`). |
| 2 | Avvia coda a modelli assenti; Annulla a meta' | **OK** | Le coppie falliscono in ~2 s ciascuna («anchor insufficienti», file finti), la coda prosegue, riepilogo «0 riuscite, 4 fallite, 0 non eseguite». Annulla: «0 riuscite, 1 fallita, 3 non eseguite», righe «non eseguita», 50 %. **Identico a master** (inclusa la riga 2 che resta «FALLITA» dalla corsa precedente). Nessun python/ffmpeg orfano. |
| 3 | Chiusura finestra mentre la coda gira | **OK** | Si chiude senza blocchi; compare poi il messaggio «Coda conclusa: 0 riuscite, 1 fallite, 3 non eseguite». Uguale a master. Nessun processo orfano. La coda principale e il Glossario bloccati durante il sync: non verificato visivamente. |
| 4 | Scheda Singolo, file inesistenti | **OK parziale** | I campi sono di sola lettura (si riempiono solo con «Sfoglia»), quindi non si possono inserire percorsi inesistenti; con campi vuoti: «Seleziona un file video.». Non confrontato su master. |
| 5 | Glossario: nome proposto con `...\Show\Season 2` | **OK** | Nome proposto «Show» (non «Season 2»), stato «TMDB id non ancora risolto. (Show -> Season 2)». Con cartella gia' pulita e cartella film: non provati. Su master non ripetuto (la schermata iniziale del Glossario e' identica). |
| 6 | Risolvi TMDB | **OK senza chiave** | «Nessun risultato trovato su TMDB» (chiave non presente nella home isolata). Con la chiave vera non provato. |
| 7 | Senza `venv_glossary`: avviso, Avvia analisi, Annulla, chiusura a vuoto | **OK** | Avviso in alto «venv_glossary non trovato...» (non in rosso nello screenshot); «Avvia analisi» chiede conferma («Nessun TMDB id risolto... Procedere comunque (solo analisi)?») e poi «Fallito: venv_glossary non trovato...», senza crash. «Annulla» e' disattivo a vuoto; la finestra si chiude. |

## Osservazioni (da master, non solo G2)
- I pulsanti dei messaggi di conferma sono in inglese («Yes»/«No») in «Avvia coda» e nel Glossario: uguale su master.
- Gli SRT ricevono il nome `.synced.it.srt`; nessun file di output scritto (le coppie fallivano prima).

## Differenze rispetto a master
Nessuna differenza di comportamento o di aspetto trovata nei punti 1-7. Unica differenza: il crash del processo di pytest nel run intero (sopra) e i 2 test ambientali nuovi.

## Non provato
Punti 8-10 (sync reale, coda reale con una annullata, glossario reale su uno show piccolo, controllo processi Qwen orfani), Glossario con chiave TMDB vera, cartella show gia' pulita/film, blocco della coda principale durante il sync, popup/caso «da controllare» nell'abbinamento.

## Aggiornamento dopo la correzione (`refactor/g2-prova` HEAD `94a6aa7`, ora basato su master con la PR #40)
- Clone G2 portato su `origin/refactor/g2-prova` (aggiornamento forzato sul remoto).
- **Run INTERO di pytest in un solo processo, 3 volte** (venv di produzione, home isolata `C:\tp_prova_home_g2`, nessuna esclusione): **815 passati, 8 falliti, 28 saltati**, identico nelle 3 prove (61 s ciascuna). **Il crash `0xC0000409` non si e' ripresentato.** I 8 falliti sono gli stessi ambientali noti di master (`test_amd_family` x2, `test_amd_rocm_f6`, `test_core_jobs_unit` x3, `test_queue_gui/runner_characterization::test_contratto_del_sottoprocesso`); i 2 fallimenti nuovi della prima prova (`test_run_ok`, `test_successo`) ora passano.
- Bisezione: non necessaria (nessun crash).
- **Prova manuale punti 1 e 7 rifatta** (GUI vera, clone su `94a6aa7`, PC libero; la finestra e' stata portata in primo piano dalla barra delle applicazioni): **identica a master e alla prima prova.**
  - Punto 1: abbinamento con sottocartelle «4 coppie pronte, 0 da controllare, 1 video senza SRT, 2 SRT non abbinati»; spunta tolta alla riga 3 -> «3 coppie pronte»; riga 2 forzata sullo stesso SRT della riga 1 -> «OUTPUT DUPLICATO» su entrambe, «1 coppie pronte». Stessi testi e stessa tabella di master.
  - Punto 7: cartella `...\Show\Season 2` -> nome proposto «Show», stato «TMDB id non ancora risolto. (Show -> Season 2)»; senza chiave «Nessun risultato trovato su TMDB»; «Avvia analisi» -> conferma -> «Fallito: venv_glossary non trovato...» senza crash; avviso `venv_glossary` in alto. Nessun processo python/ffmpeg orfano; app chiusa.
  - Nota per chi automatizza: l'incolla da clipboard nel dialogo cartelle di Windows non e' affidabile (autocompletamento a «Desktop»); ho digitato i tasti.

## Seconda parte (con dati veri, produzione aggiornata con i 10 file di G2; OK esplicito del proprietario)
- **Backup** (`Desktop\backup_prod_pre_G2`): i 5 file modificati di produzione (`gui/glossary_dialog.py`, `glossary_worker.py`, `sync_batch_worker.py`, `sync_dialog.py`, `sync_worker.py`), `config.json` e `history.json` con SHA256, e l'intera cartella `~\.transcriberpro\glossary` (14 file).
- **Verifica prima della copia:** i 5 file esistenti erano identici a `origin/master` 1.34.38; i 5 nuovi non esistevano. `git diff origin/master..94a6aa7` (esclusi test/docs) coincideva con l'elenco dei 10 file.
- **Copiati 10 file** da `refactor/g2-prova` `94a6aa7` (nuovi: `core/jobs/glossary_run.py`, `sync_batch.py`, `sync_single.py`, `core/services/glossary_service.py`, `sync_batch_plan.py`; modificati: i 5 `gui/*` sopra); hash identici alla sorgente (0 differenze); `APP_VERSION` resta 1.34.38; import di tutti i moduli senza errori. Nessun altro file toccato.
- **Metodo:** per non interferire con il PC del proprietario, i punti 8-10 sono stati eseguiti senza pilotare il desktop: i worker veri di produzione (`SyncWorker`, `SyncBatchWorker`, `GlossaryDialog`) pilotati da script Python con Qt offscreen; per il confronto con master 1.34.38 ho caricato i vecchi worker dal backup (con la stessa cartella di progetto), sugli stessi input. Copie dei file di prova in `Desktop\g2_prova_dati` (non cancellate).
- **Punto 8, sync singolo reale (OK):** `Ponies S01E01` (mkv 561 MB + `.it.srt`), ancoraggio sulla traccia ENG incorporata (1065 segmenti, 1053 sottotitoli). Progresso 5 eventi monotoni fino al 100 %, log di 19 righe. **Il file `.synced.it.srt` di G2 e quello di master hanno lo stesso SHA256** (stesso numero di righe e stessa durata: 1053 blocchi). Il log e' identico a meno del percorso. Durata ~3 s (anchor incorporato, senza modelli pesanti).
- **Punto 9, coda reale con 2 coppie, una annullata (OK):** annullo a 4,5 s, durante la coppia 2: G2 e master danno entrambi `riuscite 1, fallite 0, non eseguite 1`, coppia 2 «annullato», output della coppia 1 con lo stesso SHA256. Nessun processo python/ffmpeg orfano. Nota: le corse annullate lasciano cartelle `tp_sync_*` in `%TEMP%` (5 presenti, anche da corse precedenti e da master): comportamento invariato, non rimosse.
- **Punto 10, Glossario reale (primo run OK, secondo run annullato NON provato):**
  - Il primo tentativo era stato terminato dal sistema («memoria insufficiente») prima del gate. Chiuso Chrome (RAM libera 21,1 GB) e rilanciato. Misura: il run usa circa 8-9 GB di RAM (libera 20,1 -> 12,1 GB durante la fase Qwen, 6 processi python), non 20 GB; i 20 GB erano la RAM libera di partenza.
  - Show: `V:\PONIES\Season 1` (8 episodi con SRT), dialogo vero in offscreen: nome proposto «PONIES», TMDB #262793 risolto; gate OK; avanzamento `collect` -> `align` (0/25 -> 25/25 in 94 s) -> `qwen` (1/2845 -> 2845/2845), totale 534 s; «25 candidati trovati»; 25 schede, Salva abilitato. Salvati 5 termini (approvazione automatica dello script: What->cosa, This->questo, So->Quindi, How->come, Missus Grant->Signora Grant) in `~\.transcriberpro\glossary\tmdb_262793.json` (+ `tmdb_262793.used_episodes.json`). **Attenzione:** sono file NUOVI (lo show non aveva un glossario) con termini poco utili: il backup `Desktop\backup_prod_pre_G2\dati\glossary` non li contiene; vanno rimossi se non si vogliono nelle future traduzioni di PONIES (non cancellati, serve OK).
  - Processi: a fine run 0 python/ffmpeg, GPU tornata a 701 MiB, RAM libera 21,2 GB. File di lavoro in `glossary_engine\glossary_work\ponies_262793`: il file `glossary_qwen_gpu_pid.txt` rimasto dal run terminato e' stato sostituito da `glossary_qwen_gpu_result.json` (nessun temporaneo residuo).
  - **Secondo run annullato a meta': non riuscito.** Rilanciato su PONIES (gate: 0 blocchi, episodi gia' usati) e su `Resident Alien S1` (solo mkv, nessun SRT) e `Last Exile` (0 blocchi): il gate si ferma subito, quindi non c'e' stato nessun annullamento a meta'. Nessun processo orfano e glossario invariato in tutti questi run, ma la parte «Annulla durante Qwen» resta da provare (richiede uno show con episodi ancora non usati, o la rimozione di `tmdb_262793.used_episodes.json`). Effetto collaterale: sono comparse le cartelle di lavoro `glossary_work\resident_alien_96580` e aggiornati gli `args.json` di `last_exile_31679` e `ponies_262793`.
- App di produzione: **chiusa** (nessun processo).


## Annulla durante Qwen e pulizia (27/10/2026, su OK esplicito del proprietario)
- **Master ora 1.34.39 (`97c6173`):** repository di lavoro allineato con `git pull`. I 10 file di G2 in produzione hanno hash identici a quelli di master (0 differenze). Nota: `main.py` di produzione resta a `APP_VERSION = "1.34.38"` (non copiato, come da istruzioni).
- **Prima della prova:** `tmdb_262793.json` e `tmdb_262793.used_episodes.json` verificati (data 27/10/26 17:55, i 5 termini What/This/So/How/Missus Grant) e **spostati** (non cancellati) in `Desktop\backup_prod_pre_G2\glossary_ponies_prova`.
- **Annulla durante la fase Qwen (worker di G2, dati veri, show PONIES) — OK:**
  - Run partito, gate OK, `align` 25/25 a ~110 s, fase `qwen` avviata (VRAM da 823 MiB a 9835 MiB, RAM libera da 19,8 a 11,3 GB). Annulla premuto a 150 s con la barra a `[qwen] Bea (29/174) (231/2845)`.
  - La chiamata `cancel` e' tornata in **0,007 s** (la GUI non si blocca); il worker e' terminato **0,11 s** dopo l'Annulla; stato «Fallito: Annullato dall'utente».
  - Dopo: **0 processi python/ffmpeg/llama** (rilevati a +5 s e +10 s), VRAM tornata a 823 MiB, RAM libera 20,3 GB (base).
  - `glossary_work\ponies_262793`: rimossi dal run `glossary_builder_args.json`, `glossary_qwen_gpu_request.json` e `glossary_qwen_gpu_result.json`. Restano solo gli 8 `en_01x0N.srt` (episodi copiati dalla fase `collect`, cache dello show, non temporanei).
  - Nessun `tmdb_262793.*` ricreato in `~\.transcriberpro\glossary`.
  - Nota: un primo tentativo lo stesso giorno non era partito per un errore di sintassi nel mio script di prova (nessun effetto sui dati).
- **Residui rimossi (tutti creati oggi dalle mie prove, nessuna giunzione):**
  - 5 cartelle `%TEMP%\tp_sync_*` (create 16:14-17:22, vuote);
  - `glossary_engine\glossary_work\resident_alien_96580` (creata 17:56, 1 file);
  - `glossary_engine\glossary_work\ponies_262793` (creata 17:39, 8 file; non esisteva prima delle prove).
- **Lasciati:** `glossary_work\last_exile_31679` (creata il 10/10/26, preesistente; il suo `glossary_builder_args.json` e' stato riscritto dal mio run di gate: contiene la configurazione standard di Last Exile, 360 byte, nessun dato utente) e `glossary_work\ponies` (preesistente, 29/08/26, non toccata).
- **Stato finale:** `~\.transcriberpro\glossary` identico al backup pre-prova (14 file, nessun `tmdb_262793.*`); `config.json` e `history.json` con gli stessi SHA256 del backup; 0 processi di prova; app di produzione chiusa.
