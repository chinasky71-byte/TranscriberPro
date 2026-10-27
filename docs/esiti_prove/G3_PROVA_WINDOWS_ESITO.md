# G3 (parte 1: Revisione OCR e Profilo di trascrizione): esito della prova su Windows (27/10/2026)

Branch provato: `refactor/g3-prova` (HEAD `2ee4767`), confrontato con un worktree di `master` 1.34.39 (`97c6173`). Nessun codice modificato, nessuna unione, produzione e `development` non toccati, niente cancellato.

## Ambiente e metodo
- Windows 11, RTX 3060 (non usata). Interprete: venv di produzione solo come eseguibile (cartella di lavoro e `PYTHONPATH` sul clone). Tesseract 5.5.0 (ita/eng), ffmpeg 8.0, mkvmerge v99.0, tutti nel PATH.
- Dove ho lavorato: clone nuovo `Desktop\Transcriber_Pro_G3` e worktree di master `Desktop\Transcriber_Pro_G3_master`; dati isolati in `C:\tp_prova_home_g3` (nuova, vuota); file di prova e output in `Desktop\g3_prova_dati\lavoro` (copie fresche; gli estratti in `...\ocr` e la libreria non sono stati toccati).
- **Metodo:** per non interferire con il PC del proprietario non ho pilotato il desktop. Ho usato i worker e i dialoghi veri (`OcrWorker`, `OcrReviewDialog`, `ProfileSelectionDialog`) pilotati da script Python con Qt offscreen, uno stesso script su G3 e su master, in sequenza, con la stessa configurazione (strategia, write-back, lingua `ita`, soglia 75). E' meno fedele della GUI sullo schermo per l'aspetto, ma esercita lo stesso codice di logica e di vista; le schermate non sono state confrontate.
- Download di modelli: nessuno (per il ramo di traduzione ho forzato `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`: il caricamento di NLLB e' fallito senza scaricare nulla).

## 1. pytest (un solo processo, home isolata, nessuna esclusione)
| Albero | Passati | Falliti | Saltati |
|---|---|---|---|
| master `97c6173` | 815 | 8 | 28 |
| `refactor/g3-prova` | 871 | 8 | 28 |

Gli 8 falliti sono gli stessi ambientali noti su entrambi (`test_amd_family` x2, `test_amd_rocm_f6`, `test_core_jobs_unit` x3, `test_queue_gui_characterization::test_contratto_del_sottoprocesso`, `test_queue_runner_characterization::test_contratto_del_sottoprocesso`). **Nessun crash `0xC0000409`** (88 s e 69 s).

## 2. Punti della checklist
| # | Punto | Esito | Confronto con master |
|---|---|---|---|
| 1 | Profilo: scheda Trascrizione | **OK** | 4 voci del motore nell'ordine di master (Auto, Canary-Qwen, Qwen3-ASR, Faster-Whisper); stile dialoghi e 2 gruppi («Motore di trascrizione», «Stile dialoghi professionale»), 0 schede di profilo (`SHOW_PROFILE_CARDS = False`). Ogni scelta + riavvio (processo nuovo) resta: canary/0, qwen3/1, faster-whisper/0, auto/1. Identico. |
| 2 | Revisione mirata, PGS italiano (`cinderella_pgs`: PGS ita+eng derivato da cinderella) | **OK** | Finestra: 42 eventi, contatore «Eventi: 42 · Dubbi: 0» (con soglia 98: «Dubbi: 42»), filtro «solo dubbi» (42 righe), Precedente/Successivo, Invio (salva e salta), «Verificato» (contatore a «Dubbi: 0»), corsivo su tutto il testo (`<i>…</i>` e rimozione) e su selezione (`<i>Cor</i>rezione…`), ridimensionamento (immagine 640 px), «Fine». Tutto uguale a master. |
| 3 | Write-back dopo la revisione (stesse 3 correzioni «Correzione di prova N» + tutto Verificato) | **OK** | **Sidecar:** `.it.srt` con stesso SHA256 (`72b9e8ba66f83ddf`, 2803 byte) su G3 e master. **Mux:** MKV risultante identico in dimensione (48.377.818 byte), stesse tracce (video, audio, PGS eng, SRT ita «Italiano SRT»; la PGS italiana sostituita) e stesso SHA256 dell'SRT estratto (`c1bd2c32…`). Senza correzioni (soglia 75, 0 dubbi): SRT `10afdc00…` identico. |
| 4 | Solo automatico, `blue_warmest_color` (3 PGS: ita, eng, ita SDH) | **OK** | Log e esito identici («37 battute», «39 battute», «2 tracce PGS italiane: sidecar dalla traccia 4»); `.it.srt` stesso SHA256 (`49a4e126…`). |
| 5 | PGS inglese (`shrek`), ramo «non italiano → traduce» | **Come master** | Il motore di traduzione non e' disponibile nella home isolata: l'OCR della traccia inglese riesce (sorgente `shrek_estratto.en.srt`, stesso SHA256 `046814db…`), poi «Errore caricamento NLLB-200: We couldn't connect to 'https://huggingface.co'…» (offline forzato) e `auto_done = False`, uguale su G3 e master. Nessun download. Ramo di traduzione riuscita non provato. |
| 6 | Annulla durante l'OCR (review e auto), stop a 0,8 s | **OK** | Worker terminato in 0,14 s / 0,16 s (G3) e 0,02 s / 0,08 s (master), «OCR annullato»; nessun file prodotto; **0 processi tesseract/python/ffmpeg/mkv* orfani** dopo 3 s. |
| 7 | Casi di errore: file senza bitmap (`cinderella_nosub`, `-sn`) | **OK** | «Nessun sottotitolo bitmap trovato» in review e in auto, identico. Mixed PGS+VobSub (`cinderella_man_estratto` con kind=pgs): «Codec dvd_subtitle non supportato dal ramo review (solo PGS; VOBSUB/DVD è fase 2)», uguale (rilevato sulla prima corsa su G3; non rieseguito su master per questo file). «Lingua senza tessdata»: non provato. |
| d | VobSub (`cinderella_vobsub`, kind=vobsub) | **OK** | Review: 42 eventi, confidenza media 93,86, SRT di revisione `b6179826…`; auto: `.it.srt` stesso SHA256. Identico a master. |

## 3. Misure (G3 vs master, stessa macchina, esecuzioni singole)
| Prova | Tempo OCR G3 / master | RAM di picco (processo + figli) G3 / master | Eventi | Confidenza media |
|---|---|---|---|---|
| a) Revisione PGS ita (cinderella_pgs) | 1,7 s / 1,7 s | 404-444 MB / 396-409 MB | 42 | 94,61 |
| b) Auto 3 PGS (blue_warmest) | 2,7 s / 2,8 s | 452 MB / 461 MB | 37 + 39 (2 tracce ita) | n.d. (0 da rivedere) |
| d) VobSub review (cinderella_vobsub) | 2,5 s / 1,7 s | 441 MB / 378 MB | 42 | 93,86 |
| d) VobSub auto | 1,6 s / 1,7 s | 398 MB / 382 MB | 42 | n.d. |
| c) PGS eng (shrek, review → traduzione) | 7,8 s / 7,5 s | 797 MB / 805 MB | (sorgente) | n.d. |

Le differenze di tempo e RAM (es. VobSub 2,5 s contro 1,7 s) sono nel rumore di una sola esecuzione a 1-3 s e senza ripetizioni; nessuna regressione evidente. Il picco RAM include `tesseract.exe` e i figli campionati ogni 0,2 s.

## 4. Differenze rispetto a master
Nessuna differenza di comportamento o di risultato trovata (SRT, tracce MKV, messaggi, UI di revisione, impostazioni).

## 5. Non provato
GUI vera sullo schermo (Library Scanner con azione OCR, scheda Impostazioni → Trascrizione, aspetto), ramo di traduzione riuscita (serve il modello NLLB), lingua senza tessdata, uso reale di «Invio»/tasti con tastiera simulata (l'handler `_on_enter_save_next` e' stato esercitato direttamente).

## Aggiornamento produzione (27/10/2026, su OK esplicito del proprietario, per la sua prova a mano)
- **Sorgente:** `origin/refactor/g3-prova2` HEAD `6cf8d09`. Elenco copiato (9 file): nuovi `core/jobs/env_cli.py`, `core/jobs/ocr_run.py`, `core/services/ocr_review_service.py`, `core/services/transcription_settings_service.py`, `core/services/translation_model_service.py`; modificati `gui/ocr_review_dialog.py`, `gui/ocr_worker.py`, `gui/profile_dialog.py`, `gui/translation_model_dialog.py`. Nient'altro (niente `linux_tests`, `docs`, `CHANGELOG`, `README`, `.git`).
- **Controllo prima della copia:** `git diff origin/master..6cf8d09` (esclusi test/docs) coincide con i 9 file; i 5 nuovi non esistevano in produzione; i 4 modificati erano **identici a master 1.34.39** (confronto del contenuto). Nota: `main.py` di produzione resta `APP_VERSION = "1.34.38"` (non copiato).
- **Backup** `Desktop\backup_prod_pre_G3`: i 4 file sovrascritti (`codice\gui\...`), `config.json` e `history.json` con SHA256 (`dati\sha256.txt`).
- **Copiati 9 file; hash identici alla sorgente (0 differenze).** Hash (primi 12): env_cli `F87763F249A2`, ocr_run `08409370E9F3`, ocr_review_service `387FC27E5D55`, transcription_settings_service `F0A296887D9C`, translation_model_service `57F0ACF10F27`, ocr_review_dialog `968ECB102E5F`, ocr_worker `6BAC8155456C`, profile_dialog `E5BF17982084`, translation_model_dialog `5A2A9896EF1A`.
- **Avvio di controllo:** import di tutti i moduli senza errori; l'app di produzione e' partita con i dati veri (finestra presente, stderr vuoto, 0 righe di errore nel log) ed e' stata chiusa; `config.json` e `history.json` con gli stessi SHA256 del backup. Nessuna elaborazione.
- **Stato:** app CHIUSA, in attesa della prova a mano del proprietario (Library Scanner -> OCR su un PGS con finestra di revisione; Impostazioni -> Trascrizione e Traduzione). In caso di problema: ripristino dal backup, senza correggere il codice. Alla conferma «tutto ok»: rimozione dei soli file di prova G3 in `Desktop\g3_prova_dati\lavoro` (dopo averli elencati).

### Prova a mano sullo schermo, fatta dalla sessione locale (il proprietario era lontano e l'ha delegata)
Codice di produzione con i 9 file di G3, PC libero, mouse e tastiera simulati con screenshot.
- **Revisione OCR (finestra vera sullo schermo):** per non toccare la libreria (il write-back puo' fare mux nell'MKV originale) ho usato una COPIA (`cinderella_pgs.mkv`, PGS ita+eng) in `Desktop\g3_prova_dati\lavoro\prod_review` e un piccolo script che esegue `OcrWorker` e apre `OcrReviewDialog` di produzione a video (soglia 98 per avere dubbi). Provati con la finestra reale: elenco con pallini e «#N», contatore «Eventi: 42 · Dubbi: 42», filtro «Solo righe dubbie», testo corretto + Invio (salva e salta al prossimo dubbio), Corsivo senza selezione (`<i>Si.</i>` e rimozione) e con selezione col mouse (`St<i>asera</i>`), Verificato (compare «✓», contatore a «Dubbi: 41» ... «Dubbi: 0»), ridimensionamento/massimizzazione (l'immagine si adatta), «Fine revisione». Esito: accettato; `.it.srt` sidecar scritto accanto alla copia (2805 byte, contiene «Correzione di prova 0» e `<i>Si.</i>`). Nota: i tasti freccia con Maiusc non si simulano bene su Windows (selezione da tastiera non provata sullo schermo; la selezione e' stata fatta col mouse).
- **Library Scanner → azione OCR:** NON provata (avrebbe scritto nella libreria del proprietario).
- **Impostazioni → Trascrizione e Traduzione (app di produzione, dati veri):** si aprono senza errori (stderr vuoto, 0 errori nel log). Trascrizione: motore «Auto (routing per lingua)» e «Stile dialoghi professionale» attivo, nessuna scheda di profilo. Traduzione: sezioni, percorso NLLB-FT del proprietario con «Modello configurato e pronto», beams 4. Solo osservazione: nessuna scelta o salvataggio.
- **Effetto collaterale ripristinato:** aprire Impostazioni ha cambiato in `config.json` solo la chiave `ui_settings_last_tab` («general» → «translation»); l'ho rimessa a «general»: `config.json` di nuovo con lo stesso SHA256 del backup (`A758DA8F…`); `history.json` invariato.
- App chiusa, 0 processi. **File di prova in `Desktop\g3_prova_dati\lavoro` NON rimossi** (serve il «tutto ok» del proprietario).

## Pulizia G3 (27/10/2026, su OK esplicito del proprietario)

Master allineato a 1.34.40 (`b41e957`). Repository di lavoro: `git fetch --prune`, `checkout master`, `pull`; i 3 file privati non tracciati sono al loro posto.

**Produzione:** i 9 file di G3 hanno hash identico a quelli di master (`env_cli`, `ocr_run`, `ocr_review_service`, `transcription_settings_service`, `translation_model_service`, `ocr_review_dialog`, `ocr_worker`, `profile_dialog`, `translation_model_dialog`). `main.py` di produzione resta a 1.34.38. Import dei moduli core OK.

**Cancellato** (nessuna giunzione/link trovato; nessun processo di prova attivo; i processi `msedgewebview2` presenti appartengono a Windows, non alle prove):

| Voce | Esito |
|---|---|
| `Desktop\g3_prova_dati\lavoro` (elencata prima: copie `.mkv`, `.srt` e `derivati` generati dalle prove G3) | cancellata (1,89 GB) |
| `Desktop\g3_prova_dati\ocr` (estratti e `.sup`) | **intatta** (9 file) |
| `Desktop\g2_prova_dati` | cancellata (3,29 GB) |
| worktree `Transcriber_Pro_G3_master` e `Transcriber_Pro_G2_master` | rimossi con `git worktree remove` |
| clone `Transcriber_Pro_G3` e `Transcriber_Pro_G2` | cancellati (nessun lavoro non spinto: `git log --branches --not --remotes` vuoto, `git status` pulito) |
| `C:\tp_prova_home_g2`, `_g3`, `_g3b` | cancellate (il blocco in radice di C:\ non è scattato; erano già quasi vuote) |

**Branch locali del repository di lavoro:** esisteva solo `g3/prova-dati` (commit `c8f0781`, identico a `origin/g3/prova-dati`, quindi già su origin): cancellato. Resta `master`. Gli altri branch (`refactor/g2-*`, `refactor/g3-*`, `release/*`, `fix/test-posix-only`, `g1/*`, `g2/*`, `g3/*`) esistono solo come branch remoti su origin e non sono stati toccati.

**Spazio libero su C:** 317,23 → 322,62 GB (+5,39 GB).

**Non toccati:** produzione, venv, models, ui_bench, `~\.transcriberpro`, `development`, `webui/main`, `webui/p1-results`, `studio/webui`, `backup_prod_pre_G2`, `backup_prod_pre_G3`.

**Verifica finale:** `config.json` `A758DA8F23643B6B…` e `history.json` `B7C1D43C7D174E0B…` invariati rispetto al backup pre-G3; repository di lavoro su `b41e957`, solo i 3 file privati non tracciati; 0 processi python/ffmpeg/tesseract.
