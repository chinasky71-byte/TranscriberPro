# Transcriber Pro – interfaccia web (guida)

L'interfaccia web e' una **seconda interfaccia** per lo stesso programma: stessa coda, stessi motori, stessa configurazione. **E' l'interfaccia predefinita**: `python main.py` e `Lancia Transcriptor.bat/.vbs` avviano la web UI; la GUI Qt (in dismissione) si ottiene con `--ui qt` o `ui: qt` nel config.
E' in `master` (dalla 1.34.41 + web UI): si avvia senza argomenti, con `--ui web` o con `Lancia Transcriptor Web.bat/.vbs`. Verificata su Windows contro la finestra Qt vera (rapporti in `docs/webui_rapporti/`).

## Avvio
| Come | Comando |
|---|---|
| Windows (con console) | `Lancia Transcriptor Web.bat` |
| Windows (senza console) | `Lancia Transcriptor Web.vbs` |
| Linux | `./run_web.sh` |
| A mano | `python main.py --ui web` oppure `python -m tpweb` |

Opzioni: `--shell auto\|on\|off` (finestra nativa), `--no-browser` (stampa solo l'indirizzo; niente finestra). La scelta dell'interfaccia puo' stare nel
config (chiave `ui`); `--ui qt` forza la GUI Qt.

**Finestra nativa (opzionale).** Con `pywebview` installato (`pip install -r requirements-web.txt`; su Windows usa WebView2) la pagina si apre in una
finestra propria, con i dialoghi di Windows per scegliere file e cartelle e il trascinamento di file da Esplorer. Senza pywebview, o se la finestra
non si apre (lo si verifica da soli: pagina bianca dopo 20 s -> secondo tentativo con un profilo pulito -> browser predefinito), si usa il browser.

## Cosa c'e' (parita' con la GUI)
Pagina **Coda** (file, filtri, riordino, eccezioni per file, Avvia/Stop, spegnimento, locandina, log con Log Sintetico, card «Pipeline in corso»,
diagnostica, risorse), **Cronologia**, **Impostazioni** (7 schede), **Strumenti** (Glossario per show, Sincronizzazione), **Library Scanner** (elenco, import,
conversione ASS/SSA, OCR con revisione mirata, Superpower). La matrice completa, voce per voce e con i test, e' in `tpweb/PARITY.md`.

Differenze volute rispetto alla GUI (sono nella matrice): il tasto **Esci**; chiudere la scheda del browser **non ferma** l'elaborazione (con la finestra
nativa si, con conferma se la coda e' al lavoro); i dialoghi Glossario/Sincronizzazione sono viste su un lavoro che vive sul server (ricaricare la pagina
non lo interrompe, chiudere il dialogo si).

## Sicurezza
- Il server ascolta **solo su 127.0.0.1**, su una porta libera, con un **token** casuale per ogni avvio (cookie `HttpOnly`); controlla `Host` e `Origin`;
  nessun CORS; intestazioni CSP restrittive. Dal resto della rete non e' raggiungibile.
- Chiavi e password (Library Scanner, OpenSubtitles, Claude, OpenAI, token Hugging Face) **non escono mai dal server**: la pagina sa solo se sono impostate
  e puo' farsele mostrare una alla volta (`Mostra`).
- Un solo server per utente (`~/.transcriberpro/tpweb.lock`); rifiuta di partire se la GUI Qt o la coda headless stanno usando la coda.

## Struttura
`tpweb/` (server FastAPI, nessun PyQt6): `app.py`, `routes_*.py`, `queue_backend.py` (coda + motore), `tools.py` (Glossario/Sincronizzazione), `ocr.py`,
`library.py`, `shell.py` (finestra nativa), `static/` (pagina senza passaggio di build: moduli ES + Preact/htm in copia locale). La logica condivisa con la
GUI sta in `core/` (servizi senza Qt estratti dalla GUI, con test di caratterizzazione).

## Test
`pytest linux_tests -q` (servono fastapi, uvicorn, httpx e, per le prove nel browser, `playwright` con Chromium). Le prove che richiedono Windows (aspetto
confrontato con Qt, finestra pywebview, dialoghi nativi, pacchetto PyInstaller) sono elencate in `tpweb/PARITY.md` e le fa la sessione locale.

## Pacchetto
`TranscriberProWeb.spec` (PyInstaller): SPERIMENTALE. Costruisce un unico `TranscriberProWeb.exe` da ~70 MB (senza torch, CUDA e bitsandbytes) che si avvia e mostra la pagina della coda; l'elaborazione vera richiede ancora l'ambiente Python con le librerie pesanti (sottoprocesso `core.pipeline_cli`) e non e' stata provata dall'exe. Non fa parte dell'installazione supportata. `test_tpweb_packaging.py` verifica che tutto cio' che elenca esista.
