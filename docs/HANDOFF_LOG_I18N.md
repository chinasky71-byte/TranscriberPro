# Registro Fase B: traduzione dei log della pipeline

Piu' recenti in alto. Regole: testo italiano identico carattere per carattere; consumatori che leggono il testo
riconoscono IT ed EN; mai tradurre `logger.*` (restano in italiano per gli sviluppatori).

## 2026-10-23 · PR 6 — tutto il resto (`gc_*`, `g2_*`, `gcl_*`, `gr_*`, `sg_*`, `di_*`, `pr_*`, `al_*`, `pgs_*`, `oa_*`, `boc_*`, `ec_*`, `fb_*`, `pc_*`, `sc_*`, `ab_*`, `oa2_*`, `sf_*`, `qr_*`, `pd_*`...)

**Fatto**: gender_corrector (18), gender_corrector_v2 (11), gender_corrector_cli (11), gender_rewriter (2), speaker_gender (4), diarizer (12), punctuation_restorer (5+1), aligner (5), pgs_ocr (12+5), vobsub_ocr (12+6), ocr_auto (8), bitmap_ocr_common (1), env_check_cli (15), fallback_translate_cli (12), pipeline_cli (9), sync_cli (9), utils/adaptive_batch_manager (7), utils/opensubtitles_ai_translator (13), opensubtitles_rest_uploader (1), subtitle_formatter (7), queue_runner (7), utils/profile_dialog (2 etichette). `verify_i18n_identity.py`: 0 differenti (un falso positivo in subtitle_formatter:116, indirizzi diversi dei generatori finti, controllato a mano).

**Punti delicati**
1. Il filtro del rumore ha ora la variante EN anche per `AdaptiveBatchManager avviato` (`logm_noise_abm_started`); barre `Correzione genere: [` / `⚙️ OCR — Analisi bitmap` / `OCR — Traduzione` / `SRT italiano scritto` provate con le righe reali in IT ed EN (`test_i18n_consumers.py`).
2. **Venv dedicati**: `core/glossary_builder_cli.py` (venv_glossary) non ha le dipendenze di `utils` (importare `utils.translations` esegue `utils/__init__`): lasciato in italiano (3 messaggi `{"ev":"error","msg":...}`), voce nell'elenco ammesso di `test_i18n_scan.py`. Idem `core/gender_selector_cli.py` (venv NLP) e `core/engines/canary_cli.py`: non toccati.
3. Esiste `test_i18n_scan.py`: lo scanner su core/ e utils/ deve restituire solo l'elenco ammesso.
4. Non convertiti volutamente: `print` dei blocchi `__main__` di test (pipeline.py, config.py, profile_dialog.py), `print` di `utils/config.py` (avvisi di configurazione sul terminale, non nella finestra del log), diagnostica `Issue` del validatore LLM (solo log di sviluppo), `logger.*`.
5. Smoke test di import con moduli pesanti simulati (torch, numpy, ...): tutti i moduli modificati si importano.

**Test**: `python -m pytest linux_tests -q` → 305 passed, 6 skipped. **Non verificato**: esecuzione reale (GPU/modelli) e prova della pipeline su video.

## 2026-10-23 · PR 5 — engines, engine_router, audio_processor (`fw_*`, `qw_*`, `ca_*`, `be_*`, `er_*`, `ap_*`)

**Fatto**: faster_whisper_engine 30, qwen3_asr_engine 16, canary_engine 14, base_engine 1, engine_router 20 (+ i motivi di `EngineRouter.plan`, mostrati in "Engine selezionato/pianificato"), audio_processor 47.
Le righe con parti variabili a concatenazione/ternario sono chiavi a mano (`er_vram_freed_suffix`, `er_language_suffix`...). `verify_i18n_identity.py`: tutti identici, 0 differenti.
Non convertiti volutamente: barre `Demucs: [` e righe `Workers:`/`VRAM`/`Batch size` (gia' senza testo italiano), `❌ {line}` del figlio Canary.

**Punti delicati**
1. Rumore del filtro (`FILE_ONLY_RE`): le righe `Profilo:`, `VAD ... disponibile`, `BatchedInferencePipeline attivo / file unico`, `Chunking robusto`, `Caricamento audio` hanno ora la variante EN (chiavi `logm_noise_*`, test sulle righe reali in IT ed EN).
2. Barre `Trascrizione: [` → `Transcription: [` (file_progress e log_filter bilingui dalla PR 1; test con le righe reali).
3. `core/engines/canary_cli.py` (venv dedicato, protocollo `PROGRESS`/`LOAD_DONE`/`ERRORE:` letto da canary_engine) NON e' stato toccato: sono token di protocollo, non testo per l'utente; resta italiano `ERRORE: ...` mostrato come `❌ {line}`.
4. Dopo la revisione: convertite anche le eccezioni con testo italiano che arrivano all'utente via `Errore ...: {e}` (canary_engine 4, qwen3 1, faster_whisper 1, audio_processor 4 `InterruptedError`: nessuno le confronta, grep su `annullat`). `canary_cli.py` (venv dedicato) e i `logger.debug` restano italiani.
5. I motivi di `plan()` e `LanguageNotAlignable` non vengono confrontati da nessuno (grep): solo mostrati.

**Test**: `python -m pytest linux_tests -q` → 302 passed, 6 skipped. **Non verificato**: trascrizione/Demucs reali (GPU/modelli).

## 2026-10-23 · PR 4 — core/translator.py (`tl_*`) e core/llm_subtitle_translator/{engine,translator}.py (`le_*`, `lt_*`)

**Fatto**: 84 punti in translator.py (76 `log(...)`, 7 eccezioni/`error_msg` mostrate all'utente, etichette dei contatori dell'audit), 7 in engine.py, 7 in llm translator.py (5 automatici + riga "Completato in..." con concatenazione, a mano).
`verify_i18n_identity.py`: 76 + 7 + 5 identici, 0 differenti. Non convertiti volutamente: `[Serbatoio] {line}` (testo del figlio), `log(msg)` del batch manager (inoltra solo righe "Warm-up", vedi PR adaptive_batch_manager), i prompt dell'LLM (non sono log).

**Punti delicati**
1. Barre `Traduzione: [` / `Progresso:`: EN `Translation: [` / `Progress:` (test: log_filter e FileProgress con le righe reali di tl_* e lt_*).
2. `Recupero senza mascheramento` e' rumore del filtro (`FILE_ONLY_RE`): aggiunta la variante EN (`logm_noise_recovery`).
3. I contatori dell'audit ("riparati L1" ecc.) sono chiavi di dizionario mostrate: ora `tr(...)`, solo mostrati.
4. `error_msg` (riga ~1965) arriva anche a `logger.error` (lingua dell'interfaccia nel file di log, come in pipeline.py); `msg` di "Generazione rallentata" idem.

**Test**: `python -m pytest linux_tests -q` → 292 passed, 6 skipped. **Non verificato**: traduzione reale (NLLB/LLM/API) in cloud.

## 2026-10-23 · PR 3 — core/subtitle_synchronizer.py (67 chiavi `sy_*`) e core/timing_aligner.py (2 chiavi `ta_*`)

**Fatto**: 73 messaggi `_log` del sincronizzatore (69 automatici + 4 ternari a mano, chiavi `sy_embedded_*`/`sy_no_non_italian_*`) + nota "finestra" e riga di sintesi dell'allineatore. `verify_i18n_identity.py`: 69 + 1 identici, 0 differenti.
Non convertiti volutamente: righe `[LLM] {line}` (testo del figlio) e simili senza testo proprio.

**Punti delicati trovati (testo letto dal codice)**
1. `SubtitleSynchronizer._log` impostava `last_error` solo se la riga iniziava con `"ERRORE"` (poi scritto in result.json e mostrato dalla coda): in inglese
   sarebbe rimasto vuoto. Ora usa `all_texts('logm_error_prefix')` (ERRORE/ERROR); il test controlla che ogni riga `sy_*` d'errore inizi col prefisso in EN. Il testo di `last_error` e' solo mostrato, mai confrontato.
2. `if 'finestra' in note` (nota dell'allineatore) → chiave `logm_kw_window` (finestra/window), la nota e' ora `ta_piecewise_offset_at_the_window`.
3. `test_timing_aligner.py` (radice) verificava `'ERRORE'`: ora accetta `ERRORE|ERROR` perche' il messaggio segue la lingua.
4. Da fare in PR engines: `core/engines/canary_engine.py:305` fa `line.startswith("ERRORE")` su righe del figlio Canary.

**Test**: `python -m pytest linux_tests -q` → 284 passed, 6 skipped; `test_timing_aligner.py` 11 passed. **Non verificato**: sincronizzazione reale (richiede modelli/GPU).

## 2026-10-23 · PR 2 — core/pipeline.py (117 chiavi `pl_*`, 126 punti)

**Fatto**: 113 chiamate `_log(...)` convertite + 13 messaggi fuori da `_log` diretto (eccezioni mostrate in `Errore critico pipeline: {e}`,
`error_msg`, nome del passo di `_video_unchanged`, `what` di mux/upload). Strumenti: `scripts_manutenzione/i18n_convert.py` (estrae il modello IT
dall'AST, riscrive il sorgente in `tr('chiave').format(nome=espressione)` senza toccare altro) e
`scripts_manutenzione/verify_i18n_identity.py` (valuta vecchio e nuovo con valori finti: 113 identici, 0 differenti).
Non convertiti volutamente: separatori `'='*80` (nessun testo) e `   [Gender] {line}` (riga del figlio, nessun testo proprio).

**Punti delicati**: i passi `N.` restano numerati (letti per numero). Le parole chiave dei passi 1b/6/6.5 sono bilingui (test con le righe reali in IT ed EN:
`pl_1b_*` contiene "traduzione"/"translation" solo nel ramo con traduzione; `pl_6_*` "Salto traduzione"/"Skipping translation"; 6.5 "saltata"/"skipped").
`error_msg` (riga 445) va anche a `logger.error`: nel file di log comparira' nella lingua dell'interfaccia (unico caso in cui un logger riceve testo tradotto).
Le eccezioni `raise Exception("...")` convertite sono mostrate solo via `Errore critico pipeline: {e}`; nessun codice confronta quei testi (grep).
Da fare nelle PR dei file corrispondenti: `plan_reason` di `engine_router.EngineRouter.plan` (testo italiano mostrato in "Engine pianificato").

**Test**: `python -m pytest linux_tests -q` → 282 passed, 6 skipped. **Non verificato**: esecuzione reale della pipeline (manca torch/GPU in cloud).

## 2026-10-23 · PR 1 — infrastruttura (lingua nel figlio, consumatori bilingue, test)

**Fatto**
- `utils/translations.py`: `all_texts(chiave)` (testo in tutte le lingue), `init_language_headless()` (senza Qt;
  `TP_LANG=it|en` vince, poi config `language`, poi lingua di sistema) e 17 chiavi `logm_*` (marcatori di log letti da altro codice).
- Il figlio chiama `init_language_headless()` in tutti i `core/*_cli.py` e in `queue_runner.py`.
- Consumatori resi bilingue: `gui/services/log_filter.py` (barre aggiornabili, rumore, riga "Modello trascrizione"),
  `gui/progress_log.py` (ora usa la stessa lista), `gui/file_progress.py` (barre interne, lingua audio, embedded, ramo OCR, parole chiave dei passi).
- Test nuovi: `linux_tests/test_i18n_texts.py`, `linux_tests/test_i18n_consumers.py`.

**Punti delicati trovati**
1. Consumatori che leggono il testo: `log_filter` (UPDATABLE_PATTERNS, FILE_ONLY_RE, "Modello trascrizione:"), `progress_log`, `file_progress`
   (fallback testuale accanto agli eventi `TP_EVENTS`). `step_plan` e `pipeline_steps_widget` lavorano solo sugli eventi: nessun testo.
   I passi numerati ("6. ...") sono letti per numero (`^\d+\.`), indipendenti dalla lingua; solo alcune parole chiave del testo
   dei passi 1b/6/6.5 (ora bilingue). `sync_worker`/`sync_batch_worker` leggono solo il numero del passo e `[SYNC-PCT]`.
2. Lingua nel figlio: prima NON veniva inizializzata (solo `main.py`): ora si'. Con lingua impostata a mano nella config GUI e figlio concordano.
3. Le righe `FILE_ONLY_RE` (rumore) aggiungeranno la variante EN man mano che le PR convertono le righe corrispondenti.

**Test**: `python -m pytest linux_tests -q` → 274 passed, 6 skipped.
**Non verificato**: esecuzione reale su Windows con GUI; prova completa con video (vedi consegna finale).
