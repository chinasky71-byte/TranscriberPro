# Matrice di parità: GUI Qt  ->  web UI (pagina Coda e Cronologia)

Stati: `da fare` · `fatto` (codice + test nel cloud) · `verificato Win` (provato dalla sessione locale su Windows, C-010 e seguenti).
La web UI non sostituisce la Qt finché ogni riga non e' `verificato Win`. Riferimento visivo: `tpweb/proto/p2_qt_capture.py` (finestra Qt vera).

## Cornice
| Controllo (GUI Qt) | Web | Stato | Test |
|---|---|---|---|
| Titlebar 52 px: marchio, sottotitolo, pill di stato, strumenti, sincronizza, impostazioni | `chrome.js` TitleBar | fatto (strumenti/sincronizza/impostazioni: icone senza azione, fasi 3-4) | `test_geometria_come_la_finestra_qt_vera_stato_righe` |
| Pill «Pronto» / «In elaborazione» (punto che pulsa) (anche «connessione persa») | `chrome.js` | fatto | `test_badge_gpu_stato_in_barra...` |
| Pulsante «Esci» (nuovo, assente in Qt: chiudere la finestra chiude l'app) | `chrome.js`, `/api/quit` | fatto | `test_uscita_senza_coda_e_con_coda_al_lavoro` |
| Schede: «Coda di processamento  (n)» con n = in coda + in lavorazione (nessun numero se 0); «Cronologia  (n)» | `chrome.js` TabBar | fatto | `test_badge_gpu_stato_in_barra_e_conteggi_delle_schede` |
| Badge scheda video (GPU): verde NVIDIA, rosso AMD, «CPU only»; secondo giro dopo 30 s se incompleto | `chrome.js`, `tpweb/gpu.py` | fatto | `test_badge_gpu_*` |
| Tre pannelli 414/472/472 con maniglia 6 px; trascinare le maniglie (orizzontali e quella tra anteprima e monitor) e ricordare le dimensioni | CSS grid fisso | fatto le misure; maniglie mobili: da fare | `test_geometria...` |

## Pannello sinistro (coda)
| Controllo | Web | Stato | Test |
|---|---|---|---|
| Filtro Tutti/Attivi/Coda/Completati con contatori | `SegmentedFilter` | fatto | `test_righe_stati_filtri_e_contatori` |
| Riga: pallino di stato, nome (ElideMiddle), dimensione · stato · %, eccezioni `ov`, barra 4 px | `FileRow` | fatto | `test_righe_stati_filtri_e_contatori` |
| Selezione: clic, Ctrl, Maiusc | `FileList` | fatto | `test_selezione_con_clic_ctrl_e_maiusc...` |
| Canc: toglie solo le righe in attesa, anche a coda al lavoro | `FileList` + `/api/queue/remove` | fatto | idem |
| Riordino per trascinamento (solo righe in attesa, una alla volta) | `FileList` (HTML5 drag and drop) | fatto | `test_riordino_*` |
| Menu contestuale: eccezioni per file (lingua, modello, audio forzato, genere, mux, upload), ripristina, rimuovi; voce spuntata comune | `context_menu.js` | fatto (revisione OCR differita del menu: fase 5) | `test_menu_*` |
| Aggiungi File (dialogo con filtro video, ricorda l'ultima cartella) | `FileBrowser` mode files | fatto (dialogo nativo: con pywebview, fase 6) | `test_aggiungi_file_con_il_navigatore` |
| Aggiungi Cartella (scansione ricorsiva in background, nessun doppione) | `FileBrowser` mode folder + `/api/queue/scan` | fatto | `test_aggiungi_cartella_scansiona_e_aggiunge` |
| Trascinamento di file da Esplora risorse | - | da fare (fase 6, guscio pywebview) | - |
| Pulisci (rifiutato mentre lavora) | `QueuePanel` | fatto | `test_svuota_e_riga_aggiunta...`, `test_stop_chiede...` |
| Scheda Library Scanner (comprimibile) | segnaposto statico | da fare (fase 5) | - |
| Avvia (disabilitato a coda vuota o al lavoro; blocchi per OCR/Glossario/Sync) | `QueuePanel` | fatto (blocchi: fasi 4-5) | `test_avvia_elabora...`, `test_avvia_con_coda_vuota...` |
| Ferma con conferma (predefinito No, Esc = No) | `Confirm` | fatto | `test_stop_chiede_conferma...` |
| Riga «Predefiniti: ...» (apre Impostazioni > Opzioni job) | `QueuePanel` | fatto il testo; il clic: fase 3 | `test_casella_spegni_salva_nel_config` |
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
| Aspetto misurato su Windows a 100/125/150% (forme <= 1%, testo SSIM) | da fare (C-010) | - |
