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
