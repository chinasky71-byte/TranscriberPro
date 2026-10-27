# Studio: la coda di elaborazione fuori dalla GUI

Data: 26/10/2026. Autore: sessione cloud di Claude Code. Solo lettura del codice di `master` (6dfde21) e prove di importazione in un ambiente Linux senza Qt; **nessuna modifica al codice**.

Domanda: «la GUI possiede la coda (`ProcessingWorker`/`QueueService`) e `queue_runner` la duplica: due implementazioni, Qt nel percorso headless, impossibile rimuovere la GUI. Riusciamo a fare il refactoring in modo che la GUI non possieda la coda e che tutto il resto non subisca regressioni?»

## 1. Risposta breve

**Sì, è fattibile, ma solo a piccoli passi e con una rete di sicurezza costruita prima del primo spostamento.** Il lavoro è soprattutto uno *spostamento* di codice già provato (non nuova logica) verso un modulo senza Qt in `core/`, con la GUI e il runner headless che diventano due «adattatori» sottili. Stima: 4-5 giornate in 5 passi indipendenti; i primi tre (circa 2 giornate) hanno rischio basso ed eliminano già due delle tre duplicazioni. Il passo rischioso è uno solo (F3, il cambio del possesso della lista e del lock) e si può rinviare.

Due correzioni alla formulazione del problema, verificate sul codice (sezione 2): `QueueService` esiste già ed è senza widget, quindi la GUI «possiede» la coda solo nel senso che il servizio sta in `gui/` ed è fatto di tipi Qt; e il percorso headless **non importa Qt a runtime**, ma dipende dal *pacchetto* `gui` (`gui.file_progress`), per cui togliere `gui/` romperebbe comunque `queue_runner`.

## 2. Stato attuale (fatti verificati)

| Pezzo | Dove | Cosa fa | Dipendenze |
|---|---|---|---|
| `QueueService` | `gui/services/queue_service.py` (431 righe) | possiede `processing_queue` (lista), `queue_mutex` (`QMutex`), eccezioni per file, contatori, avvio/arresto del worker, scansione cartelle, spegnimento | PyQt6 (`QObject`, `QMutex`, `QThread`, `QTimer`, segnali) |
| `ProcessingWorker` | `gui/workers.py:187-626` | `QThread` che prende il primo file dalla lista condivisa (prelievo + rimozione + eccezioni atomici sotto lo stesso lock), lancia `core.pipeline_cli` in un sottoprocesso, legge stdout, emette 11 segnali, a fine coda ripulisce le cache | PyQt6 |
| `queue_runner` | `core/queue_runner.py` (458 righe) | lista statica di file, `QueueStatus` (JSON atomico), `run_one` (stesso sottoprocesso), lock su file, notifiche | solo libreria standard + `gui.file_progress` + `utils.translations` |
| Vista | `gui/main_window.py` | non possiede più la lista: espone `processing_queue`, `queue_mutex`, `worker`, contatori come **proprietà che rimandano a `QueueService`** (righe 1649-1724) | PyQt6 |
| Altri lettori della lista | `gui/library_scanner_widget.py` (righe 494, 1148, 1174-1181), `gui/main_window.py:830` | leggono e **modificano direttamente** `main_window.processing_queue` con `QMutexLocker(queue_mutex)` | PyQt6 |

Verifiche fatte:
- `python -c "import core.queue_runner"` in un ambiente **senza PyQt6**: riesce, nessun modulo `PyQt*` caricato. Il headless non usa Qt a runtime; il legame è con il pacchetto `gui` (`gui/file_progress.py`, 297 righe, senza Qt) e, indirettamente, con `gui/services/step_plan.py` (393 righe, senza Qt, usato solo dal worker della GUI).
- `core/`, `utils/` e `glossary_engine/` non importano mai `gui`, tranne `queue_runner` (`core/queue_runner.py:383`, `from gui.file_progress import FileProgress`): è l'**unico** legame del headless con la GUI.
- Esistono **tre copie** della «uccisione dell'albero dei processi»: `ProcessingWorker._kill_proc_tree`, `queue_runner.kill_tree` e `utils/platform_compat.kill_tree` (la sola portabile e testata, già usata da `gui/glossary_worker.py`).

### Cosa è davvero duplicato

Lo *spawn* di `core.pipeline_cli` (`gui/workers.py:372-590` contro `core/queue_runner.py:273-367`): cartella IPC con `args.json`/`result.json`, ambiente del figlio (`PYTHONIOENCODING`, `TP_SUBPROCESS`, `TQDM_DISABLE`, `TP_EVENTS`, `apply_subprocess_env`, **nessun** `PYTHONUTF8`), flag di creazione (`CREATE_NEW_PROCESS_GROUP`, `CREATE_NO_WINDOW`), lettura di stdout riga per riga con `utils.events.parse_line` e `FileProgress.feed/feed_event`, lettura dell'esito da `result.json`, pulizia di `<video>.converting`, kill dell'albero.

### Cosa NON è duplicato (diverge per scelta o per storia)

| Aspetto | GUI (`ProcessingWorker`) | Headless (`queue_runner`) |
|---|---|---|
| Coda | dinamica: si aggiunge, si toglie, si riordina mentre lavora; prelievo atomico | lista fissa all'avvio |
| Eccezioni per file (`job_overrides`) e lingua di destinazione per file | sì | **no** (solo configurazione) |
| Anteprima dei passi (`StepTracker`, 393 righe) | sì, segnale `file_steps` | no |
| Voce di cronologia (`file_history_entry`) | sì | no |
| Pulizia cache modelli a fine coda | sì (anche dopo Stop) | **no** |
| Righe di rumore (`Downloading:`, `Using cache found in`) e `[DIAG-RAM]` | escluse dal log a video e dalla barra | scritte tutte nel log del file |
| stderr del figlio | solo nel log dell'applicazione | nel log del file con prefisso `[stderr]` |
| Avanzamento | un segnale a ogni punto percentuale | scrittura dello stato a ogni punto o ogni 15 s |
| Interruzione | `cancel()` dal thread GUI: il file corrente emette `file_failed`, i restanti restano in coda | `Ctrl+C`: stato `cancelled` |
| Pulizia `.converting` | solo se annullato | sempre (innocuo) |
| Esito | segnali `file_completed`/`file_failed` | `QueueStatus` JSON, codice di uscita 0/2/3/130 |

Un unico motore dovrà quindi avere **opzioni**, non un comportamento unico.

## 3. Architettura proposta

```
core/queue/                      (nessun import di PyQt6 né di gui/)
  job_queue.py    JobQueue       lista + eccezioni + lock (threading); prelievo atomico; rimozione, riordino sul posto,
                                 istantanea per le viste. Sostituisce processing_queue + QMutex + job_overrides.
  file_runner.py  FileRunner     UNA sola copia di: IPC, ambiente, spawn, lettura stdout, eventi, kill (platform_compat),
                                 pulizia. Restituisce FileResult(esito=completed|failed|cancelled, output, durata).
                                 Callback: on_line(riga), on_progress(pct, fase), on_steps(istantanea); sink per stderr.
  engine.py       QueueEngine    ciclo: prende, esegue con FileRunner, conta, emette eventi a listener Python semplici;
                                 cancel(); hook di fine coda (pulizia cache) opzionale.
  progress.py / step_plan.py / formatting.py   spostati da gui/ (puri) con ri-esportazione da gui/ per compatibilità

Adattatori
  GUI        ProcessingWorker (QThread, STESSE 11 segnali) = QueueEngine dentro run() + conversione evento -> segnale.
             QueueService possiede un JobQueue; MainWindow continua a esporre le stesse proprietà.
  Headless   queue_runner = JobQueue + QueueEngine + listener QueueStatus + QueueLock + notifiche.
```

Così la GUI non possiede più la coda (la possiede `core/queue`), il headless e la GUI condividono motore e sottoprocesso, e `gui/` diventa rimovibile (nessun import da `core/` o `utils/` verso `gui/`, verificabile con un test di lint come quello di piattaforma).

Scelta di sicurezza: **`ProcessingWorker` resta un `QThread`** che esegue il motore dentro `run()`. Il modello di thread della GUI (chi emette, su quale thread arrivano i segnali) non cambia.

## 4. Piano a passi (ciascuno una PR indipendente)

| Passo | Cosa | Rischio | Stima |
|---|---|---|---|
| **F0** | **Test di caratterizzazione**, nessun cambio al codice: uno script finto al posto di `core.pipeline_cli` (stdout con righe normali, eventi `TP_EVENTS`, `result.json`, exit code) e test che registrano (a) la sequenza esatta di segnali del `ProcessingWorker` con Qt offscreen, (b) i `queue_status.json` successivi del runner. Scenari: tutto ok; un file fallisce; Stop a metà; file rimosso/aggiunto/riordinato mentre lavora; eccezioni per file; coda vuota; righe di rumore; stderr; `.converting` residuo | nullo | 1 giorno |
| **F1** | Spostare in `core/` le classi pure (`FileProgress`, `StepTracker`, formattazione, modello del job) con ri-esportazione da `gui/`; `queue_runner` smette di importare `gui` | molto basso | 0,5 |
| **F2** | `FileRunner` unico (con `platform_compat.kill_tree`); `ProcessingWorker._process_single_file_subprocess` e `run_one` lo usano. I test F0 devono restare identici | basso-medio | 1 |
| **F3** | `JobQueue` + `QueueEngine`; `ProcessingWorker` diventa adattatore; `queue_runner` usa lo stesso motore; `QueueService` passa a `JobQueue`. Sostituire i 21 punti che oggi nominano `queue_mutex`/`QMutexLocker` fuori da `workers.py` (13 in `queue_service.py`, 4 in `library_scanner_widget.py`, 4 in `main_window.py`, per lo più shim) con metodi del servizio (`enqueue_many`, `snapshot`) | **medio-alto** | 1,5-2 |
| **F4** | Togliere gli shim, test «`core` e `utils` non importano `gui`» e «`core.queue` si importa senza PyQt6» | basso | 0,5 |

Ordine consigliato: F0 → F1 → F2 subito (circa 2,5 giornate, già eliminano la duplicazione dello spawn e delle tre `kill_tree`); F3 solo dopo la prova manuale del proprietario (sezione 6).

## 5. Come si evitano le regressioni

**Invarianti da preservare** (sono già scritti come commenti in `queue_service.py`/`workers.py`, vanno trasformati in test in F0):
1. La lista della coda non si riassegna mai; il riordino scrive sul posto; mutazioni e letture decisionali sotto lock; i segnali si emettono **dopo** il rilascio del lock.
2. Prelievo del file, rimozione dalla coda e prelievo delle sue eccezioni sono **un'unica operazione atomica**.
3. Nel `ProcessingWorker` il segnale `finished` è ridefinito (oscura `QThread.finished`): va mantenuto uguale.
4. Ordine dei segnali per file: `file_started` → `file_steps`/`file_progress`… → `file_history_entry` → `file_completed` (o `file_failed`) → `progress` → `queue_updated`.
5. Totale per la percentuale (`total_files_at_start`) e `note_removed()` quando si toglie un file in attesa.
6. Annullamento: il file corrente emette `file_failed`, i restanti restano in coda, le cache si ripuliscono comunque a fine coda.
7. Sottoprocesso identico: stesso `argv`, stesse variabili d'ambiente, stessi flag di creazione, cartella di lavoro, **niente** `PYTHONUTF8`. Sul percorso Windows + NVIDIA nessuna di queste cose deve cambiare di un carattere (è il percorso in produzione).

**Rete di sicurezza**: i test F0 (sequenze registrate *prima* del refactoring) devono passare **invariati** dopo ogni passo; nessun test viene «aggiornato per far tornare i conti» senza una nota nella PR. Si possono scrivere e far girare interamente nel cloud (Linux, senza GPU, senza modelli): il sottoprocesso è uno script finto e le prove con Qt usano `QT_QPA_PLATFORM=offscreen`, come per il Library Scanner (`linux_tests/test_library_scanner_fake_server.py`).

**Decisioni di prodotto da prendere** (non tecniche; senza risposta il motore conserva il comportamento attuale di ciascun lato):
1. Il headless deve passare le eccezioni per file e, a fine coda, ripulire le cache come la GUI? Oggi no; la docstring di `queue_runner` avverte di non usarlo insieme alla GUI proprio per le cache.
2. Il filtro delle righe di rumore e di `[DIAG-RAM]` va applicato anche nel log del headless? (Oggi il log del file le contiene tutte, utile per la diagnosi.)
3. Cronologia e anteprima dei passi per il headless: servono o restano solo della GUI?

## 6. Cosa non si può verificare nel cloud (serve una prova del proprietario)

La VM cloud è Linux senza GPU e senza Windows. Restano da provare a mano su Windows + NVIDIA, dopo F2 e dopo F3, con due clip brevi (una delle quali fatta fallire apposta):
1. Coda di 2 file dalla GUI: stesso esito, stessi tempi, stessi messaggi, barra e cronologia.
2. Stop a metà del primo file: si ferma, nessun processo orfano (`ffmpeg`, `gender_corrector_cli`), nessun `*.converting`.
3. Mentre lavora: rimuovere un file in attesa, aggiungerne uno dal Library Scanner, riordinare, impostare un'eccezione.
4. `python -m core.queue_runner <cartella>`: 2 file, `queue_status.json`, `Ctrl+C`.
5. Nessuna finestra console che compare (flag `CREATE_NO_WINDOW`).

## 7. Rischi principali

| Rischio | Passo | Mitigazione |
|---|---|---|
| Cambia l'ordine o il thread dei segnali verso la GUI | F3 | `ProcessingWorker` resta `QThread`; test di sequenza F0 |
| Race tra GUI e motore su prelievo/rimozione/riordino | F3 | prelievo atomico in `JobQueue`; test con thread che rimuove e riordina durante l'esecuzione |
| Il Library Scanner scrive nella lista senza passare dal servizio | F3 | metodi espliciti nel servizio, migrazione dei punti di accesso, test già esistenti del Library Scanner |
| Differenza sottile nell'ambiente o nei flag del figlio su Windows | F2 | confronto del dizionario `env`/`creationflags` costruito dal vecchio e dal nuovo codice in un test; prova manuale |
| Test di fumo dei proprietari fuori dal repository (suite locale) che toccano `ProcessingWorker`/`QueueService` | F2-F3 | il repository ne contiene pochi (`linux_tests/`); la suite locale va lanciata dal proprietario a ogni PR |

## 8. Raccomandazione

Procedere con F0, F1 e F2 (sono sicuri, reversibili e riducono subito il debito: una sola copia dello spawn e una sola `kill_tree`). Decidere su F3 dopo la prova manuale della sezione 6 e le tre domande della sezione 5. Se si preferisce un passo ancora più piccolo, F0 da solo ha già valore: fissa il comportamento della coda con test che oggi non esistono.
