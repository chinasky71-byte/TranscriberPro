# G1: aggiornamento della produzione a 1.34.38 (27/10/2026)

Master `1a74d6e` (PR #39). Produzione aggiornata dalla cartella di lavoro; dati utente non toccati.

## Test (venv di produzione, home isolata `C:\tp_prova_home`)
- 737 passati, 8 falliti, 26 saltati (723 nel run principale + 14 di `test_platform_compat.py` lanciati uno a uno).
- Esclusi: `test_install_retry.py` (importa `termios`) e `test_platform_compat.py::test_process_alive_posix` (su Windows uccide pytest; `--deselect` non e' bastato, quindi file escluso dal run principale).
- Gli 8 falliti sono gli ambientali noti (percorsi/ambiente del sottoprocesso). `test_pulsanti_azione` ora passa.

## Copia in produzione
- Backup prima della copia: `Desktop\backup_prod_pre_1.34.38` (11 file sovrascritti, `config.json`, `history.json`, SHA256).
- 20 file copiati (9 nuovi in `core/services/` + 11 modificati: `core/jobs/history_store.py`, 5 widget `gui/*_settings_widget.py` e `history_widget.py`, 3 in `gui/services/`, `gui/workers.py`, `main.py`). Prima della copia i 11 file esistenti coincidevano con la vecchia master. Dopo: hash identici alla cartella di lavoro (0 differenze).
- `main.py`: `APP_VERSION = "1.34.38"`.

## Avvio con dati veri
- Nessun errore di import; stderr vuoto; log di sessione senza errori ne' download.
- Coda e Cronologia (1196 voci) mostrate correttamente; GPU RTX 3060 rilevata; Library Scanner attivo.
- Chiusa e riaperta senza elaborazioni: `config.json` e `history.json` con SHA256 identici al backup.
- **Schede Impostazioni, Glossario e Sincronizza SRT:** il proprietario conferma che si aprono (prova a mano). Le singole schede (Generali, Batch adattivo, OCR, OpenSubtitles, Opzioni job) non sono state elencate una per una.

## Differenze
Nessuna rilevata. Backup non rimosso; nessuna cartella cancellata.

## Prova a mano del proprietario (produzione 1.34.38)
Coda lunga, riordino dei file, log a schermo e card con fasi ed ETA: funzionano. Log della sessione: 3 file su 3 completati, 0 falliti (OCR PGS, traduzione con sottotitoli embedded, trascrizione Qwen3 + diarizzazione). Nota: nel log i contatori mostrano `File 2/1` e `File 3/1` (totale fermo a 1). Il proprietario conferma di aver riordinato la coda a elaborazione iniziata; il riordino funziona, ma il totale del contatore non si aggiorna con file aggiunti o riordinati a coda avviata (cosmetico, non legato a G1: da verificare su master).




## Locandine TMDB
Il proprietario conferma che le schede con locandina da TMDB funzionano in produzione (viste durante la prova a mano). Con la chiave vera quindi il punto 4 della prova G1 e' coperto.


## Pulizia (27/10/2026, su OK esplicito del proprietario)
- Cancellate: `Desktop\Transcriber_Pro_P1_copia_prova` (34,4 GB), `Desktop\Transcriber_Pro_G1` (clone, 0,09 GB; nessun lavoro non spinto, entrambi i branch locali in sync con origin) e `Desktop\Transcriber_Pro_G1_master` (worktree registrato nel clone G1, tolto con `git worktree remove` + `prune`). Nessuna giunzione o link simbolico presente. Spazio libero su C: da 291,0 a 325,8 GB (+34,8 GB).
- **Non cancellata:** `C:\tp_prova_home` (0,01 GB, home isolata di prova): il blocco di sicurezza dello strumento protegge i percorsi in radice di `C:\`. Va eliminata a mano dal proprietario.
- Branch: dopo `git fetch --prune` sono spariti dal remoto `g1/prova-risultati`, `refactor/g1-*`, `release/1.34.38`. Nel repository di lavoro non esisteva alcun branch locale di quelli elencati (solo `master` e `g1/produzione-esito`). `development` non toccato.
- Verifiche: produzione, backup e `~\.transcriberpro` presenti; repository di lavoro su `master` `1a74d6e`, pulito (solo i 3 file privati non tracciati).
