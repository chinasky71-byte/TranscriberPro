# Matrice di parità: GUI Qt  ->  web UI (pagina Coda e Cronologia)

Stati: `da fare` · `fatto` (codice + test nel cloud) · `verificato Win` (provato dalla sessione locale su Windows, C-010 e seguenti).
La web UI non sostituisce la Qt finché ogni riga non e' `verificato Win`. Riferimento visivo: `tpweb/proto/p2_qt_capture.py` (finestra Qt vera).

## Cornice
| Controllo (GUI Qt) | Web | Stato | Test |
|---|---|---|---|
| Titlebar 52 px: marchio, sottotitolo, pill di stato, strumenti, sincronizza, impostazioni | `chrome.js` TitleBar | fatto (impostazioni, strumenti e sincronizza aprono i loro dialoghi) | `test_geometria_come_la_finestra_qt_vera_stato_righe` |
| Pill «Pronto» / «In elaborazione» (punto che pulsa) (anche «connessione persa») | `chrome.js` | fatto | `test_badge_gpu_stato_in_barra...` |
| Pulsante «Esci» (nuovo, assente in Qt: chiudere la finestra chiude l'app) | `chrome.js`, `/api/quit` | fatto | `test_uscita_senza_coda_e_con_coda_al_lavoro` |
| Schede: «Coda di processamento  (n)» con n = in coda + in lavorazione (nessun numero se 0); «Cronologia  (n)» | `chrome.js` TabBar | fatto | `test_badge_gpu_stato_in_barra_e_conteggi_delle_schede` |
| Badge scheda video (GPU): verde NVIDIA, rosso AMD, «CPU only»; secondo giro dopo 30 s se incompleto | `chrome.js`, `tpweb/gpu.py` | fatto | `test_badge_gpu_*` |
| Tre pannelli 414/472/472 con maniglia 6 px; trascinare le maniglie (orizzontali e quella tra anteprima e monitor) e ricordare le dimensioni | CSS grid fisso | fatto (misure e maniglie mobili, anche quella tra anteprima e monitor; salvate) | `test_geometria...` |

## Pannello sinistro (coda)
| Controllo | Web | Stato | Test |
|---|---|---|---|
| Filtro Tutti/Attivi/Coda/Completati con contatori | `SegmentedFilter` | fatto | `test_righe_stati_filtri_e_contatori` |
| Riga: pallino di stato, nome (ElideMiddle), dimensione · stato · %, eccezioni `ov`, barra 4 px | `FileRow` | fatto | `test_righe_stati_filtri_e_contatori` |
| Selezione: clic, Ctrl, Maiusc | `FileList` | fatto | `test_selezione_con_clic_ctrl_e_maiusc...` |
| Canc: toglie solo le righe in attesa, anche a coda al lavoro | `FileList` + `/api/queue/remove` | fatto | idem |
| Riordino per trascinamento (solo righe in attesa, una alla volta) | `FileList` (HTML5 drag and drop) | fatto | `test_riordino_*` |
| Menu contestuale: eccezioni per file (lingua, modello, audio forzato, genere, mux, upload), ripristina, rimuovi; voce spuntata comune | `context_menu.js` | fatto (compresa la revisione OCR dei job differiti) | `test_menu_*` |
| Aggiungi File (dialogo con filtro video, ricorda l'ultima cartella) | `FileBrowser` mode files | fatto (con il guscio pywebview si apre il dialogo di Windows) | `test_aggiungi_file_con_il_navigatore` |
| Aggiungi Cartella (scansione ricorsiva in background, nessun doppione) | `FileBrowser` mode folder + `/api/queue/scan` | fatto | `test_aggiungi_cartella_scansiona_e_aggiunge` |
| Trascinamento di file da Esplora risorse | `main.js` (percorso vero con pywebview) | fatto lato cloud; da provare su Windows | `test_trascinamento_da_esplorer_*` |
| Pulisci (rifiutato mentre lavora) | `QueuePanel` | fatto | `test_svuota_e_riga_aggiunta...`, `test_stop_chiede...` |
| Scheda Library Scanner (comprimibile) | `scanner.js` | fatto (vedi sezioni Library Scanner e OCR) | `test_tpweb_scanner_page.py` |
| Avvia (disabilitato a coda vuota o al lavoro; blocchi per OCR/Glossario/Sync) | `QueuePanel` | fatto (blocchi: fasi 4-5) | `test_avvia_elabora...`, `test_avvia_con_coda_vuota...` |
| Ferma con conferma (predefinito No, Esc = No) | `Confirm` | fatto | `test_stop_chiede_conferma...` |
| Riga «Predefiniti: ...» (apre Impostazioni > Opzioni job) | `QueuePanel` | fatto (il clic apre Impostazioni > Opzioni job) | `test_casella_spegni_salva_nel_config` |
| Casella «Spegni al termine» (salva in config, spegne a fine coda anche dopo Stop) | `QueuePanel`, `WebQueue` | fatto (azione reale: solo `--ui web` vero) | `test_casella_spegni...`, `test_spegnimento_*` |
| Barra di avanzamento 14 px + percentuale a destra | `QueuePanel` | fatto | `test_avvia_elabora...` |

## Pannello centrale
| Controllo | Web | Stato | Test |
|---|---|---|---|
| Anteprima: locandina TMDB, pillola col nome, striscia (lingua, stato, titolo «Nome show SxxExx», dimensione · %, barra) | `Poster`, `InfoStrip`, `tpweb/preview.py` | fatto. **Differenza voluta:** un risultato tardivo di una ricerca annullata non sovrascrive piu' la locandina (corsa nota nella GUI Qt) | `test_anteprima_*` |
| Monitor risorse: CPU, RAM, GPU, VRAM, Download, Upload | `ResourceMonitor` + `/api/resources` | fatto (uptime e dimensioni esatte: da rifinire) | `test_monitor_risorse_mostra...` |

## Pannello destro
| Controllo | Web | Stato | Test |
|---|---|---|---|
| Tessere Completati / In corso / In coda / ETA (ogni secondo a coda al lavoro) | `RightPanel` + `/api/queue/live` | fatto | `test_avanzamento_e_tessere_si_aggiornano_dal_vivo` |
| Log di elaborazione (filtro rumore, colori, barre sul posto, 5.000 righe) e «Log Sintetico» (acceso all'apertura) | `LogBuffer` sul server, `LogView` | fatto: stessa uscita della GUI su sequenze scritte (`test_log_buffer_characterization.py`) | `test_log_*`, `test_barre_*` |
| Card «Pipeline in corso» (passi, anelli, %, ETA, barra stimata/indeterminata, apri/chiudi ricordato) | `pipeline_card.js` | fatto | `test_card_*`, `test_barra_stimata_*` |
| Diagnostica (Tempo, Errori, Modello, Traduttore, Engine). **Come la GUI:** «Errori» si aggiorna solo a inizio coda e sugli errori del worker, non sui file falliti (da decidere con il proprietario se correggerlo in entrambe) | `RightPanel` | fatto | `test_diagnostica_*`, `test_tessera_errori_*` |

## Cronologia
| Controllo | Web | Stato | Test |
|---|---|---|---|
| Tessere totale / spazio / tempo | `HistoryView` | fatto | `test_cronologia_tabella...` |
| Ricerca per nome o lingua | idem | fatto | idem |
| Tabella (nome, data, lingua, durata, dimensione) e «Apri .srt» / «Cartella» | idem | fatto | idem |

## Trasversali
| Requisito | Stato | Test |
|---|---|---|
| Ogni testo da `tr()` (IT/EN, stessi segnaposto), nessun testo a mano nei JS | fatto | `test_tpweb_assets.py` |
| Lingua: impostazione, con «auto» la lingua del browser | fatto | `test_pagina_in_inglese...`, `test_lingua_auto...` |
| Nessuna risorsa esterna, file solo dalla stessa origine, nessun traversal | fatto | `test_tpweb_assets.py` |
| Token e tema generati dalla GUI (una sola fonte) | fatto | `test_tokens_e_icone_coincidono_con_la_gui` |
| Ripresa dopo caduta della connessione (stato completo se gli eventi sono scartati) | fatto | `test_ripresa_dopo_la_caduta_del_flusso` |
| Aspetto misurato su Windows a 100/125/150% (forme <= 1%, testo SSIM) | da fare: C-011 (14 stati: Coda + 7 schede delle Impostazioni) | - |


## Impostazioni (fase 3)
| Elemento GUI | Web | Stato | Test |
|---|---|---|---|
| Dialogo 840x620, intestazione 48, barra laterale 200 con 7 schede, ultima scheda ricordata | `settings.js` | fatto | `test_finestra_barra_laterale_e_ultima_scheda`, `test_il_riepilogo_dei_predefiniti_apre_la_scheda_opzioni_job`, `test_esc_chiude_prima_il_messaggio_poi_la_finestra` |
| Generali: lingua (+avviso riavvio), Library Scanner URL/API key (mostra/nascondi via server, mai nello stato), prova connessione, cartelle montate (solo fuori da Windows) | `settings_basic.js` | fatto | `test_generali_*` |
| Opzioni job | idem | fatto | `test_opzioni_job_si_salvano_subito` |
| Batch adattivo (abilita, Salva, Ripristina senza salvare, intervalli) | idem | fatto | `test_batch_*` |
| OCR | idem | fatto | `test_ocr_*` |
| OpenSubtitles (credenziali .org/.com «mantieni invariata», test, guida) | idem | fatto | `test_opensubtitles_*` |
| Trascrizione (motore, stile dialoghi; schede profilo nascoste come nella GUI) | `settings_models.js` | fatto | `test_trascrizione_*` |
| Traduzione (6 modelli, percorsi, chiavi, beams, diarizzazione, genere, forza audio, download LLM e test pyannote con righe in diretta, pagina d'errore) | idem | fatto | `test_traduzione_*`, `test_tpweb_settings_models.py` |
| Aspetto confrontato con Qt (SSIM) | | da misurare in C-011 (Windows) | |


## Strumenti (fase 4)
| Elemento GUI | Web | Stato | Test |
|---|---|---|---|
| Mutua esclusione coda / Glossario / Sincronizzazione / OCR (verdetti di avvio, apertura strumenti, avviso) | `core/services/tool_gate.py`, `WebQueue.start` atomico | fatto (compreso l'OCR) | `test_tool_gate.py` (16 combinazioni identiche a `QueueService.can_start`, gara, atomicita') |
| Glossario per show: cartella, nome, ricerca TMDB (fuori dal ciclo degli eventi), run, annulla, schede candidato, salva | `tools_glossary.js`, `tpweb/tools.py`, `routes_tools.py` | fatto | `test_tpweb_tools.py`, `test_tpweb_tools_page.py`, `test_glossary_tmdb_resolve.py` (caratterizzazione sul vecchio codice) |
| Chiudere il dialogo annulla il run; ricaricare la pagina no; stato ripristinato dopo un buco di eventi | idem | fatto (scelta di prodotto per il web) | `test_ricaricare_la_pagina_non_annulla_chiudere_il_dialogo_si` |
| Sincronizzazione: singola, coda di coppie (tabella, scelta SRT, spunte, riepilogo), progresso, log con barre sul posto, annulla | `tools_sync.js`, `SyncManager`, `core/services/progress_log.py` | fatto | `test_tpweb_sync.py`, `test_tpweb_sync_page.py`, `test_progress_log.py` (identico a `append_log_line`) |
| Chiusura del server: annulla e attende i run (nessun sottoprocesso orfano) | `ToolRuns.shutdown` | fatto | `test_chiusura_del_server_*` |
| Differenza voluta: a run in corso il dialogo si puo' riaprire (e' una vista sul run, non un secondo run); un secondo avvio e' rifiutato dal server | | confermato dal proprietario (28/10/2026) | |
| Aspetto confrontato con Qt (SSIM) | | da misurare in C-011 (Windows) | |


## Library Scanner (fase 5a)
| Elemento GUI | Web | Stato | Test |
|---|---|---|---|
| Card collassabile (titolo, badge, stato Attivo/Inattivo, pallino, aggiorna), apertura ricordata, primo caricamento a ~2,5 s, aggiornamento ogni 5 min a card aperta | `scanner.js`, `tpweb/library.py` | fatto | `test_card_chiusa_apertura_ricordata_*` |
| Ricerca (500 ms), tipo, giorni, formato (ASS/SSA e ritorno ricaricano dal server; gli altri filtri no), ordinamento colonne | idem | fatto | `test_filtri_giorni_formato_ricerca_e_ordinamento`, `test_filtri_giorni_e_formato_senza_ricaricare` |
| Righe: colori giorni, audio ITA, badge PGS/VOB/MIX e ASS, pulsante «+» / ✓ | idem | fatto (clic sul badge bitmap: 5b) | `test_righe_badge_colori_e_statistiche` |
| Importa singolo / tutti i filtrati (mappa dei percorsi, niente doppioni, riga con ASS converte) | `LibraryManager.import_paths` | fatto | `test_import_*` |
| Conversione ASS/SSA sul server (messaggi e log come la GUI) | `convert_ass` | fatto | `test_conversione_ass_*` |
| Notifica al server a ogni sottotitolo creato (solo dopo il primo caricamento; in batch niente ricarica) | `notify_subtitle_created` + evento `library_changed` | fatto | `test_notifica_*` |

## OCR e Superpower (fasi 5b/5c)
| Elemento GUI | Web | Stato | Test |
|---|---|---|---|
| OCR dal badge PGS/VOB/MIX (strategia da configurazione, un solo OCR alla volta, riga «job OCR» nella coda con avanzamento, avanzamento al posto delle statistiche) | `tpweb/ocr.py` `OcrManager`, `scanner.js` | fatto | `test_tpweb_ocr.py`, `test_badge_avvia_l_ocr_*` |
| Esiti: automatico ok/fallito, formato non supportato, lingua saltata (completato), errore; messaggi come la GUI | idem | fatto | `test_esiti_negativi_e_strategia` |
| Coda al lavoro: il job aspetta («in coda») e parte a fine coda; revisione per file dal menu (Predefinita / Mirata / Automatica) | `finished_hooks`, `deferred-mode`, menu in `queue_panel.js` | fatto | `test_con_la_coda_al_lavoro_*`, `test_fine_coda_*`, `test_menu_dei_job_ocr_differiti` |
| Revisione mirata: lista con pallini, «solo dubbi», contatore, immagine, editor (Invio salva e salta; Maiusc/Ctrl+Invio riga nuova), corsivo, precedente/successivo, «verificato», «Fatto» (write-back), chiudere = annulla | `ocr_review.js`; eventi e immagini sul server | fatto | `test_revisione_*` |
| Superpower: controlli, conferma, elenco dal server, batch automatico, riepilogo, spegnimento a fine batch | `OcrManager.superpower` | fatto | `test_superpower_*` |
| Differenza voluta: con la revisione aperta il lavoro conta come «OCR in corso» (la coda non parte, nessun altro OCR) | `gate.ocr_running` | confermato dal proprietario (28/10/2026) | `test_revisione_elenco_*` |
| Aspetto confrontato con Qt (SSIM) | | da misurare in C-011 (Windows) | |

## Guscio, finestra e pacchetto (fase 6)
| Elemento | Web | Stato | Test |
|---|---|---|---|
| Finestra nativa pywebview con watchdog (pagina bianca -> profilo pulito -> browser) | `tpweb/shell.py`, `--shell auto\|on\|off` | codice e logica provati con un finto `webview`; **finestra vera da provare su Windows** | `test_tpweb_shell.py` |
| Dialoghi nativi per file/cartelle (ripiego sul navigatore web) | `ShellApi`, `pickNative` | logica provata; **dialogo vero da provare su Windows** | `test_tpweb_shell.py`, `test_tpweb_shell_page.py` |
| Trascinamento di file da Esplorer (`pywebviewFullPath`) | `main.js` | logica provata; **da provare su Windows** | `test_trascinamento_da_esplorer_*` |
| Chiusura della finestra a coda al lavoro (conferma dalla pagina) | evento `closing` + `tp-quit-request` | logica provata; **da provare su Windows** | `test_chiusura_a_coda_libera_*`, `test_richiesta_di_uscita_*` |
| Maniglie dei tre pannelli (QSplitter, misure salvate) | `SplitRow` in `main.js`, `/api/settings/splitter` | fatto | `test_tpweb_splitter.py` |
| Script di avvio (.bat, .vbs, run_web.sh), `requirements-web.txt`, NOTICE | | fatto | `test_tpweb_packaging.py` |
| Pacchetto PyInstaller `TranscriberProWeb.spec` | | scritto; **build da provare su Windows** | `test_lo_spec_elenca_*` |
| Splash di avvio | | non fatto: il server parte prima della finestra (< 1 s); da rivalutare su Windows | |
