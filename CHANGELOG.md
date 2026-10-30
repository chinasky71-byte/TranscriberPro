# Changelog

Tutte le modifiche rilevanti di Transcriber Pro. Versioni secondo
[SemVer](https://semver.org/lang/it/): `APP_VERSION` in `main.py` è l'unica fonte di verità.

## 1.34.43 — 2026-10-30 — Log del serbatoio NLLB più chiaro

- Con TranslateGemma il log mostrava «Modello NLLB fine-tuned scaricato dalla VRAM»: vero (il serbatoio L3 aveva caricato NLLB-FT per 1 frase) ma fuorviante. Ora il serbatoio scrive un messaggio dedicato (solo se è riuscito); `NLLBFineTunedTranslator.cleanup(announce=...)`. Test: `test_reservoir_nllb_message.py`. Nessun cambio alla traduzione.

## 1.34.42 — 2026-10-28 — Cronologia web: ordinamento e cancellazione

- **Ordinamento:** clic sull'intestazione di Nome, Data, Lingua, Durata o Dimensione (crescente → decrescente → ordine del file). Si ordina sul server sui dati veri (data ISO, secondi, byte), non sul testo mostrato; l'indice di riga resta la posizione nel file.
- **Cancella cronologia:** pillola con avvertimento di operazione NON reversibile (video e sottotitoli non vengono toccati); il server pretende `confirm: true` oltre al token.
- **Robustezza (bugcheck):** lucchetto in `HistoryService` (coda e server scrivono lo stesso file), `reload_and_append` per la coda, temporaneo per thread; «Apri .srt/Cartella» rifiuta (409) se la riga mostrata non è più quella dell'indice.
- **Verifica:** test di servizio, API e pagina (Edge); i soli rossi sono gli ambientali noti su Windows (12, compreso `test_prerequisiti_genere`: manca il venv NLP nella cartella del repo).

## 1.34.41 — 2026-10-28 — G4: Library Scanner fuori dalla GUI (PR #48, #49, #50)

- **Client:** `LibraryScannerClient` e `call_api` (chiamate HTTP al server, messaggi d'errore identici, nuovi tentativi solo per errori di rete) in `core/services/library_scanner_client.py`.
- **Righe e azioni:** `library_rows` (tipo di sottotitolo, badge, classi per giorni, filtri, righe nascoste, statistiche, tipo selezionato) e `library_actions` (piano di importazione, richieste ASS e Superpower, risposte, testi di avanzamento, strategia) in `core/services/`. `LibraryScannerWidget` e `LibraryScannerWorker` restano la vista, con gli stessi segnali.
- **GUI invariata, nessun file di dati cambia formato.**
- **Verifica:** test di caratterizzazione scritti sul vecchio codice (94 test) e passati identici su master e sul nuovo; prova su Windows con server vero in sola lettura (risultati identici a master) e GUI vera con finto server (tabella, ordinamento, import, badge ASS, revisione OCR, Superpower, chiusura durante il batch senza processi orfani); SRT automatici identici a master.
- Scopo: base per la futura GUI web (`docs/WEBUI_PIANO.md`); nessun cambiamento visibile all'utente.

## 1.34.40 — 2026-10-28 — G3: revisione OCR, profilo e modello di traduzione fuori dalla GUI (PR #44, #45, #46)

- **Revisione OCR:** `OcrRunEngine` (OCR dei sottotitoli bitmap PGS/VobSub nei modi ocr e writeback, rami review e auto, esiti per formato non supportato, lingua senza tessdata, annullamento ed errori) in `core/jobs/ocr_run.py`; `ocr_review_service` (etichette e pallini di confidenza, contatore, filtro "solo dubbi", prossimo dubbio con giro completo, "verificato", corsivo, riga di info) in `core/services/`. `OcrWorker` e `OcrReviewDialog` restano la vista.
- **Profilo di trascrizione:** `TranscriptionSettingsService` (motore, stile dei dialoghi, schede dei profili) in `core/services/`; `ProfileSelectionDialog` resta la vista. `utils/profile_dialog.py` e' una copia vecchia non usata: non toccata.
- **Modello di traduzione:** `TranslationModelService` (scelta del modello con i controlli di prerequisiti, percorsi NLLB fine-tuned e LLM, chiavi API e token con validazione, parametri NLLB, diarizzazione, genere, forza-audio) in `core/services/`; `EnvCliRunner` (download del modello LLM e test pyannote in sottoprocesso) in `core/jobs/env_cli.py`. `TranslationModelDialog` e `EnvCliWorker` restano la vista.
- **GUI invariata, nessun file di dati cambia formato.** I worker non formano cicli di riferimenti (listener con riferimento debole).
- **Verifica:** test di caratterizzazione scritti sul vecchio codice e passati identici su master e sul nuovo; mutazioni mirate tutte rilevate (salvo poche equivalenti documentate); prova su Windows con file PGS/VobSub reali: SRT sidecar e MKV con mux con lo stesso SHA256 di master, annullamento senza processi orfani; schermate della scheda Traduzione identiche pixel per pixel; revisione OCR provata a video con il codice di produzione.
- Scopo: base per la futura GUI web (`docs/WEBUI_PIANO.md`); nessun cambiamento visibile all'utente.

## 1.34.39 — 2026-10-27 — G2: logica di Sync SRT e Glossario fuori dalla GUI (PR #41, #42)

- **Sync SRT:** `SyncBatchEngine` (ciclo della coda multi-file: un sottoprocesso `core.sync_cli` per coppia, ambiente, avanzamento, kill dell'albero) e `SyncRunner` (sync di un solo video) in `core/jobs/`; `SyncBatchPlan` (stato della tabella delle coppie: abbinamento, scelta dell'SRT, spunte, stati, duplicati, riepilogo) in `core/services/`. `SyncBatchWorker`, `SyncWorker` e `SyncDialog` restano la vista, con gli stessi segnali nello stesso ordine.
- **Glossario per show:** `GlossaryRunEngine` (lancio nel `venv_glossary`, righe JSON, annullamento con kill dell'albero Qwen, pulizia dei file temporanei) in `core/jobs/`; `glossary_service` (nomi, candidati TMDB, richiesta di avvio, report, salvataggio) in `core/services/`. Worker e dialogo restano la vista (i vecchi nomi sono alias).
- **GUI invariata, nessun file di dati cambia formato.** I worker non formano piu' cicli di riferimenti (listener con riferimento debole): un `QThread` non viene piu' distrutto in un momento imprevedibile dal garbage collector.
- **Verifica:** test di caratterizzazione scritti sul vecchio codice e passati identici su master e sul nuovo; mutazioni mirate tutte rilevate (salvo poche equivalenti documentate); prova su Windows con GUI vera e con file reali: SRT sincronizzato con lo stesso SHA256 di master, coda reale con coppia annullata identica, glossario reale su uno show di 8 episodi (25 schede, Salva funzionante, nessun processo orfano).
- Scopo: base per la futura GUI web (`docs/WEBUI_PIANO.md`); nessun cambiamento visibile all'utente.

## 1.34.38 — 2026-10-27 — G1: logica di cronologia, metadati e impostazioni fuori dalla GUI (PR #36, #37, #38)

- **Nuovo `core/services/` (senza Qt e senza `gui`, regola verificata da un test):** `HistoryService` (cronologia: caricamento, salvataggio atomico, statistiche, ricerca, formati), `TitleResolver` e `find_poster` (titoli per l'overlay e ricerca locandina), e un servizio per ciascuna scheda di impostazioni: Generali (lingua, Library Scanner), Batch adattivo, OCR, OpenSubtitles. `JobOptionsService` e `SettingsService` si spostano qui (i vecchi nomi in `gui/services` sono alias dello stesso modulo).
- **GUI invariata:** i widget restano la vista, con gli stessi segnali, testi e chiavi di config. Nessun file di dati cambia formato.
- **Verifica:** test di caratterizzazione scritti sul vecchio codice e passati identici su master e sul nuovo; 46+ mutazioni mirate tutte rilevate; prova su Windows con GUI vera (home isolata) senza differenze rispetto a master.
- Scopo: base per la futura GUI web (`docs/WEBUI_PIANO.md`); nessun cambiamento visibile all'utente.

## 1.34.37 — 2026-10-27 — Refactoring della coda: un solo motore per la GUI e per la coda headless (PR #34)

- **La coda non e' piu' della GUI: vive in `core/jobs/`** (senza Qt e senza `gui`): `JobQueue` (lista, eccezioni per file, lock, prelievo atomico),
  `FileRunner` (unica copia di: avvio di `core.pipeline_cli`, lettura dell'output, esito, kill dell'albero dei processi, pulizia di
  `<video>.converting`), `QueueEngine` (ciclo, contatori, avanzamento, anteprima dei passi, cronologia, pulizia cache a fine coda),
  `FileProgress`/`StepTracker` (spostati da `gui/`: i vecchi nomi sono alias dello stesso modulo) e `history_store`.
- **La GUI non cambia:** `ProcessingWorker` e `QueueService` sono adattatori sul motore, con gli stessi 11 segnali, nello stesso ordine e nello stesso
  thread; aspetto e comportamento identici (confermato dall'utente). Un file che solleva un'eccezione non ferma piu' la coda: il file fallisce, con il
  motivo nel log. Le tre copie di "uccidi l'albero dei processi" sono diventate una.
- **Coda headless (`python -m core.queue_runner`) allineata alla GUI:** log con etichetta `[INFO]`/`[WARNING]`/`[ERROR]` e stessi testi della GUI
  (`<data>_queue.log` per l'intero flusso, `<data>_NNN.log` per il file N), voci in `history.json` per i file completati, anteprima dei passi in
  `queue_status.json` (`current.steps`), pulizia delle cache dei modelli a fine coda (`--keep-caches` per evitarla), eccezioni per file.
- **Prova del 27/10/2026 (Windows 11, RTX 3060, venv di produzione):** headless con la vera pipeline (coda di 2 clip con una rovinata, esiti e codici di
  uscita come la produzione; log senza righe di librerie ne' eventi; cronologia solo per i completati; lock con codice 3; lock stantio riconosciuto; Ctrl+C
  simulato: codice 130 in 0,3 s, nessun processo orfano ne' `.converting` ne' cartelle `tp_*`) e GUI (coda normale, Stop a meta' file senza orfani,
  coda dinamica: rimozione, riordino, eccezioni, aggiunta, no doppioni; file sparito prima del suo turno; aspetto identico). I `.it.srt` non sono identici
  byte per byte tra due giri della stessa clip (nemmeno tra due giri della produzione): audio e trascrizione non sono deterministici.
  Non provati: il tasto Ctrl+C vero in un terminale e l'avviso di blocco con un'attivita' fuori coda.
- **Test:** nuovi test di caratterizzazione identici sul vecchio e sul nuovo codice (`linux_tests/test_queue_*`, `test_core_jobs_*`); i test locali che
  innestavano il finto su `ProcessingWorker._process_single_file` ora usano `QueueEngine._process_file_inner`. Su Windows due test del cloud
  (`test_motore_senza_qt_ciclo_completo`, `test_motore_eccezione_in_un_file_non_ferma_la_coda`) confrontano percorsi con separatori di Linux.

## 1.34.36 — 2026-10-26 — Soglia IQ3_M abbassata a 7,3 GiB (misura su RTX 3060 con VRAM limitata a 7,3 GiB)

- **`DEFAULT_GGUF_MIN_FREE_GIB['IQ3_M']` e `llm_translator_gguf_iq3_min_free_gb` da 7,5 a 7,3 GiB.** Con il desktop di Windows (~0,65 GiB) una scheda da 8 GB ha ~7,2-7,4 GiB liberi: con 7,5 finiva su NLLB fine-tuned anche se il GGUF ci sta. Il 7,5 era una stima (pesi 5,27 + KV 0,75 + buffer 0,8 + margine 0,4 = 7,2-7,5), ora e' una misura. Q4_K_M resta a 10,0; nessun'altra soglia toccata.
- **Misura (26/10/2026, Windows 11, RTX 3060 12 GB, scheda da 8 GB simulata):** un processo a parte riserva VRAM con torch fino a lasciare N GiB liberi, poi traduce con il motore di produzione (`GGUFSubprocessEngine`, n_parallel 4, ctx 512); VRAM dedicata con nvidia-smi ogni 0,25 s, memoria GPU condivisa di Windows con typeperf (serve a vedere lo sconfinamento in RAM, che non da errori).
  - IQ3_M a **7,3 GiB** liberi: Deadpool 2 (600 righe) picco +6.786 MiB, margine 853 MiB, condivisa max 286 MiB, 5,25 righe/s; The Ark S03E12 (655 blocchi, glossario di 16 termini, percorso di produzione) picco +7.102 MiB, margine 540 MiB, condivisa max 292 MiB, 2,59 blocchi/s, 253 s, **655/655 completati**.
  - IQ3_M a **7,0 GiB** liberi (The Ark): picco +7.291 MiB, margine 229 MiB, Windows sposta ~1,8 GiB in RAM (condivisa max 1.846 MiB), 1,03 blocchi/s, 636 s: non fallisce ma e' 2,5 volte piu' lento. La prova a 6,8 GiB non e' partita; il punto di rottura sta fra 7,0 e 7,3, quindi **non scendere sotto 7,3**.
  - Q4_K_M senza zavorra (Deadpool 2): picco +8.397 MiB, margine 2.394 MiB, 4,96 righe/s. Q4_K_M e IQ3_M lasciano 18 righe vuote o non tradotte su 600 in entrambi i casi (stesso comportamento, non una regressione).
- La stima di ingombro (`gguf_need_gib`, IQ3_M a n_parallel 4 = 7,22 GiB) e' gia' sotto 7,3: il pavimento governa e non rimanda a NLLB una scheda con 7,3 GiB.
- **Non misurato:** scheda da 8 GB reale, Linux, AMD/Vulkan, altre VRAM libere; i tempi dipendono da banda e core della 3060.
- Test aggiornati in `linux_tests/test_translator_path_select.py` (limiti a 7,3 e 7,29); README (EN/IT) aggiornato.

## 1.34.35 — 2026-10-25 — Avanzamento ed ETA del riconoscimento dei parlanti (diarizzazione)

- **Nuovo passo "Riconoscimento parlanti" nella card "Pipeline in corso" (Log Sintetico)**, tra Trascrizione e Traduzione, con percentuale ed ETA come gli altri passi: prima la diarizzazione (circa 5 minuti su una
  puntata di 165 minuti) non dava nessun segnale. Segue le regole delle altre fasi: disattivato se il riconoscimento parlanti e' spento o manca il token Hugging Face, "non necessario" con sottotitoli
  gia' nel video, tenuto al 99% finche' inizia il passo successivo. Riga di log aggiornata sul posto ("Riconoscimento parlanti: [███░░░] 30% │ ETA:~3m"), in italiano e in inglese.
- **Come:** `core/diar_progress.py` trasforma i passi dell'hook di pyannote in una frazione monotona (segmentazione 4%, impronte vocali fino al 94%, poi 97% e 100%): misura su X Factor S20E07 (165 min, GPU):
  segmentazione 4%, impronte vocali 90%, clustering 3%, finalizzazione 3%; l'avanzamento e il tempo restano entro ~4 punti. Peso 1,0 nella barra complessiva.
- Se una versione di pyannote non accetta l'hook si ricade sulla chiamata di prima (senza barra). La diarizzazione della correzione di genere non riaccende il passo escluso (revisione Opus).
- Test nuovi: piano dei passi, percentuale complessiva, riga aggiornata sul posto (IT/EN) e `linux_tests/test_diar_progress.py`.

## 1.34.34 — 2026-10-25 — Correzioni dalla validazione su GPU AMD (Linux/ROCm) e criterio di successo della traduzione

- **Prima prova reale su AMD** (Radeon RX 9060 XT, ROCm 7.0, Ubuntu): rapporto in `docs/VALIDAZIONE_AMD_2026-10-24.md`. Correzioni: `torchaudio.info` (rimosso da torchaudio 2.9/2.10) sostituito da `soundfile`;
  NLLB su ROCm sul solo dispositivo 0 (con una iGPU AMD `device_map="auto"` mandava i layer su entrambe e la generazione moriva); ctranslate2 inizializzato prima di torch su Linux (SIGSEGV di Whisper su ROCm,
  `utils/ct2_bootstrap.py`, **solo Linux**: su Windows l'ordine degli import non cambia).
- **Criterio di successo della traduzione** (vale su tutte le piattaforme): una traduzione con oltre l'80% dei blocchi rimasti nella lingua di partenza (`translation_max_untranslated_pct`) o con un errore GPU
  sistemico non e' piu' data per riuscita (prima il file veniva salvato come tradotto con exit 0). Test in `linux_tests/test_translation_success_gate.py`.
- Lavoro della sessione cloud (PR #28), controllato in locale: suite verde e avvio della finestra verificato su Windows.

## 1.34.33 — 2026-10-25 — Lingua per voto su piu' blocchi, attesa della VRAM prima della traduzione, barra della correzione di genere

- **Rilevamento automatico della lingua per voto** su piu' blocchi sparsi (Qwen3 e faster-whisper, `core/lang_vote.py`) invece di un solo campione.
- **Attesa che la VRAM degli ASR sia davvero libera prima della traduzione** su GPU (sconfinamento della memoria su Windows, `core/vram_settle.py`); solo nel ramo di traduzione su GPU.
- **Correzione di genere v2:** barra di avanzamento ed ETA nella card del log; la barra non dichiara 100% se non ha lavorato.
- Lavoro della sessione cloud (PR #25-#27), controllato in locale: suite verde e avvio della finestra verificato.

## 1.34.32 — 2026-10-24 — Installer GGUF: testi ripristinati, sostituzione solo se l'impronta cambia

- **Ripristinati i 38 testi `gd_*` dell'installer dei GGUF** persi nella 1.34.30 (rilascio che aveva sovrascritto `utils/translations.py` con una copia piu' vecchia): i messaggi del download tornano in italiano e inglese.
- L'installer sostituisce un GGUF gia' presente solo se il suo SHA-256 e' diverso, avvisa quando lo fa, e segnala se il file e' in uso. Dati dei GGUF (nome, byte, SHA-256, repository) in un solo punto del codice.
- Test nuovo: ogni chiave di `tr()` e `_tr()` usata nel codice esiste in inglese e in italiano con gli stessi segnaposto (core, utils, gui). Lavoro della sessione cloud (PR #24).

## 1.34.31 — 2026-10-24 — TranslateGemma in GGUF ACCESO di default; installer che scarica i modelli

- **Il traduttore LLM usa di default i pesi GGUF quantizzati** (`llm_translator_gguf_enabled` e `llm_translator_gguf_before_nf4` a `True`; le voci delle versioni 1.34.27-1.34.29 che dicono "spento di default" sono superate).
  Sulle schede da 12 a 20 GB passa avanti Q4_K_M (soglia 10 GiB liberi), da 8 a 12 GB IQ3_M (7,5 GiB), sotto 7,5 GiB NLLB fine-tuned; da 20 GiB resta il modello intero. Con il file GGUF assente, non
  adatto o non caricabile si torna in automatico a NF4 con un messaggio nel log; le due opzioni a `False` forzano il percorso storico. Provato su Windows (RTX 3060) nell'app: traduzione con GGUF (72 s contro 192 s
  per un video di 2 minuti), Stop durante il caricamento e durante la traduzione, ripiego su NF4 con file assente.
- **Installer:** `install.ps1` / `install.sh` scaricano da Hugging Face (`Chinasky71/translategemma-12b-it-subtitles-gguf`) il GGUF adatto alla scheda, con ripresa e controllo SHA-256.
- Test che `import utils` non carica PyQt6/torch/onnxruntime (regressione della 1.34.30). Lavoro della sessione cloud (PR #19-#22).

## 1.34.30 — 2026-10-24 — Correzione urgente: l'app non si avviava su Windows

- **Difetto (introdotto con la traduzione dell'interfaccia, fase B, 1.34.26):** `import utils` caricava `utils.translations`, che per rilevare la lingua importava PyQt6; su Windows PyQt6
  caricato PRIMA di onnxruntime fa fallire l'avvio (`DLL load failed while importing onnxruntime_pybind11_state`). L'app partiva solo nei test e nella pipeline in processo figlio, non dalla GUI.
- **Correzione:** `Translations._detect_language()` usa QLocale solo se PyQt6 e' gia' caricato (dopo `QApplication`, come prima per la GUI), senza mai importarlo lui. Test di regressione:
  `import utils` non carica PyQt6 e onnxruntime si importa dopo.

## 1.34.29 — 2026-10-24 — Percorso GGUF in sottoprocesso pulito (risolto il crash su Windows); modelli GGUF su Hugging Face

- **Il traduttore GGUF gira ora in un processo di lavoro separato** (`gguf_subprocess.py`, `gguf_worker.py`), con `llama_cpp` come primo import: su Windows, importato dopo `utils`/PyQt6, mandava in
  access violation `llama_supports_gpu_offload()` (la correzione della 1.34.28 non bastava: la voce era imprecisa). Stesso schema del glossario con Qwen. Il worker si chiude con `unload()` e libera la VRAM
  (provato su Windows con RTX 3060: 9,0 GB occupati col modello, 0,7 GB dopo lo scarico). Gestiti morte del worker (un riavvio), timeout, annullo dalla GUI e processo orfano.
- **Banco di qualita'** (TranslateGemma-12B, 900 righe di *Deadpool 2* e *A Man Called Otto*, giudizio alla cieca): Q4_K_M, Q3_K_M e IQ3_M **non inferiori a NF4** con margine di 3 punti e circa 14 volte piu' veloci
  (NF4 6,6% errori gravi; Q4_K_M 6,2%; IQ3_M 7,1%; Q3_K_M 7,4%). Il percorso GGUF resta **spento di default** (`llm_translator_gguf_enabled`).
- **File GGUF pubblicati** su https://huggingface.co/Chinasky71/translategemma-12b-it-subtitles-gguf (licenza Gemma): l'installer li scarichera' in un lavoro successivo.
- Lavoro della sessione cloud (PR #17) e prova locale su Windows; registro in `docs/HANDOFF_LOG_GGUF_TRANSLATOR.md`.

## 1.34.28 — 2026-10-24 — Percorso GGUF: corretto il crash su Windows prima del caricamento

- `GGUFEngine.load()` chiamava `llama_supports_gpu_offload()` prima di creare un qualunque modello: sulle ruote Windows con backend caricati dinamicamente il registro dei backend e' ancora
  vuoto e la chiamata andava in access violation. Ora il motore chiama prima `llama_backend_init()` (idempotente, lo fa anche `Llama()` alla prima istanza). Emerso durante il banco di qualita' GGUF
  sul PC dell'utente (RTX 3060, ruota llama-cpp-python 0.3.34); il percorso resta spento di default. Test nuovo in `linux_tests/test_gguf_engine.py`.

## 1.34.27 — 2026-10-24 — TranslateGemma in GGUF per schede da 8-12 GB e AMD/Vulkan (codice pronto, SPENTO di default)

- Nuovo percorso del traduttore LLM con pesi GGUF quantizzati (llama-cpp-python): selettore per VRAM e backend (`utils/translator_path_select.py`), motore (`core/llm_subtitle_translator/gguf_engine.py`),
  router (`path_router.py`), strumenti di conversione e quantizzazione (`scripts_manutenzione/gguf_convert.py`, guida `docs/GGUF_CONVERSIONE.md`).
- **Nessun effetto finche' il flag `llm_translator_gguf_enabled` resta spento** (default): bf16 e NF4 si comportano come prima. Il flag si accende solo dopo il banco di qualita' (non ancora eseguito).
- Lavoro della sessione cloud (PR #14-#16); registro in `docs/HANDOFF_LOG_GGUF_TRANSLATOR.md`.

## 1.34.26 — 2026-10-23 — Interfaccia tradotta (fase B): righe di log della pipeline in inglese o italiano

- Le righe di log emesse da pipeline, traduttori, sincronizzazione, motori di trascrizione, genere, diarizzazione, OCR e coda headless (circa 800 testi in `core/` e `utils/`) seguono la lingua dell'interfaccia.
  Il testo italiano e' identico carattere per carattere (verificato con `scripts_manutenzione/verify_i18n_identity.py`).
- I consumatori che leggevano le righe dal testo (filtro del log, avanzamento, sincronizzazione) riconoscono italiano e inglese.
- I processi figli leggono la lingua con `init_language_headless` (variabile `TP_LANG`, poi config, poi locale di sistema).
- Lavoro svolto dalla sessione cloud (PR #8-#13); registro in `docs/HANDOFF_LOG_I18N.md`. Restano in italiano i CLI che girano in ambienti virtuali senza `utils` (glossario, selettore genere, Canary).

## 1.34.25 — 2026-10-23 — Interfaccia tradotta (fase A): circa 120 testi che erano solo in italiano

- Library Scanner (tooltip, messaggi di conversione ASS/SSA, Superpower, OCR, righe di log), finestra Traduzione (modelli, chiavi API e token, correzione del genere), Impostazioni generali,
  Cronologia, stati della coda (riga e riquadro anteprima), "Pronto"/"In elaborazione", "Anteprima"/"Diagnostica" e righe di log della finestra principale passano da `tr()` con inglese e italiano.
  Il pulsante "Cancel" della finestra Traduzione diventa "Annulla" in italiano.
- Test nuovi: chiavi EN/IT in parita' e con gli stessi segnaposto, ogni `tr('chiave')` del codice esiste, nessun nuovo testo italiano scritto direttamente nei widget di `gui/`.
- Strumenti di sola lettura `scripts_manutenzione/scan_i18n.py` e `scan_i18n_literals.py` per cercare i testi non tradotti.
- Restano in italiano le righe di log emesse dalla pipeline (fase B).

## 1.34.24 — 2026-10-23 — Nomi delle lingue e schede della coda tradotti

- I nomi delle lingue dei sottotitoli (menu tasto destro e scheda "Opzioni job") e le schede "Coda di processamento" / "Cronologia" seguono la lingua dell'interfaccia (inglese se il sistema non e' in italiano).
  Test di parita' delle chiavi EN/IT e del menu in inglese.

## 1.34.23 — 2026-10-23 — "Forza trascrizione da audio" tra le opzioni per file

- Il menu tasto destro della coda ha anche **Forza trascrizione da audio** (Predefinito / Si' / No): per quel file ignora i sottotitoli gia' presenti nel video e trascrive l'audio.
  Sulla riga compare la sigla `audio`. Stessa logica delle altre eccezioni per file (mai scritta in `config.json`).

## 1.34.22 — 2026-10-23 — Opzioni job predefinite nelle Impostazioni; piu' spazio a coda e Library Scanner

- **Scheda "Opzioni job" nelle Impostazioni:** lingua dei sottotitoli, upload OpenSubtitles, "Muxa nel video" e genere avanzato (con righe che rimandano alle schede Traduzione e OCR per motore e revisione).
  Sono i valori di partenza di ogni file; per un file solo si usa il menu tasto destro della coda. Ogni modifica va subito in `config.json`. Le schede Traduzione e OpenSubtitles si riallineano
  quando le riapri.
- **Pannello principale:** la card "Opzioni job" non c'e' piu' (coda e Library Scanner guadagnano lo spazio). Sotto Avvia/Ferma c'e' una riga "Predefiniti: ITA · ↗ OS · NLLB" (un clic apre la scheda)
  e la casella "Spegni al termine", che riguarda tutta la coda.

## 1.34.21 — 2026-10-23 — Opzioni specifiche per file nella coda (tasto destro) e selezione multipla

- **Menu tasto destro sulla coda:** per i file in attesa si possono cambiare, solo per quel file, lingua dei sottotitoli, motore di traduzione (NLLB fine-tuned / TranslateGemma), correzione
  del genere, "Muxa nel video" e upload OpenSubtitles (ogni voce: Predefinito / valore). "Ripristina i predefiniti" azzera le eccezioni. Sulla riga compare una sigla (es. `ENG · TG · ⚧`);
  la lingua scelta si vede anche nel riquadro dell'anteprima. Per i job OCR in attesa: revisione mirata o automatica per file.
- **Selezione multipla** (Ctrl/Maiusc) nella lista: le opzioni e "Rimuovi dalla coda" (Canc) valgono per tutti i file selezionati; il riordino per trascinamento resta per una riga alla volta.
- **Come funziona:** le eccezioni non vengono mai scritte in `config.json`; il worker le prende insieme al file (sotto lo stesso lock della coda) e il processo figlio le applica come
  sovrapposizione in memoria (`Config.set_overlay`). Un file gia' preso, finito o rimosso non si modifica; riaccodare un file riparte pulito. Logica in `utils/job_overrides.py` (14 test).

## 1.34.20 — 2026-10-23 — Scheda video rilevata in primo piano

- **Etichetta GPU** sulla riga delle schede, centrata sotto la pill di stato: modello della scheda rilevata, **verde per NVIDIA, rosso per AMD**, oppure "CPU only" (grigio) se non c'e' una GPU compatibile
  (NVIDIA con CUDA; AMD con ROCm o Vulkan; Intel e integrate = CPU). Rilevamento in un thread (non rallenta l'avvio); se `nvidia-smi` e' lento al primo avvio e la scheda risulta senza CUDA
  il rilevamento si ripete dopo 30 s. Tooltip con il dettaglio. Logica in `utils/gpu_label.py` (7+1 test).

## 1.34.19 — 2026-10-23 — Installer: con --no-gpu / -NoGpu un download CPU fallito ferma l'installazione; Linux/AMD (lavoro del cloud)

- **Installer (`install.sh`, `install.ps1`):** con `--no-gpu` / `-NoGpu`, se il download delle ruote CPU di torch o di llama-cpp-python fallisce, lo script si ferma con un messaggio chiaro
  invece di ripiegare sulle ruote CUDA di `requirements.txt` (~3 GB inutili senza GPU NVIDIA). Basta rilanciare dopo aver controllato la rete.
- **Linux/AMD (sessione cloud, gia' in master):** `install.sh --system-deps` si rilancia da solo dopo i pacchetti di sistema (anti-ciclo); `--gpu-backend=vulkan|rocm`;
  `requirements-rocm.txt` (torch 2.10+rocm7.0), `scripts_manutenzione/amd_smoke_test.py`; Python 3.12 provato su Ubuntu 24.04. Dettagli in `docs/HANDOFF_LOG_LINUX_AMD.md`.

## 1.34.18 — 2026-10-23 — Rimozione di un file dalla coda anche durante l'elaborazione; niente doppioni del file in lavorazione

- **Rimuovi dalla coda:** tasto Canc o menu contestuale ("Rimuovi dalla coda") sulla riga selezionata, anche mentre la coda lavora. Vale per i file ancora in attesa; quello in
  elaborazione o gia' finito resta (il log dice di usare Stop). Il menu agisce sulle righe selezionate all'apertura. La percentuale e l'intestazione "File N/totale" si
  riallineano al nuovo totale (`ProcessingWorker.note_removed`), cosi' la barra arriva al 100%.
- **Bug corretto:** lo stesso file si poteva riaccodare mentre era in lavorazione (il worker lo toglie dalla lista d'attesa appena lo prende) e veniva rifatto da capo,
  sovrascrivendo il risultato. Ora `QueueService.is_active()` vede le righe 'in attesa' e 'in lavorazione' dello stesso percorso (confronto normalizzato: `/` e `\` sono lo
  stesso file) in tutti i punti da cui si aggiunge: Aggiungi file/cartella, trascinamento e Library Scanner. I job OCR dello stesso video non contano, e un file completato si puo'
  ancora riaccodare.

## 1.34.17 — 2026-10-22 — Rilevamento GPU multi-vendor (Windows e Linux)

- **`utils/gpu_detect.py`** (nuovo, solo libreria standard, non inizializza mai CUDA): rileva le GPU NVIDIA, AMD e Intel con piu' fonti e ripiego —
  `nvidia-smi` (nel PATH e nei percorsi noti di Windows) e NVML via ctypes; sysfs, `rocm-smi` e `/dev/kfd` su Linux; registro di Windows (VRAM a 64 bit);
  `lspci`; `vulkaninfo` (i device software come llvmpipe non contano). Restituisce nome, VRAM totale/libera, driver, integrata o no, PCI id, e i backend
  disponibili (cuda, rocm, vulkan) con un backend consigliato (cuda / rocm / vulkan / cpu). Riconosce WSL. Timeout per ogni fonte, nessuna finestra di console,
  nessuna eccezione verso il chiamante, deduplicazione tra fonti; un errore momentaneo non resta in cache. Variabili per prove e assistenza:
  `TP_GPU_DETECT=off`, `TP_GPU_FORCE_BACKEND=cuda|rocm|vulkan|cpu`. Da riga di comando: `python utils/gpu_detect.py [--json|--vram|--backend]`.
- **`utils/llm_model_select.py`**: la VRAM per la scelta del Qwen viene dal nuovo modulo; con una GPU NVIDIA il valore e' quello di sempre. Le GPU AMD/Intel
  per ora non contano (il `llama-cpp-python` installato e' la ruota CUDA o CPU): si attiveranno con il backend Vulkan/ROCm.
- Non verificato su hardware AMD/Intel reale, Linux, WSL e macOS (provato su NVIDIA/Windows e con uscite simulate).

## 1.34.16 — 2026-10-21 — Linux: download dei modelli in `install.sh` (NON VERIFICATO su Linux reale)

- **`install.sh`**: nuove opzioni `--with-models` e `--qwen-size=auto|7b|14b`, equivalenti a `-WithModels` / `-QwenSize` di `install.ps1`: scarica il Qwen2.5 (14B con GPU da 12 GB o piu', 7B con GPU piu' piccola o `--no-gpu`) e il NLLB fine-tuned da Hugging Face. Provato solo con `bash -n` e con `uname` finto.

## 1.34.15 — 2026-10-21 — Qwen 7B come ripiego automatico per le GPU piccole

- **Scelta del modello** (`utils/llm_model_select.py`, `Config.resolve_llm_model`): quando il percorso del Qwen (glossario per-show e serbatoio L3) non e' impostato,
  l'app sceglie da sola in `models/` il Qwen2.5-14B con GPU da 12 GB o piu', il 7B tra 6 e 12 GB o se manca il 14B, con i layer su GPU calcolati dalla VRAM (offload parziale
  sotto soglia). Senza GPU il canale Qwen del glossario non si accende da solo (su CPU richiederebbe ore). **Con un percorso impostato e il file presente, il comportamento e' identico a prima.**
  Un errore momentaneo di `nvidia-smi` non resta in cache.
- **`install.ps1`**: nuova opzione `-QwenSize auto|7b|14b`; con `-WithModels` e `auto` scarica il 14B (3 file) con GPU da 12 GB o piu' e il 7B (2 file, ~4,7 GB) con GPU piu' piccola o `-NoGpu`.
- Misure (Grey's S22 e Veronica Mars, riferimento = sottotitolo professionale): glossario corretto nel 90,2% dei casi col 14B e nel 67,7% col 7B (7B 2x piu' veloce, meta' VRAM); sul testo finale righe con errore grave 9,8% (14B) contro 10,4% (7B). Per questo il 14B resta il predefinito e il 7B e' solo il ripiego.

## 1.34.14 — 2026-10-21 — Licenze e contenuti di terze parti

- **`utils/tmdb_client.py`**: tolta la chiave TMDB che era scritta nel codice (pubblica nel repo). La chiave si legge da `tmdb_api.txt` o dalla variabile `TMDB_API_KEY`;
  senza chiave le funzioni TMDB (locandine, ricerche) restano disattivate e il log lo dice. Chi aveva `tmdb_api.txt` non nota differenze.
- **`LICENSE`** (MIT, codice originale) e **`NOTICE.md`** (componenti di terze parti con le loro licenze: tokenizer NLLB CC-BY-NC, vobsub MIT, pgsreader senza licenza upstream, font OFL).
- Rimossi dal repo i file di prova di `core/vendor/pgsreader/tests/` (un fotogramma PGS di un film e un foglio di calcolo): non erano usati dall'app.

## 1.34.13 — 2026-10-20 — Linux, fase 3: installer, percorsi del Library Scanner, notifiche (NON VERIFICATO su Linux reale)

- **`install.sh` / `run.sh`** (nuovi): installer e lanciatore per Linux. Riconoscono apt, dnf, pacman o zypper e propongono (con `sudo`, solo su richiesta) i pacchetti di sistema;
  se la distribuzione e' sconosciuta stampano l'elenco da installare a mano. Python 3.11 (provato) o 3.12 (ruote disponibili per tutti i pin, non verificato a runtime).
  `--no-gpu` installa le ruote CPU di torch e llama-cpp-python. Mai eseguiti su una macchina Linux: provati solo con `bash -n` e con un `uname` finto.
- **Library Scanner**: nuova impostazione `library_scanner_path_map` ("Cartelle montate", visibile solo fuori da Windows): una regola per riga `<percorso del server>=<cartella montata>`.
  I file entrano in coda e vanno all'OCR con il percorso locale; le chiavi di riga e le chiamate all'API del server restano quelle del server. Vuota = comportamento invariato (Windows).
- **`scripts_manutenzione/selfcheck_env.py`**: portabile (Python 3.11/3.12 su Linux, niente controlli di Visual C++ o scoop, percorso della config con `os.path.join`); su Windows stampa le stesse righe.
- **`core/queue_runner.py`**: notifica di fine coda con `notify-send` su Linux (senza il programma non fa nulla).
- **`requirements-canary.txt`**: `pywin32` solo su Windows. Nuovo `.gitattributes` (`*.sh`, `*.tpl`, `*.qss` con fine riga LF).
- Verificato da questo PC: tutti i pin di `requirements.txt` hanno una ruota Linux per cp311, cp312 e cp313 (o sono Python puro/sorgente); `llama-cpp-python` 0.3.34 ha ruote Linux CPU e CUDA.

## 1.34.12 — 2026-10-20 — Installazione su PC senza GPU e programmi esterni fuori dal PATH

- **Programmi esterni** (`utils/platform_compat.py::find_tool`): Tesseract, mkvextract e mkvmerge si trovano anche se winget li ha messi in `Program Files` senza aggiungerli al PATH
  (ordine: Impostazioni, PATH, cartelle standard, shim di scoop). Con il programma nel PATH il comportamento e' identico. Usata da OCR PGS/VOBSUB, dal mux (`pipeline.py`) e da `selfcheck_env.py`.
- **`install.ps1` con `-NoGpu`**: installa torch/torchaudio CPU (~250 MB invece di ~2,9 GB della +cu126) e li toglie dal file dei requisiti usato da pip, che altrimenti li rimpiazzerebbe.
- **`utils/config.py`**: indirizzo predefinito del Library Scanner corretto (`192.168.1.12:6680`, era `.18`): su un PC nuovo partiva verso il server sbagliato.
- Provato su PC pulito senza GPU (Windows 11): installazione, idempotenza (33 s), GUI e selfcheck.

## 1.34.11 — 2026-10-20 — Installer: ruota CPU di llama-cpp-python con -NoGpu

- **`install.ps1`**: con `-NoGpu` il venv principale installa, PRIMA di `requirements.txt`, la ruota CPU di `llama-cpp-python` (stessa versione del pin, indice
  `whl/cpu`, `--force-reinstall --no-deps`). Trovata nella prova su PC pulito senza GPU: la ruota CUDA non carica `llama.dll` senza `nvcuda.dll` (driver NVIDIA),
  quindi correzione del genere, glossario e Qwen GGUF non partivano. La ruota CPU pesa ~7 MB invece di 536 MB. Se la versione non si legge dal pin o l'indice non risponde,
  avvisa e prosegue. Limite noto: un venv creato con `-NoGpu` e poi rilanciato senza resta con la ruota CPU (si ripristina reinstallando `llama_cpp_python` dall'indice cu124).

## 1.34.10 — 2026-10-20 — Installer: lingue di Tesseract automatiche

- **`install.ps1`**: con `-InstallSystemDeps`, se Tesseract non ha `ita`/`eng` scarica da solo `ita.traineddata` e `eng.traineddata` (tessdata_best) nella
  cartella tessdata che Tesseract stesso dichiara; se la cartella e' di sistema (Program Files) rilancia la sola copia con UAC. Controlla la dimensione dei file,
  avvisa se Tesseract non e' nel PATH e toglie la voce dai prerequisiti mancanti solo a lingue presenti. Con `-CheckOnly` non fa nulla.

## 1.34.9 — 2026-10-20 — Compatibilita' Linux, fase 3a: percorsi Windows nella config

- **`utils/config.py` (`Config.get`)**: fuori da Windows, un valore salvato che e' un percorso con lettera di unita' (`V:\...`, tipico di una
  config copiata da Windows) viene ignorato e si usa il valore predefinito. Su Windows il comportamento e' identico a prima.
- **`utils/platform_compat.py`**: nuova `is_foreign_windows_path()`.

## 1.34.8 — 2026-10-20 — Compatibilita' Linux, fase 1b: anche il motore del glossario

- **`glossary_engine/glossary_qwen_bridge.py`**: l'interprete del venv principale e il flag di console passano da `utils/platform_compat.py`
  (caricato dal file, perche' questo modulo gira anche nel venv_glossary dove `import utils` non e' possibile). Su Windows i valori sono
  identici a prima. Il resto di `glossary_engine/` era gia' protetto per sistema operativo.

## 1.34.7 — 2026-10-20 — Compatibilita' Linux, fase 1: i punti Windows noti passano dall'helper

- **Percorsi dei venv e flag di console** (`core/engines/canary_engine.py`, `core/gender_corrector_v2.py`, `core/speaker_gender.py`,
  `gui/glossary_worker.py`, `gui/translation_model_dialog.py`, `main.py`): usano `utils/platform_compat.py` (`venv_python()`,
  `no_window_flags()`). Su Windows i valori sono identici a prima (`Scripts/python.exe`, `0x08000000`).
- **Annullamento del glossario Qwen** (`gui/glossary_worker.py`): l'albero del sottoprocesso GPU si uccide con `kill_tree()` (psutil)
  al posto di `taskkill`, quindi funziona anche fuori da Windows. Non bloccante come prima.
- Verificato: 260 test, banco `c7_gender` e `c13_eta_canary` OK, bugcheck senza difetti. Restano da migrare solo le docstring d'uso e
  il modulo `glossary_engine/`.

## 1.34.6 — 2026-10-20 — Compatibilita' Linux, fase 0: helper per le differenze tra sistemi operativi

- **`utils/platform_compat.py`** (nuovo, non ancora usato dal codice): `venv_python()`, `no_window_flags()`, `kill_tree()`, `IS_WINDOWS`.
  Su Windows restituiscono esattamente i valori che il codice oggi cabla (`Scripts/python.exe`, `0x08000000`); su Linux gli
  equivalenti POSIX. Nessun cambio di comportamento. Le fasi successive sposteranno i punti Windows-dipendenti noti sull'helper.

## 1.34.5 — 2026-10-20 — Log Sintetico acceso all'apertura

- **Log Sintetico** e' ora acceso di default all'apertura dell'app (e quindi la card "Pipeline in corso" e' attiva). Si puo' spegnere per
  la sessione dalla casella; la scelta non e' persistita.

## 1.34.4 — 2026-10-20 — Card dei passi: niente ETA stantia a fine passo

- Quando il motore chiude la barra (100%) l'ETA del passo viene azzerata: prima restava l'ultima ricevuta (es. "~15s" accanto a 100%).

## 1.34.3 — 2026-10-20 — Interfaccia: pulsanti Avvia e Ferma piu' bassi

- **Avvia / Ferma**: padding verticale da 12 a 6 px e font da 10,5 a 10 pt (circa 12 px in meno di altezza) per lasciare piu' spazio
  alla lista della coda e al Library Scanner.

## 1.34.2 — 2026-10-20 — Card dei passi: trascrizione e traduzione non arrivano a 100% prima del tempo

- **Trascrizione** e **Traduzione** restano a 99% nella card finche' non inizia il passo successivo: dopo il 100% del motore c'e'
  ancora lavoro (allineamento, caricamento e lavoro del diarizzatore, punteggiatura; recupero dei blocchi da rifare senza mascheramento).
  Il passo diventa "fatto" solo a quel punto. Solo la card (`gui/services/step_plan.py`): nessun cambio alla pipeline ne' ai testi del log.

## 1.34.1 — 2026-10-19 — ETA della correzione di genere nella card

- **Correzione di genere**: l'evento della barra porta ora `eta_s` (la stessa ETA del suo log, media sui blocchi fatti); la card dei passi
  la mostra subito, senza le soglie del 3% / 20 s del ricalcolo dalle percentuali.

## 1.34.0 — 2026-10-19 — ETA dei motori nella card dei passi, barra reale per Demucs

- **ETA del motore negli eventi `bar`** (`eta_s`): trascrizione (Canary, Qwen3, Whisper), Demucs (percorso a chunk) e traduzione
  NLLB / traduttori via API. La card "Pipeline in corso" la mostra subito, uguale a quella del log, senza le soglie del 3% / 20 s
  del ricalcolo dalle percentuali. NLLB e API hanno ora anche il suffisso ETA nella riga di log.
- **Demucs, percorso standard (file 5-60 min)**: barra reale con percentuale ed ETA (prima nessuna misura: barra indeterminata).
  `apply_model(progress=True)` itera i segmenti con `tqdm`: durante la chiamata il suo `tqdm` e' sostituito da un iteratore che riporta
  l'avanzamento (ripristinato sempre; con controllo di annullamento e guardia se la libreria cambia).
- `EtaEstimator.eta_seconds()`; nuovi strumenti di prova in `ui_bench/tools` (fuori dal repo).

## 1.33.4 — 2026-10-18 — Interfaccia: ETA della traduzione nella card dei passi

- **Card "Pipeline in corso"**: il traduttore LLM porta nell'evento della barra la propria ETA (`eta_s`, la stessa del suo log),
  e la card la mostra subito, senza le soglie del 3% / 20 s del ricalcolo dalle percentuali (che su file brevi non
  mostrava mai nulla). Senza `eta_s` (altri motori) resta il ricalcolo.

## 1.33.3 — 2026-10-18 — Interfaccia: riga di stato dello scanner unica

- **Library Scanner**: l'avanzamento OCR e "N senza sub / N totali" condividono ora UNA riga (si alternano: durante l'OCR si vede
  l'avanzamento). Prima la riga dell'OCR era sempre riservata, anche vuota: circa 28 px in piu' per la lista.

## 1.33.2 — 2026-10-18 — Interfaccia: pulsanti dello scanner piu' bassi

- **Library Scanner**: "Importa Tutti i Filtrati" e "Superpower" piu' bassi (padding 1 px, altezza minima 14 px, circa 8 px in meno)
  per lasciare piu' spazio alla lista.

## 1.33.1 — 2026-10-18 — Interfaccia: la card dei passi resta a fine elaborazione

- **"Pipeline in corso"**: a fine coda la card resta visibile con lo stato finale dell'ultimo file (tutti "fatto", oppure
  errore/interrotto) invece di sparire; quando parte il file successivo si rigenera da capo.

## 1.33.0 — 2026-10-18 — Interfaccia: anteprima dei passi con "Log Sintetico"

- **"Pipeline in corso"**: con "Log Sintetico" spuntato, durante l'elaborazione compare tra le tessere e il log un elenco dei
  passi del file (Estrazione audio, Separazione voce, Trascrizione, Traduzione, Correzione di genere, Salvataggio .srt,
  Upload OpenSubtitles, Muxa nel video se attivo). Ogni passo e' "fatto" (spunta), in corso (percentuale, ETA e barra),
  in attesa (numero d'ordine), "disattivato" (interruttore spento) o "non necessario" (lo decide il file: sottotitoli embedded,
  lingua gia' finale, IMDb mancante). Il contatore n/m conta i passi fatti sui non esclusi; il percorso OCR ha i suoi passi.
  Con la casella spenta nulla cambia.
- **Barre**: Demucs, trascrizione, traduzione, genere e lettura OCR hanno una percentuale reale; salvataggio e upload una barra
  stimata animata; gli altri passi una barra indeterminata. Con la card aperta le righe di barra escono dal log.
- **Eventi della pipeline** (additivi): `step save|upload|mux` (start/done/skip, con l'esito reale: un upload o un mux falliti
  non risultano "fatto") e `bar ocr`. `FileProgress` e la barra del file non cambiano.
- **ETA di Demucs** nella riga di log (percorso a chunk, file lunghi o con memoria GPU scarsa).
- Nuovo `gui/services/step_plan.py` (logica pura, testata) e `gui/pipeline_steps_widget.py` (vista).

## 1.32.3 — 2026-10-18 — Interfaccia: note minori del bugcheck

- **Contrasto dei badge dello scanner**: sfondi piu' scuri per avere testo bianco >= 4,7:1 (nuovo token `danger_deep`).
- **Badge del formato** (PGS/VOB/ASS/MIX): non piu' tagliati dall'altezza minima globale dei bottoni ne' dal padding.
- **Focus**: i bottoni non prendono piu' il focus al clic, restano raggiungibili con Tab.
- **Token**: tolti 16 token mai usati.

## 1.32.2 — 2026-10-17 — Interfaccia: intestazioni compatte e spazio condiviso con lo scanner

- **Intestazioni delle card** (Opzioni job, Library Scanner e le altre card collassabili) piu' basse: margini 4 px, titolo 10 pt,
  chevron 18 px, tasto refresh dello scanner 20 px (~15 px in piu' per la coda).
- **Spazio verticale**: con il Library Scanner aperto, coda e tabella dello scanner si dividono lo spazio libero (2 : 3);
  chiuso, tutto lo spazio resta alla coda.

## 1.32.1 — 2026-10-17 — Interfaccia: spazio verticale e numeri tagliati

- **Spinbox**: le cifre non vengono piu' tagliate (padding verticale 4 px, altezza minima 22 px).
- **Library Scanner**: filtri Tipo/Giorni/Formato su un'unica riga (le tendine si stringono senza allargare il pannello),
  barra di ricerca, filtri, bottoni e righe della tabella piu' compatti, tolto il limite di 250 px all'altezza della tabella.
- **Opzioni job**: caselle piu' piccole (9 pt, indicatore 14 px) in una griglia 2x2 allineata; testi accorciati
  ("Genere avanzato", "Spegni al termine") con tooltip tradotti (it/en).

## 1.32.0 — 2026-10-17 — Interfaccia: abbellimento (contrasto, icone, barra di avanzamento, dialoghi)

- **Contrasto e bordi**: testo secondario e disabilitato a livello WCAG AA (nuovo token `fg_disabled`; `fg_4` 4,67:1 su `bg_2`),
  bordi piu' morbidi, stati hover/focus/pressed con anello accent, raggi coerenti (card 12, controlli 8, chip 6).
- **Emoji doppie tolte** da 30 stringhe di bottoni, titoli e label (it/en): restano le icone SVG; i log e le pillole di stato
  non cambiano.
- **Barra del titolo**: pillola di stato a 26 px centrata; l'icona di Strumenti e' una chiave inglese (l'ingranaggio resta
  Impostazioni).
- **Barra di avanzamento** a capsula da 12 px con la percentuale in una label separata a destra (prima toccava il bordo).
- **Controlli**: frecce di combo/spinbox, spunte e radio ora SVG (`assets/icons/*.svg`, percorso risolto a runtime);
  groupbox con titolo dentro la card; tolti i riquadri scuri dentro card, campi, righe e tabelle.
- **Dialoghi** allineati alla palette (via il blu `rgba(0,120,212)` e i fondi navy): Sync, Profilo, OCR, OpenSubtitles, Scanner.
  Numeri delle statistiche in JetBrains Mono.
- **Difetti preesistenti corretti**: pulsante "Mostra" della API key tagliato, bottoni dello storico tagliati, campi
  sovrapposti nella pagina OpenSubtitles a 840x620 (ora scorre in una `QScrollArea` senza fermata di Tab).
- **Dal bugcheck Opus**: il pulsante "+" dello scanner non mostra piu' icona e "✓" insieme dopo l'import; `fg_4` portato sopra AA.
- **`gui/theme.qss`** non e' piu' nel repo: e' un file generato che contiene il percorso assoluto delle icone di questa
  macchina; l'app usa `build_qss()` dal template (`python -m gui.theme --write` lo rigenera in locale).
- **Verifica**: 216 test (golden del log rigenerati: la differenza e' solo il colore del testo secondario, verificata dal
  bugcheck), 101 screenshot offscreen, smoke senza avvisi; montaggi prima/dopo approvati dall'utente.
- **Note minori note**: contrasto del bianco su rosso/arancione dei badge dello scanner (3,3-4,3:1) e `min-height` globale dei
  pulsanti da rivedere in una fase successiva.

## 1.31.1 — 2026-10-17 — Interfaccia: logica separata dalla vista (`gui/services/`)

- **Servizi** (`gui/services/`, senza import di QtWidgets): `QueueService` (coda, stato dei job, avvio/arresto, statistiche,
  spegnimento, scansione cartelle e dimensioni), `MetadataService` (locandine e titoli), `JobOptionsService`, `SettingsService`,
  `LogFilter` (decisioni sul log), `formatting`, `job_model` (`JobRecord`). `main_window.py` passa da 1570 a 1489 righe ed e'
  solo vista; restano alias di compatibilita' per scanner, glossario e sync.
- **Invariante della coda** (v3.5): lista e `QMutex` creati una sola volta e condivisi con `ProcessingWorker`; riordino sul posto.
- **Bug corretto**: premendo Avvia con glossario o sincronizzazione attivi veniva sollevato `UnboundLocalError` (import locale di
  `QMessageBox` in `start_processing`); ora compare l'avviso corretto.
- **Pulizia**: tolti `_on_transcription_model_line` (codice morto), alias inutilizzati e import non usati.
- **Verifica** (banco fuori dal repo, `ui_bench/`): 216 test (worker con runner finto, coda, Stop con albero di processi, spegnimento,
  filtro del log su 3.264 righe reali, impostazioni, metadati); 100 screenshot identici al riferimento; pipeline reale senza GPU
  (clip con italiano embedded) completata dalla `MainWindow` con il nuovo servizio; bugcheck Opus: pulito (note minori sistemate).
- **Non incluso**: compatibilita' Linux del `core/` (resta da fare).

## 1.31.0 — 2026-10-17 — Interfaccia: token di design e stili centralizzati (nessun cambio visivo)

- **Token di design** (`gui/design_tokens.py`, `T`): palette, alpha, sezioni, font, raggi e spaziature in un solo posto.
- **Tema generato** (`gui/theme.qss.tpl` + `gui/theme.py::build_qss`; `python -m gui.theme --check|--write`): `theme.qss` e'
  ora un file generato dal template; main.py applica `build_qss()` (con ripiego su `theme.qss`). Nuova sezione "Ruoli (v1.31)"
  con regole a proprieta' dinamica (`set_role(widget, 'muted'|'h2'|...)`).
- **Componenti** (`gui/components.py`): `RoundedLabel` (prima duplicata), `section_qss`, piu' `Card`, `Badge`, `StatusPill`,
  `Section` pronti per le prossime schermate. QSS dei dialoghi grandi in `gui/styles/*.qss.tpl`.
- **Pulizia**: dai file `gui/*.py` tolti ~145 colori `#rrggbb` letterali e ~45 `setStyleSheet` sparsi (52 -> 6 solo in
  `translation_model_dialog.py`); restano pochi stili con colori calcolati a runtime.
- **Verifica**: banco visivo `ui_bench/` (fuori dal repo, 100 screenshot offscreen riproducibili byte per byte): 100/100
  identici al riferimento prima del refactoring, 0 avvisi Qt di stile; bugcheck Opus: pulito (3 note minori sistemate).
- **Prossimo passo**: separare la logica dalla vista in `main_window.py` (servizi `gui/services/`).

## 1.30.13 — 2026-10-17 — Upload OpenSubtitles degli anime: ID dell'episodio per titolo

- **Causa** (verificata sulla pagina OpenSubtitles di Last Exile): per gli anime TMDB non ha l'IMDb ID dell'episodio, quindi
  l'upload ripiegava sull'ID della serie e il sottotitolo finiva sulla serie, senza stagione ne' episodio ("uncategorized").
  Le serie normali non erano toccate (TMDB ha l'ID episodio).
- **Ripiego per titolo** (`tmdb_client._get_episode_imdb_id_by_title`, solo se TMDB non ha l'ID): il nome TMDB dell'episodio
  (en-US, normalizzato) deve coincidere ESATTAMENTE e in modo UNIVOCO con un episodio OMDb della stessa serie; la numerazione
  stagioni di IMDb si ignora (per gli anime accorpa serie diverse). Titoli generici ("Episode 11", numerici, < 4 caratteri)
  scartati. Last Exile: 18 episodi su 26 risolti, nessun ID duplicato; gli altri restano sull'ID di serie.
- **OMDb** (`IMDbClient.get_series_episodes`): elenco solo se completo (qualunque risposta anomala -> nessun elenco),
  salvato nella cache su disco per 14 giorni (ogni file gira in un processo a parte; quota 1000/giorno).
- **Verifica**: percorso reale `search_tv` (Last Exile S1E8 -> ID episodio, S1E1 resta sulla serie, Grey's invariato);
  bugcheck Opus: 1 difetto alto (titoli generici) e 2 medi corretti, ricontrollo pulito.
- **Non risolto**: le serie senza schede episodio su OpenSubtitles (Last Exile 2003 non ne ha) restano sulla serie.

## 1.30.12 — 2026-10-16 — Sottotitoli con blocchi fuori ordine temporale

- **Causa**: 14 dei 654 `.it.srt` nostri nelle librerie (Petra, Hadestown, Be Kind Rewind...) hanno blocchi con tempo di
  inizio non crescente (qualche blocco per file). Il contenitore MKV li tiene ordinati per tempo, quindi la verifica del
  mux ("Muxa nel video", confronto blocco per blocco) li rifiutava: il video restava senza traccia.
- **Cleaner**: `SubtitleCleaner` ordina i blocchi per tempo di inizio (ordinamento stabile, solo se ci sono blocchi fuori
  ordine; log "N sottotitoli fuori ordine temporale: riordinati") prima di `fix_overlaps` e di `renumber`. Su 60 sidecar
  gia' ordinati l'output e' identico byte per byte; sui 14 disordinati l'output e' ordinato.
- **Verifica del mux**: confronta le battute come insieme (il contenuto resta verificato, l'ordine no).
- **Limite noto**: un duplicato fuori ordine che prima veniva scartato (non accorciabile) ora puo' restare come battuta
  ripetuta; sui 14 file reali: 138 -> 140 coppie consecutive uguali. Non si aggiunge una regola ad hoc.
- **Verifica**: A/B vecchio/nuovo cleaner su 74 sidecar reali, prova di mux con sidecar disordinato; bugcheck Opus: 1 difetto
  medio-basso (il limite sopra, accettato). Origine del disordine nei dati dell'ASR: da verificare con il banco.

## 1.30.11 — 2026-10-16 — "Muxa nel video" anche su MKV con copertine mjpeg

- **Mux/sostituzione traccia con ripiego su mkvmerge** (`_remux_with_sidecar`): `ffmpeg -map 0` falliva sugli MKV con flussi
  mjpeg (copertine/allegati, "bits 51 is invalid"); ora, se ffmpeg non produce il file, si ripiega su `mkvmerge`
  (copia allegati e capitoli). Le verifiche restano quelle di prima e una in piu' (dal bugcheck): le tracce sottotitoli
  rimaste devono essere esattamente le altre, stesso ordine, codec e lingua, cosi' una traccia tolta al posto di un'altra
  (ID mkvmerge non allineato all'indice ffprobe) non passa. Il log d'errore indica quale strumento e' fallito e riporta
  anche stdout (mkvmerge scrive li' gli errori).
- **Mojibake residuo** di `subtitle_cleaner.py` (righe 18 e 533) corretto.
- **Banco** (fuori repo): nuovi casi `c12_mjpeg_mux`, `c13_eta_canary`/`c13_eta_whisper` (clip da 50 min: l'ETA compare dopo 20 s,
  prima le clip erano troppo brevi; confermato con Canary e Whisper), `c14_ocr_fail_audio` (OCR bitmap fallito con ripiego
  sull'audio); il banco non dipende piu' dall'impostazione "Muxa nel video" del config utente.
- **Verifica**: banco su clip reali, tutti i casi OK; bugcheck Opus senza difetti bloccanti (2 punti bassi corretti).

## 1.30.10 — 2026-10-16 — Mojibake nel sorgente, `output` negli episodi OCR, OCR multi-traccia in sidecar

- **Mojibake nel sorgente** (231 righe in 8 file: `core/pipeline.py`, `core/subtitle_cleaner.py`, `core/translator.py`,
  `gui/workers.py`, `utils/config.py`, `utils/profile_dialog.py`, `utils/subtitle_uploader_interface.py`, `utils/tmdb_client.py`)
  e nel blocco autotest di `core/pipeline.py`: emoji e accenti nei log/effetti (queue_runner, ❌/⚠ colorati in GUI) ora corretti.
  Restano 2 righe di `subtitle_cleaner.py` (18 e 533) con un byte perso, non convertibili.
- **`output` negli episodi OCR**: `last_output_path` non veniva impostato nel ramo OCR, quindi `queue_status.json` riportava
  `output: null`; ora punta al `.it.srt`.
- **OCR multi-traccia in pipeline = sempre sidecar** (decisione 09/10): con piu' tracce PGS/VobSub italiane `_writeback_mux_multi`
  incorporava gli SRT nell'MKV togliendo i bitmap e senza `.it.srt`. Ora, con `ocr_writeback=sidecar`, scrive UN sidecar dalla
  traccia completa (non forced) italiana con piu' testo e lascia l'MKV intatto. Modalita' `mux` (default GUI/Scanner) invariata.
  Il bugcheck ha trovato che la scelta ignorava la lingua riconosciuta (rischio di `.en.srt` e job "completato" senza italiano):
  ora si preferiscono le tracce riconosciute `it`.
- **Verifica**: banco su clip reali 13/13 OK (nuovi `c8`–`c11` multi-traccia PGS/VobSub, controllo `output` su c4/c6); picco
  memoria 37,8 GB di commit, minima RAM libera 9,1 GB; bugcheck Opus: difetto medio corretto, resto pulito.
- **Noto, non corretto**: "Muxa nel video" (`_remux_with_sidecar`) fallisce su MKV con flussi mjpeg (copertine/allegati).

## 1.30.9 — 2026-10-15 — `process()` spezzato: anche STEP 0/1/1b (solo spostamento di codice)

- Selezione dei sottotitoli embedded e OCR dei bitmap spostati in `_select_subtitles_step`, che restituisce
  `(subtitle_path, source_language_639_2, ocr_done)`; `process()` e' ora un orchestratore di ~115 righe (era 970).
  Stesso log, stessi eventi, stesse eccezioni.
- **Verifica**: stringhe costanti identiche; banco 9/9 OK con tracce uguali al riferimento 1.30.8 (salvo il conteggio dei
  blocchi non tradotti in `c3b_force_audio`, ASR non deterministico); bugcheck Opus senza difetti.

## 1.30.8 — 2026-10-15 — `process()` spezzato (solo spostamento di codice)

- **Refactor senza cambi di comportamento**: `ProcessingPipeline.process()` (970 righe) cede i blocchi a metodi privati:
  `_transcribe_step` (STEP 2-4.5), `_clean_subtitles_step` (cleanup anticipato + 5), `_release_asr_models_before_translation`
  (5.5), `_translate_step` (6), `_gender_correction_step` (6.5), `_finalize_output` (7-9). Stesso log, stessi eventi, stesse
  eccezioni; il `try/finally` con `_cleanup` resta in `process()`. Resta in `process()` la selezione dei sottotitoli (STEP 0/1/1b).
- **Verifica**: stringhe costanti e chiamate `_log`/`_ev` identiche prima/dopo; banco su clip reali 9/9 OK con tracce
  (eventi non-barra e righe-marcatore) uguali al riferimento 1.30.7 (unica differenza: il conteggio dei blocchi non tradotti
  in `c3b_force_audio`, trascrizione non deterministica); bugcheck Opus senza difetti. Il banco ha intercettato un `return`
  mancante introdotto durante il lavoro (corretto prima del rilascio).

## 1.30.7 — 2026-10-15 — Eventi strutturati dalla pipeline per l'avanzamento (accanto al log, non al suo posto)

- **Eventi strutturati (`utils/events.py`, nuovo)**: la pipeline dichiara direttamente cosa sta facendo (fase, motore ASR,
  ramo OCR con o senza traduzione, lingua dell'audio, sottotitoli embedded scelti, fasi saltate, percentuale delle barre di
  Demucs/trascrizione/traduzione/genere) invece di lasciarlo ricavare dal testo del log. Una riga su stdout con prefisso
  `@@TPEV@@ ` e un JSON; il genitore (GUI e coda headless) la toglie dal log e la passa a `FileProgress.feed_event`.
  **Opt-in**: il figlio li emette solo se il genitore imposta `TP_EVENTS=1`; senza sink `emit` non fa nulla (Library Scanner,
  chiamate in-process). Il sink si installa solo quando `pipeline_cli`/`gender_corrector_cli` sono il programma, non quando
  vengono importati. Il testo visibile del log e' identico.
- **`FileProgress` ibrido**: testo ed eventi aggiornano lo stesso stato (decisioni idempotenti); per le barre interne, dopo il
  primo evento `bar` di un gruppo il testo di quel gruppo non conta piu'. Il parsing del testo resta come ripiego.
- **Correzioni dal bugcheck**: anche le righe finali "100%" emettono l'evento (senza, la barra restava a ~90-97% fino alla fase
  successiva); un evento anomalo nel relay del correttore di genere non puo' piu' interrompere il ciclo.
- **Validazione**: banco su clip reali, 9 casi su 9 (nuovi `c3b_force_audio`, `c7_gender`); il banco verifica che gli eventi
  arrivino davvero e che la sola via eventi dia la stessa percentuale finale del solo testo (+-8). Test su CPU in
  `pipeline_bench/test_events.py` (fuori dal repo). Non esercitato: eventi dal processo del correttore di genere (la v2 non
  stampa barre, quindi non c'e' emettitore) e il traduttore con Canary/Whisper batched.

## 1.30.6 — 2026-10-15 — Sostituzione del bitmap italiano con testo straniero; fix OCR con lingua corretta dal contenuto

- **Bitmap (PGS/VobSub) dichiarato italiano ma con testo di un'altra lingua**: dopo OCR e traduzione la traccia errata viene
  sostituita nell'MKV dal sidecar italiano (come gia' avveniva per le tracce testo), dopo l'upload. Si sostituisce solo la traccia
  che l'OCR ha trattato come completa e di cui ha provato il testo non italiano; il flag forced del contenitore (anomalo, ignorato
  dalla selezione) non la protegge. Sidecar sempre mantenuto; se la sostituzione e' tentata, riuscita o no, non si aggiunge anche la
  traccia dell'opzione "Muxa nel video". Interruttore: `replace_mislabeled_italian_track` (default acceso).
- **Bug corretto (`core/pgs_ocr.py`, `core/vobsub_ocr.py`)**: un `import` locale di `available_tesseract_langs` la rendeva variabile
  locale e dava `UnboundLocalError` ogni volta che la lingua del contenuto veniva corretta dopo l'OCR o il tag era `und`: l'OCR
  falliva e la pipeline ripiegava in silenzio sulla trascrizione da audio. Rimosso l'import locale (c'e' gia' quello di modulo).
- **Validazione**: banco su clip reali, nuovo caso `c6_pgs_mislabel` (PGS inglese dichiarato `ita` → una sola traccia `subrip` `ita`,
  nessun ripiego audio) piu' `c4_pgs_ocr_mux` invariato. Fix VobSub: stessa correzione, solo compilata.

## 1.30.5 — 2026-10-15 — Coda headless con file di stato; ETA arrotondato; banco di validazione

- **Coda headless (`core/queue_runner.py`, nuovo)**: esegue i file uno alla volta con lo stesso `core.pipeline_cli` della GUI e
  scrive a ogni evento `~/.transcriberpro/queue_status.json` (file corrente, fase, percentuale, ETA del file e della coda,
  completati/falliti, un log per file), con la stessa percentuale della GUI (`FileProgress`). Ctrl+C uccide l'intero albero dei
  processi e segna la coda `cancelled`; ogni errore su un file lo segna fallito e la coda prosegue; lock tra due code; avviso se la GUI
  e' aperta; `--skip-existing`, `--recursive`, `--notify` (notifica di Windows). Uso: `python -m core.queue_runner "<cartella>"`.
- **ETA della trascrizione (`utils/eta.py`)**: il suffisso `~Nm` troncava i minuti e sottostimava sempre (errore medio 15% sul log
  reale di Bake Off, fino a -39% nel finale); ora arrotonda al minuto piu' vicino.
- **Validazione**: banco su clip reali (fuori dal repo) che copre selezione per contenuto, sostituzione della traccia segnata come
  italiana, guardia contro il file riscritto, opzione "Muxa nel video", OCR+traduzione con barre, ETA e avanzamento: 6 casi su 6.

## 1.30.4.15.10.26 — 2026-10-15 — Guardia contro la riscrittura del video durante il job

- **File cambiato da un altro programma (`core/pipeline.py`, `_video_unchanged`)**: il remux in place (sostituzione della traccia segnata
  come italiana, opzione "Muxa nel video") finisce con `temp.replace(video)`. Se un altro programma (es. FileFlows) riscrive il file mentre
  la pipeline lavora, la sostituzione ne cancellerebbe in silenzio il risultato, e l'upload avrebbe l'hash di un file non piu' esistente
  (visto con RahXephon E04, sparito a meta' job). Ora la firma del video (dimensione + data di modifica) si registra a inizio job e si
  ricontrolla prima dell'upload, all'inizio del mux e subito prima di sostituire l'originale: se e' cambiato o sparito non si fa ne'
  upload ne' remux, il video resta intatto, il sidecar si mantiene e il log lo dice. Dopo un mux nostro la firma si aggiorna.
  Con input `.srt` la risoluzione del video non puo' sollevare eccezioni (share offline).

## 1.30.4 — 2026-10-15 — Avanzamento del file proporzionale alla durata reale delle fasi

- **Barra del singolo file (`gui/file_progress.py` nuovo, `gui/workers.py`)**: la percentuale (barra nell'elenco della coda e barra sotto la
  locandina) si muoveva solo sui marcatori di passo con una tabella fissa: la trascrizione (84% di un job solo-trascrizione, misurato)
  aveva la fascia 60->68% e la traduzione (88-99% di un job con traduzione) la fascia 88->93%, quindi la barra restava ferma per ore e
  poi saltava a 100%. Ora ogni fase pesa in proporzione alla durata MISURATA sui log reali (Demucs 1, trascrizione 2,5-6 secondo il
  motore, traduzione 30, genere 1,5), dentro la fase segue la barra interna che la fase stampa ("Trascrizione: [", "Traduzione: [",
  "Progresso:", "Correzione genere: ["; "Warm-up: [" ignorato) e le fasi che non avverranno (traduzione con lingua gia' finale, audio con
  sottotitoli embedded, OCR fallito) escono dal calcolo. Mai 100 (lo mette la GUI a fine file), mai in calo; classe senza Qt e a prova di
  eccezione. Curva misurata sui log reali: Bake Off 17/25/44/67/86/96% a 10/30/50/70/90/100% del tempo, V/H/S 11/29/48/67/87/98%.
- **OCR + traduzione (`core/ocr_auto.py`)**: il traduttore dell'OCR non aveva nessun callback di log: durante la traduzione (~15 min per
  episodio) non stampava barre, warm-up ne' ETA e la barra del file restava ferma. Ora riceve il `log_callback`.
- **Titolo sotto la locandina (`gui/main_window.py`)**: il titolo provvisorio degli anime con solo numero assoluto veniva ricalcolato a
  ogni aggiornamento della barra (fino a ~99 volte per file, con righe di debug); ora al massimo ogni 5 s.

## 1.30.3.15.10.26 — 2026-10-15 — ETA nella barra di trascrizione

- **Tempo rimanente nella fase di trascrizione (`utils/eta.py` nuovo; `qwen3_asr_engine.py`, `canary_engine.py`, `faster_whisper_engine.py`)**:
  la barra "🎙️ Trascrizione" mostra ora ` │ ~12m` / ` │ ~40s`, nello stesso formato della traduzione. La stima usa il ritmo recente
  (ultimo 15% del lavoro, almeno 5 s reali), con ripiego sulla media; non compare prima del 3% di avanzamento e dei primi 20 s.
  Vale per tutti i job che trascrivono (con o senza traduzione successiva).
- **Whisper, percorso a file unico**: `list(segments)` consumava il generatore pigro (cioe' tutta la trascrizione) prima del ciclo con la
  barra, che saltava da 0 a 99% in un istante. Ora il generatore si consuma con barra ed ETA reali; il tempo finale "│ Nm" include la
  trascrizione vera. **Canary**: il cronometro parte a modello caricato (`LOAD_DONE`).

## 1.30.3.14.10.26 — 2026-10-14 — Barre di avanzamento del log di sincronizzazione

- **Log del dialogo Sincronizzazione sottotitoli (`gui/progress_log.py` nuovo, `gui/sync_dialog.py`)**: le barre di avanzamento
  (Demucs, Traduzione, Trascrizione...) comparivano come una riga nuova per ogni aggiornamento (0/23, 1/23, 2/23...). Ora si riscrivono
  sul posto come nel log principale: la barra sostituisce la propria precedente se non e' completa (✅) e la percentuale non scende,
  altrimenti si accoda; una riga intercalata la lascia come ultima riga. Solo estetica.

## 1.30.3 — 2026-10-11 — Opzione job "Muxa nel video"

- **Nuova opzione nella card "Opzioni job" (`gui/job_options_card.py`)**: casella "🎞️ Muxa nel video" sulla stessa riga di "Upload
  OpenSubtitles" (le due caselle non impongono larghezza minima al pannello). Chiave `mux_subtitle_into_video` (default spenta).
  A fine job, dopo l'upload (l'hash OpenSubtitles resta quello del file originale), il sottotitolo creato entra nel MKV come nuova
  traccia con lingua e titolo corretti; **il sidecar resta accanto al video**. La traccia è predefinita solo se il file non ha già un
  sottotitolo predefinito. Vale per traduzione, trascrizione e OCR bitmap; non si aggiunge una copia di una traccia embedded già nella
  lingua finale e non si tocca il file se la sostituzione di una traccia segnata per errore come italiana è stata tentata.
- **Remux comune (`core/pipeline.py`, `_remux_with_sidecar`)**: una sola funzione per aggiungere o sostituire (v. 1.30.2.11.10.26) una
  traccia: file temporaneo `.converting`, verifica (stesse tracce più quella nuova, durata entro 1 s, lingua, battute identiche al
  sidecar) e solo dopo la sostituzione dell'originale; un input `.srt` usa il video vero accanto. Solo MKV.
- **Stop**: i ffmpeg del remux sono annullabili, il file di verifica sta nella cartella temporanea e il worker cancella un eventuale
  `<video>.converting` rimasto dopo lo Stop (che uccide l'albero dei processi).

## 1.30.2.11.10.26 — 2026-10-11 — Traccia italiana errata sostituita dal sidecar

- **Sostituzione della traccia segnata per errore come italiana (`core/pipeline.py`, `_replace_mislabeled_italian_track`)**: in un MKV una
  traccia testo dichiarata `ita` (tag o titolo) conteneva inglese (V/H/S Mixtape). La pipeline la riconosceva dal contenuto, la traduceva e
  scriveva il sidecar `.it.srt`, ma nel file restava una traccia "italiana" in inglese. Ora, dopo l'upload OpenSubtitles (l'hash resta quello
  del file originale), quella traccia viene tolta dall'MKV e al suo posto c'e' il sidecar come `ita` "Italian", con lo stesso flag predefinito;
  **il sidecar resta accanto al video**. Scatta solo se: traccia testo completa (non forced, nemmeno per flag del contenitore), il contenuto
  contraddice la dichiarazione di italiano, il sottotitolo usato deriva proprio da quella traccia, file MKV, traduzione riuscita.
  Verifica prima di sostituire (stesse tracce, durata entro 1 s, ultima traccia `ita`, battute identiche al sidecar); in caso contrario il
  video resta com'era. Non copre i bitmap (PGS/VobSub). Interruttore `replace_mislabeled_italian_track` (default True).
  I ffmpeg interni sono annullabili dallo Stop.

## 1.30.2.10.10.26 — 2026-10-10 — Ordine warm-up / barra di traduzione

- **Barra di traduzione dopo il warm-up (`core/llm_subtitle_translator/translator.py`, `core/translator.py`)**: all'avvio della traduzione
  compariva prima la barra "Traduzione: [░░░░░░░░░░] 0%" e subito sotto le righe "Warm-up: [...]". Ora a schermo c'è prima il warm-up del
  gestore batch e la barra della traduzione parte solo a warm-up concluso (TranslateGemma e NLLB/NLLB fine-tuned). Senza gestore batch
  la barra compare subito come prima; la riga finale ✅ 100% non cambia. Solo estetica: nessuna modifica a batch, qualità o tempi.

## 1.30.2.09.10.26 — 2026-10-09 — Selezione sottotitoli embedded per contenuto, cache dei modelli preservata, OCR sempre in sidecar

- **Lingua di una traccia dal contenuto (`core/subtitle_lang.py`, nuovo)**: normalizzatore unico dei codici lingua (2 e 3 lettere, nomi,
  varianti regionali; un codice ignoto diventa `und`, mai le prime 2 lettere). Prima `it` a 2 lettere non era nella mappa di `pipeline.py`:
  una traccia davvero italiana diventava `und`, veniva instradata su NLLB e "tradotta" italiano→italiano (RahXephon E01). Il titolo della
  traccia completa il tag solo se manca; la lingua si verifica sul testo estratto (parole frequenti it/en/es/fr/de/pt/nl + controllo degli
  alfabeti; ≥40 parole riconosciute, quota ≥65 %, rapporto ≥2,5, verdetto coerente in almeno 2 terzi del file, battute con ♪ escluse) e,
  per i bitmap, sul testo OCR. Se il verdetto contraddice il tag si corregge la lingua (una volta per traccia); se non c'è verdetto non
  cambia nulla. Misurato: 146/150 SRT italiani reali riconosciuti (4 senza verdetto: dialoghi misti), 14/14 `.en.srt` reali, nessun falso verdetto.
- **Forced (`core/subtitle_extractor.py`)**: forced anche dal titolo ("Forced", "forzati", "signs"; non "non-forced"). Il flag del contenitore
  viene ignorato solo se i tag mkvmerge (NUMBER_OF_FRAMES, PGS = frame/2) mostrano ≥150 battute e ≥5 al minuto, non esiste un'altra traccia non
  forced nella stessa lingua e il codec non è ASS/SSA: RahXephon marca forced+default la PGS "English Translation" (≈195 battute in 24 min).
  Su 682 file della cronologia 3 film sceglievano la traccia "Forced SRT" italiana invece della regolare: corretto.
- **Classifica unica (`pipeline.py` STEP 1)**: testo it > bitmap it > testo en > bitmap en > altre lingue (testo, poi bitmap) > lingua ignota;
  a parità regolare > HI > commento > indice. Le tracce testo senza lingua si verificano prima della classifica; `dvb_subtitle`/`xsub`
  (senza motore OCR) non sono candidate; se l'OCR di un tipo fallisce si passa al testo o alla trascrizione.
- **OCR (`pgs_ocr.py`, `vobsub_ocr.py`, `ocr_auto.py`, `bitmap_ocr_common.py`)**: usano la lingua effettiva della traccia; dopo l'OCR la lingua
  del testo corregge quella presunta (e rilegge con il modello Tesseract giusto); una traccia data per italiana ma con testo straniero viene
  tradotta (`ContentNotItalian`, porta il testo SRT, non gli eventi con le immagini); la decisione si prende sulle sole tracce complete, non
  sulle forced. **Nella pipeline l'OCR scrive sempre `<video>.it.srt` accanto al file e non tocca l'MKV** (`writeback_override`); l'impostazione
  `ocr_writeback` resta valida per Library Scanner e GUI OCR.
- **Cache dei modelli preservata (`utils/cache_cleaner.py`, `utils/config.py`, `core/engines/canary_engine.py`)**: a fine coda veniva cancellata anche
  la cache di Canary: il file successivo la riscaricava (4,8 GB, fino a 54 minuti con 1,6 MB/s). Ora sono preservati i modelli di
  trascrizione, allineamento inglese, punteggiatura, diarizzazione, genere, LaBSE del Glossario e il checkpoint Demucs, più quelli configurati
  (`canary_model_id`, `qwen3_*`, `whisper_model_by_language`…); l'allineamento fr/es/de resta scaricato a ogni coda per scelta; confronto esatto
  sullo slug; pulizia dei blob condivisi orfani (3,85 GB di Cohere). Interruttore `model_cache_cleanup_enabled` (False = non cancella nulla).
  Avviso a schermo "📥 Modello Canary non in cache: download di circa 5 GB…" e `hf-xet` in `requirements-canary.txt`.

## 1.30.2.08.10.26 — 2026-10-08 — Anime con numerazione assoluta, striscia sotto la locandina a spazio fisso, colonne stabili

- **Anime con file grezzi (`utils/tmdb_client.py`)**: `RahXephon.E01.1080p[WEB-DL]...` veniva trattato come film ("RahXephon E01"):
  nessun risultato TMDB, quindi nessuna locandina, nessun IMDb ID e upload OpenSubtitles disabilitato. `parse_filename` ora riconosce,
  SOLO con un indizio esplicito, `Titolo.E01` / `.EP05`, `Titolo - 12 [...]` (almeno 2 cifre), `[Gruppo] Titolo - 12` e la stagione
  nel titolo (`Oshi no Ko S2 - 05`, `Season 2 - 05`). Esclusi anni, numeri decimali (`- 1.55GB`), un anno DOPO il numero (film) e i batch
  `01-12`. Il numero assoluto diventa stagione/episodio con gli episodi per stagione di TMDB (speciali esclusi), scegliendo tra i primi
  4 risultati il primo con abbastanza episodi (AoT - 30 → S02E05, - 60 → S04E01); se nessuno è compatibile si ripiega sul film.
  I nomi nel formato Sonarr/TRaSH (`Titolo (Anno) - S01E01 - 001 - Titolo episodio`) restano invariati. Su 839 nomi della cronologia nessuno cambia.
  Con gli anime l'IMDb ID è quello della serie.
- **`gui/workers.py`**: il caricamento della locandina passa il nome file completo (il doppio `.stem` toglieva `.E26` e il nome veniva cercato come film).
- **Striscia sotto la locandina (`gui/main_window.py`)**: spazio SEMPRE riservato (altezza fissa), così la locandina non cambia più dimensione a inizio
  file. Contenuto: pillole lingua/stato, `Nome show SxxExx` (film: solo titolo), sotto in piccolo `dimensione · percentuale`, barra. "Pulisci" ora
  svuota anche striscia, contatore dei rimanenti e badge dei filtri.
- **Colonne stabili (`gui/widgets.py`, `gui/main_window.py`)**: i valori del Monitor Risorse (CPU/RAM/GPU/VRAM) e l'ETA erano `QLabel` semplici:
  quando il testo si allarga ("5.0%" → "100.0%", "9.7GB" → "10.66GB", "–" → "12h 59m") crescevano i minimi dei pannelli e lo splitter
  ridistribuiva le colonne (misurato offscreen, anche sulla 1.30.1). Ora sono `ElideLabel`.

## 1.30.2.03.10.26 — 2026-10-03 — Metadati TMDB: l'anno della stagione nel nome del file non blocca più la ricerca

- **`utils/tmdb_client.py`**: per `Bake Off Italia - Dolci In Forno (2026) s14e05` TMDB non restituiva nulla, perché l'anno nel
  nome (2026, quello della stagione) veniva passato come `first_air_date_year` e la serie è del 2013: nessuna locandina,
  nessun IMDb ID e quindi upload su OpenSubtitles disabilitato ("Metadati non trovati"). Ora `search_tv` prova prima col filtro
  anno (che disambigua casi come "The Howard Stern Show 2026") e, SOLO se trova "nessun risultato" (non se la ricerca è fallita
  per chiave API, timeout o rete), ripete la ricerca senza anno con il solo titolo intero (le varianti più larghe, senza anno,
  davano risultati sbagliati, es. "The Corporation 2003" → serie del 1973). Nessuna ricerca che già riusciva cambia esito.
  `_clean_title` toglie anche le parentesi vuote lasciate dall'anno estratto (`Dolci In Forno ()`).
- Resta noto: per Bake Off l'IMDb ID è quello della serie (TMDB non ha un ID per l'episodio); il primo giro con l'anno può
  restituire serie sbagliate per titoli omonimi (es. Ghosts 2026) — comportamento preesistente, non toccato.

## 1.30.2 — 2026-10-03 — Profilo di trascrizione fisso su Massimo, log pulito, riordino coda, Glossario in `glossary_engine/`

- **Profilo di trascrizione fisso (`utils/config.py`, `gui/profile_dialog.py`)**: `Config.get_transcription_profile()` restituisce
  sempre `maximum` finché `transcription_profile_locked` è true (default). Default e ripieghi passano da `balanced` a `maximum`
  (una nuova installazione partiva da Bilanciato). Le schede dei profili sono nascoste (`SHOW_PROFILE_CARDS = False`, codice mantenuto);
  il selettore del motore resta e mostra i tempi tipici per motore. Misure su ~40 minuti di italiano, solo ASR: Whisper 2,9 / 2,3 / 1,9 /
  1,8 / 1,5 min per ora di audio (Massimo / Alta qualità / Batch / Bilanciato / Veloce) con lo 0,1–0,4 % di parole diverse dal Massimo;
  Qwen3-ASR 8,7–9,3 min/h con testo identico a batch 2, 4 e 8; Canary-Qwen non legge i profili.
- **Tessera "Modello" della Diagnostica (`gui/main_window.py`, `core/pipeline.py`, `core/engine_router.py`, `core/engines/faster_whisper_engine.py`,
  `utils/engine_labels.py`)**: mostra il modello realmente in uso, aggiornata dalla riga `🧩 Modello trascrizione` emessa dalla pipeline
  (anticipo), da Whisper dopo il caricamento e dal router per Qwen3/Canary.
- **Log a schermo (`gui/main_window.py`, engine, `core/whisper_lang_retry.py`, `core/audio_processor.py`)**: righe per chunk (ripristino
  punteggiatura, chunk ritrascritti) e interni di caricamento solo nel file di log, con riepilogo a fine fase; le barre di avanzamento sono
  sempre l'ultima riga e si riscrivono per singola barra; i `📦 Caricamento modello` restano a schermo. `audio_processor` e
  `whisper_lang_retry` usano `setup_logger` (un logger "nudo" scarta le info). Il passo 2.5 si chiama "Pre-caricamento Whisper (ordine CUDA / ripiego)".
- **"⚠️ Generazione rallentata" (`core/llm_subtitle_translator/translator.py`)**: il flag si azzerava a ogni cambio di batch e l'avviso
  poteva comparire più volte nello stesso file; ora una sola volta per file a schermo, con il totale nella riga "Completato in".
- **Riordino della coda (`gui/reorderable_list.py`)**: gli elementi ancora in attesa si riordinano con il trascinamento, anche a elaborazione
  avviata; `processing_queue` è riscritta sotto mutex. Layout e dimensioni delle colonne invariati.
- **Split per frasi in spagnolo (`core/whisper_sentence_split.py`)**: pubblicate le regole `lang='es'` (scritte il 29/09/2026); `es` era già tra
  le lingue di `whisper_split_sentence_langs`. Attivo per scelta dell'utente.
- **Glossario per show: motore in `glossary_engine/`**: i moduli attivi (`build_glossary_candidates.py`, `glossary_align.py`, `glossary_cluster.py`,
  `glossary_qwen_bridge.py`, `glossary_qwen_extract.py`, `glossary_qwen_gpu_cli.py`) stavano in `mt_eval/`, cartella di banchi di prova; ora sono in
  `glossary_engine/` insieme a `film_srt.py` (helper SRT copiati da `mt_eval/build_film_bench.py`). `build_glossary_candidates.py` nel repo era la
  versione precedente al 04/09: ora delega il canale Qwen al venv principale (GPU) con progresso globale per coppia e `qwen_channel_error` nel
  report. I dati di lavoro e i report vivono in `glossary_engine/` (ignorati da git). Percorsi aggiornati in `core/glossary_builder_cli.py`,
  `gui/glossary_dialog.py`, `gui/glossary_worker.py`.
- **Repository: solo codice attivo**: rimossi i banchi e gli strumenti di valutazione (`mt_eval/`, `asr_eval/`, `whisper_split_eval/`, `split_eval/`,
  `gender_eval/`, `diar_eval/`, `Gemma training/`), che restano nella cartella di lavoro; `.gitignore` aggiornato. I riferimenti a quei percorsi nelle
  voci precedenti di questo file sono storici.

## 1.30.1 — 2026-09-29 — Stessa correzione anche sul percorso "N chunk sequenziali"

- **`core/engines/faster_whisper_engine.py`**: la correzione della lingua forzata (v1.30.0) copriva solo il
  percorso "file unico" (BatchedInferencePipeline), usato quando l'utente forza Faster-Whisper o quando è il
  motore pianificato. Ora copre anche il percorso a chunk multipli — usato quando Whisper interviene come
  RIPIEGO automatico dopo un errore di Qwen3/Canary a metà file, con i chunk già tagliati dal motore
  originale — riusando la stessa `core/whisper_lang_retry.apply()`, chunk per chunk.
  - Gate su tre condizioni: mai in auto-detect, solo se il VAD è disponibile, e la chiave di config.
  - Un solo riepilogo di log a fine file (non uno per chunk).
  - Ripiego automatico se il modello caricato non accetta il parametro `batch_size` nella ritrascrizione
    (caso raro: `WhisperModel` puro, senza `BatchedInferencePipeline`).
  - Verificato end-to-end riusando l'audio già separato in cache (senza rieseguire Demucs) e chiamando il
    motore direttamente con chunk tagliati come farebbe Qwen3: recupera il canto perso e lascia invariato il
    parlato italiano, come sul percorso file-unico.
- **`asr_eval/sandbox.py`**: `qwen3_lang_retry_enabled` e `whisper_lang_retry_enabled` spenti nei banchi di
  misura ASR (`BENCH_SETTINGS`), che altrimenti misurerebbero i motori con la correzione già attiva sotto,
  falsando i confronti futuri fra motori "grezzi".

## 1.30.0 — 2026-09-29 — Stessa correzione anche per Faster-Whisper

- **`core/whisper_lang_retry.py` (nuovo) + `core/engines/faster_whisper_engine.py`**: quando la lingua è
  FORZATA (mai in auto-detect), i segmenti sospetti E i vuoti fra i segmenti vengono ritrascritti con
  rilevamento lingua, esattamente come per Qwen3-ASR (`core/qwen3_lang_retry.py`, v1.29.0). Config
  `whisper_lang_retry_enabled` (default `True`) e `whisper_lang_retry_accept_langs` (default `['en']`).
  Utile in particolare quando l'utente forza Faster-Whisper dal menu del motore (Impostazioni → Profilo →
  motore di trascrizione) al posto di Qwen3, per esempio se non è soddisfatto dell'output di Qwen3.
- **Due differenze rispetto a Qwen3, trovate misurando su Faster-Whisper** (`mt_eval/xfactor_canto/`):
  - il VAD di Faster-Whisper spesso non rileva ALCUNA voce sul canto: interi tratti restano ASSENTI dai
    segmenti (non "vuoti", proprio assenti). Si esaminano quindi anche i vuoti fra un segmento e il successivo:
    se contengono voce, sono trattati come un segmento sospetto vuoto;
  - un vuoto lungo ritrascritto in un'unica chiamata recupera pochissimo (misurato: 114 s di rap, solo 2 righe
    recuperate — lo stesso VAD, riapplicato in blocco, scarta comunque la maggior parte). I vuoti più lunghi di
    30 s vengono quindi divisi in sotto-finestre, con parametri VAD più permissivi per la ritrascrizione.
  - Verificato end-to-end dopo la correzione: sulla clip "Bang Bang" (X Factor) il testo recuperato passa da 2
    righe isolate a "bang bang into the room i know you want it bang bang all over you" + "Thank you for
    watching!"; sulla clip dove un approccio senza filtro aveva sovrascritto parlato italiano vero con testo
    allucinato in polacco, il parlato italiano resta ora invariato ("Grazie. Tocca...").
- Esiti: `mt_eval/xfactor_canto/CONCLUSIONI.md`, `review/CONFRONTO.md`.

## 1.29.0 — 2026-09-29 — Canto in lingua diversa recuperato (Qwen3) + spagnolo su Whisper con split per frasi

- **`core/qwen3_lang_retry.py` (nuovo) + `core/engines/qwen3_asr_engine.py`**: Qwen3-ASR forzava la lingua della
  traccia su ogni chunk, anche nell'allineatore; le parti cantate/parlate in un'altra lingua (quasi sempre
  l'inglese: canzoni, citazioni) sparivano o uscivano come testo storpiato nella lingua forzata. Un chunk
  "sospetto" (vuoto, poche parole rispetto alla voce presente, o pieno di parole inglesi pur forzato in
  un'altra lingua) viene ora ritrascritto con rilevamento lingua e tenuto solo se la lingua rilevata è diversa,
  allineabile e nell'insieme accettato (di default solo l'inglese: è l'unica lingua validata su materiale
  reale — il LID su rumore/applausi può allucinare altre lingue). Config `qwen3_lang_retry_enabled` (default
  `True`) e `qwen3_lang_retry_accept_langs` (default `['en']`).
  - **Misura** (`mt_eval/xfactor_canto/`, 9 esibizioni cantate di X Factor con canto perso dalla lingua forzata):
    recupera testo inglese vero e leggibile in tutte le clip inglesi, zero rumore fuori dai chunk toccati, la
    clip di controllo in italiano resta bit-per-bit identica. Verificato anche che l'approccio "senza filtro"
    (rilevamento lingua su ogni segmento, provato su Faster-Whisper nella stessa misura) sia rischioso — ha
    sovrascritto parlato italiano vero con testo allucinato in un'altra lingua vicino ai bordi delle esibizioni:
    per questo la correzione resta mirata ai soli chunk sospetti, non generalizzata.
- **`utils/config.py` (`whisper_model_by_language`, `whisper_split_sentence_langs`)**: lo spagnolo passa da
  Qwen3-ASR a Faster-Whisper large-v3 e riceve lo split per frasi (regole in `core/whisper_sentence_split.py`).
  Migrazione della config per revisione (rev 3 → 4).
  - **Misura** (`mt_eval/asr_es/`, 5 motori su 4 film spagnoli originali — Qwen3, Whisper large-v3, NVIDIA
    Canary-1B-v2, Cohere Transcribe, HiTZ/whisper-large-v3-es): nessun candidato nuovo ha superato la soglia
    della regola congelata contro le due basi. Whisper e Qwen3 riconoscono le parole quasi allo stesso modo
    (89,2% contro 88,5%), ma Whisper sbaglia meno, inventa meno testo, è più veloce e usa meno VRAM; con lo
    split per frasi spagnolo i suoi blocchi migliorano nettamente (tagli senza punteggiatura 37,7% → 1,0%).
    Il passaggio a Whisper non era coperto dalla regola (confrontava solo i candidati nuovi contro le basi):
    scelta dell'utente. Verificato end-to-end (spagnolo → italiano): instradamento su Whisper confermato nel
    log, nessuna riga rimasta non tradotta, blocchi corretti.
  - Esiti completi: `mt_eval/asr_es/RESULT.md`, `mt_eval/xfactor_canto/CONCLUSIONI.md` e
    `mt_eval/xfactor_canto/review/CONFRONTO.md`.

## 1.28.0 — 2026-09-28 — Split per frasi anche in tedesco

- **`core/whisper_sentence_split.py`**: regole tedesche (`_boundary_type_de`, `SUPPORTED_LANGS` + `de`), con nomi
  locali per non toccare en/it/fr:
  - i sostantivi sono sempre maiuscoli: nei casi ambigui (numero, lettera o sigla seguiti dal punto) decide la
    parola dopo, con una lista di aperture di frase che non sono sostantivi;
  - ordinali ("am 3. Mai");
  - "z. B." diviso in due parole;
  - "ss" al posto di "ß", come scrive il modello primeline;
  - virgolette „“ ‚‘ »«;
  - le parole funzionali che possono chiudere una frase prima di una congiunzione ("was ich gesehen habe | und").
- **Difetto evitato:** i codici lingua a 3 lettere venivano tagliati alle prime 2 lettere, e `ger` diventava `ge`:
  il tedesco non si sarebbe mai acceso. Ora c'è una mappa esplicita, sia nel modulo sia nel motore
  (`faster_whisper_engine`).
- **Acceso di default** (`whisper_split_sentence_langs` = `["en", "it", "fr", "de"]`). La migrazione della config ora
  è per revisione (`_SPLIT_LANGS_BY_REV`, marcatore rev 3): una config con il default della propria revisione riceve
  le lingue nuove e viene salvata; le liste personalizzate non si toccano.
- **Misura** (`whisper_split_eval/`). La misura principale è nuova, `naked_cuts.py`: conta i tagli senza punteggiatura
  né congiunzione e non si basa sulla minuscola, che in tedesco non funziona.
  - Taratura su 3 film: 45,0% → 3,3%.
  - Conferma su 8 film tedeschi originali mai usati: **37,0% → 2,7%** (sottotitoli professionali 1,9%), in calo in
    ogni film.
  - Altri dati di conferma: blocchi di più di 2 righe 248 → 37, blocchi oltre 9 s 76 → 37, testo identico; inglese,
    italiano e francese invariati bit per bit.
  - Verdetto formale: **non vincente** per un solo sotto-criterio, la densità per film. In *Vi presento Toni Erdmann*
    il sottotitolo tedesco è parziale (511 battute su 162 minuti); in *Funny Games* il confronto è con i sottotitoli
    italiani, 7,1 contro 7,0 blocchi al minuto.
  - **Acceso per scelta dell'utente.** Esito in `whisper_split_eval/results/esito_de_2026-09-28.md`.
- `split_eval/midcut.py`: parole di continuazione tedesche, codici `ger`/`deu`, virgolette „‚ in apertura.

## 1.27.0 — 2026-09-28 — Split per frasi anche in francese

- **`core/whisper_sentence_split.py`**: regole francesi (`_boundary_type_fr`, `SUPPORTED_LANGS` + `fr`):
  tipografia francese (" ?" " !" " :" " »" sono parole a sé: mai tagliare prima), "M." = Monsieur, abbreviazioni,
  parole funzionali, congiunzioni e locuzioni ("parce que", "alors que", "même si") che restano unite.
- **Acceso di default** (`whisper_split_sentence_langs` = `["en", "it", "fr"]`). Migrazione una tantum in
  `utils/config.py` (`_migrate_split_langs`): chi ha ancora nella config il default precedente `["en", "it"]` riceve
  `fr` al primo avvio; le liste personalizzate non si toccano e, se poi si toglie `fr`, resta tolto (marcatore
  `whisper_split_sentence_langs_rev`).
- **Misura** (`whisper_split_eval/`, modello whisper-large-v3-french della 1.26.0):
  - taratura su 3 film, blocchi che finiscono a metà frase 45,1% → 12,6%;
  - conferma su 9 film francesi originali mai usati, 50,7% → 19,4%. Blocchi di più di 2 righe 272 → 30, testo
    identico, inglese e italiano invariati bit per bit;
  - blocchi che finiscono su parola funzionale (spaCy) 23,9% → 3,0%, contro l'1,9% dei sottotitoli professionali.
  - Verdetto formale della regola congelata: **non vincente**. Il rapporto richiesto era ≤ 0,33, si è ottenuto 0,38;
    i blocchi con più di 20 caratteri al secondo salgono di 2,4 punti, oltre il limite di 2,0. Il criterio conta
    anche i tagli su virgola: il 78% del residuo sono virgole in frasi più lunghe di 84 caratteri, dove il taglio è
    obbligato. I tagli senza punteggiatura né congiunzione scendono dal 41,6% al 2,1%, sotto il 3,2% dei professionali.
  - **Acceso per scelta dell'utente.** Esito completo in `whisper_split_eval/results/esito_fr_2026-09-28.md`.
- `split_eval/midcut.py`: parole di continuazione francesi per la metrica.
- `whisper_split_eval/run_whisper.py`: carica il modello Whisper della lingua (`whisper_model_by_language`).

## 1.26.0 — 2026-09-28 — Trascrizione: Whisper specializzato per francese e tedesco

- **Nuova opzione `whisper_model_by_language` (`utils/config.py`)**: per le lingue elencate, in modalità `auto`
  la trascrizione usa faster-whisper con un modello Whisper specializzato invece di Qwen3-ASR. Default:
  - `fr` → `bofenghuang/whisper-large-v3-french` (cartella `ctranslate2/` del repo);
  - `de` → `primeline/whisper-large-v3-german`, dal repo `TiMoMuc/whisper-large-v3-german-ct2`: il suo `model.bin`
    è identico byte per byte alla nostra conversione CTranslate2 float16 dell'originale (sha256 318956c2…).
  Valori ammessi: `utente/repo`, `utente/repo/sottocartella` o una cartella CTranslate2 locale. I modelli si
  scaricano al primo uso (~3 GB per lingua) nella cache dei modelli del programma (`models/.cache`).
  Per spegnere una lingua: `"fr": ""` (cancellare la chiave non basta, i default la rimettono).
- **`core/engine_router.py`**: la tabella viene consultata per prima in modalità `auto`; una modalità forzata
  (`transcription_engine_mode`) resta prioritaria. Tracce senza lingua (`und`) restano su Qwen3 con rilevamento
  automatico.
- **`core/transcriber.py` / `core/pipeline.py`**: la lingua della traccia arriva al pre-caricamento dello STEP 2.5
  (`language_hint`), quindi il modello giusto si carica subito, prima di Demucs, senza ricaricamenti.
- **`core/engines/faster_whisper_engine.py`**: se il modello specializzato non si scarica o non si carica, si usa
  `whisper_model` (large-v3) e il file non fallisce; il cambio di modello in `transcribe_chunks` resta solo come rete
  di sicurezza.
- **Misura francese (4 film in lingua originale, 8 finestre valide, riferimento = sottotitoli francesi del film):**
  WERc Qwen3 44,1%, Whisper large-v3 41,9%, whisper-large-v3-french 40,4%; parole del riferimento riconosciute
  73,8% / 69,3% / 74,2%. Il miglioramento (−8,5% relativo) è sotto la soglia fissata prima di misurare (10%): la
  scelta è dell'utente, con ~1,8× di velocità sull'intera pipeline. Il tedesco non è misurato.
- **Limite noto**: francese e tedesco non hanno ancora lo split per frasi; i blocchi Whisper sono lunghi e alcune
  frasi finiscono a cavallo di due blocchi anche in traduzione. La traduzione resta su NLLB fine-tuned.

## 1.25.1 — 2026-09-27 — Traduttore LLM: il secondo giro non accetta più blocchi bocciati due volte

- **Difetto corretto (`core/translator.py`, fase L2 di `LLMSubtitleTranslator.translate_file`):** un blocco bocciato
  dal validatore al primo giro e di nuovo al secondo (degenerato, lingua sbagliata, copia del sorgente) veniva contato
  come "recuperato" e finiva nel sottotitolo. Il controllo calcolava i bocciati del secondo giro come differenza fra
  due insiemi, e un blocco già bocciato al primo non risultava "nuovo". Ora il secondo giro registra i propri
  bocciati a parte (`_run_with_isolated_unresolved`) e quei blocchi passano al serbatoio. Trovato su una battuta
  tedesca uscita come "So, so. So, so. So, so. So, so."; vale per ogni lingua, inglese compreso.
- Test: `test_l2_retry.py`. Non ancora verificato su un film inglese intero.

## 1.25.0 — 2026-09-27 — Traduzione da lingue non inglesi: instradamento automatico su NLLB fine-tuned

- **Instradamento automatico (`core/pipeline.py::_route_non_english_away_from_llm`):** quando il motore selezionato è
  TranslateGemma (`translation_model='llm'`, incluso l'alias storico `'aya'`) e la lingua sorgente rilevata NON è
  l'inglese, la traduzione passa automaticamente a NLLB fine-tuned, con un avviso a schermo. TranslateGemma è stato
  addestrato SEMPRE con `source_lang_code: "en"` nel prompt, anche sulle coppie non inglesi: su una sorgente diversa
  dichiara una lingua falsa. Non tocca la scelta esplicita dell'utente per gli altri motori (NLLB base, Claude, OpenAI,
  OpenSubtitles), che dichiarano già la lingua sorgente vera nel proprio prompt.
- **Misura (140 blocchi reali, audio francese, giudice GEMBA-MQM + revisione umana cieca su 203 blocchi):** passare
  l'etichetta vera `fr` a TranslateGemma dimezza il francese lasciato non tradotto (42→19 su 140) ma peggiora la
  fluidità oltre la soglia fissata prima di misurare (GEMBA fluency+style +14,3%, soglia +10%): **non adottata**. NLLB
  fine-tuned, sullo stesso materiale, batte entrambe le etichette su ogni fronte misurato (1 blocco residuo su 140,
  migliore fedeltà, fluidità comparabile).
- **Correzione di un difetto reale nel percorso TranslateGemma** (resta in produzione, indipendente dall'esito sopra):
  la guardia sul codice lingua forzato accettava valori (`'fra'`, `'fre'`, `'FR'`) che non sono chiavi del chat
  template del modello (solo ISO 639-1) e ne facevano fallire la generazione con un errore inghiottito in silenzio —
  il file intero finiva svuotato al serbatoio senza nessun avviso. Ora normalizza il codice e fa risalire l'errore
  invece di ripeterlo su ogni gruppo di blocchi.
- Test: `test_translation_routing.py`, `test_llm_source_label.py`.

## 1.24.0 — 2026-09-26 — Subtitle Sync: coda multi-file e nuovo motore solo-tempi

- **Nuovo motore di allineamento (predefinito, `sync_engine='timing'`):** `core/timing_aligner.py` sostituisce NLLB+Qwen.
  Confronta il parlato dell'SRT con quello del riferimento (sottotitoli incorporati non italiani, oppure il parlato
  dell'audio con Demucs + Silero VAD quando mancano) e stima scala+offset globali (correlazione FFT, rapporti di framerate
  25/23,976 ecc.) e poi un offset per tratto (Viterbi; l'ordine delle battute non si inverte). Durate e pause dell'SRT
  restano invariate. Secondi a episodio invece di circa 80 minuti. Il vecchio percorso resta con `sync_engine='llm'`.
- **Rifiuto delle coppie sbagliate:** un indice di sovrapposizione al netto del caso decide se l'SRT corrisponde al video
  (soglie misurate su coppie giuste e sbagliate: rifiuto 0,60 con sottotitoli di riferimento, 0,30 con il parlato
  dell'audio; avviso 0,80 / 0,50). Sotto soglia la coppia fallisce senza scrivere l'output, con il motivo nel log e nella
  tabella della coda; non si ripiega su Qwen.
- **Coda multi-file:** nuova scheda "Coda (cartelle)" nella finestra di sync. Accoppia video e SRT per nome (codici
  episodio SxxEyy/NxMM obbligatoriamente uguali, duplicati rilevati, scelta manuale dell'SRT), esegue una coppia alla
  volta in un processo separato (`core/sync_cli.py`, `gui/sync_batch_worker.py`, `core/sync_pairing.py`); una coppia che
  fallisce non ferma la coda; annullo con terminazione dell'albero dei processi.
- **Verifica:** episodi interi, sei film/serie di controllo con salti, scene aggiunte/tolte, cambi di framerate;
  undici SRT reali di altre release (opensubtitles.org): framerate sbagliato corretto da solo, 98,7-100% delle righe
  verificate per testo entro 0,5 s (caso peggiore 81,6-90,3%); coda reale su 3 coppie. Test: `test_timing_aligner.py`,
  `test_sync_batch.py`. Non provati: montaggi con scene aggiunte reali (solo simulati); le soglie del riferimento
  audio poggiano su 3 film.

## Installer e requisiti — 2026-09-26 (nessun cambio di versione dell'app)

L'installer è un programma a sé stante, con un proprio ciclo di vita: non cambia `APP_VERSION`.
- **`install.bat` / `install.ps1`:** preparano l'ambiente su un PC Windows dove Transcriber Pro non è installato.
  Controllano Python 3.11 (64 bit), driver NVIDIA, Visual C++ Redistributable, FFmpeg, Tesseract con `ita`+`eng`,
  MKVToolNix e lo spazio su disco; creano i venv e installano i requisiti; offrono winget (con conferma per ciascun
  programma), i venv secondari (`-WithNlp`, `-WithCanary`, `-WithGlossary`) e il download dei modelli locali
  (`-WithModels`); `-CheckOnly` non modifica nulla, `-NoGpu` per PC senza GPU. Non copia né scrive credenziali.
  Alla fine esegue `scripts_manutenzione/selfcheck_env.py`.
- **`requirements.txt` riscritto:** versioni esatte dal venv provato, solo le dipendenze realmente usate (chiusura
  transitiva, extra compresi); 41 pacchetti non necessari esclusi; aggiunto `peft`, che mancava; `setuptools==70.3.0`
  pinnato di proposito. Nuovi lock per gli ambienti separati: `requirements-nlp.txt`, `-canary.txt`, `-glossary.txt`,
  `-dev.txt`. Rimosso `requirements_utf8.txt`.
- **Correzione per PC senza CUDA Toolkit:** `llama-cpp-python` non si importava senza cudart/cublas 12 nel PATH se torch
  non era già caricato. Nuovo `utils/cuda_dll_path.py` (mette `torch\lib` nel PATH prima dell'import) usato da sync
  sottotitoli, correzione del genere, serbatoio L3 e canale Qwen del glossario; gli `except ImportError` attorno a
  `llama_cpp` ora prendono anche `RuntimeError`.
- **`Lancia Transcriptor.bat`:** il percorso non è più scritto a mano.
- **Glossario per-show, canale Qwen su GPU:** pubblicati `mt_eval/glossary_qwen_bridge.py` e `glossary_qwen_gpu_cli.py`
  (usati da `gui/glossary_worker.py`, mai stati nella copia GitHub) e l'aggiornamento di `glossary_qwen_extract.py`.
- **`.gitignore`:** coperti anche `tmdb_api.txt`, `omdb_api.txt`, `claude api key.txt` e `install_log.txt`.
- **Verifica:** venv nuovi con i requisiti (`pip check` pulito, versioni identiche al venv di lavoro), import dei moduli,
  test CPU, smoke GPU di Whisper e Qwen3-ASR con un PATH senza CUDA Toolkit, installer end-to-end su cartella temporanea.
  Non verificati: avvio della GUI, pipeline pyannote, caricamento di NLLB/GGUF, winget reale, PC pulito reale.

## [1.23.0.26.9.26] — 2026-09-26

### Fix: «Error saving config: WinError 5» all'avvio
`Config.load()` chiamava `save()` con `config.json` ancora aperto: su Windows `os.replace` (il salvataggio atomico
introdotto nella 1.19.0) non può sostituire un file che lo stesso processo tiene aperto, quindi falliva sempre. Quando
alla config mancava una chiave di default nuova, il salvataggio non avveniva mai (i default restavano solo in memoria)
e ogni avvio perdeva 2,4 s in tentativi inutili prima di stampare l'errore. Il salvataggio ora avviene dopo la chiusura
del file: `Config()` impiega circa 0,16 s, senza errori. Nessun cambiamento alle impostazioni esistenti.
- Aggiunto `test_config_load_save.py`: fallisce sulla versione precedente (2,3 s e WinError 5) e passa su quella corretta.

## [1.23.0] — 2026-09-26

### Split per frasi attivo anche per l'italiano
`whisper_split_sentence_langs` passa da `["en"]` a `["en", "it"]`: con faster-whisper anche l'italiano divide i
segmenti sui confini di frase (le altre lingue restano sullo split originale). Per tornare al solo inglese:
`"whisper_split_sentence_langs": ["en"]` in `~/.transcriberpro/config.json`.
- **Perché è stato acceso:** conferma su 8 file italiani nuovi con regola congelata prima della selezione
  (blocchi a metà frase 46,8% → 11,2%, blocchi su articolo/preposizione/congiunzione 24,9% → 2,1%, parole identiche,
  ogni file migliora). Vedi 1.22.0 e `whisper_split_eval/README.md`.
- **Riserve invariate:** film doppiati in prevalenza (3 file in italiano originale, con un miglioramento più debole
  su *Sono qui per Caos*: 68% → 30%), effetto sulla traduzione e ascolto umano non misurati.
- **Pulizia:** cancellato l'audio dei dati di prova di `whisper_split_eval/` (~19 GB in locale); nel repository non
  cambia nulla.
- README aggiornato (badge di versione e sezione Changelog, inglese e italiano).

## [1.22.0] — 2026-09-26

### Split per frasi: regole per l'italiano (pronte e confermate, NON attive di default)
`core/whisper_sentence_split.py` ha ora un ramo `lang='it'` (abbreviazioni, articoli, preposizioni e
congiunzioni, locuzioni tipo «quello che»/«solo che», iniziali maiuscole). Il motore legge la lista di lingue
`whisper_split_sentence_langs` (nuova chiave, default `['en']`): con il default il comportamento non cambia
(inglese sì, italiano no, altre lingue split originale). Per accenderlo: `"whisper_split_sentence_langs": ["en", "it"]`
in `~/.transcriberpro/config.json`. Nessuna voce nella GUI.
- **Effetto misurato sull'italiano** (file interi, Demucs a chunk, Whisper di produzione): blocchi a metà frase
  46,8% → 11,2% (professionali 10,8%), blocchi che finiscono su articolo/preposizione/congiunzione/ausiliare
  (controllo indipendente con spaCy) 24,9% → 2,1%, parole identiche, ogni file migliora, blocchi >84 caratteri 1,3% → 0.
- **Prove:** taratura su 3 file; conferma round 1 su 7 file (NON VINCENTE per un criterio: elisioni con un salto di
  10-15 s dentro la parola, timestamp errati di Whisper); correzione; conferma round 2 su 8 file NUOVI con regola
  congelata prima della selezione: VINCENTE. Dettagli, riserve e una nota di trasparenza sull'analisi del round 2 in
  `whisper_split_eval/README.md` e `whisper_split_eval/results/`.
- **Riserve:** quasi tutti i file sono film doppiati (l'italiano originale è coperto da 3 file); i sottotitoli
  professionali dei doppiati sono traduzioni e servono solo per la forma dei blocchi; effetto sulla traduzione e
  ascolto umano non misurati.
- **Correzione valida anche per l'inglese:** un token attaccato (elisione, trattino) preceduto da un salto di 9 s
  o più non appartiene più alla parola precedente. Prima una parola con un timestamp errato (es. «Cos» a 1423 s e
  «'è» a 1529 s) produceva un blocco di 111 s mostrato 100 s in anticipo. Sull'inglese l'output resta identico su
  2323 segmenti di 5 campioni; con il default l'inglese di due file della v5 resta identico anche su GPU.
- **Test:** 76 (fixture con dialoghi reali solo in locale, mai su GitHub: i test relativi si saltano se mancano).

## [1.21.1] — 2026-09-25

### Demucs a chunk oltre i 60 minuti (prima 90)
`AudioProcessor.STANDARD_PATH_THRESHOLD` passa da 5400 s a 3600 s: i file tra 60 e 90
minuti, che prima usavano lo standard path (audio e risultato a 4 sorgenti interi in
RAM), ora usano il percorso a chunk da 5 minuti con overlap di 10 s. Motivo: sulla
macchina da 32 GB lo standard path su file da ~90 minuti portava la RAM di sistema a
0 GB liberi (picco di 23-25 GB), mentre il percorso a chunk è arrivato a circa 8 GB su
un film da 107 minuti. Nessun altro cambiamento: sotto i 60 minuti tutto invariato.
- **Non misurato:** l'effetto dei vocals a chunk (overlap con giunzioni) sull'accuratezza
  della trascrizione per i file tra 60 e 90 minuti. I tempi sono simili (194 s per 89,7
  minuti nello standard path, 210 s per 107 minuti a chunk).

## [1.21.0] — 2026-09-25

### Split di Whisper sui confini di frase (attivo di default, solo inglese)
`faster-whisper` divideva i segmenti lunghi a 80 caratteri / 6 s senza guardare la
punteggiatura: il 37-43% dei blocchi finiva a metà frase e la traduzione riceveva
frammenti. Ora, per l'**inglese**, i segmenti si dividono preferendo i confini di
frase (`core/whisper_sentence_split.py`, opzione `whisper_split_sentence_aware`,
default `true`; `false` ripristina il comportamento precedente). Altre lingue:
split originale, invariato. Vale solo per faster-whisper in modalità batched
(Qwen3 e Canary non sono coinvolti).
- **Effetto misurato** (3 campioni indipendenti, regole congelate prima dei dati):
  blocchi a metà frase 37-43% → 6-9%, parole e testo identici, blocchi > 84 caratteri
  ~1% → 0, blocchi con più di 2 righe quasi azzerati, opzione spenta bit-identica.
  Ogni singolo file dei 6 interi migliora. I blocchi diventano un po' più numerosi e
  brevi (per esempio 6,6 → 8,0 al minuto; i sottotitoli professionali ne hanno 12,4).
- **Correzione del ripiego** (trovato dalla prova su file interi): un segmento di
  ripetizioni attaccate («Boop-a-doop-a» ×5) veniva rimandato allo split originale, che
  taglia dentro le parole. Ora non si taglia mai dentro una parola; aggiunte le
  abbreviazioni italiane (Sig., Dott., Avv., …) nell'elenco.
- **Prove:** v2 NON VINCENTE solo per i criteri sui blocchi brevi (+23% contro +15%),
  criterio ricalibrato sul riferimento professionale → v3b VINCENTE su 45 finestre
  nuove; v4 su 6 file interi NON VINCENTE per un solo caso di taglio dentro parola
  (presente anche nello split originale), poi corretto e verificato offline sugli
  stessi dati (un solo segmento cambia; 40 test verdi). Dettagli e riserve in
  `whisper_split_eval/README.md`.
- **Riserve dichiarate:** criterio (f) ricalibrato dopo il fallimento della v2; margine
  0 s nella v3b (meno indipendenza dalla v2); correzione del ripiego non riconfermata
  su dati nuovi; effetto sulla traduzione e leggibilità dei blocchi più brevi non
  misurati. Non attivo per le altre lingue perché non misurato (abbreviazioni e regole
  sono inglesi).

## [1.20.1] — 2026-09-25

### Rimossa la ricomposizione delle frasi spezzate (vicolo cieco)
Il controllo umano alla cieca su 100 coppie di file reali (8 titoli) non ha
confermato il vantaggio misurato da GEMBA/COMET: ricomposizione 38, base 30,
pari 32 (p unilaterale 0,198). Regola congelata: ARCHIVIA. In 13 delle 22
coppie con difetti segnalati la traduzione ricomposta perdeva una parte del
testo (la coda dell'unità).
- Rimossi `core/sentence_recompose.py`, l'opzione `translation_recompose_sentences`
  e il ramo relativo in `core/pipeline.py`: il percorso di traduzione torna
  quello della 1.19.x (già identico con l'opzione spenta).
- Rimossi il controllo cieco (`blind_check/`) e il prototipo/banco di
  `split_eval/`; resta solo la misura `midcut` usata da `asr_eval`. Esiti e
  motivazioni in `split_eval/README.md`.
- Le voci 1.20.0 sotto restano come storico.

## [1.20.0] — 2026-09-24

### Ricomposizione delle frasi spezzate prima della traduzione (OPT-IN, spenta di default)
Nuova opzione `translation_recompose_sentences` (default `false`; si attiva in
`~/.transcriberpro/config.json`). Quando è attiva, i blocchi che finiscono a
metà frase vengono riuniti in unità di frase, tradotti interi e la traduzione
viene ridistribuita sui blocchi originali (stessi numeri, stessi tempi).
- **Ambito**: solo NLLB / NLLB fine-tuned, solo inglese → italiano, solo SRT
  da trascrizione (i sottotitoli già presenti, embedded o da OCR, e gli altri
  motori ignorano l'opzione con un messaggio nel log). Non coperti: OCR
  (`core/ocr_auto.py`) e sync (`core/subtitle_synchronizer.py`).
- **Sicurezza**: con l'opzione spenta il percorso di traduzione è identico
  alla 1.19.x (nessun import del modulo nuovo). Se qualcosa non torna
  (unità tradotte in numero sbagliato, testo vuoto, eccezione) si ripiega sul
  percorso normale senza far fallire la traduzione; i blocchi a due voci con
  trattino, le etichette di speaker (`MARY:`) e le didascalie (`[laughs]`) non
  si uniscono mai; la cancellazione è rispettata; il traduttore viene
  ricreato se il serbatoio L3 l'ha scaricato.
- **Modulo**: `core/sentence_recompose.py` (solo libreria standard). Il
  prototipo misurato resta in `split_eval/`.
- **Evidenza** (prova confermativa con regole v2 su dati nuovi, Qwen3, NLLB-FT):
  giudice GEMBA B 179 contro A 48 (pari 23), COMET +0,04 in 7 film su 7.
  La ridivisione è stata migliorata offline dopo il verdetto formale «archivia»
  del banco (blocchi vuoti 1,94% → 0,48%, ripiego 4% → 1%, sbilanciamento
  p90 0,236 → 0,154): correzioni progettate sulle stesse 200 unità, quindi
  post-hoc, con un margine stretto sullo sbilanciamento. Prova con NLLB-FT
  vero su 14 finestre: indici e tempi identici, nessun blocco vuoto, traduttore
  ricreato dopo lo scarico. Un bugcheck Opus ha trovato e corretto: etichette di
  speaker unite oltre il cambio di voce, ambito esteso ai sottotitoli
  embedded, ridivisione lenta su traduzioni anomale.
- **Da fare prima di attivarla**: controllo alla cieca su file reali (l'SRT
  non porta lo speaker: due persone che si passano una frase senza trattino
  potrebbero essere unite).

### Controllo alla cieca della ricomposizione su file reali (`blind_check/`)
Strumenti per confrontare, senza sapere quale sia quale, la traduzione normale
con quella ricomposta su estratti di 20 minuti di film e serie della libreria
(5 film + 3 episodi, seme fisso, motori Whisper e Qwen3 in alternanza, solo
traccia audio inglese): selezione, trascrizione con la pipeline reale e
traduttore finto che cattura l'SRT, doppia traduzione NLLB-FT, foglio cieco
(A/B scambiati a caso, mappatura nascosta) e conteggio con regola congelata
(quota ≥60% fra i non pari, p ≤ 0,025, film in maggioranza ≥60%, difetti
visibili ≤3%). Nota: con una traccia audio italiana presente la pipeline
trascrive l'italiano e salta la traduzione, quindi gli estratti contengono solo
l'inglese. 12 test CPU.

### Test nei banchi
I test dei banchi `asr_eval/` e `split_eval/` non erano mai stati pubblicati
(il `.gitignore` del repository ignora `test_*.py`): ora lo sono (76 test in
`split_eval/tests`, 70 in `asr_eval/tests`).

## [1.19.1] — 2026-09-24

Nessuna modifica al comportamento dell'app: due banchi di misura nuovi
(`asr_eval/`, `split_eval/`, con test e README) e i loro primi risultati.

### `asr_eval/` — banco di accuratezza ASR contro i sottotitoli professionali
Whisper large-v3 (profilo di produzione), Canary-Qwen-2.5B (solo inglese) e
Qwen3-ASR su 140 finestre da ~150 s di 16 film (inglese, audio ENG contro
sub ENG professionali), con e senza Demucs. Regole di decisione, normalizzazione
e statistica (bootstrap per film, Wilcoxon esatto) congelate PRIMA dei run
(`decision_rules.py`); sandbox della config di produzione; guardia che rifiuta
di partire con la GPU occupata. 70 test. Risultati (`asr_eval/results/`):
- Gruppo principale (9 film, voce separata), WERc: Qwen3 12,1%, Canary 14,0%,
  Whisper 15,8%. Qwen3 batte Canary di 1,85 punti (IC95% 0,50–3,39,
  Wilcoxon p=0,012, stesso segno nel gruppo dei film più vecchi): verdetto
  «cambio proposto», NON definitivo (manca il set d'oro corretto a mano).
  Whisper contro Canary: pareggio, ma con il doppio di battute perse (8,0% contro 4,2%).
- Demucs: Whisper +2,1 punti, Canary +1,9, Qwen3 +0,2 (nessun effetto significativo).
- Velocità (s per minuto di audio): Whisper 2,0, Canary 2,2, Qwen3 5,5.
- Limiti: il riferimento è un sottotitolo condensato (i valori assoluti sono
  gonfiati, conta la classifica); l'italiano NON è misurato (i sub ITA normali
  dei film doppiati sono la traduzione dell'inglese, non il copione: serve un
  controllo d'ascolto manuale, `work/listen_check.csv`).

### `split_eval/` — frasi spezzate a metà: misura e prototipo di ricomposizione
- **Misura (midcut):** nei blocchi finali del formatter i blocchi che finiscono
  a metà frase sono il 41% con Whisper, il 10-11% con Qwen3 e Canary, il 10%
  nei sottotitoli professionali. Con Whisper la traduzione riceve quindi
  frammenti molto più spesso.
- **Prototipo (`recompose.py`):** unisce le frasi spezzate in unità, traduce
  l'unità intera e ridistribuisce il testo tradotto sui blocchi originali
  (tempi invariati). Esperimento A/B con NLLB fine-tuned su 140 finestre,
  58 con fusioni (195 unità): chrF −0,62 (IC95% −1,28…+0,02, n.s.), COMET
  +0,03 (IC95% 0,02–0,05, 7 film su 7 a favore di B, p=0,016); blocchi >20
  cps 13,3% → 6,9%, >84 caratteri 6,6% → 1,0%; nessun blocco vuoto. Giudice
  GEMBA-MQM (gpt-4o, 480 unità fuse di tutti i film, A e B nella stessa
  chiamata, ordine casuale): B preferito 303 volte, A 161, pari 16; MQM
  pesato medio A 6,65, B 4,51 (più basso = meglio); costo ~2,7 $ (548.700
  token in ingresso, 130.487 in uscita). Verdetto secondo le regole
  congelate: **ARCHIVIA**, perché il criterio chrF (IC95% non interamente
  sopra 0, Wilcoxon p=0,078) non passa; la regola non è stata modificata
  dopo i risultati. Le metriche divergono: chrF confronta con una sola
  traduzione e premia la resa letterale, mentre COMET (7 film su 7), il
  giudice GEMBA e la lettura di esempi favoriscono B (frammenti tipo
  «…come pensi I ricordi», «…scelto per i suoi talenti. per il loro genere»
  diventano frasi complete). NON portato nel codice di produzione: la
  decisione se derogare alla regola spetta all'utente.
- **Prova confermativa (regole v2, dati nuovi).** La regola v1 era difettosa:
  il suo testo dava COMET come metrica di record e chrF come inaffidabile, ma
  il codice richiedeva anche chrF > 0; la memoria di progetto indica la
  preferenza del giudice come metrica principale. La v1 non è stata riscritta:
  la v2 (`decision_rules_split_v2.py`, congelata prima di tradurre) usa come
  endpoint primari la preferenza GEMBA (esatto binomiale, maggioranza in ≥70%
  dei film) e COMET, con chrF solo descrittivo, su dati nuovi (segmenti di
  Qwen3, il motore standard: 200 unità fuse in 61 finestre) e su un campione
  casuale di 250 unità per il giudice. Risultati: GEMBA B 179, A 48, pari 23
  (MQM 2,57 contro 5,10); COMET +0,04 (IC95% 0,02–0,07, 7 film su 7,
  p=0,016); chrF +0,21 (n.s.). Endpoint primari superati e replicati; verdetto
  formale **ARCHIVIA** per tre guardie strutturali sul taglio: blocchi vuoti in
  B 1,94% (soglia 1%), sbilanciamento ai tagli p90 0,236 (soglia 0,20), inglese
  residuo B 28 contro A 27. Il difetto è nell'implementazione della
  ridivisione (8 unità su 200 finite in ripiego), non nella traduzione: la
  ridivisione non cambia le parole, quindi gli endpoint di qualità non
  dipendono da essa. Costo del giudice ~0,9 $. Il selettore delle regole è la
  variabile d'ambiente `SPLIT_RULES_MODULE`.
- Non eseguito: TranslateGemma (`--engine llm`).
- Un bugcheck Opus ha trovato e corretto, prima dell'esecuzione, un difetto
  che rendeva inservibile il traduttore NLLB-FT dopo il serbatoio L3 (asimmetria
  A/B), lo scivolamento degli id COMET/GEMBA e alcune granularità di conteggio.

## [1.19.0] — 2026-09-24

Revisione della qualità a 5 revisori indipendenti (trascrizione, traduzione,
diarizzazione/genere, output SRT/sync/OCR, robustezza) + arbitro, poi due
bugcheck Opus sul codice scritto. Le correzioni sotto sono solo quelle con
evidenza misurata; le idee non dimostrate restano fuori (v. in fondo).

### Trascrizione: struttura e tempi dei sottotitoli
- **`core/aligner.py` — il forced alignment non frammenta più i segmenti.**
  `whisperx.align` divide ogni segmento in frasi (nltk punkt): adottare il
  suo output moltiplicava i segmenti (678 → 1696 su un film reale) e
  produceva blocchi-lampo, mentre il ripristino dei timestamp non scattava
  mai. Ora si allinea UN segmento Whisper alla volta e si copiano soltanto i
  tempi wav2vec2 sulle parole Whisper, con guardia (spostamento massimo
  1,5 s, durata massima max(1,5 s, 2× Whisper), niente nuove sovrapposizioni);
  il testo e il numero dei segmenti restano quelli di Whisper. Verificato su
  6 finestre da 5 minuti di un film (1760 parole): segmenti 426 → 169,
  blocchi < 0,83 s 183 → 16, parole più lunghe di 1,5 s 84 → 6. Il beneficio
  è nei tempi INTERNI delle parole (usati dal diarizer per spezzare ai
  cambi di parlante); inizio/fine dei segmenti restano quelli di Whisper.
  Le parole col trattino (Whisper: " Uh" + "-huh.") non fanno più scartare
  l'intero segmento (5/169 → 0/169 mantenuti con i tempi Whisper).
- **`core/subtitle_formatter.py` — leggibilità (nuovo, `readability`,
  chiave `subtitle_readability_enabled`, default True).** Le frasi
  brevissime consecutive restavano blocchi-lampo perché il blocco seguente
  partiva subito dopo. Ora si uniscono le frasi vicine (gap ≤ 0,5 s) dello
  STESSO speaker quando almeno una è troppo breve (< 1,2 s) o troppo veloce
  (> 17 caratteri/s), entro 2 righe e 6 s, e si allunga la fine del blocco
  fino a 17 cps (max 7 s) senza toccare il blocco seguente. Guardie:
  contesto dialogo (non si esclude un blocco a due voci), una risposta breve
  dopo una domanda non si fonde (il diarizer attribuisce le battute sotto le
  3 parole al parlante precedente), confidenza speaker come media pesata sui
  caratteri (il minimo faceva perdere trattini validi). Su Goodrich, con
  speaker: blocchi 2008 → 1652, < 0,83 s 234 → 68, > 20 cps 311 → 160,
  trattini 220 → 222, nessuna sovrapposizione. Con `readability=False`
  l'output è bit-identico al formatter precedente (verificato).
- **Formattazione anche senza diarizzazione**: se la diarizzazione è
  disattivata, fallisce o manca il token HuggingFace, l'SRT viene comunque
  formattato (CPL, durata minima, leggibilità) invece di restare grezzo
  (prima: 24,5% di blocchi a riga singola oltre 42 caratteri). Se il
  formatter fallisce non si sostituisce mai l'SRT grezzo con uno vuoto.
- `subtitle_cleaner`: non inserisce più lo spazio dopo `, : ;` fra due cifre
  ("10:30" → "10: 30", "3,5" → "3, 5").

### Diarizzazione e correzione del genere
- **`diarization_clustering_threshold` di default 0.85 → 0.0 (default di
  fabbrica 0.7046).** Banco `gender_eval` su 8 episodi (63 punti, Veronica
  Mars) sulla mappa voce → genere dello STEP 6.5: soglia di fabbrica,
  automatico: accuratezza 91,9%, copertura 98,4% (23 parlanti medi);
  automatico a 0.85: 86,8% / 60,3%; `num_speakers=10` esatto: 75,0% / 76,2%;
  0.85 con tetto a 10: 77,8% / 57,1%. I cluster fusi abbassano la
  confidenza sotto soglia e la correzione in 1ª persona non scatta. Sul
  dialogo il confronto Goodrich non aveva mostrato differenze. Il
  commento in `config.py` prevedeva proprio di riconsiderare questo valore
  in caso di sovra-fusione.
- Tooltip del numero di parlanti: > 0 è il numero ESATTO (non un massimo) e
  disattiva la soglia di clustering. La causa era un'incomprensione: il
  valore 10 in una config reale forzava 10 cluster su ogni file.

### Robustezza
- **Traduzione fallita** (`core/pipeline.py`, STEP 6-7): un'eccezione in
  factory/callback/traduzione equivale a "traduzione fallita" (prima: fine
  del job senza salvare nulla e cartella temporanea cancellata). Se il file
  di destinazione (es. `X.en.srt`) esiste già NON viene mai sovrascritto: la
  trascrizione/OCR viene conservata in `~/.transcriberpro/recuperati/` e il
  job risulta fallito. Se non esiste, viene salvato nella lingua originale
  ma il job risulta fallito (niente watermark del motore, niente upload).
- **`Config.save()` atomico**: file temporaneo unico per processo + fsync +
  `os.replace` con retry su `PermissionError` di Windows (un test con 2
  processi e un lettore concorrente aveva prodotto oltre 1.200 letture di
  JSON troncato con la versione a nome fisso). Se `config.json` è
  illeggibile ne resta una copia `config.json.illeggibile-<data>` prima che
  i default lo sovrascrivano.
- **`punctuation_restore_mode='auto'`** (nuovo default): segue il motore di
  trascrizione scelto (Canary e Qwen3: `missing`; faster-whisper non usa il
  ripristino). Le modalità `off|missing|all` restano una forzatura globale.
- `core/llm_subtitle_translator/translator.py`: canale di log del gestore
  batch verso lo schermo e reset del ritmo di riferimento (modifiche del
  12/09 già in uso in produzione, mai sincronizzate prima d'ora).

### Verifiche
- Due bugcheck Opus indipendenti sul codice scritto: trovati e corretti
  (perdita del lavoro con traduzione fallita e `X.en.srt` esistente,
  eccezioni di traduzione non gestite, collisione del file temporaneo di
  `Config.save()`, confidenza speaker minima che faceva perdere trattini,
  ripiego del formatter che poteva scrivere un SRT vuoto o ignorare un
  `save()` fallito).
- Test end-to-end su un estratto reale di 5 minuti (trascrizione,
  allineamento, diarizzazione, formattazione, traduzione, correzione genere:
  exit 0) e test del ramo di traduzione fallita.

### Valutato e NON adottato
- WhisperX come motore (stesso decoder; VAD/diarizzazione di default
  diversi), `initial_prompt`/`hotwords`, parametri anti-allucinazione di
  faster-whisper (ignorati in modalità batched) e Demucs a 44,1 kHz senza
  banco WER: nessuno ha dato un beneficio dimostrato.
- Aperti, non toccati: contesto tra battute consecutive nella traduzione
  (i blocchi tagliati a metà frase vengono tradotti come frammenti),
  banco WER per l'ASR, scelta di STEP 1 (sottotitoli non italiani anche con
  audio già italiano), sovrascrittura del sidecar OCR di `X.<lingua>.srt`.

## [1.18.0] — 2026-09-18

### Valutazione `pyannote/speaker-diarization-community-1` come alternativa a 3.1 — verdetto: NON promuovere
Dalla ricerca aggiornamenti venv: pyannote.audio 4.x introduce una pipeline
di diarizzazione più recente (clustering VBx invece di agglomerativo),
con benchmark pubblici migliori su 10/12 dataset. Valutata con lo stesso
rigore del banco `diar_eval/` già esistente (50 coppie etichettate a mano
su un film reale, Goodrich 2024).

- **Infrastruttura aggiunta, comportamento di produzione INVARIATO**:
  nuova chiave `diarization_model` (default `pyannote/speaker-diarization-
  3.1`, il comportamento storico), `Diarizer` accetta un `model_id`
  opzionale, `diar_eval/diar_bench.py` supporta `--model` per l'A/B.
  Verificato con un run di non-regressione: SRT prodotto bit-identico
  (stesso sha256) al run storico pre-refactoring.
- **`core/diarizer.py::_apply_clustering_overrides`**: community-1 usa
  VBxClustering, che ha `threshold` ma NON `min_cluster_size`. Aggiunta
  introspezione (`pipeline.parameters(instantiated=True)`) che scarta con
  avviso visibile i parametri non supportati dal modello caricato, invece
  di lasciarli sparire in un log che poi mente sull'esito. Un bugcheck
  Opus ha trovato che l'`instantiate()` di pyannote applica le chiavi una
  alla volta e solleva sulla prima sconosciuta: se l'introspezione stessa
  falliva, un override misto restava parzialmente applicato con l'except
  che azzerava comunque i valori "effettivi" nel log — corretto applicando
  ogni chiave separatamente.
- **Guardia esplicita** quando si eredita la soglia 0.85 (tarata su 3.1)
  su un modello diverso: su VBx la stessa chiave inizializza solo il
  clustering agglomerativo preliminare (default del modello 0.6,
  intervallo previsto dagli autori 0.5-0.8) — il numero non porta lo
  stesso significato, va ritarato.
- **Campagna A/B sul banco Goodrich** (C0 soglia di fabbrica 0.6, C1 0.7,
  C2 0.8, C3 0.85): nessun arm di community-1 batte la produzione attuale
  (`balanced_acc` 0.906). Il migliore (C3, 0.875) resta sotto la soglia di
  rumore statistico del banco (~4 punti). Confermato dopo il bugcheck che
  il confronto è onesto (`n_unmatched` — coppie senza parlato rilevato —
  pari a 0 su tutti gli arm confrontati). **Nessuna modifica al default di
  produzione.**
- Bug reale trovato e corretto in `diar_eval/diar_bench.py`: `threshold
  or None` collassava "0 esplicito" e "non specificato" sullo stesso ramo
  — l'unico modo di ottenere il default di fabbrica di un modello diverso
  da quello di produzione era scrivere nella config globale, esattamente
  ciò che la regola dello script vieta. Corretto con una sentinella a tre
  vie (`<0`=da config, `0`=default di fabbrica, `>0`=valore esplicito).

## [1.17.1] — 2026-09-18

### Upgrade `llama-cpp-python` 0.3.4→0.3.34 (ricerca aggiornamenti venv)
Da una ricerca sui venv del progetto per margini di miglioramento simili a
quello di Canary: `llama-cpp-python` (serbatoio L3 traduzione,
`fallback_translate_cli.py`) era 31 versioni patch indietro, con feature
di batching nel changelog aggregato dell'intervallo.

- La nota storica in `requirements.txt` ("solo 0.3.4 ha wheel pre-built
  CUDA per Windows cp311") era superata: esistono wheel CUDA Windows per
  ogni versione fino alla 0.3.35 (verificato con `pip install --dry-run`).
- **0.3.35 (latest) è rotta su questa macchina**: carica i tensori del
  modello su GPU senza errori ma va in crash all'inizializzazione del
  contesto (`OSError: Windows Error 0xc000001d`, istruzione illegale —
  sospetto AVX-512 disabilitato via microcode sui core Alder Lake hybrid
  P-core/E-core, non confermato riga per riga). Bisecting empirico
  0.3.4→0.3.35 caricando il GGUF multi-parte Qwen2.5-14B reale con i
  parametri di produzione: 0.3.16/0.3.26/0.3.31/0.3.33/0.3.34 funzionano
  tutte, solo 0.3.35 rompe. **Fermato a 0.3.34**, un solo patch sotto
  latest.
- Verificato end-to-end sul vero script di produzione
  (`fallback_translate_cli.py`, non solo la libreria isolata): traduzione
  di due frasi con glossario attivo, entrambe risolte correttamente.

## [1.17.0] — 2026-09-18

### Batching sulla trascrizione Canary-Qwen-2.5B (GPU sotto il 70% durante le trascrizioni)
Diagnosi partita da un'osservazione dell'utente: la GPU non superava il 70%
durante le trascrizioni con Canary. Causa: `core/engines/canary_cli.py`
chiamava `model.generate()` un chunk audio alla volta (batch_size=1) in un
for-loop sequenziale, mai sfruttando il supporto nativo al batching
dell'API NeMo SALM. Confermato con ricerca: lo script ufficiale NVIDIA
(`examples/speechlm2/salm_generate.py`) usa `batch_size=64` di default per
questo stesso modello, e il suo benchmark pubblico mostra l'inferenza
"offline" (non-streaming, il nostro caso) come la configurazione con il WER
migliore — nessuna prova che il batching degradi la qualità nell'uso
ufficiale.

- **Upgrade `nemo_toolkit`** in `venv_canary/` da 2.7.3 a 3.0.0 (major,
  repo NVIDIA rinominato in `NVIDIA-NeMo/Speech`). Solo il package NeMo,
  torch/CUDA invariati. Verificato che il flusso storico (batch=1)
  continua a funzionare prima di introdurre il batching.
- **Batching implementato**: `canary_cli.py` raggruppa i chunk in batch
  (`canary_batch_size`, default 8, nuova chiave in `utils/config.py`) e
  decodifica ogni riga del tensore risultato invece di assumere
  `answer_ids[0]`. `canary_engine.py` passa il batch size al subprocess.
- **Bugcheck indipendente** (agente Opus) ha trovato e corretto 3 bug
  reali prima della messa in produzione: (1) un disallineamento silenzioso
  testo↔chunk se `generate()` avesse restituito un numero di righe diverso
  dal batch — ora fa fallire esplicitamente invece di corrompere l'output
  in silenzio; (2) `batch_size` letto fuori dal blocco protetto: un valore
  rovinato a mano in config.json faceva crashare il subprocess prima che
  scrivesse l'esito, lasciando solo un "exit code 1" senza motivo nei log;
  (3) il set di token di stop non includeva il pad (che su questo
  tokenizer coincide con `<|endoftext|>`, usato da Qwen anche come
  fine-turno alternativo) — se il modello lo avesse emesso la riga sarebbe
  proseguita fino a `max_new_tokens` con testo spazzatura in coda. Aggiunto
  anche un ripiego che dimezza il batch se la VRAM non basta.
- **Misurato** (GPU reale, 6 clip di durata diversa): testi identici a
  parola per parola tra batch_size=1 e batch_size=6 in 5/6 clip; nella
  sesta le parole coincidono, cambia solo punteggiatura/maiuscole — nessun
  errore di contenuto osservato. VRAM 5,19→5,56 GB (batch 1→6 su 12 GB
  disponibili): il default 8 è misurato sicuro. Ordine dei testi verificato
  stabile anche con batch disuguali e ordine invertito.

## [1.16.2] — 2026-09-17

### Fix: il padding fisso del placeholder di glossario introduceva nuovi artefatti (bugcheck indipendente)
Il fix v1.16.1 aveva chiuso il bug "Garnet"→"Granato" mascherando anche le
identità sul motore LLM e ripulendo a valle, con regex, lo spazio spurio che
il padding `f" {token} "` introduceva vicino a punteggiatura/virgolette.
Un bugcheck indipendente su quel codice ha trovato che la ripulitura a
valle era essa stessa fonte di bug reali, riproducibili con input concreti:

- `"Mornin' Garnet."` → il regex leggeva l'apostrofo dialettale come
  virgoletta di apertura e incollava il placeholder al testo:
  `"Mornin'<GLOSS0>."`.
- `'"Get out," Garnet said.'` → la virgoletta dritta è ambigua (lì chiude,
  non apre) e veniva trattata sempre come apertura: `'"Get out,"<GLOSS0> said.'`.
- Con un glossario attivo ma nessun termine sulla riga, la ripulitura
  riscriveva anche punteggiatura estranea al glossario (es. un'ellissi
  `". . ."` compattata a `"..."`).
- Annidamento musica/glossario in `_unmask_tolerant`: un placeholder di
  glossario dentro un blocco `♪...♪` (es. `"Garnet!\n♪ Sail on, Ark ♪"`)
  veniva cercato nell'ordine sbagliato e dichiarato irrecuperabile pur
  essendo stato tradotto perfettamente — il blocco finiva nel recupero
  senza mascheramento, riaprendo esattamente il bug che il fix chiudeva.

**Correzione**: invece di aggiungere padding e poi ripulirlo con regex
(che devono indovinare se un apostrofo/virgoletta adiacente apre, chiude o
è una contrazione — casi che a volte richiedono l'opposto l'uno
dell'altro), il padding non viene più inserito affatto sul ramo non-NLLB:
il pattern di ricerca del termine è già ancorato a `\b` su entrambi i
lati, quindi il carattere adiacente al termine nel sorgente non è mai un
carattere di parola — il padding non separava nulla che non fosse già
separato, raddoppiava spazi esistenti o ne inventava dove l'autore non li
aveva. Il padding resta solo su NLLB (comportamento pre-esistente,
invariato — non misurato lì). Corretto anche l'ordine di risoluzione in
`_unmask_tolerant` per l'annidamento musica⊃glossario. Verificato: NLLB
bit-identico al pre-fix, tutti i casi sopra puliti senza elencare
apostrofi/virgolette caso per caso.

## [1.16.1] — 2026-09-17

### Fix: glossario per-show ignorato sui nomi propri identità con il motore LLM (TranslateGemma)
Diagnosi partita da un episodio reale (The Ark S03E08): il personaggio
"Garnet" tradotto come "Granato" (il nome comune inglese della pietra),
nonostante il glossario della serie avesse la voce corretta
`"Garnet": "Garnet"`.

- **Causa 1** (`core/translator.py::_mask_glossary`): le voci di glossario
  "a resa identità" (termine e resa uguali, es. `"FTL": "FTL"`,
  `"Garnet": "Garnet"`) non venivano mai mascherate su NESSUN motore — una
  regola pensata per NLLB (misurato: 8/24 blocchi rimasti in inglese per un
  singolo placeholder identità, decoder word-level che non regge un token
  opaco) ma applicata anche al motore LLM, dove non era mai stata misurata
  alcuna regressione analoga. Un'identità che coincide con una parola
  inglese comune restava quindi esposta alla traduzione letterale, e il
  controllo a valle (`_apply_glossary_posthoc`) non la intercetta perché
  cerca il termine INGLESE ancora presente nell'italiano, non una resa
  sbagliata plausibile. Il salto ora vale solo per NLLB.
- **Causa 2**, scoperta misurando il fix della causa 1 su TranslateGemma-12B
  reale: il placeholder veniva inserito con spazi fissi su entrambi i lati
  (`f" {token} "`), producendo doppio spazio o uno spazio prima della
  punteggiatura quando il termine confinava con virgola/punto
  ("you,  &lt;GLOSS0&gt; ."). Con questo artefatto TranslateGemma scartava
  silenziosamente il placeholder dalla generazione, facendo fallire la fase
  mascherata e facendo cadere il blocco nel recupero senza mascheramento —
  riesponendolo alla stessa causa 1. Normalizzata la spaziatura (solo spazi
  orizzontali, per non fondere i newline dei blocchi dialogo multi-parlante;
  solo fuori da NLLB, mai misurato lì). Verificato su rerun reale
  dell'episodio: blocchi da recuperare 29→21 su 719, nessuna riga di
  dialogo fusa, riga del personaggio corretta.

## [1.16.0] — 2026-09-08

### Fix: pipeline di trascrizione audio — 3 difetti reali diagnosticati e corretti su un film reale
Diagnosi partita da un file prodotto in produzione (Goodrich 2024, audio
italiano trascritto direttamente): duplicati da chunk sovrapposti, testo
sulla riga del personaggio sbagliato, ~30% dei blocchi senza punteggiatura
nelle scene di crosstalk/dialogo concitato.

- **Bug chunker** (`core/audio_processor.py::chunk_audio_intelligent`):
  l'estensione di un chunk troppo corto poteva sconfinare fisicamente nel
  chunk successivo → stessa battuta trascritta due volte con timestamp
  leggermente diversi. Fix + rete di sicurezza finale che garantisce
  `chunk[i].end <= chunk[i+1].start` per costruzione. Verificato: 12
  salti temporali all'indietro → 0 su rerun reale.
- **Gate di confidenza sul trattino di dialogo** (`core/subtitle_
  formatter.py`, `core/diarizer.py`): il trattino "- " veniva assegnato
  solo su gap/lunghezza, senza verificare l'affidabilità dell'attribuzione
  speaker — un'attribuzione debole diventava un trattino permanente sulla
  riga sbagliata. Nuovo campo `speaker_confidence` per segmento, soglia
  minima (`DASH_CONFIDENCE_MIN`) prima di concedere il trattino.
- **Chunk audio configurabili + cap per engine** (`asr_chunk_target/min/
  max_duration`, `ENGINE_CHUNK_CAP_S` in `core/audio_processor.py`):
  durata chunk non più fissa a 20s, cappata per engine (Canary ≤35s,
  Qwen3 ≤150s, whisper ≤30s) per non rompere i limiti di ciascun motore.
- **Fix `qwen3_max_new_tokens`**: il cap di generazione era fisso a 256,
  già al limite di troncamento su chunk densi da 25s. Ora 0 = calcolato
  automaticamente dalla durata massima dei chunk configurata.
- **Riscrittura assegnazione word-level** (dietro
  `diarization_word_vote_enabled`, default `False` — non ancora
  promossa): voto pesato sull'overlap invece del lookup a midpoint,
  politica esplicita sulle run corte (interiezioni come "Sì."/"No.")
  invece della fusione automatica nella run precedente. Percorso storico
  intatto e ancora attivo di default.
- **Nuovo modulo `core/punctuation_restorer.py`** — ripristino
  punteggiatura sui chunk ASR completamente privi di essa (modello
  dedicato `oliverguhr/fullstop-punctuation-multilang-large`, CPU,
  garanzia strutturale 1:1 parole/timestamp). **Promosso a default**
  (`punctuation_restore_mode='missing'`) dopo validazione mirata su 22
  frasi campione (invariante sempre rispettata, un solo errore che
  alterava il senso su 22 casi). Limite noto: il modello non produce mai
  "!" (classi di addestramento fisse, non un bug).
- **Soglia di clustering pyannote promossa a default**
  (`diarization_clustering_threshold=0.85`, contro lo 0,7046 calibrato
  dal produttore del modello): riduce nettamente il sovra-clustering
  (27→12 "parlanti" osservati) misurato con una campagna di taratura
  dedicata — nuovo banco riutilizzabile **`diar_eval/`** (`diar_bench.py`
  + `metrics.py`, sottocomandi prepare/run/gold-make/gold-score/sweep-c),
  50 coppie audio etichettate a mano come insieme oro. **Nota onesta**:
  un ricalcolo successivo ha mostrato che il segnale statistico sulla
  metrica aggregata era debole (differenza non significativa, test di
  McNemar p=1,00, su un campione di quella taglia) — la soglia resta una
  decisione esplicita, non un risultato schiacciante, da ricontrollare
  per primo se emergono sintomi di sovra-fusione su film di generi
  diversi da quello testato.
- Tre bug trovati dall'utente stesso durante l'etichettatura manuale
  dell'insieme oro (margine di contesto che mescolava due voci sui turni
  adiacenti, micro-turni pyannote da 17ms campionati per errore, parsing
  CSV che si rompeva su file salvati da Excel in locale italiano) —
  tutti corretti in `diar_eval/diar_bench.py`.

## [1.15.0] — 2026-09-06

### Fix: correzione della diagnosi PAL/NTSC della v1.14.0 — il drift non era il problema, era il gate
- **Origine**: l'utente ha messo in dubbio la voce "drift PAL/NTSC non gestito"
  della v1.14.0, facendo notare che gli anchor sono timestamp VERI per-riga
  presi dalla traccia embedded del video stesso (o da Whisper sul suo
  audio), non un offset/fattore di scala globale — quindi il matching
  per-riga dovrebbe essere di per sé immune al drift.
- **Verificato con un bugcheck dedicato**: con un matcher semanticamente
  perfetto (zero allucinazioni, solo drift PAL simulato) e il gate di
  offset DISATTIVATO: 100% esatto, errore massimo 0,0s. Confermato: il
  gate introdotto nei round precedenti confrontava ogni timestamp
  candidato con la posizione ORIGINALE (sempre più sbagliata su un file
  con drift) del sottotitolo esterno, scartando come "implausibili" match
  CORRETTI verso la fine del film; la stessa cattura delle finestre non
  proponeva il 65% delle righe di fine film alla finestra giusta.
- **Fix implementato**: `core/subtitle_synchronizer.py` — nuovo modello di
  shift lineare (`_expected_shift`/`_learn_shift`, fit Theil-Sen sui match
  già accettati, raffinato finestra dopo finestra, con controllo di
  qualità obbligatorio che disattiva il modello — comportamento identico a
  prima — se il fit non è affidabile). Il gate di plausibilità e lo slack
  di cattura ora confrontano con la posizione ATTESA (appresa) invece di
  quella originale grezza.
- **Verificato**: drift PAL puro (matcher perfetto) → 100% esatto, errore
  massimo 0,0s, pendenza appresa 0,0427 (vero rapporto 25/23,976); nessun
  drift + 100% allucinazioni → modello resta disattivato, comportamento
  identico a prima (nessuna regressione).

## [1.14.0] — 2026-09-05

### Fix: sincronizzazione SRT "Anchor & Match" — mai validata prima, tre giri di revisione
- **Causa radice (BUG1+2+3+4 combinati)**: finestre di matching sovrapposte
  con merge "vince la prima finestra arrivata" + fallback posizionale che
  sparge le righe non risolte su tutto il film + split codice morto (timestamp
  identici per le due metà) + un formatter di un'altra feature che fondeva
  cue con timestamp identici perdendo battute. Misurato: 50% delle righe
  sbagliate in silenzio su una simulazione di film intero, nessun errore,
  "Sincronizzazione Completata".
- **Fix round 1**: merge per confidence migliore invece che per ordine di
  arrivo; nuovo `_interpolate_fallback` (shift dai vicini risolti, non
  rapporto d'indice su tutto il film); split riscritto (`match_type`
  controllato prima dei timestamp, nuovo `_find_split_partner`); rimosso
  `SubtitleFormatter` dal percorso di scrittura (scrive solo i tempi,
  preserva testo/formattazione utente); +8 fix minori (lingua anchor mai
  rilevata, correzione genere no-op per `video_path` mancante, buco di
  copertura finestre in coda, ecc.). Verificato: 100% esatto sulla stessa
  simulazione.
- **Fix round 2** (dopo che una seconda revisione ha misurato il fix del
  merge come solo parziale — 22% di righe ancora sbagliate, perché la
  confidence auto-riportata da Qwen è quasi sempre ≈1.0 anche sui match
  sbagliati): **gate di offset globale** — nessuna riga può spostarsi oltre
  `sync_max_offset_sec` (nuova chiave config) dalla sua posizione originale,
  indipendentemente da cosa dichiari il modello. Slack di cattura
  disaccoppiato dal gate di plausibilità. Corretta anche una regressione
  introdotta nello stesso giro: normalizzare la lingua dell'anchor senza
  gestire tag reali come `pob`/`pt-BR`/`en-US` faceva fallire l'intera
  sincronizzazione invece di limitarsi a tradurre peggio.
- **Fix round 3** (bugcheck + bugfix diretto): il gate del round 2 aveva un
  bypass completo sul ramo split (fino a 176s di errore, non coperto dal
  gate); slack di cattura matematicamente sbagliato (`2×` invece del bound
  stretto `offset+5`); collisione a 3+ cue con lo stesso timestamp non
  gestita; **regressione GUI**: chiudere il dialog con la X ora chiamava sia
  `closeEvent` sia `reject()`, raddoppiando l'attesa di spegnimento a 60s.
  Tutti corretti. Verificato su un episodio reale da 794 righe (20%
  allucinazioni + 10% split simulati): 0 cue invertite, 0 sovrapposte, errore
  massimo 38.0s contro un limite teorico di 39.5s.
- Sincronizzazione, coda principale e strumento glossario ora mutuamente
  esclusivi (stessa GPU).
- **Aperto, non affrontato**: rilevazione del drift progressivo PAL/NTSC
  (25↔23,976fps) — il desync che cresce lungo il file invece di restare
  costante non viene riconosciuto come caso a parte. Misurato ~79% delle
  righe fuori tolleranza su un file con questo tipo di drift. Il gate
  rifiuta correttamente di indovinare oltre `sync_max_offset_sec` (logga un
  avviso esplicito quando succede) invece di produrre un risultato sbagliato
  con sicurezza, ma non risolve il problema: serve un fix di design
  dedicato (es. stima e compensazione di un fattore di scala lineare sul
  tempo, non solo di un offset costante).
- Aperto, rimandato: l'intera pipeline gira ancora nel processo GUI invece
  che in un subprocess isolato (`core/sync_cli.py` sul modello di
  `core/gender_corrector_cli.py`); l'annullamento non interrompe una singola
  chiamata al modello già in corso; le chiavi `sync_*` non hanno UI nelle
  Opzioni.

## [1.13.0] — 2026-09-05

### Fix: upload OpenSubtitles — funzionante per la prima volta, verificato con 4 upload reali
- **Causa radice**: `utils/opensubtitles_xmlrpc_uploader.py` comprimeva
  `subcontent` con gzip; il protocollo XML-RPC di opensubtitles.org si aspetta
  zlib. Il server decomprimeva a stringa vuota → sia "403 SubHashes non
  corrispondono" sia "402 formato non valido" da un'unica causa. Corretto
  (`zlib.compress`) e verificato con 4 upload reali riusciti (Brilliant Minds
  S02E17-E20, IDSubtitle 14025912/14025925/14025926/14025927).
- opensubtitles.org e opensubtitles.com sono account separati con credenziali
  proprie: nuove chiavi config dedicate `opensubtitles_xmlrpc_username`/
  `_password` (`utils/config.py`) + campi Opzioni separati
  (`gui/opensubtitles_settings_widget.py`). La diagnosi storica "User-Agent
  non registrato" per il 401 di XML-RPC era sbagliata (quella registrazione
  non è più disponibile dal 2022): `authenticate()` ora riporta "credenziali
  sbagliate per questo account".
- L'endpoint REST `/upload` usato dal codice non esisteva (404, percorso
  inventato). Il percorso reale `/api/v1/subtitles/upload` risponde
  `403 uploads_not_enabled` per API key normali — funzione opt-in, va
  richiesta a OpenSubtitles. Costante corretta; REST non è più il default
  per l'upload (lo è XML-RPC), rimosso il fallback automatico verso REST
  (non poteva mai funzionare, indipendentemente dall'esito XML-RPC).
- `utils/tmdb_client.py`: IMDb ID di episodio (non solo di serie) per gli
  upload di serie TV, via `external_ids` per-episodio con fallback a quello
  di serie.
- `core/pipeline.py`: tabella esplicita ISO 639-1→639-2 per l'upload (prima
  una dict-comprehension d'inversione sceglieva il codice sbagliato per
  tedesco/olandese/ceco/**rumeno→russo**/greco); `utils/opensubtitles_rest_uploader.py`
  ritorna `None` su codice lingua non mappato invece di indovinare — l'upload
  si interrompe invece di inviare la lingua sbagliata.
- Fix crash: "Test connessione" con credenziali incomplete sollevava
  `AttributeError` fuori dal `try/except` del metodo, abbattendo l'app.
- Rimossi `utils/opensubtitles_client.py`, `utils/opensubtitles_integration.py`,
  `utils/opensubtitles_config.py` (mai usati in produzione; uno di questi
  fingeva sempre successo senza chiamare alcuna API).
- Altri: credenziali non salvate cancellate cambiando metodo API; tooltip
  non aggiornato; gate credenziali del traduttore "OpenSubtitles AI"
  disallineato da quello dell'upload; controllo duplicati ridondante con
  quello già interno all'upload XML-RPC.

**Nota**: un test diagnostico dal vivo contro l'API reale (prima del fix) ha
pubblicato anonimamente un sottotitolo grezzo (non ripulito) per l'episodio
S02E17 — resta online accanto a quello corretto, non rimovibile da codice
(nessun account associato), segnalazione a OpenSubtitles necessaria.

## [1.12.2] — 2026-09-05

### Fix: strumento glossario per-show — cartelle stagione, subprocess GPU orfano, contesa GPU con la coda
- Corretto `tmdb_id` sbagliato scritto in silenzio quando la cartella scelta è
  la sottocartella stagione di una libreria Plex (`V:\Show\Season N\...`): il
  nome "Season 2" degradava a "Season" nel parsing e trovava un risultato TMDB
  estraneo. `gui/glossary_dialog.py`: riconoscimento cartelle stagione/speciali
  multilingua + lista di titoli candidati (cartella padre, poi titolo estratto
  dal primo file episodio) prima di chiamare `search_tv()`.
- `gui/glossary_worker.py`: annullare il tool lasciava un subprocess GPU orfano
  con ~9GB residenti in VRAM (il canale Qwen lo lancia sul venv principale,
  `terminate()` su Windows non si propaga ai discendenti) — ora traccia il PID
  e uccide l'intero albero (`taskkill /T`).
- `gui/main_window.py`: strumento glossario e coda di trascrizione/traduzione
  resi mutuamente esclusivi (stessa GPU, contesa altrimenti silenziosa).
- `qwen_n_gpu_layers` reso configurabile per-show (`core/glossary_builder_cli.py`,
  prima cablato nel codice).

## [1.12.1] — 2026-09-05

### Fix: batch manager adattivo cieco alla contesa GPU esterna
- Misurato su un run reale: due traduzioni NLLB in parallelo hanno fatto salire
  la memoria dal 50% all'85% mentre il nostro batch restava a 24, e il gestore
  lo riduceva comunque — non libera memoria altrui, e ha misurabilmente
  peggiorato il tempo per frase del 62% (0,271s → 0,438s).
- Nuovo `_external_pressure_gb()` (`utils/adaptive_batch_manager.py`):
  `torch.cuda.memory_reserved()` (quota di questo processo) vs memoria totale
  usata; sopra 1,5GB di scarto il gestore tiene la dimensione invece di ridurre.
- **Bug trovato e corretto nella stessa guardia durante il bugcheck**: campionava
  solo dentro `mem > high_threshold`, quindi su un file che incontra la contesa
  a metà la prima lettura cadeva già a contesa iniziata e la registrava come
  normale — guardia inerte esattamente sul caso per cui esisteva. Corretto
  campionando a ogni batch.
- Guardia temporale ms/token (NLLB) e ms/carattere (LLM) in `core/translator.py`
  e `core/llm_subtitle_translator/translator.py`: zero eventi OOM reali in tutto
  lo storico dei log (WDDM pagina in RAM di sistema invece di sollevare
  un'eccezione CUDA) — l'unica firma reale è il tempo che risale. Solo
  diagnostica (un log se ≥2× più lento del ritmo migliore del file), nessuna
  riduzione automatica.
- Risalita del batch moltiplicativa invece di +1 dopo la fine di una contesa.
- Analisi su 875 batch reali (23 run) pubblicata come artifact: la soglia di
  riduzione esistente (85%) è già ben calibrata — non toccata.

## [1.12.0] — 2026-09-05

### Fix: righe non tradotte rimaste silenziosamente in inglese (glossario per-show)
- Causa radice: quando un placeholder di mascheramento del glossario (`<GLOSS0>`) non
  veniva riprodotto fedelmente dal modello, il ripiego esistente riportava l'originale
  inglese — ma l'avviso passava da `logger.warning()` con un `logging.getLogger()` nudo,
  mai attaccato al file di log condiviso né alla GUI: il fallimento non lasciava
  **nessuna** traccia diagnosticabile.
- Sostituita la logica con una catena di recupero a 5 livelli, condivisa da ramo NLLB e
  ramo LLM: (L0) il glossario non maschera più i termini a resa identica (es. "FTL"→"FTL"),
  che non avevano nulla da guadagnare dal placeholder e tutto da perdere; (L1) unmask
  tollerante che ripara placeholder storpiati (spazi, maiuscole, parentesi perse); (L2)
  ritraduzione senza mascheramento sul motore primario ancora in VRAM, con glossario
  applicato a posteriori; (L3) "serbatoio" — un solo swap di modello a fine file per ciò
  che sopravvive, deduplicato per testo sorgente; (L4) inglese, ma con log rumoroso e
  visibile, mai più silenzioso.
- Nuovo audit indipendente a fine file (`_is_untranslated`/`_log_audit`): confronto di
  identità normalizzata sorgente↔output, indipendente da qualunque meccanismo di
  recupero — cattura anche cause future non ancora previste.
- Motore del serbatoio (`reservoir_engine`, nuova chiave config) scelto da una misura
  reale: valutazione testa a testa GEMBA-MQM su 39 righe corte dense di glossario da 4
  show ha trovato NLLB fine-tuned nettamente migliore di Qwen2.5-14B (64% vs 26% di
  preferenza, MQM pesato 1,41 vs 4,31). Default: sempre un motore diverso dal primario
  già in uso (NLLB-FT se il primario è l'LLM, Qwen se il primario è NLLB).
- Nuovo `core/fallback_translate_cli.py`: entrypoint subprocess isolato per il motore
  Qwen del serbatoio (stesso contratto di `core/gender_corrector_cli.py`).
- 8 bug aggiuntivi trovati e corretti in revisione, tra cui una chiamata a
  `_apply_fallback` mai definita nel progetto (crashava l'intera traduzione del file su
  un singolo blocco vuoto), sostituzione di glossario a posteriori che si fermava alla
  prima occorrenza di un termine ripetuto, e un bug preesistente di batch duplicato nel
  percorso di retry-errore del ramo NLLB.
- Verificato su episodio reale con glossario attivo (24/24 righe prima silenziosamente
  inglesi risolte) e su batch di produzione di 21 file (20 con glossario + 1 senza, come
  controllo di non-regressione).

## [1.10.1.22.8.26] — 2026-08-22

### Fix: cache del modello LLM di produzione cancellata a ogni fine coda
- Il modello LLM che occupa lo slot di produzione (oggi TranslateGemma-12B)
  veniva scaricato nella cache HuggingFace e poi ricancellato a fine coda da
  `cache_cleaner.py`: la lista di preservazione copriva solo i motori ASR
  (whisper/wav2vec), non il ramo di traduzione LLM. L'adattatore LoRA
  fine-tuned promosso in produzione non era coinvolto (vive su disco fuori
  dalla cache HF). Il cleaner ora risolve a runtime quale modello occupa lo
  slot (chiave config `llm_translator_model`, con lo stesso ripiego sul
  default già usato da `LLMSubtitleTranslator`) e lo preserva; i modelli
  usati solo per confronti sperimentali continuano a essere cancellati come
  prima.

## [1.10.1] — 2026-08-18

### Rimosso il percorso "adapt" del ramo LLM: disallineava battute e tempi
- Il ramo LLM interrogava il modello in due modi: "mt" (una battuta per
  conversazione, l'output è direttamente la traduzione) e "adapt" (un gruppo
  di blocchi in JSON con id, che il modello doveva restituire intatti). Sotto
  una certa taglia i modelli sbagliavano gli id — fondevano due blocchi e
  scrivevano le traduzioni successive nel posto sbagliato — con i tempi
  ancora corretti, quindi il file sembrava sano. Il percorso era ormai
  irraggiungibile dall'interfaccia (nessun motore attivo lo usa più, dopo la
  rimozione di Aya in v1.10.0) e rischiava di essere ereditato per difetto da
  un futuro modello aggiunto senza dichiararlo esplicitamente. Rimosso
  interamente; resta solo "mt", immune al problema per costruzione (una
  conversazione per battuta, nessun id da sbagliare). Validato end-to-end col
  modello di produzione su un SRT con tutti i casi (marcatore musicale,
  lirica, dialogo coi trattini, turpiloquio): zero retry.

## [1.10.0] — 2026-08-17

### Motore di traduzione LLM riscritto, TranslateGemma-12B sostituisce Aya
- Il ramo LLM (`core/llm_subtitle_translator/`) è stato riscritto come
  package model-agnostic con un registro `MODEL_SPECS`, correggendo quattro
  difetti del vecchio ramo Aya che ne rendevano la misura priva di senso:
  prompt senza chat template, `padding_side` di default che corrompeva ogni
  batch maggiore di uno, `output.split('\n')[0]` che scartava la seconda
  battuta di ogni dialogo, fallback che scriveva la frase inglese originale
  nell'SRT finale.
- Valutazione su banco sintetico prima e su film reali poi (Deadpool 2, A Man
  Called Otto, con i sottotitoli professionali come riferimento): il banco
  sintetico dava TranslateGemma-12B vincente, ma sui blocchi reali il
  verdetto si ribalta — **NLLB fine-tuned resta il motore di produzione**,
  davanti a TranslateGemma-12B e Aya su tutte le varianti testate (giudice
  GEMBA-MQM, 400 segmenti per confronto, due film). Instradamento per quality
  estimation (CometKiwi) testato e bocciato: indovina il motore migliore solo
  nel 59% dei casi.
- Aya rimossa dal registro (perdeva ogni confronto e il suo percorso "adapt"
  poteva disallineare battute e tempi su blocchi consecutivi, vedi v1.10.1).
  `DEFAULT_MODEL_KEY` passa a `translategemma-12b`; le configurazioni
  esistenti con `aya` vengono migrate automaticamente.
- **Bug critico trovato eseguendo per la prima volta il percorso reale della
  pipeline** (STEP 6 → `get_translator` → `translate_file` → `_polish`, mai
  esercitato prima su un file vero): NLLB traduceva il **contesto** (la trama
  del film) al posto della battuta stessa, non essendo un modello con prompt
  di sistema. Il contesto resta passato e utile solo ai motori che sanno
  usarlo (ramo LLM, Claude, OpenAI).
- Blocchi di dialogo a due voci consegnati appiattiti su una riga sola dal
  ramo NLLB: nuova riparazione in post-processing che li divide di nuovo sul
  trattino interno.
- Marcatori musicali in convenzione USA (`**testo**`, non solo `♪testo♪`)
  allucinati dal modello TranslateGemma 48 volte su 48 nei test: la maschera
  che protegge i blocchi non traducibili ora copre qualunque blocco senza
  nessuna lettera, non solo l'elenco esplicito di simboli.
- Post-processing tipografico condiviso in `BaseTranslator._generate_srt`:
  righe fuori norma dal 59,3% al 9,7%, per tutti i motori (NLLB, Claude,
  OpenAI, ramo LLM).
- Barra di progresso del ramo LLM allineata a quella di NLLB (si aggiorna
  in-place invece di riempire il registro riga per riga), con stima del
  tempo rimanente.
- `.gitignore`: chiusi quattro buchi da complessivamente ~12 GB
  (`venv_canary/`, `venv_comet/`, corpus di addestramento Gemma in crescita,
  checkpoint NLLB fine-tuned) — il pattern copriva solo la cartella `venv/`
  esatta, non le altre virtual-env del progetto.

## [1.9.7] — 2026-08

### Fix fusione battute nei blocchi dialogo multi-parlante
- NLLB non garantisce la preservazione dell'a capo quando traduce un blocco
  di sottotitoli a due parlanti (testo con newline interno tra le due
  battute): a volte le fondeva in un'unica riga, a volte inseriva persino
  trattini propri spuri, producendo blocchi come "- Vorrei che tu fossi
  qui. Anch'io." invece di due righe separate correttamente attribuite. I
  blocchi dialogo (identificati dai marcatori "- " già tracciati) vengono
  ora tradotti riga per riga anziché come blocco unico, garantendo per
  costruzione che il conteggio righe post-traduzione resti sempre fedele
  all'originale.

## [1.9.6] — 2026-08

### Fix critico: lingua sorgente NLLB ignorata per qualunque lingua diversa dall'inglese
- Il tokenizer NLLB richiede `tokenizer.src_lang` impostato ad ogni chiamata
  per taggare correttamente la lingua del testo in input. Questo valore non
  veniva mai impostato e restava bloccato sul default caricato al momento
  del `from_pretrained()` (`eng_Latn`) — qualunque traduzione con sorgente
  diversa dall'inglese (tedesco, francese, spagnolo, russo, ecc.) veniva
  quindi tokenizzata come se il testo fosse inglese, causando frasi lasciate
  non tradotte o allucinazioni del modello. Verificato empiricamente su un
  campione di frasi tedesche: 5/10 non tradotte senza il fix, 0/10 con il
  fix applicato. Il bug era presente fin dall'introduzione del modulo NLLB e
  ha interessato ogni traduzione con sorgente non inglese.

### Fix minori (naming file e correzione genere su input .srt)
- Quando l'input della pipeline è già un file `.srt` con codice lingua nel
  nome (es. `Movie.en.srt`), il nome del file finale non includeva più
  correttamente solo la lingua di destinazione (produceva `Movie.en.it.srt`
  invece di `Movie.it.srt`).
- La correzione di genere grammaticale (STEP 6.5) andava in errore quando
  l'input della pipeline era già un `.srt`: tentava di estrarre l'audio con
  ffmpeg direttamente dal file dei sottotitoli invece di risolvere il video
  reale corrispondente nella stessa cartella.

## [1.9.5] — 2026-07

### Fix batch adattivo di traduzione, seconda puntata
- Il tetto statico per classe introdotto in v1.9.3 (NLLB `max_size=24`)
  riduceva ma non eliminava lo sconfinamento sostenuto in RAM condivisa in
  alcuni run reali, e non era legato alla lingua sorgente come ipotizzato
  inizialmente: erano due lacune nella logica reattiva del batch manager.
  (1) Durante il warm-up il manager poteva solo *aumentare* il batch — non
  controllava mai la pressione di memoria per ridurlo, quindi sui file corti
  (la maggior parte delle traduzioni gira in meno di 10 batch) l'intero file
  poteva concludersi con un batch sovradimensionato e la memoria GPU satura.
  (2) `torch.cuda.empty_cache()` girava solo ogni 10 batch, soglia che quegli
  stessi file corti non raggiungevano mai, quindi la cache dell'allocator di
  PyTorch non veniva mai restituita al driver. Entrambi i punti ora reagiscono
  alla lettura di memoria reale ad ogni batch, warm-up incluso. Verificato
  sullo stesso file che aveva causato la segnalazione originale: lo step di
  traduzione è passato da 800 s (13 m 13 s) con 2,44 GB di sconfinamento
  sostenuto in RAM condivisa a 196 s (3 m 16 s) con solo un picco transitorio
  di ~19 s.

## [1.9.4] — 2026-07

### Fix spaziatura diarization multi-engine
- Le frasi divise dalla speaker diarization per cambio di parlante potevano
  comparire con le parole attaccate ("Sièe trasferitadapoco" invece di "Si è
  trasferita da poco") quando la trascrizione proveniva dagli engine
  Qwen3-ASR o Canary. Causa: la ricostruzione del testo del sotto-segmento
  assumeva la convenzione di spaziatura di faster-whisper (spazio incorporato
  a inizio parola), non valida per gli altri due engine. Corretto con una
  normalizzazione della spaziatura indipendente dall'engine.

## [1.9.3] — 2026-07

### Fix batch adattivo di traduzione
- Il batch manager di NLLB / NLLB fine-tuned / Aya-23 ignorava il tetto
  storico della propria classe e seguiva solo la soglia di configurazione
  condivisa con la trascrizione, causando in alcuni casi lo sforamento della
  VRAM dedicata con spillover silenzioso in RAM condivisa (Windows/WDDM non
  genera un errore di memoria in quel caso, solo un forte rallentamento).
  Ora ogni traduttore rispetta il proprio tetto di batch storicamente sicuro.

## [1.9.2] — 2026-07

### Ancoraggio sottotitoli alle battute + fix batch adattivo
- La regola anti-frammento riunisce la coda corta solo se è un vero frammento
  della stessa frase (pausa ≤ 0,8 s e frase non conclusa) — niente più blocchi
  con due battute distanti nella stessa riga.
- Fix batch adattivo trascrizione: lettura memoria a livello device, cap batch
  16, tetto VRAM-aware anche in modalità classica (su Windows/WDDM lo
  sforamento VRAM non dà OOM ma spillover silenzioso in RAM condivisa).
- Barra di progresso non più interrotta dai log di aggiustamento batch.

## [1.9.1] — 2026-07

### Ottimizzazione picco memoria Demucs
- Tensori residenti su CPU: `apply_model` sposta sulla GPU solo il segmento in
  lavorazione → picco VRAM costante (~0,6 GB) indipendente dalla durata del
  file (prima: >21 GB GPU committed su un episodio da 83 min).
- Unload anticipato di Demucs e Whisper a fine STEP 3 quando l'engine
  pianificato è Qwen3 / Canary.

## [1.9.0] — 2026-07

### Stile dialoghi professionale (Netflix)
- Trattini "- " solo quando due parlanti condividono lo stesso blocco SRT
  (una battuta per riga); speaker diarization estesa a tutti gli engine
  (opzione `dialogue_style_enabled`, default ON, richiede token HuggingFace).
- Trattini preservati anche negli SRT tradotti (tutti e 4 i backend).
- Nuovo `core/subtitle_formatter.py`: CPL 42, anti-flash, merge frammenti,
  raggruppamento dialoghi.

## [1.8.1] — 2026-07

- Fix: il gender corrector non gira più sulle trascrizioni in italiano nativo
  (senza traduzione).

## [1.8.0] — 2026-07

### Trascrizione multi-engine con routing automatico per lingua
- **NVIDIA Canary-Qwen-2.5B** (solo inglese, WER migliore; opzionale, richiede
  `venv_canary` dedicato con NeMo 2.7.3).
- **Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B** (pacchetto pip `qwen-asr`):
  11 lingue con timestamp word-level (zh, en, yue, fr, de, it, ja, ko, pt, ru,
  es), auto-detect lingua nativo.
- **Faster-Whisper large-v3** come fallback universale garantito: la pipeline
  non fallisce mai per colpa di un engine nuovo.
- Un solo engine ASR in VRAM per volta.
- Nuove chiavi config: `transcription_engine_mode` (auto / canary / qwen3 /
  faster-whisper), `canary_enabled`, `qwen3_enabled`; combo di selezione
  engine nelle impostazioni profilo.

## [1.7.0] — 2026-07-16

### Avvio senza freeze UI
- Tab Traduzione da 3719 ms a 15 ms; I/O asincrono; torch mai importato nel
  processo GUI (check ambiente via CLI esterna); splash in ~2 s.

## [1.6.1] — 2026-07-15

- Fix (GUI): rimosso "(LLM)" dall'etichetta della checkbox correzione genere.

## [1.6.0] — 2026-07-15

### Gender Corrector v2 — redesign completo (audio-driven, deterministico)

Il correttore di genere LLM (Qwen2.5-14B GGUF) è stato sostituito integralmente:
misurato sul benchmark, correggeva 2 errori su ~90 (+0,66 punti — di fatto inerte).

**Nuovo approccio**: il genere di chi parla non è deducibile dal testo
("I'm tired" non dice se parla un uomo o una donna) — ma è nella **voce**.

- **Speaker Gender Map** (`core/speaker_gender.py`): diarization pyannote +
  classificatore ECAPA (VoxCeleb2) → genere di ogni parlante con confidenza.
  Accuratezza 95,0% (validata su 22 episodi contro sottotitoli professionali).
- **Selettore morfosintattico** (`core/gender_line_selector.py`, spaCy in venv
  separato): individua le sole forme di 1ª/2ª persona che concordano col
  parlante/interlocutore; esclusioni blindate (participi con *avere*,
  modificatori nominali, dialoghi doppi, impersonali...).
- **Riscrittura deterministica + validatore** (`core/gender_rewriter.py`):
  flip morfologico (-o↔-a + tabella articoli/pronomi) accettato solo se ogni
  parola cambiata è una coppia di flessione plausibile → allucinazioni
  impossibili per costruzione. Il motore deterministico ha battuto Qwen2.5-14B
  nel confronto diretto (86,8% vs 83,1%).
- **2ª persona** ("sei stanca?"): genere dell'interlocutore dai turni di
  dialogo (91,4%, modalità strict) e dai vocativi col cast TMDB
  ("Sei cresciuta, Veronica").
- **Riuso diarization**: i turni calcolati in trascrizione vengono riusati
  dallo STEP 6.5 (~1-2 minuti risparmiati a film).

**Risultati** (ground-truth auto-estratto da sottotitoli professionali dual-track):
| Metrica | Prima (NLLB) | Dopo |
|---|---|---|
| 1ª persona femminile (corpus) | 19,3% | **86,8%** |
| 1ª persona maschile (corpus) | 89,3% | **93,3%** |
| A/B episodio reale, femminili | 0% | **60%** |
| A/B episodio reale, maschili | 100% | **100%** (mai degradato) |

**Migrazione**: il modello GGUF non serve più. Per la correzione genere ora
servono: venv NLP separato con spaCy (`venv_nlp/`, vedi README → Installation)
e un token HuggingFace (pyannote). Nuove chiavi config:
`gender_correction_second_person` (default on), `gender_selector_python`
(auto-discovery se vuota). UI impostazioni aggiornata.

Include inoltre: harness di valutazione completo in `gender_eval/`
(benchmark MT-GenEval, ground-truth builder dai film dual-track, A/B runner).

## [1.5.x] — 2026-06/07

Versioni precedenti al changelog: modulo OCR bitmap PGS/VOBSUB → SRT
(Tesseract parallelo, review UI, writeback mux/sidecar), integrazione Library
Scanner (badge bitmap, batch OCR, Superpower), routing OCR nella coda
principale, GUI revamp (icone SVG, settings unificati, i18n IT/EN),
ottimizzazione avvio (~2s), fix import bitmap in coda. Vedi la cronologia git.
