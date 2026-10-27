# Studio di fattibilità: GUI HTML5 (web UI) al posto di PyQt6

Data: 27/10/2026. Autore: sessione cloud di Claude Code. Fonte: **solo il codice di `master`** (6789d7d); nessun altro ramo è stato considerato. Solo lettura e misure sul codice, **nessuna modifica**. Le stime sono stime: dove è un fatto verificato è scritto «verificato», dove è un'ipotesi da provare è scritto «da provare».

Domanda: passare a una web UI HTML5 che **mantenga tutte le funzioni attuali, senza regressioni di nessun ramo dell'app** (Windows + NVIDIA, Linux, AMD, solo CPU, coda headless, strumenti, impostazioni, Library Scanner).

## 1. Risposta breve

**Sì, è fattibile.** Non c'è nessuna funzione della GUI attuale che un'interfaccia web non possa offrire, e il progetto ha già quasi tutto il necessario: lo stack web è **già nelle dipendenze** (`fastapi 0.139.2`, `uvicorn 0.51.0`, `starlette 1.3.1`, `jinja2`, `httpx`, `python-multipart` in `requirements.txt`), il motore della coda è già separato dalla GUI (`core/jobs/`, refactoring del 27/10) e il tema ha già i **design token** (`gui/design_tokens.py`) e icone SVG riusabili.

Ma è un lavoro **grande** (stima 55-73 giornate, 11-15 settimane di lavoro continuo) e c'è **un punto che decide l'esito**: il **trascinamento di file dal Esplora risorse** e i **selettori di file/cartelle nativi**. Un browser puro non dà i percorsi assoluti dei file trascinati. Senza una «shell» nativa (una piccola finestra che contiene la pagina) questa funzione si perde, e si sostituisce con un navigatore di cartelle lato server. Va deciso prima di cominciare (sezione 6) e si può provare con un prototipo di 1-2 giorni.

**Raccomandazione:** farlo, ma **a strati e con le due interfacce in parallelo** (la Qt resta fino alla parità completa, selezionabile con `--ui qt|web`), nell'ordine: (0) estrarre dalla GUI Qt tutta la logica rimasta in servizi senza Qt, (1) backend e contratto API, (2) coda/cronologia/log, (3) impostazioni, (4) strumenti, (5) Library Scanner e revisione OCR, (6) pacchetto e installer. Ogni fase si chiude con una **matrice di parità** e test automatici eseguibili nel cloud (Chromium + Playwright), che è un vantaggio importante rispetto a oggi: una GUI Qt nel cloud si prova solo in modo limitato, una web UI si prova per intero.

## 2. Che cosa c'è oggi (fatti verificati)

| Misura | Valore |
|---|---|
| Codice della GUI (`gui/`, 35 moduli + 8 servizi) | 12.260 righe |
| Resto del progetto (`core/`, `utils/`, `glossary_engine/`) | 42.704 righe |
| Classi Qt in `gui/` (finestre, dialoghi, widget, `QThread`) | ~40 |
| Tema | `gui/theme.qss.tpl` 1.300 righe + 6 fogli minori (424 righe) + `design_tokens.py` 213 righe |
| Testi tradotti | `utils/translations.py`: 2.963 righe, ~2.430 chiavi, italiano/inglese, funzione `tr()` |
| Icone | ~37 icone SVG (`gui/icons.py`) |
| Qt fuori da `gui/` | solo `main.py` (avvio), `utils/profile_dialog.py` (un dialogo Qt dentro `utils/`) e `utils/ui_stall_monitor.py` (telemetria); il resto sono commenti |
| Coda di elaborazione | già senza Qt in `core/jobs/` (motore, `FileRunner`, `JobQueue`); `QueueService` e `ProcessingWorker` sono adattatori |
| Dialoghi di file nativi | 8 punti (aggiungi file, aggiungi cartella, 2 in traduzione, 3 in sync, 1 in glossario) |
| Finestre di messaggio | ~120 usi di `QMessageBox` |
| Trascinamento | 7 usi (aggiunta di file alla coda, riordino della coda) |

### Le funzioni da conservare (perimetro)

| Area | Moduli | Righe | Cosa fa |
|---|---|---|---|
| **Coda** | `main_window.py`, `queue_service.py`, `workers.py`, `file_row_delegate.py`, `reorderable_list.py`, `segmented_filter.py` | ~2.800 | Aggiungi file/cartella (anche trascinando), scansione cartelle, righe con stato/barra/badge, filtri (tutti/in coda/in lavorazione/completati/falliti), riordino, rimozione (tasto Canc), menu contestuale con eccezioni per file (lingua, modello, audio forzato, genere, mux, upload), Avvia/Stop con conferme, spegnimento a fine coda, contatori, ETA |
| **Avanzamento** | `pipeline_steps_widget.py`, `progress_log.py`, `main_window.py` | ~420 (+ parte di `main_window.py`) | Card «Pipeline in corso» (passi con anelli, percentuale, ETA, barra stimata), log colorato con modalità compatta/Log Sintetico, filtro del rumore, correzione dei caratteri |
| **Anteprima file** | `main_window.py`, `metadata_service.py`, `workers.py` | ~250 (+ parte di `main_window.py`) | Locandina da TMDB, titolo, info del file |
| **Cronologia** | `history_widget.py` | 242 | Tabella con ricerca, statistiche, apertura di `.srt` e cartella |
| **Impostazioni (5 sezioni)** | `settings_dialog.py`, `general_settings_widget.py`, `profile_dialog.py`, `translation_model_dialog.py`, `adaptive_batch_settings_widget.py`, `opensubtitles_settings_widget.py`, `ocr_settings_widget.py`, `job_options_card.py` | ~3.200 | Lingua dell'interfaccia, Library Scanner, profili di trascrizione, modello di traduzione (NLLB/TranslateGemma/Claude/OpenAI, controlli d'ambiente), batch adattivo, OpenSubtitles (due API, credenziali, test), OCR, opzioni job |
| **Library Scanner** | `library_scanner_widget.py`, `library_scanner_worker.py` | 1.404 | Pannello collassabile: elenco video senza sottotitoli dal server (API FastAPI con chiave), filtri, importazione, conversione ASS, OCR bitmap (PGS/VOBSUB), «Superpower», notifica al server, mappa delle cartelle montate |
| **Revisione OCR** | `ocr_review_dialog.py`, `ocr_worker.py` | 664 | Confronto bitmap/testo con modifica manuale |
| **Glossario per show** | `glossary_dialog.py`, `glossary_worker.py` | 755 | Costruzione e approvazione dei candidati (sottoprocesso in `venv_glossary`) |
| **Sincronizzazione sottotitoli** | `sync_dialog.py`, `sync_worker.py`, `sync_batch_worker.py` | 802 | Coppie video/SRT, coda di sincronizzazione, annullamento |
| **Monitor risorse** | `widgets.py` | 342 | Barre CPU/RAM/GPU/VRAM (pynvml) e badge GPU |
| **Tema e avvio** | `theme.py`, `design_tokens.py`, `splash_screen.py`, `components.py`, `collapsible_card.py`, `segmented_filter.py`, `icons.py` | ~1.000 | Stile, icone, schermata iniziale, componenti |

**Rami dell'app che non cambiano e che la web UI deve solo continuare a poter lanciare:** coda headless (`core.queue_runner`), tutti i CLI (`pipeline_cli`, `sync_cli`, `glossary_builder_cli`, `env_check_cli`, ...), installer (`install.ps1`/`install.sh`), selfcheck, backend GPU (CUDA, ROCm, Vulkan, CPU), mappa delle cartelle montate su Linux.

## 3. Architettura proposta

```
 Browser (o piccola finestra nativa)                Processo «server» (Python, nessun PyQt6)
┌────────────────────────────────┐   HTTP + SSE    ┌──────────────────────────────────────────┐
│ SPA HTML5 / CSS / JS modules   │ ◄────────────► │ FastAPI + uvicorn (127.0.0.1, token)      │
│ - stato solo di vista          │  JSON, eventi   │  API: coda, file, impostazioni, i18n,     │
│ - i18n da /api/i18n            │                 │       strumenti, library, ocr, risorse    │
│ - tema = CSS variables         │                 │  Servizi senza Qt (core/…)                │
└────────────────────────────────┘                 │   QueueEngine/JobQueue (già in core/jobs) │
                                                   │   Config, TMDB, Library, Sync, Glossario… │
                                                   │  Sottoprocessi: pipeline_cli, sync_cli, … │
                                                   └──────────────────────────────────────────┘
```

Scelte, con la motivazione:

- **Server locale FastAPI, nessuna dipendenza nuova.** Le versioni sono già fissate in `requirements.txt` e provate nell'installer.
- **Eventi in tempo reale con Server-Sent Events (SSE), comandi con REST.** SSE basta (il traffico in tempo reale è quasi solo dal server al browser: log, avanzamento, passi, stato coda) e non richiede il pacchetto `websockets`. Il flusso dei log va **raggruppato** (invio ogni ~100 ms) per reggere i log lunghi (oggi il riquadro tiene 5.000 blocchi).
- **I18n senza duplicare i testi:** `GET /api/i18n/{lingua}` restituisce il dizionario di `utils/translations.py` (unica fonte). Cambiare lingua resta un'azione di una riga.
- **Tema:** i token di `design_tokens.py` diventano variabili CSS (`:root{--accent:…}`) generate dal server; i 1.300 righe di QSS si riscrivono come CSS (è il lavoro di sola vista più lungo). Le icone SVG si riusano così come sono.
- **Nessun build step per il frontend** (nessun Node nell'installazione): moduli ES nativi + una piccola libreria reattiva «vendored» (Preact+htm o Alpine, ~15 KB, in `webui/static/vendor/`, nessuna CDN: l'app funziona anche offline). Questo evita di introdurre una catena di strumenti in un progetto Python/Windows.
- **Il server possiede la coda e le attività lunghe;** il browser è solo una vista. Chiudere o ricaricare la scheda non ferma l'elaborazione (oggi chiudere la finestra la ferma, con conferma): è un cambio di ciclo di vita da progettare, vedi sezione 5.
- **Vincoli del progetto che il server deve rispettare:** nessuna inizializzazione CUDA nel processo del server (come oggi nel processo GUI: l'ML gira nei sottoprocessi), niente di nuovo che importi `torch`/`ctranslate2` nel server. La regola «`onnxruntime` prima di PyQt6» e il crash silenzioso di ctranslate2 sotto PyQt6 **scompaiono** con l'uscita da Qt (un rischio in meno nel lungo periodo).

## 4. I punti difficili (dove nascono le regressioni)

| # | Punto | Perché è difficile | Soluzione | Rischio |
|---|---|---|---|---|
| 1 | **Trascinare file da Esplora risorse nella coda** | Un browser non espone il percorso assoluto dei file trascinati | Shell nativa che lo espone (pywebview/WebView2: da provare) oppure navigatore di cartelle lato server + campo «incolla percorso» (la funzione cambia) | **Alto** |
| 2 | **Selettori nativi di file/cartella** (8 punti) | Il browser li ha ma senza percorso | Navigatore server-side (`/api/fs/list`, dischi Windows, UNC, mappa delle cartelle montate); con la shell nativa, i dialoghi nativi | Medio |
| 3 | **Sicurezza** | Un server locale che spegne il PC, lancia processi, legge percorsi e scrive configurazioni è un bersaglio (pagine web ostili, DNS rebinding) | Solo 127.0.0.1, porta casuale, token nell'URL/cookie `SameSite=Strict`, controllo di `Host` e `Origin`, nessun CORS, nessun accesso remoto di default (opzione `--listen` esplicita con autenticazione) | **Alto se trascurato** |
| 4 | **Ciclo di vita** | Oggi chiudere la finestra chiude l'app; col server a sé la coda sopravvive alla scheda | Pulsante «Esci» esplicito, avviso se la coda lavora, arresto ordinato, «un solo server per utente» (come il lock della coda headless) | Medio |
| 5 | **Aggiornamenti in tempo reale** | Log fino a migliaia di righe, barre che cambiano molte volte al secondo | SSE con raggruppamento, numero di riga progressivo per riprendere dopo una riconnessione | Medio |
| 6 | **Logica rimasta dentro i widget** | `library_scanner_widget.py` (1.290 righe), `translation_model_dialog.py` (1.294), `ocr_review_dialog.py`, `sync_dialog.py`, `glossary_dialog.py` mescolano vista e regole | Fase 0: estrarla in servizi senza Qt **prima** di scrivere il frontend (giova anche alla GUI Qt) | **Alto (è la maggior parte del lavoro)** |
| 7 | **Viste disegnate a mano** | `FileRowDelegate`, `PipelineStepsWidget`, `ResourceMonitor` usano `QPainter` | HTML/CSS/SVG: sono più semplici in web che in Qt | Basso |
| 8 | **Revisione OCR** | Immagini bitmap + modifica del testo | Immagini servite dal backend (PNG), modifica con `<textarea>` | Basso-medio |
| 9 | **Notifiche, apertura cartelle/file, spegnimento** | Sono azioni del computer, non della pagina | Il server le esegue (`os.startfile`/`xdg-open`, `shutdown`); hanno senso solo se browser e server sono sulla stessa macchina | Basso |
| 10 | **Prestazioni su PC modesti** | Un browser consuma RAM, che serve ai modelli | Il browser è un processo a parte; misurare il consumo con la scheda aperta; la shell nativa pesa meno di una scheda di Chrome | Medio, da misurare |
| 11 | **Aspetto «identico»** | Qt e web non rendono uguale | Si riusano token, icone, spaziature, ma l'identità pixel per pixel **non è garantita** (decisione del proprietario, sezione 9) | Medio |

## 5. Ciclo di vita e stato (cambiamenti voluti da trattare come requisiti)

- La **coda vive nel server** e può essere salvata su disco (oggi si perde alla chiusura: è un miglioramento facoltativo, non una regressione).
- Più schede aperte vedono lo stesso stato; i comandi sono idempotenti; le azioni distruttive (Stop, spegnimento, svuota) chiedono conferma come oggi.
- Ogni evento ha un numero progressivo; il browser che si ricollega riceve lo **stato completo** e poi gli eventi successivi.
- Il lock «una sola coda alla volta» (oggi `queue.lock`) estende alla web UI: un solo server per utente.

## 6. Quale «guscio» (shell) usare

| Opzione | Pro | Contro | Giudizio |
|---|---|---|---|
| **A. Solo browser** (`python -m webui` apre la scheda predefinita) | Zero dipendenze, funziona anche da remoto, test facili | Niente trascinamento con percorsi, nessuna icona nella barra, la scheda può chiudersi | Base obbligatoria |
| **B. pywebview** (WebView2 su Windows, WebKit/GTK su Linux) | Finestra propria, dialoghi nativi tramite ponte JS, probabile percorso completo nei file trascinati (**da provare**) | Dipendenza nuova, runtime WebView2 (presente su Windows 11), su Linux richiede GTK/WebKit | **Raccomandata come secondo livello** |
| C. Qt WebEngine (PyQt6-WebEngine) | Mantiene PyQt6 come contenitore | Porta con sé Chromium (~100 MB), l'ordine d'importazione e i crash di PyQt6 che si volevano evitare | Sconsigliata |
| D. Electron / Tauri | Il più completo come app desktop | Toolchain Node/Rust, aggiornamenti, pacchetto grande: fuori scala per questo progetto | Sconsigliata |
| E. Restare su Qt | Nessun lavoro | Non risolve i motivi che portano a chiedere la web UI | Alternativa «zero» |

Raccomandazione: **A + B**. Il server e la pagina sono uguali in entrambi; B è un guscio di poche decine di righe che aggiunge dialoghi nativi e trascinamento. La scelta fra A, B o entrambi si prende **dopo il prototipo P1** (sezione 8).

## 7. Come si evitano le regressioni

1. **Matrice di parità** (file `webui/PARITY.md`): una riga per ogni funzione della sezione 2, scomposta fino al singolo controllo (pulsante, menu, tasto, conferma, messaggio di errore), con lo stato `da fare / fatto / verificato su Windows / verificato su Linux` e il test che la copre. La web UI non sostituisce la Qt finché **ogni riga** non è `verificato`.
2. **Doppia interfaccia in parallelo.** `main.py` resta; si aggiunge `python -m webui`. Opzione `--ui qt|web` e una impostazione. Una release intera con entrambe, poi si valuta il ritiro della Qt.
3. **Fase 0 prima di tutto:** estrarre la logica dai widget in servizi senza Qt con test di caratterizzazione, come fatto per la coda (stesso metodo: i test passano identici sul codice vecchio e sul nuovo; prova di mutazione). Questo lavoro non cambia nulla per l'utente e riduce il rischio di tutto il resto.
4. **Test del contratto API** su ogni endpoint, con il finto `pipeline_cli` già esistente (`linux_tests/queue_stub_pipeline.py`) e i server finti già scritti per il Library Scanner.
5. **Test end-to-end della pagina nel cloud:** Chromium è già installato nell'ambiente (`/opt/pw-browsers`); si aggiunge Playwright **solo ai requisiti di test**. Ogni voce della matrice ha un test del browser: aggiungi file, avvia, stop, riordina, filtro, menu contestuale, impostazioni, cronologia, Library Scanner con server finto, glossario con CLI finto, ecc. Si confrontano anche schermate di riferimento (non per l'identità pixel, ma per accorgersi di regressioni di layout).
6. **Prova sui tre rami hardware:** Windows + NVIDIA (prova manuale del proprietario, con una checklist come per il refactoring della coda), Linux (cloud + prova su macchina AMD), CPU. Nel cloud si prova tutto tranne GPU, driver e Windows reale.
7. **Nessuna modifica al percorso Windows + NVIDIA di installazione** finché la web UI non è dichiarata pari: nessun cambio a `requirements.txt` (lo stack web c'è già), a `install.*`, ai pin (`ctranslate2==4.6.0`, `llama-cpp-python==0.3.34`).

## 8. Piano a fasi e stime

Stime in giornate di lavoro continuo di un singolo sviluppatore, con assistenza dell'IA; il collo di bottiglia reale non è scrivere il codice ma **verificarlo su Windows con la GPU**, che il cloud non può fare. L'intervallo tiene conto di questo.

| Fase | Contenuto | Giornate | Uscita |
|---|---|---|---|
| **P1 – prototipi** | (a) pywebview/WebView2: percorsi dei file trascinati e dialoghi nativi; (b) server FastAPI + SSE con 5.000 righe di log e 10 aggiornamenti/s; (c) sicurezza: token, Host/Origin, DNS rebinding; (d) consumo di RAM della scheda vs Qt | 2-3 | Decisione A / A+B; numeri veri |
| **0 – servizi senza Qt** | Estrarre da `library_scanner_widget`, `translation_model_dialog`, `ocr_review_dialog`, `sync_dialog`, `glossary_dialog`, `history_widget`, impostazioni, `MetadataService` e `QueueService` (versione senza Qt con bus di eventi) | 10-14 | Servizi con test; la GUI Qt usa gli stessi |
| **1 – backend** | App FastAPI, token e sicurezza, SSE, endpoint di coda/config/i18n/fs/risorse, avvio e chiusura del server, `--ui` | 5-7 | Contratto API + test |
| **2 – coda** | Pagina principale: coda, filtri, riordino, menu contestuale/eccezioni, Avvia/Stop, spegnimento, card «Pipeline in corso», log, contatori, locandina, cronologia, monitor risorse, tema CSS | 10-13 | Parità della scheda Coda e Cronologia |
| **3 – impostazioni** | Le 5 sezioni (profili, modello di traduzione con controlli d'ambiente, OpenSubtitles, OCR, batch adattivo, generali) | 7-9 | Parità delle impostazioni |
| **4 – strumenti** | Glossario per show, Sincronizzazione (singola e in coda) | 5-6 | Parità degli strumenti |
| **5 – Library Scanner e OCR** | Pannello Library Scanner (filtri, conversione ASS, OCR, Superpower, mappa cartelle), revisione OCR | 7-9 | Parità del Library Scanner |
| **6 – rifinitura e pacchetto** | Avvio/lancio (`.bat`, `.vbs`, `run.sh`), schermata iniziale, installer, PyInstaller, documentazione, guida alla migrazione | 3-4 | Release candidata con entrambe le UI |
| **7 – validazione** | Matrice di parità completa, prove manuali Windows/Linux/AMD, correzioni | 6-8 | «Verificato» su tutte le righe |
| **Totale** | | **~55-73** (11-15 settimane) | |

Il corpo di lavoro più grosso e meno visibile è la fase 0 (≈20% del totale): chi la salta si ritrova a riscrivere nel frontend le regole nascoste nei widget.

## 9. Decisioni che servono al proprietario

1. **Trascinamento di file e dialoghi nativi sono irrinunciabili?** Se sì, serve la shell B (pywebview) e la fase P1(a) decide la fattibilità. Se si accetta un navigatore di cartelle e un campo «incolla percorso» al posto del trascinamento, basta A.
2. **L'aspetto deve essere pixel-identico a quello Qt, o «coerente» (stessi colori, icone, spaziature, struttura)?** Pixel-identico ha un costo alto e poco senso su due motori di rendering diversi.
3. **Accesso da altri dispositivi** (telefono, altro PC) è un requisito, un vantaggio facoltativo o da vietare? Cambia il modello di sicurezza.
4. **La coda deve sopravvivere alla chiusura del programma** (persistenza su disco)? È una funzione nuova, non una regressione, ma conviene deciderla ora.
5. **Si accetta che per un periodo ci siano due interfacce** (Qt e web) e che la Qt si ritiri solo dopo una release intera con la web UI «verificata»?
6. **Chi fa le prove su Windows + NVIDIA?** Ogni fase si chiude con una checklist da eseguire sul PC del proprietario.

## 10. Rischi e benefici

**Benefici:** controllo da qualunque dispositivo (utile per il PC Linux/AMD e per un NAS), la coda sopravvive alla chiusura della finestra, test automatici completi nel cloud (oggi limitati), niente più librerie Qt di sistema su Linux (`libxcb-cursor0`, `libxkbcommon-x11`, `libegl1`, `libfontconfig1` nell'installer), scomparsa dei vincoli di importazione legati a PyQt6, una API che rende scriptabile tutta l'app.

**Costi e rischi:** 11-15 settimane di lavoro; perdita (o sostituzione) del trascinamento nativo senza shell; nuova superficie di attacco (serve disciplina sulla sicurezza); due interfacce da mantenere durante la transizione; il browser consuma RAM; difetti sottili di temporizzazione negli eventi in tempo reale; verifica su Windows reale sempre manuale.

## 11. Cosa non è stato verificato

- Il comportamento di pywebview/WebView2 con i file trascinati e con la tua versione di Windows (P1).
- Il consumo di RAM e CPU di una scheda del browser con log lunghi su un PC modesto.
- Se qualche widget Qt nasconde regole non documentate che la lettura del codice non ha fatto emergere (la fase 0 serve proprio a scoprirle).
- Le stime di tempo: sono stime a partire dalle righe di codice e dalla complessità dei moduli, non misure.
- Nessuna prova su GPU o su Windows; nessun prototipo è stato scritto.

## 12. Prossimo passo suggerito

Se si procede: fase **P1 (prototipi)**, 2-3 giornate, che dà risposte vere alle domande 1 e 3 e ai rischi più grossi (trascinamento, sicurezza, prestazioni). Subito dopo, la **fase 0** (servizi senza Qt) ha valore anche se la web UI non dovesse partire, perché semplifica la GUI attuale e la rende testabile.
