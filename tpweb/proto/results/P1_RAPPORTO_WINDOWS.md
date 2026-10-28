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

---

## P2b-bis: calibratore corretto (barra a 14 px reali, spostamento verticale, profili di rendering)

**Verifica dello strumento:** con `--profili predefinito` il «totale prima» e' 3,276 / 3,247 / 2,955% a 100/125/150%, identico a P1e (3,28 / 3,25 / 2,96). Lo strumento e' coerente. (Il confronto di P2b precedente, 4,2-4,5%, era sbagliato per lo strumento, non per Windows.)

### Totale schermata prima → dopo, per profilo e scala
| Profilo | 100% | 125% | 150% | Media dopo |
|---|---|---|---|---|
| predefinito | 3,28 → 2,25 | 3,25 → 2,39 | 2,96 → 2,26 | 2,300 |
| crenatura_off (migliore) | 3,45 → 2,40 | 3,29 → 2,15 | 3,00 → 2,32 | 2,288 |
| text_geometricPrecision | 3,28 → 2,25 | 3,25 → 2,39 | 2,96 → 2,26 | 2,300 |
| text_optimizeSpeed | 3,28 → 2,25 | 3,25 → 2,39 | 2,96 → 2,26 | 2,300 |
| glifi_a_pixel_interi | 3,28 → 2,25 | 3,25 → 2,39 | 2,96 → 2,26 | 2,300 |
| hinting_none | 3,28 → 2,25 | 3,25 → 2,39 | 2,96 → 2,26 | 2,300 |

I profili di rendering (`geometricPrecision`, `optimizeSpeed`, glifi a pixel interi, hinting) **non cambiano nulla** (valori identici al predefinito). Solo disattivare la crenatura sposta qualcosa, e di pochissimo (2,288 contro 2,300): il «migliore» e' praticamente un pareggio.

### Profilo migliore (crenatura_off): per elemento, prima → dopo e parametri
| Scala | Elemento | Prima → Dopo | Peso | Dimensione | Spaziatura | Sposta X | Sposta Y |
|---|---|---|---|---|---|---|---|
| 100% | Titolo | 12,63 → 8,69% | 400 | x1,00 | +0,4 px | +2,0 px | +0,5 px |
| 100% | «Aggiungi file» | 11,49 → 8,10% | 350 | x0,97 | 0 | 0 | 0 |
| 100% | «Avvia» | 4,35 → 3,02% | 450 | x1,00 | 0 | 0 | 0 |
| 125% | Titolo | 11,44 → 6,97% | 600 | x1,01 | 0 | +2,5 px | +0,5 px |
| 125% | «Aggiungi file» | 10,50 → 7,31% | 400 | x1,01 | 0 | 0 | -1,5 px |
| 125% | «Avvia» | 3,95 → 2,29% | 450 | x0,98 | +0,2 px | 0 | -1,5 px |
| 150% | Titolo | 10,99 → 8,50% | 500 | x1,00 | +0,3 px | +0,5 px | +0,5 px |
| 150% | «Aggiungi file» | 10,00 → 7,93% | 450 | x0,99 | 0 | 0 | 0 |
| 150% | «Avvia» | 3,73 → 2,64% | 450 | x1,01 | 0 | -0,5 px | 0 |

Barra: 0,10% (100%), **2,19% (125%)**, 0,15% (150%): a 125% non e' migliorata rispetto a P1e, quindi non e' un artefatto dello strumento di P2b.

### Risposte
1. **Peso:** NO, non e' 400 per tutti. Va da 350 a 600 a seconda di elemento e scala; i pulsanti stanno tra 350 e 450 (il QSS dice 500/600), cioe' Qt li disegna piu' leggeri; il titolo oscilla (400/600/500). Nessun peso al limite inferiore della ricerca (300) come in P2b; 600 del titolo a 125% coincide col valore del QSS.
2. **Spostamento del titolo:** sistematico in verticale (+0,5 px a tutte le scale) e in orizzontale a 100% e 125% (+2,0 e +2,5 px, in linea col cloud: +2,5/+0,5 a 100%), ma NON a 150% (+0,5 px).
3. **Totale sotto l'1,5%?** NO: 2,40 / 2,15 / 2,32% (profilo migliore). Nessun elemento di testo e' sotto il 2%, tranne «Avvia» a 125% (2,29%, ancora sopra) — nessuno sotto il 2%.

### Immagini `crenatura_off_<scala>_dopo_diff.png`
La barra e i bordi dei pulsanti sono ora puliti (linee sottili). Sul testo il diff segue il profilo delle lettere ma e' ancora marcato su titolo e «Aggiungi file» (a 150% il titolo ha tratti spessi): e' per lo piu' differenza di rasterizzazione dei contorni, con un residuo di larghezza/peso (il titolo a 150% pare piu' largo in alcune lettere). Nessuna differenza di posizione evidente dopo la calibrazione.

### Anomalie e dubbi
- Spostamenti verticali di -1,5 px su «Aggiungi file» e «Avvia» a 125% (e 0 alle altre scale): non sistematici, probabile arrotondamento di layout a scala frazionaria; da non portare nel prodotto cosi' come sono.
- Il guadagno della calibrazione e' modesto (≈1 punto) e i parametri non sono stabili fra scale: per il testo conviene fissare una soglia piu' alta o valutare forme/posizione/larghezza a parte, come previsto dal piano.
