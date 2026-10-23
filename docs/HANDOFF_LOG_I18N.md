# Registro Fase B: traduzione dei log della pipeline

Piu' recenti in alto. Regole: testo italiano identico carattere per carattere; consumatori che leggono il testo
riconoscono IT ed EN; mai tradurre `logger.*` (restano in italiano per gli sviluppatori).

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
