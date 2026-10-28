# Piano della web UI (ramo `webui/main`)

Stato al 27/10/2026. Studio di partenza: `docs/STUDIO_WEBUI.md` (PR #35). **Solo `master` come base; nessun altro ramo si considera.**

## Decisioni del proprietario (vincolanti)
1. **Trascinamento di file da Esplora risorse e dialoghi nativi: irrinunciabili** -> serve un guscio nativo (pywebview/WebView2, oppure Qt WebEngine di riserva); decide il prototipo P1.
2. **Aspetto pixel-perfect** rispetto alla GUI Qt attuale, **misurato**: confronto automatico con tolleranza (obiettivo: meno dell'1% di pixel diversi per schermata, con il testo valutato a parte), contro schermate della GUI Qt vera su Windows a 100%, 125%, 150%. Ci si adegua a CIO' CHE QT DISEGNA DAVVERO (anche i suoi difetti, p.es. i pesi del font variabile), non a quello che dice il QSS.
3. **Nessun accesso da altri dispositivi:** il server ascolta solo su 127.0.0.1, nessuna modalita' `--listen`.
4. **Nessuna persistenza della coda:** chiudere la finestra chiude l'app e la coda, come oggi.
5. **Rami: B con ripiego A.** Sviluppo nel ramo lungo `webui/main` (da `master`); `master` resta Qt; al momento dell'unione la Qt resta nel codice per una release con `--ui qt|web`. `webui/main` si allinea a `master` con `git merge master` almeno ogni settimana. Il codice nuovo sta in `tpweb/` (nome distintivo).
6. **Fase 0 «a gruppi»:** le estrazioni di logica dai widget Qt entrano in `master` con PR separate per area, ma si **uniscono due o tre alla volta** e la sessione locale prova il gruppo. Ogni PR segue il metodo della coda: test identici sul codice vecchio e sul nuovo, prova di mutazione, nessun cambio visibile. Un merge in `master` non cambia la produzione: i file si copiano in produzione solo dopo la prova.
7. **Prove su Windows:** le fa la sessione locale di Claude Code (ha accesso in scrittura a GitHub: scrive i rapporti nel ramo `webui/p1-results` e, in futuro, `webui/<fase>-results`; non scrive su `master` ne' su `webui/main`). Al proprietario restano i controlli fisici e i via libera.
8. **Prima di scrivere codice di prodotto: prototipi P1.**

## Fase 0: gruppi (la coda e' gia' fatta)
| Gruppo | Aree | Da estrarre da |
|---|---|---|
| G1 | Cronologia, locandine/metadata, impostazioni semplici (generali, opzioni job, batch adattivo, OpenSubtitles, OCR) | `history_widget`, `metadata_service`, `general_/job_options/adaptive_batch/opensubtitles/ocr_settings_*` |
| G2 | Sincronizzazione, Glossario | `sync_dialog`+workers, `glossary_dialog`+worker |
| G3 | Revisione OCR, Profili, Modello di traduzione | `ocr_review_dialog`, `profile_dialog` (anche `utils/profile_dialog.py`), `translation_model_dialog` |
| G4 | Library Scanner | `library_scanner_widget`, `library_scanner_worker` |

Dopo la fase 0: backend (`tpweb/`), coda e cronologia, impostazioni, strumenti, Library Scanner e OCR, pacchetto, validazione (vedi lo studio).

## P1 – prototipi (tpweb/proto, vedi il suo README)
Criteri di decisione:
- **Guscio:** pywebview se i file trascinati da Esplora risorse tornano con il **percorso assoluto** (disco locale, nomi con accenti e spazi, percorso di rete UNC, unita' mappata) e i dialoghi nativi funzionano; altrimenti Qt WebEngine di riserva (`p1_qtwebengine.py`); se nessuno dei due -> si torna a discutere.
- **Flusso di eventi:** 5.000 righe consegnate senza perdite, latenza p95 < 300 ms, attivita' lunga della pagina < 400 ms. Misura nel cloud (Chromium/Linux): 5.000/5.000, p95 136 ms, una attivita' lunga di 265 ms.
- **Sicurezza:** tutti i test di `p1_security_tests.py` passano (nel cloud: 7 passati, 1 saltato perche' la VM ha solo il loopback).
- **Memoria:** il guscio non deve aggiungere piu' di ~250 MB rispetto alla GUI Qt a riposo (soglia proposta, da rivedere con i dati).
- **Pixel:** prima misura su Windows, senza esito pass/fail: serve a calibrare il criterio e a vedere dove Qt e Chromium divergono. Nel cloud (Linux): le forme (bordi, barra) combaciano (barra 0,3% di pixel diversi), il testo no (Qt su Linux non applica i pesi 500/600 del font variabile Inter Tight, Chromium si').

## Esiti P1 su Windows (27/10/2026, commit fada9d2; rapporto: `tpweb/proto/results/P1_RAPPORTO_WINDOWS.md`)
| Criterio | Soglia | Misura | Esito |
|---|---|---|---|
| Sicurezza | tutti i test | 8 passati, 0 saltati | OK |
| Flusso di eventi (Edge) | 5.000/5.000, p95 < 300 ms, attivita' lunga < 400 ms | 5.000/5.000, p95 118 ms, 0 attivita' lunghe | OK |
| Percorsi dei file trascinati (pywebview, lato Python) | assoluti per ogni caso | locale, accenti/spazi, 3 insieme, UNC `\\localhost\C$\...`, unita' mappata `W:` (SMB reale): tutti corretti | OK (con riserve sotto) |
| Dialoghi nativi | funzionanti | file multipli e cartella OK | OK |
| Memoria | <= Qt a riposo + 250 MB | Qt 227 MB; pywebview 439 MB a riposo (+212 MB), 549 MB dopo il banco | OK, margine stretto |
| Pixel | prima misura, nessun pass/fail | 3,3% / 3,2% / 3,0% a 100/125/150%; forme combaciano, testo no | da calibrare (P2b) |

**Guscio: pywebview (WebView2).** Il percorso del file trascinato arriva solo lato Python (`pywebviewFullPath`, `null` nella pagina): il guscio lo consegna al backend, che e' un componente di prodotto da progettare.

### Riserve e voci aperte
- Trascinamento fatto con mouse simulato dalla sessione locale da Esplora risorse reale: serve **conferma fisica** del proprietario (1 minuto).
- Il percorso UNC provato e' `\\localhost\C$`: manca un `\\server\share\...` remoto senza lettera di unita'.
- **Blocco** della prima esecuzione automatica di pywebview (oltre 4 minuti, poi ripetuta senza problemi): non spiegato -> P2a (avvio ripetuto con tappe e limite di tempo). Nel prodotto servira' comunque un timeout di avvio con messaggio.
- Margine di memoria stretto (+212 su +250) con una pagina minima: la UI vera e' piu' pesante; rimisurare con la UI reale e rivedere la soglia o ridurre il consumo di WebView2.
- Pixel: nelle immagini a 125% e 150% si vede (osservazione da confermare) che il titolo Qt parte ~3 px CSS piu' a destra di quello web, che «Aggiungi file» e' ~6% piu' largo in web, e che a 125% la barra ha un lieve scarto agli estremi arrotondati. Il testo di Chromium e' piu' pieno.

### Proposta di criterio pixel (da approvare)
L'obiettivo «meno dell'1% di pixel diversi per schermata» con tolleranza per canale e' probabilmente irraggiungibile sul testo: Qt e Chromium rasterizzano i glifi con gamma e antialiasing diversi. Proposta, da confermare dopo P2b:
1. **Forme** (bordi, raggi, riempimenti, barre, tabelle): <= 1% di pixel diversi, rettangolo per rettangolo.
2. **Testo**: stessa posizione e stessa larghezza del riquadro del testo entro ±1 px, peso percepito entro una tolleranza misurata (inchiostro medio per riga), e **SSIM >= 0,97** per elemento; i pixel diversi % restano un dato riportato, non un pass/fail.
3. **Schermata intera:** SSIM >= 0,985 a 100/125/150%.
Se P2b mostra che la calibrazione porta il testo sotto il 2%, il criterio 2 si puo' irrigidire.

## P2 – prossime misure (sessione locale)
- **P2a** `p2_pywebview_startup.py`: 10 avvii consecutivi + 1 a freddo, con tappe (`loaded`, primo `evaluate_js`) e limite di 45 s; se uno si blocca, a che tappa e con quali processi.
- **P2b** `p2_calibrate_text.py`: scansione di peso, dimensione, spaziatura e spostamento del testo CSS contro le schermate Qt gia' catturate su Windows; dice quanto del 3% e' calibrabile.
- **P2c** conferma fisica del trascinamento da parte del proprietario, anche con `\\server\share\...` remoto.
- **Fase 0 / G1** in parallelo (non dipende dal guscio): vedi sopra.

## Esiti P2 su Windows (commit 251b697) e correzione del calibratore (27/10/2026)
**P2a – avvio di pywebview:** 10 avvii su 10 riusciti (1,92-2,75 s, media 2,03 s; `loaded` a ~0,6 s). Il blocco di oltre 4 minuti non si e' riprodotto. L'avvio realmente a freddo non e' provabile senza riavviare il PC (i WebView2 presenti erano `SearchHost` e `WidgetBoard` di Windows). **Requisito di prodotto:** un controllo di avvio con limite di tempo e un messaggio chiaro (e un nuovo tentativo con un profilo WebView2 pulito).

**P2b – calibrazione del testo (prima versione):** il testo non scendeva sotto il 2% (solo «Avvia» a 100%: 1,49%), con pesi al limite (300) e spostamenti anomali. **Questo risultato non e' attendibile:** il calibratore aveva due errori miei.
1. La barra era alta **12 px** nel calibratore, mentre Qt la disegna alta **14 px** (la regola generica `QProgressBar { height: 14px }` prevale su quella dell'ID, che la voleva a 12): questo spiega perche' il totale «prima» (4,2-4,5%) non coincideva con P1e (3,0-3,3%): ~1,1 punti erano la barra. Verificato nel cloud sugli stessi dati: con 14 px il «prima» coincide con P1e (2,769% e 2,635%).
2. Non cercava lo **spostamento verticale** del testo (il titolo Qt centra il testo nel suo riquadro con il padding del QSS): l'ottimizzatore lo compensava con pesi e spostamenti orizzontali irreali.

**Calibratore v2** (`p2_calibrate_text.py`): barra 14 px, spostamento verticale, **profili di rendering** (crenatura, `text-rendering`, glifi a pixel interi, hinting) e segnalazione dei pesi al limite e degli spostamenti anomali. Misura **valida nel cloud** (Qt Linux contro Chromium Linux, stesso sistema): il totale scende da 2,77% a **1,12%** a 100% e da 2,64% a **1,64%** a 150%; per «Aggiungi file» da 9,1% a 2,5% e per «Avvia» da 3,4% a 1,0% a 100%; il titolo da 10,1% a 4,9%. Osservazione: il peso migliore e' **400 per tutti gli elementi**, cioe' Qt (su Linux) **ignora i pesi 500/600 del QSS** e disegna tutto in regular; la dimensione migliore e' ~0,97-0,99 volte quella del QSS; nessun profilo di rendering batte quello predefinito.

**Conseguenza per il criterio pixel:** il testo sembra calibrabile molto piu' di quanto dicesse la prima lettura; l'obiettivo dell'1% sul totale e' vicino a 100% (1,1% su Linux) e a ~1,6% a scale frazionarie. **Il criterio proposto (forme <= 1%, testo con SSIM) resta, ma si irrigidira' se la rimisura su Windows conferma questi numeri.** Va rifatta la misura sul PC Windows con il calibratore v2 (P2b-bis): finche' non c'e', nessuna conclusione definitiva sul testo.

Lezione di metodo: ogni strumento di misura va prima verificato riproducendo un valore gia' noto (qui: il totale «prima» di P1e). Si aggiunge a `tpweb/proto/README.md`.

## P2b-bis: misura SSIM sulle immagini Windows (sessione cloud)

SSIM (grigio, finestra 7) fra Qt e Chromium, dalle immagini pubblicate dalla sessione locale (prima/dopo la calibrazione del testo):

| Scala | Schermata | Titolo | Pulsante primario | Avvia | Barra |
|---|---|---|---|---|---|
| 100% prima → dopo | 0,953 → **0,986** | 0,75 → 0,94 | 0,86 → 0,96 | 0,98 → 0,98 | 1,000 |
| 125% prima → dopo | 0,953 → **0,988** | 0,77 → 0,95 | 0,85 → 0,96 | 0,96 → 0,99 | 0,997 |
| 150% prima → dopo | 0,956 → **0,973** | 0,79 → 0,89 | 0,87 → 0,91 | 0,97 → 0,96 | 1,000 |

Lettura: forme (barra) praticamente identiche; il testo non scende sotto ~2% di pixel diversi perché Qt (DirectWrite) e Chromium (Skia) rasterizzano diversamente i glifi, non per un parametro CSS. Con SSIM la schermata supera 0,985 a 100% e 125%, non a 150%.

**Criterio rivisto proposto (da approvare):** forme ≤1% di pixel diversi; testo valutato per posizione (bbox ±1 px), larghezza (±1 px) e SSIM per elemento ≥0,95 (≥0,90 a 150%); schermata SSIM ≥0,985 a 100% e 125%, ≥0,97 a 150%. Da indagare: arrotondamento ai pixel interi a scale frazionarie (barra 125% 2,19%).

**Decisione del proprietario:** criterio rivisto del testo approvato; pywebview confermato come guscio (fallback Qt WebEngine). Requisito di prodotto: watchdog all'avvio (timeout + nuovo tentativo).

## Fase 1 – backend (ramo `webui/p3-backend`, avviata 28/10/2026)
Ordine delle fette (ognuna: PR in `webui/main`, test del contratto, prova di mutazione, suite verde):
1. **1a – fondamenta (fatta):** `tpweb/security.py` (token, Host/Origin, nessun CORS), `tpweb/events.py` (bus con numeri progressivi), `tpweb/app.py` (`/api/ping`, `/api/i18n/{lingua}`, `/api/state`, `/events` SSE raggruppato con ripresa da `Last-Event-ID`/`?after=` e stato completo se gli eventi sono stati scartati), `tpweb/runner.py` (server in un thread, solo 127.0.0.1). Test: `test_tpweb_security.py`, `test_tpweb_events.py`, `test_tpweb_pure.py` (nessun PyQt6/gui/torch nel pacchetto).
2. **1b – coda (fatta):** `tpweb/queue_backend.py` (`WebQueue`: JobQueue + righe `JobRecord` + `QueueEngine` in un thread, ogni cambiamento sul bus; stesse regole di `QueueService`: niente doppioni, file in lavorazione non riaccodabile, Stop lascia gli altri in coda, svuota rifiutato mentre lavora, rimozione abbassa il totale del motore, job OCR solo in elenco) e `tpweb/routes_queue.py` (`/api/queue`, `add`, `remove`, `reorder`, `overrides`, `clear`, `start`, `stop`). `JobRecord` e' passato a `core/services/job_model.py` (il vecchio nome in `gui/services` e' un alias). Test con motore vero e finto `pipeline_cli`: `test_tpweb_queue.py` (19, 18 mutazioni tutte rilevate). Ancora da fare in 1b+: scansione di cartelle, dimensioni dei file, spegnimento a fine coda, conferme (della pagina).
3. **1c – cronologia e impostazioni semplici (fatta):** `tpweb/routes_history.py` (celle e statistiche come la GUI, ricerca, «Apri .srt»/«Cartella» per indice di voce: il server apre solo percorsi della cronologia; la coda salva le voci riletto-il-file prima di scrivere) e `tpweb/routes_settings.py` (generali, opzioni dei job, batch adattivo, OCR, OpenSubtitles con i servizi di G1; limiti identici ai campi della GUI; chiavi API e password MAI restituite, solo `*_set`; prova di connessione di Scanner e OpenSubtitles). Profili e modello di traduzione (G3) arrivano con la fase 3.
4. **1d – file system (fatta):** `tpweb/routes_fs.py` (`/api/fs/roots`, `/api/fs/list`: dischi Windows, root/home, cartelle della mappa del Library Scanner, filtro per estensione, nascosti, ordine senza maiuscole, solo percorsi assoluti, sola lettura). Chiude anche 1b: scansione di cartelle in background (`/api/queue/scan`), dimensioni dei file (`/api/queue/sizes`), spegnimento a fine coda (il server non spegne MAI il PC se non gli e' stata data l'azione: in prova e' un finto). Estratti senza Qt, con test di caratterizzazione identici sul vecchio codice: `core/services/file_scan.py` e `shutdown_policy.py` (`gui/workers.py` e `queue_service.py` li importano).
5. **1e – risorse (fatta):** `core/services/resource_sampler.py` (CPU/RAM/GPU/VRAM/rete, senza Qt; estratto da `gui/widgets.py` con test di caratterizzazione identici sul vecchio codice: 15 passano su entrambi) e `tpweb/routes_resources.py` (`GET /api/resources`, la pagina lo interroga ~1 volta al secondo; la velocita' di rete e' quella fra due richieste).
6. **1f – ciclo di vita (fatta):** `tpweb/launcher.py` + `__main__.py` (`python -m tpweb`), `tpweb/lifecycle.py` (un solo server per utente con `~/.transcriberpro/tpweb.lock`; rifiuta di partire se la GUI Qt o la coda headless possiedono gia' la coda, codice di uscita 3), `POST /api/quit` (con la coda al lavoro serve `force`, che ferma il file in corso come Stop), `tpweb/ui_choice.py` e **`main.py`: `--ui qt|web` e chiave `ui` del config** (predefinito `qt`; `--ui web` non importa PyQt6 ne' onnxruntime, provato con PyQt6 bloccato; `--ui` non valido -> uscita 2). Il server apre il browser o, con `--no-browser`, stampa l'indirizzo. **Nota per la produzione:** `main.py` cambia (blocco di 15 righe prima dell'import di onnxruntime) e la copia in produzione resta da fare solo dopo la prova su Windows.
7. **Ancora da fare nella fase 1:** il guscio pywebview (fase 6, serve Windows) e il watchdog di avvio (timeout + nuovo tentativo con profilo WebView2 pulito); il pacchetto PyInstaller dovra' includere `tpweb/` (fase 6).

**Fase 1 completata lato server (cloud): 1a-1f.** Prossima: fase 2, frontend (pagina Coda e Cronologia), che richiede le prime schermate di riferimento e le prove di aspetto su Windows con la sessione locale.

## Fase 2 – frontend, pagina Coda (ramo `webui/p4-coda`, avviata 28/10/2026)
- **2a – impianto (fatto):** pagina senza passaggio di build (moduli ES + Preact/htm in copia locale `tpweb/static/vendor/`, nessuna CDN, licenze e `NOTICE.md`); `GET /` + `/static` + `/assets/{fonts,icons}` dalla stessa origine, tipi MIME fissi (su Windows `.js` puo' risultare `text/plain`); `tokens.css` e `js/icons.js` **generati** da `gui/design_tokens.py` e `gui/icons.py` (`scripts_manutenzione/gen_tpweb_assets.py`, test di sincronia); testi solo da `/api/i18n` (lingua dell'impostazione; «auto» = lingua del browser) con test che ogni chiave dei JS esiste in IT e EN e che non c'e' prosa scritta a mano; `formatting.py` e `log_filter.py` spostati in `core/services/` (alias in `gui/services/`).
- **2b – pannello sinistro e cornice (fatto):** titlebar, schede Coda/Cronologia, filtro con contatori, righe (ElideMiddle misurato con canvas, barra, eccezioni `ov` ora nel `JobRecord`), selezione Ctrl/Maiusc, Canc, Aggiungi File/Cartella con il navigatore dei file (ricorda l'ultima cartella), Pulisci, Avvia/Ferma con conferma, «Spegni al termine», barra, tessere ETA/tempo, monitor risorse, cronologia. Le misure sono quelle della finestra Qt VERA (`p2_qt_capture.py`): pannelli 414/472/472, bottoni, lista e righe coincidono entro 2 px nel confronto a 1400x900 (Linux).
- **Resta della pagina Coda:** 2c (riordino a trascinamento, menu contestuale con eccezioni), 2d (locandina, log con Log Sintetico, card «Pipeline in corso», diagnostica, badge GPU), scheda Library Scanner (fase 5). Stato riga per riga in `tpweb/PARITY.md`.
- **Misura (C-010):** `p2_qt_capture.py` e `p2_web_capture.py` producono le stesse schermate (1400x900, 100/125/150%) negli stessi stati; `p2_compare.py` calcola SSIM e % di pixel diversi per schermata e per pannello. Prima misura nel cloud (Linux, solo per provare lo strumento): SSIM intera 0,89-0,92, pannello sinistro 0,93-0,95.
- **2c (fatta):** menu contestuale con eccezioni per file (voce spuntata comune, ripristino, rimuovi) e riordino a trascinamento (stesso algoritmo di `ReorderableFileList`). `/api/queue/override-options`, avviso nel log per i file non modificati.
- **2d (fatta):** log di elaborazione sul server (`core/services/log_buffer.py`: filtro, barre riscritte sul posto, colori, 5.000 righe; **identico al `MainWindow.log_message` della GUI su sequenze scritte**), Log Sintetico, card «Pipeline in corso», diagnostica, anteprima (locandina e titolo con `find_poster` e `TitleResolver` di G1), badge GPU, pill di stato, conteggi delle schede. Le misure di tutti e tre i pannelli coincidono con la finestra Qt vera entro 2 px nel confronto Linux (solo le larghezze che dipendono dal testo differiscono di qualche px).

## Fase 3 – Impostazioni (ramo `webui/p8-impostazioni`, 28/10/2026)
- **Server:** `routes_settings.py` (generali, opzioni job, batch, OpenSubtitles, OCR, rivelazione dei segreti solo su richiesta), `routes_models.py` (trascrizione e traduzione; download LLM e test pyannote in sottoprocesso con righe come eventi). Segreti mai nello stato.
- **Pagina:** dialogo con 7 schede (`settings.js`, `settings_basic.js`, `settings_models.js`, `form.js`, `dialogs.js`), testi solo via `t()`.
- **Difetti trovati dai test e corretti:** campo numerico che perdeva il testo digitato se arrivava un aggiornamento dal server; messaggio non chiudibile con Esc se subito dopo l'apertura; `EnvJobs` fissava il runner troppo presto.
- Resta: confronto d'aspetto con Qt (C-011).
- **Prova di mutazione (fase 3):** 13 mutazioni, 10 uccise, 3 equivalenti documentate: `if (typed === null) return` in `Spin.commit` (senza, `parseFloat('null')` e' NaN e non scrive), richiesta della chiave del Scanner a ogni «Mostra» (il server restituisce lo stesso valore salvato) e `put(last_tab)` anche alla selezione iniziale (la GUI salva l'ultima scheda a ogni cambio di riga, anche programmatico).

## Fase 4 – Strumenti (rami `webui/p9-strumenti`, `webui/p10-sync`, 28/10/2026)
- **4a (unita, #63):** `ToolGate` – un solo lucchetto per coda e strumenti (due schede del browser possono premere insieme), flag liberati dal thread del run; verdetti identici a `QueueService.can_start`.
- **4b (unita, #64):** Glossario. Stato e report sul server; il salvataggio prende solo termini presenti nel report; la ricerca TMDB (`resolve_tmdb`, estratta dal dialogo con test di caratterizzazione) gira fuori dal ciclo degli eventi.
- **4c:** Sincronizzazione (singola e coda), `ProgressLog` identico al log del dialogo, esito annunciato una volta per run (`run_id`).
- **Difetti trovati dai test:** messaggio finale perso con run istantaneo (eventi accorpati), stato delle righe escluse, riapertura a run in corso.
- **Mutazioni:** 4a 7/7, 4b 12/12, 4c 15/15 uccise dopo i test aggiunti.

## Fase 5 – Library Scanner e OCR (rami `webui/p11-scanner` #66, `webui/p12-ocr`, 28/10/2026)
- **5a (unita):** card (elenco, filtri locali senza ricaricare, import con mappa dei percorsi, conversione ASS/SSA, notifica al server a ogni sottotitolo creato).
- **5b/5c:** `OcrManager` — macchina a stati di `LibraryScannerWidget` portata sul server: OCR singolo, revisione mirata (eventi e immagini sul server), write-back, coda differita a coda libera, batch e Superpower. `finished_hooks` della coda (a coda davvero finita), `schedule_shutdown` riusato dal batch.
- **Difetti trovati dai test:** pallino dello scanner con la stessa classe di quello della barra; nomi dei file con percorsi di Windows sul server Linux (`base_name`); hook di fine coda chiamati quando il thread della coda era ancora vivo (i differiti non sarebbero mai partiti).
- **Mutazioni:** 5a 15/16 (1 equivalente), 5b 22/22 e 5c 7/7 uccise dopo i test aggiunti.
