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
