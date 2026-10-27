# Rapporto P1 su Windows (27/10/2026)

Eseguito dalla sessione locale di Claude Code, in `Transcriber_Pro_P1` (clone di `webui/main`, ramo `webui/p1-results`) con un venv usa e getta; produzione e `master` non toccati.

## Ambiente
| | |
|---|---|
| Windows | 11 Pro, build 10.0.26300 (26H2) |
| Python | 3.11.9 (lo stesso della produzione) |
| Pacchetti | fastapi 0.139.2, uvicorn 0.51.0, starlette 1.3.1, httpx 0.28.1, psutil 7.2.2, pytest 9.1.1, pillow 13.0.0, numpy 2.4.6, playwright 1.64.1, pywebview 6.2.1, PyQt6 6.10.2 |
| Edge (banco SSE, pixel) | 156.0.4314.42 |
| WebView2 Runtime (guscio pywebview) | 155.0.4283.62 |
| Schermo | 1920x1080, 100% |

## Esiti
| Prova | Esito | Misura chiave |
|---|---|---|
| P1c sicurezza | **OK** | 8 passati, 0 saltati (il test «solo loopback» e' passato) |
| P1b flusso eventi (Edge) | **OK** | 5000/5000 righe, p95 117,9 ms, max 126 ms, 0 attivita' lunghe (cloud: p95 136 ms, 1 attivita' di 265 ms) |
| P1e pixel | **DIFFERENZA, attesa** (nessun pass/fail) | totale 3,28% / 3,25% / 2,96% a 100/125/150%; vedi sotto |
| P1d memoria Qt a riposo | **OK** (termine di confronto) | 226,6 MB dopo 30 s (un solo processo python) |
| P1a guscio pywebview | **OK** | percorsi assoluti corretti per tutti i casi, dialoghi nativi OK, SSE nella finestra OK, memoria entro soglia |

## P1a: percorsi dei file trascinati (lato Python, `pywebviewFullPath`)
| Caso | Percorso tornato |
|---|---|
| File su disco locale | `C:\Users\<utente>\Desktop\P1_prova_file\locale\video1.mp4` |
| Accenti e spazi | `...\locale\Città è caffè perché.mkv` (accenti intatti) |
| 3 file insieme | tutti e 3 con percorso assoluto |
| UNC | `\\localhost\C$\Users\<utente>\Desktop\P1_prova_file\unc\su rete UNC.mkv` |
| Unita' di rete mappata (SMB reale) | `W:\7 Women and a Murder (2021)\7.Women.and.a.Murder...[H265]-GalaxyR.mkv` (497 MB, dimensione corretta) |

- Lato pagina JS (`pagina.drops`) `path` e `fullPath` sono `null`: come atteso, il percorso e' disponibile solo lato Python (`drop_handler` registrato), quindi il guscio deve passarlo al backend.
- Dialoghi nativi: «Scegli file» ha restituito i 2 file scelti, «Scegli cartella» la cartella scelta (entrambi con percorso assoluto).
- SSE nella finestra WebView2: 5000/5000, p95 116,5 ms, 0 attivita' lunghe.
- Memoria pywebview: a riposo 438,9 MB (python 119,7 + WebView2 319,2); dopo il banco 549,0 MB. Prova automatica (`--auto`): 440,8 MB a riposo, 498,4 dopo il banco.
- Rispetto alla GUI Qt a riposo (226,6 MB): **+212 MB** (+214 nella prova automatica), sotto la soglia di +250 MB. Dopo il banco il confronto non e' alla pari (549 MB).

## P1e: pixel Qt vs Chromium (tema vero, soglia 24 per canale)
| Scala | Totale | Titolo | «Aggiungi file» | «Avvia» | Barra |
|---|---|---|---|---|---|
| 100% | 3,28% | 12,6% | 11,3% | 2,7% | 0,10% |
| 125% | 3,25% | 11,4% | 10,6% | 3,4% | 2,19% |
| 150% | 2,96% | 11,0% | 10,3% | 2,8% | 0,15% |

(a) **Forme:** combaciano (bordi, raggi, riempimenti, barra) a tutte le scale; le dimensioni delle immagini sono identiche.
(b) **Testo:** differisce nel **peso**: in Chromium i caratteri sono piu' pieni/spessi (Aggiungi file, titolo), in Qt piu' leggeri; posizione e dimensione del testo coincidono, la differenza e' nei bordi dei glifi (peso/antialiasing). Il diff e' concentrato sul testo. Qui Qt su Windows non applica i pesi 500/600 del font variabile come Chromium (come nel cloud su Linux). Per il pixel-perfect, come da piano, ci si adegua a cio' che Qt disegna davvero (peso piu' leggero), non al QSS.
(c) **Scala:** le differenze NON crescono con la scala (3,3 → 3,2 → 3,0%). A 125% la barra ha 2,19% di pixel diversi (contro 0,1-0,15%): probabile arrotondamento del bordo arrotondato a scala frazionaria; da guardare piu' da vicino. Immagini viste: 100% e 125% (qt/web/diff); per 150% solo i numeri.
Il totale (3%) e' lontano dall'obiettivo dell'1%, ma e' quasi tutto testo (regioni di forme: 0,1-3%).

## Conclusione
**Guscio consigliato: pywebview (WebView2).** Soddisfa tutti i criteri: percorsi assoluti per locale/accenti/UNC/unita' mappata, dialoghi nativi, SSE entro i limiti, memoria +212 MB (soglia +250). Qt WebEngine (P1a-bis) non e' stato provato perche' non necessario.

## Dubbi e limiti
- I trascinamenti sono stati fatti **da me con mouse simulato** (SendInput) da Esplora risorse reale, non da una persona; il drag OLE e' quello vero di Explorer, ma conviene una conferma fisica del proprietario.
- Il percorso UNC e' `\\localhost\C$\...` (condivisione amministrativa locale), non un server remoto; l'unita' mappata `W:` invece e' SMB reale. Un `\\server\share\...` senza lettera non e' stato provato.
- La prima esecuzione di `p1_pywebview.py --auto` non si e' conclusa entro oltre 4 minuti (finestra aperta, nessun risultato); fermata e rilanciata, la seconda e' andata a buon fine in pochi secondi, e cosi' la prova con persona. Non so se sia stato un avvio a freddo di WebView2: da tenere d'occhio (timeout/avvio nel prodotto).
- `webview.__version__` stampa `?` nel JSON; la versione installata e' 6.2.1.
- La misura di memoria Qt e' un solo campione a 30 s, con il codice di una copia del progetto di produzione; il file `p1_pywebview_windows.json` e' quello della prova con persona (la prova `--auto` e' riassunta qui sopra, il suo file e' stato sovrascritto).
- Pixel: una sola schermata (titolo, due pulsanti, barra); non sono state misurate le schermate reali dell'app.

---

# P2 (27/10/2026)

| Prova | Esito | Misura chiave |
|---|---|---|
| P2a avvio ripetuto (10 avvii) | **OK** | 10/10 riusciti, durata min 1,92 s, media 2,03 s, max 2,75 s; nessun avvio bloccato |
| P2a avvio a freddo | vedi sotto | |
| P2b calibrazione del testo | **DIFFERENZA** (testo NON sotto il 2%) | totale schermata 4,5% → 4,0% (100%), 4,3% → 4,0% (125%), 4,2% → 3,8% (150%) |
| P2c trascinamento fisico del proprietario | **DA FARE** (serve la persona) | |

## P2a: avvio di pywebview
- 10 avvii consecutivi, ciascuno in un processo nuovo con limite di 45 s: tappe (processo → server → finestra creata → GUI avviata → `loaded` → `evaluate_js`) tutte raggiunte, `loaded` a circa 0,6 s. Nessun avvio non riuscito, quindi nessuna tappa di blocco da riferire (`p2_startup_windows_10avvii.json`).
- Il blocco di oltre 4 minuti del primo `--auto` non si e' riprodotto. Al momento delle prove i WebView2 presenti erano 12 processi di componenti di Windows (`SearchHost` e `WidgetBoard`), non chiudibili senza forzare la shell; il profilo di pywebview e' separato e non era in uso prima di ogni avvio.

## P2b: calibrazione del testo (CSS contro le schermate Qt gia' catturate)
| Scala | Elemento | Prima | Dopo | Migliori: peso / dimensione / letter-spacing / spostamento |
|---|---|---|---|---|
| 100% | Titolo | 13,21% | 12,15% | 300 / x0,97 / -0,3 px / -4 px |
| 100% | «Aggiungi file» | 11,29% | 8,10% | 350 / x0,97 / 0 / 0 |
| 100% | «Avvia» | 2,74% | **1,49%** | 550 / x0,99 / 0 / 0 |
| 125% | Titolo | 12,69% | 11,83% | 300 / x1,01 / -0,4 px / 0,5 px |
| 125% | «Aggiungi file» | 10,63% | 9,10% | 400 / x1,01 / 0 / 0 |
| 125% | «Avvia» | 3,42% | 2,67% | 500 / x1,02 / -0,1 px / 0 |
| 150% | Titolo | 11,97% | 10,94% | 300 / x0,99 / 0,2 px / 3 px |
| 150% | «Aggiungi file» | 10,32% | 7,65% | 450 / x0,99 / 0 / 0 |
| 150% | «Avvia» | 2,83% | 2,38% | 500 / x1,01 / 0 / 0 |

Totale schermata prima → dopo: 100% 4,48 → 3,96%; 125% 4,35 → 4,00%; 150% 4,21 → 3,75%. Barra: 0,64-0,70%.

- **Il testo NON scende sotto il 2%** (solo «Avvia» a 100%: 1,49%). Titolo e «Aggiungi file» restano al 7,7-12%.
- Guardando `p2_calibrazione_windows/*_dopo_diff.png`: **non e' solo antialiasing dei bordi**. Il diff mostra ancora le lettere raddoppiate/spessite (titolo e «Aggiungi file»), cioe' una differenza di forma/larghezza dei glifi. Inoltre il titolo ha il peso al limite inferiore della ricerca (300) e spostamenti anomali (-4, +0,5, +3 px): l'ottimizzatore sta compensando una diversita' che non si risolve con questi parametri (e un peso 300 non sarebbe una scelta credibile per il prodotto).
- Sulla barra, nel diff a 150%, si vede una linea sul bordo inferiore e a sinistra: scarto di circa 1 px nel posizionamento.
- Lo scarto «prima» del totale (4,2-4,5%) non coincide con quello di P1e (3,0-3,3%): probabilmente P2b misura una pagina/ritaglio diverso da quello di P1e; non verificato.
- Possibile causa (ipotesi, non verificata): Qt su Windows disegna il font con un'altra rasterizzazione (DirectWrite/GDI, hinting, istanza del font variabile) rispetto a Chromium, e questo non si recupera cambiando peso e dimensione. Servirebbe confrontare i font effettivi usati dai due motori.

## Dubbi
- Il criterio di un testo «sotto il 2%» sembra poco realistico con Chromium e Qt su Windows; conviene probabilmente valutare il testo a parte (come gia' scritto nel piano) con una soglia piu' alta, oppure per forme/posizione/larghezza e non pixel per pixel.
- L'avvio realmente a freddo (dopo un riavvio del PC o 10+ minuti senza WebView2) non e' stato riprodotto con certezza, vedi sotto.
