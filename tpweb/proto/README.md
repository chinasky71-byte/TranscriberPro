# Prototipi P1 (tpweb/proto)

Servono a **misurare**, non sono il codice definitivo. Piano e criteri: `docs/WEBUI_PIANO.md`. Da lanciare in un venv usa e getta
(MAI in quello di produzione): `fastapi==0.139.2 uvicorn==0.51.0 starlette==1.3.1 httpx==0.28.1 psutil pytest pillow numpy playwright
pywebview PyQt6==6.10.2` (e `PyQt6-WebEngine==6.10.0` solo per il guscio di riserva).

| Script | Dove gira | Cosa misura |
|---|---|---|
| `p1_security_tests.py` | ovunque (pytest) | token, Host, Origin, CORS, intestazioni, ascolto solo su loopback |
| `p1_bench_sse.py` | ovunque (Playwright; su Windows `--channel msedge`) | consegna di 5.000 righe + 10 aggiornamenti/s, latenza, attivita' lunghe della pagina |
| `p1_pixel.py` | **Windows** (il Qt va misurato dove gira) | differenza in pixel fra tema Qt vero e CSS equivalente, a piu' scale di DPI |
| `p1_pywebview.py` | **Windows**, con una persona | percorsi dei file trascinati, dialoghi nativi, banco SSE nella finestra vera, memoria |
| `p1_qtwebengine.py` | **Windows**, solo se pywebview non basta | guscio di riserva con Qt WebEngine |
| `p1_qt_baseline_mem.py` | **Windows** | memoria della GUI Qt attuale a riposo (termine di confronto) |
| `p2_calibrate_text.py` | **Windows** | quanto del testo e' calibrabile in CSS contro le schermate Qt gia' catturate |
| `p2_pywebview_startup.py` | **Windows** | avvio ripetuto di pywebview, con tappe e limite di tempo (indaga il blocco) |

Risultati in `results/` (JSON + immagini). Le misure di `*_linux.json` sono quelle del cloud e servono solo a provare gli strumenti.

**Regola di verifica degli strumenti:** prima di fidarsi di una misura nuova, la si fa riprodurre un valore gia' noto (es. il «prima» di `p2_calibrate_text.py` deve coincidere con il totale di `p1_pixel.py` sugli stessi dati). Lo scarto della v1 del calibratore (barra 12 px invece dei 14 px reali di Qt) si e' visto cosi'.
