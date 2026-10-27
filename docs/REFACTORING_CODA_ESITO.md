# Refactoring della coda di elaborazione: esito

Data: 26/10/2026. Branch `refactor/coda-core` (da `master` 6dfde21, **non unito**). Seguito di `docs/STUDIO_REFACTORING_CODA.md` (PR #33). Lavoro della sessione cloud di Claude Code in autonomia, con i criteri del proprietario: stessa GUI e stesso aspetto, log come quelli della GUI (con etichetta di livello), cronologia e anteprima dei passi anche fuori dalla GUI, nessuna regressione.

## 1. Cosa è cambiato (in una frase)

La coda non è più della GUI: vive in `core/jobs/` (senza Qt e senza `gui`), e la GUI (`ProcessingWorker`, `QueueService`) e la coda headless (`core/queue_runner.py`) ne sono due adattatori sottili sullo **stesso motore** e sullo **stesso sottoprocesso**.

| Pezzo | Dove | Note |
|---|---|---|
| `JobQueue` | `core/jobs/job_queue.py` | lista + eccezioni per file + lock; `take_next()` atomico; stesso invariante v3.5 (lista e dizionario mai riassegnati) |
| `FileRunner` | `core/jobs/file_runner.py` | UNICA copia di: cartella IPC, ambiente del figlio, flag di creazione, lettura di stdout, esito, kill dell'albero. Righe lette da un thread e elaborate nel thread chiamante (stesso thread di emissione dei segnali di prima; Ctrl+C interrompibile anche su Windows) |
| `QueueEngine` | `core/jobs/engine.py` | ciclo, contatori, avanzamento, anteprima dei passi, cronologia, pulizia cache a fine coda; ganci `QueueListener` |
| `FileProgress`, `StepTracker` | `core/jobs/file_progress.py`, `step_plan.py` | spostati da `gui/`; i vecchi nomi in `gui/` sono **alias dello stesso modulo** (import e monkeypatch vecchi funzionano) |
| `history_store` | `core/jobs/history_store.py` | stesso `history.json` e stesso formato della scheda Cronologia |
| `ProcessingWorker` | `gui/workers.py` | resta un `QThread`, **stessi 11 segnali**, stesso thread, stesso ordine; stessi attributi usati da `QueueService`; `QMutexLock` adatta lo STESSO `QMutex` delle viste |
| `QueueService` | `gui/services/queue_service.py` | stessa interfaccia e stessi segnali; usa `JobQueue`; `processing_queue`, `job_overrides`, `queue_mutex` restano gli stessi oggetti per chi li tiene (viste, Library Scanner, `worker_factory` dei test) |
| `queue_runner` | `core/queue_runner.py` | usa il motore; `run_one` e la sua `kill_tree` non esistono più (`kill_tree` resta importabile con lo stesso nome) |

Le tre copie di "uccidi l'albero dei processi" sono diventate una (`core/jobs/file_runner.kill_tree`, stessa semantica della GUI); `utils/platform_compat.kill_tree` (usata da `glossary_worker`) non è toccata.

## 2. Come si è evitata la regressione

1. **F0, prima di toccare il codice:** test di caratterizzazione con un finto `core.pipeline_cli` (`linux_tests/queue_stub_pipeline.py`): 19 sul `ProcessingWorker`, 14 sul `QueueService`, 1 sulla vera `MainWindow` (offscreen, dal clic su Avvia alla fine), 20 sul runner headless.
2. **Stessi test sul vecchio e sul nuovo codice:** i 33 test GUI+servizio e quello della `MainWindow` sono stati eseguiti su `master` (vecchio) e sul branch: **passano identici**. Sono la prova che la GUI si comporta come prima: sequenza e ordine dei segnali, thread, contatori, rimozione/riordino/override a coda in corso, Stop, `.converting`, pulizia cache, contratto del sottoprocesso (argv, `env`, flag, `cwd`, `args.json`).
3. **Prova di mutazione:** 12 regressioni mirate sul worker vecchio e 19 su `file_runner`/motore/coda nuovi (ambiente senza `TQDM_DISABLE`, `PYTHONUTF8` aggiunto, rumore non filtrato, `[DIAG-RAM]` che muove la barra, cancel, override non passati, prelievo non atomico, riordino non sul posto, cronologia mancante...): **tutte rilevate** (una versione iniziale del finto non rilevava `[DIAG-RAM]`: corretta).
4. **Suite:** `python -m pytest linux_tests -q` in un ambiente minimo → 637 passati, 14 saltati. Nel container con torch e Qt (Ubuntu 24.04, Python 3.12): `master` 569 passati, 7 falliti, 4 errori; branch **647 passati e gli stessi 7+4** (ambientali: libreria CUDA mancante senza GPU NVIDIA); nessun fallimento in più o in meno.
5. **`core` senza GUI:** test che una coda headless vera (motore, runner, cronologia, stato) gira con `gui` e `PyQt6` **bloccati** in `sys.modules`, e che `core/`, `utils/`, `glossary_engine/` non importano `gui` (nemmeno dentro le funzioni).
6. **Concorrenza:** 8 thread che prelevano mentre un altro riordina: nessun file perso o doppio.

## 3. Comportamenti nuovi (decisi dal proprietario) e differenze volute

Solo la coda headless cambia; la GUI no.
- **Log come la GUI**, con etichetta `[INFO]`/`[WARNING]`/`[ERROR]` (regola sul primo carattere: ❌🛑⛔🚫 → ERROR, ⚠⏹ → WARNING). Stessi testi `tr()`, rumore delle librerie e `[DIAG-RAM]` come nella GUI. `<data>_queue.log` ha l'intero flusso, `<data>_NNN.log` solo il file N. Prima: flusso grezzo del figlio.
- **Cronologia:** i file completati finiscono in `~/.transcriberpro/history.json` (la stessa della GUI).
- **Anteprima dei passi:** nel file di stato, `current.steps` = `{done, total, active, steps:[{key,status,pct,eta}]}`; la fase mostrata è il passo attivo.
- **Pulizia cache a fine coda** come la GUI; `--keep-caches` per evitarla.
- **Override per file** passati a `pipeline_cli` (vuoti da riga di comando, ma il motore li supporta).
- Un file che solleva un'eccezione **non ferma più la coda** nemmeno nella GUI (prima il thread poteva morire senza `finished`): il file fallisce, motivo nel log.
- Piccole differenze del headless: la barra non legge più `[DIAG-RAM]`; `<video>.converting` si toglie solo se fermato o interrotto con Ctrl+C (prima anche su successo); `output` di un fallito è `None`.

## 4. Cosa NON è verificato

- **Windows + NVIDIA reale.** Il nuovo modo di leggere la pipe (thread lettore + coda, elaborazione nel thread chiamante) non è stato provato su Windows; `CREATE_NEW_PROCESS_GROUP`/`CREATE_NO_WINDOW` sono passati uguali e verificati solo come valori. Nessuna finestra console dovrebbe comparire: da controllare.
- **La vera `pipeline_cli`.** Nei test gira un finto con lo stesso protocollo (stdout, eventi `TP_EVENTS`, `result.json`); nessun modello, nessuna GPU.
- La GUI vera con display (qui solo offscreen); le prove dei tempi di reazione del pulsante Stop.
- La suite locale del proprietario (fuori dal repository): se contiene test su `ProcessingWorker`/`QueueService`, vanno rilanciati.

## 5. Prova manuale consigliata (Windows + NVIDIA, due clip brevi, una fatta fallire)

1. Coda di 2 file dalla GUI: stesso esito, stessi messaggi, barra e cronologia.
2. **Stop** a metà del primo: si ferma, nessun processo orfano (`ffmpeg`, `gender_corrector_cli`), nessun `*.converting`.
3. Mentre lavora: rimuovere un file in attesa, aggiungerne uno dal Library Scanner, riordinare, impostare un'eccezione.
4. `python -m core.queue_runner <cartella>`: 2 file, `queue_status.json` (con `current.steps`), log `*_queue.log`, `history.json`, `Ctrl+C`.
5. Nessuna finestra console visibile durante l'elaborazione.

## 6. Cosa resta come compromesso consapevole

- `MainWindow` conserva gli shim (`processing_queue`, `queue_mutex`, `worker`, contatori) e `LibraryScannerWidget` accede ancora a `processing_queue` con `QMutexLocker` sul `QMutex`: funzionano perché lista e mutex sono gli stessi oggetti della `JobQueue`. Migrarli a metodi del servizio è possibile ma tocca la vista senza guadagno funzionale: non fatto.
- `gui/services/job_model.py` (`JobRecord`, righe della lista) resta in `gui/`: è modello della vista, non della coda.
- `gui/` non è ancora cancellabile del tutto (resta la GUI stessa), ma nulla in `core/`, `utils/`, `glossary_engine/` la importa.

## 7. File da copiare nella cartella di produzione

Nuovi: `core/jobs/` (7 file). Modificati: `core/queue_runner.py`, `gui/workers.py`, `gui/services/queue_service.py`, `gui/file_progress.py`, `gui/services/step_plan.py` (ora alias), `utils/events.py` (solo un commento). Test: `linux_tests/_queue_testkit.py`, `queue_stub_pipeline.py`, `test_core_jobs_pure.py`, `test_core_jobs_unit.py`, `test_queue_gui_characterization.py`, `test_queue_mainwindow_e2e.py`, `test_queue_runner_characterization.py`, `test_queue_service_characterization.py`. Nessuna dipendenza nuova, nessuna modifica a `requirements*.txt`, a `install.*` o al percorso di installazione.

**Rollback:** il branch non è unito; basta non unirlo. Se unito e poi ritirato, `git revert` del merge ripristina tutto (nessun file di dati cambia formato: `history.json` e `queue_status.json` hanno solo campi aggiunti).
