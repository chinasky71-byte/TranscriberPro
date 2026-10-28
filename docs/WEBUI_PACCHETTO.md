# TranscriberProWeb.exe — documento di ripresa / resume notes

**Stato: SPERIMENTALE, sospeso per decisione del proprietario (28/10/2026).** L'eseguibile non va in produzione ora; questo documento serve a riprendere il lavoro più avanti. / **Status: EXPERIMENTAL, paused by the owner's decision (2026-10-28).** The executable is not going to production now; this document is for picking the work up again later.

L'exe di prova costruito da `master` `93286e8` è allegato a una **Release in BOZZA** (non pubblica) del repository, non è nel repository. / The test exe built from `master` `93286e8` is attached to a **draft Release** (not public) of the repository; it is not in the repository.

---

# Italiano

## Cos'è

`TranscriberProWeb.spec` (PyInstaller, in radice) costruisce **un unico `TranscriberProWeb.exe`** (~70 MB) che avvia l'interfaccia web (`main.py --ui web`) e mostra la pagina della coda: server FastAPI su `127.0.0.1`, finestra nativa `pywebview` (WebView2) o browser. Dentro ci sono `main.py`, `tpweb/` (con `static/`), `core/`, `utils/`, `assets/` e le librerie leggere (FastAPI, uvicorn, starlette, pydantic, pywebview…). **Fuori** ci sono torch, le librerie CUDA/cuBLAS, bitsandbytes, transformers, ctranslate2, onnxruntime, PyQt6, scipy e simili: lo spec le esclude (`excludes`) e poi filtra per percorso di destinazione (`drop_heavy`) quelle che i loro hook riportano comunque dentro.

## Come ricostruirlo (comandi esatti, provati il 28/10/2026)

Ambiente di prova: Windows 11, **Python 3.11.9**, il `venv` del progetto (ha già `fastapi`, `uvicorn`, `httpx`, `psutil`, `pydantic`, ecc.). Pacchetti aggiuntivi **solo in cartelle isolate**, senza toccare il `venv`:

```bat
:: cartelle di prova (esempio)
set B=C:\prova\build
mkdir %B%
python -m pip install --target %B%\pylibs pywebview==6.2.1
python -m pip install --target %B%\pyinst pyinstaller        :: provato con pyinstaller 6.22.3 + pyinstaller-hooks-contrib 2026.9

:: dal clone pulito di master
git clone https://github.com/chinasky71-byte/TranscriberPro.git %B%\repo
cd %B%\repo
set PYTHONPATH=%B%\repo;%B%\pylibs;%B%\pyinst
set PYTHONUTF8=1
<venv>\Scripts\python.exe -m PyInstaller TranscriberProWeb.spec --noconfirm --distpath %B%\dist --workpath %B%\work
```

Esito del 28/10/2026 (`master` `93286e8`): exit 0 in ~57 s, `dist\TranscriberProWeb.exe` = **73 747 257 byte (70,3 MB)**, SHA-256 `A4F6388DA913D68957C4D30E40C3E7E6CBAF0AD214A86062BD74D69A366BB03F`. Versioni: `pywebview` 6.2.1 (con `pythonnet` 3.2.1, `clr_loader` 0.3.1, `bottle`, `proxy_tools`, `cffi`), `pyinstaller` 6.22.3 (`setuptools` 84.2.1 arriva come sua dipendenza ma lo spec esclude `pkg_resources` e `setuptools` dall'exe). `test_tpweb_packaging.py` controlla che tutto ciò che lo spec elenca esista.

Per provarlo con HOME isolata (non tocca `~\.transcriberpro`):

```bat
set USERPROFILE=C:\prova\home & set HOME=%USERPROFILE%
%B%\dist\TranscriberProWeb.exe --ui web            :: finestra nativa
%B%\dist\TranscriberProWeb.exe --ui web --no-browser   :: stampa l'indirizzo
```

L'exe è "onefile": a ogni avvio si estrae in `%TEMP%\_MEI…` (cartella rimossa alla chiusura normale; se si uccide il processo può restare).

## Cosa è stato fatto e misurato (rapporti in `docs/webui_rapporti/`)

| Giro | Esito |
|---|---|
| **P14** (`P14_GUSCIO_WINDOWS.md`) | Primo pacchetto: **~3,0 GB**, build 724 s; **non partiva**: `ModuleNotFoundError: No module named 'pkg_resources.extern'` da `pyi_rth_pkgres.py` |
| **P15** (`P15_RAPPORTO_WINDOWS.md`) | Spec senza `pkg_resources`/`setuptools`: **1129 MB**, build 196 s, si avvia (pagina dopo 18 s), chiusura con coda al lavoro 2,6 s |
| **P16** (`P16_PACCHETTO.md`) | Cosa pesava: `torch` 964 MB (`cublasLt64_12` 532, `cusparse64_12` 288, `cublas64_12` 105, `nvJitLink` 39), `cublasLt64_13` 456 + `cublas64_13` 52 nella radice, `bitsandbytes` 176 MB (10 DLL `libbitsandbytes_cuda1xx`), poi `numpy.libs` 21, `PIL` 13, `cryptography` 10, `hf_xet` 9,5, `lxml` 7… ≈ 1,5 GB di CUDA/torch |
| **P17** (`P17_RAPPORTO_WINDOWS.md`) | Filtro `drop_heavy` + `excludes`: **70 MB**, build 68 s, **finestra dopo 2,7 s**, pagina Coda, chiusura con coda al lavoro (X → Sì) in **2,2 s** con lock rimosso e nessun `_MEI` residuo; aggiunta di un file con il dialogo nativo funziona |
| **28/10** (questo documento) | Ricostruito da `master` `93286e8`: 70,3 MB; avvio con `--no-browser` stampa l'indirizzo in 2,1 s, la pagina risponde HTTP 200, nessun processo residuo |

## Cosa NON è provato (e cosa si sa già dal codice)

1. **Elaborazione vera dall'exe: non provata, e così com'è quasi certamente non funziona.** La coda lancia ogni file con `FileRunner` (`core/jobs/file_runner.py`): `[sys.executable, '-m', 'core.pipeline_cli', args.json]`. Nell'exe `sys.executable` è l'exe stesso, non un Python, e `core.pipeline_cli` ha bisogno dell'ambiente con torch/CUDA/ctranslate2/transformers (esclusi dallo spec). Serve decidere **come l'exe trova l'ambiente Python** (un `venv` configurato nelle impostazioni, o una cartella accanto all'exe) e far usare quell'interprete a `FileRunner` quando il programma è "frozen" (`sys.frozen`). Lo stesso vale per gli altri sottoprocessi (traduzione GGUF, correzione genere, glossario, sync, env check).
2. **Firma del codice e antivirus:** l'exe non è firmato; un onefile non firmato di PyInstaller è spesso segnalato da SmartScreen e da alcuni antivirus. Non provato su altri PC.
3. **Aggiornamenti:** nessun meccanismo (l'exe non si aggiorna da solo; il codice dentro è una copia di `core/`, `utils/`, `tpweb/`).
4. **WebView2** assente: il ripiego sul browser c'è (watchdog 20 s) ma non provato nell'exe su un PC senza WebView2.
5. **Gestione di `~/.transcriberpro` e di `models/`** dall'exe (dove cerca i modelli e le cache quando non sta nella cartella del progetto).
6. **GPU/driver:** l'exe non include CUDA; dipende interamente dall'ambiente esterno del punto 1.
7. **Chiave di Library Scanner:** `utils/config.py` contiene ancora il valore predefinito di `library_scanner_api_key` ed è dentro l'exe: il proprietario deve ruotarla prima di rendere pubblico l'exe (per questo la Release è in bozza).

## Prossimi passi consigliati

1. Decidere la strategia di distribuzione: (a) exe "leggero" + ambiente Python esterno già installato dal programma di installazione (`install.bat`), (b) exe completo con torch/CUDA (>3 GB, scartato per ora), (c) restare con `Lancia Transcriptor Web.vbs` sul `venv` (già funzionante, nessun exe).
2. Se (a): far trovare l'interprete a `FileRunner` e agli altri lanciatori di sottoprocessi quando `sys.frozen`; test di elaborazione vera con un file breve; test con GPU.
3. Ruotare la chiave Library Scanner e togliere il valore predefinito dal codice (`utils/config.py`) prima di qualunque pubblicazione.
4. Firma del codice, prova su un PC pulito senza Python (SmartScreen/antivirus), prova senza WebView2.
5. Decidere come si aggiorna (nuova Release? installer?).

---

# English

## What it is

`TranscriberProWeb.spec` (PyInstaller, in the repository root) builds **a single `TranscriberProWeb.exe`** (~70 MB) that starts the web UI (`main.py --ui web`) and shows the queue page: a FastAPI server on `127.0.0.1`, a native `pywebview` window (WebView2) or the browser. Inside: `main.py`, `tpweb/` (with `static/`), `core/`, `utils/`, `assets/` and the light libraries (FastAPI, uvicorn, starlette, pydantic, pywebview…). **Outside:** torch, the CUDA/cuBLAS libraries, bitsandbytes, transformers, ctranslate2, onnxruntime, PyQt6, scipy and similar: the spec excludes them (`excludes`) and then filters by destination path (`drop_heavy`) those that their hooks would still bring in.

## How to rebuild it (exact commands, tested on 2026-10-28)

Test environment: Windows 11, **Python 3.11.9**, the project's `venv` (it already has `fastapi`, `uvicorn`, `httpx`, `psutil`, `pydantic`, …). Extra packages **only in isolated folders**, without touching the `venv`:

```bat
:: test folders (example)
set B=C:\test\build
mkdir %B%
python -m pip install --target %B%\pylibs pywebview==6.2.1
python -m pip install --target %B%\pyinst pyinstaller        :: tested with pyinstaller 6.22.3 + pyinstaller-hooks-contrib 2026.9

:: from a clean clone of master
git clone https://github.com/chinasky71-byte/TranscriberPro.git %B%\repo
cd %B%\repo
set PYTHONPATH=%B%\repo;%B%\pylibs;%B%\pyinst
set PYTHONUTF8=1
<venv>\Scripts\python.exe -m PyInstaller TranscriberProWeb.spec --noconfirm --distpath %B%\dist --workpath %B%\work
```

Result on 2026-10-28 (`master` `93286e8`): exit 0 in ~57 s, `dist\TranscriberProWeb.exe` = **73,747,257 bytes (70.3 MB)**, SHA-256 `A4F6388DA913D68957C4D30E40C3E7E6CBAF0AD214A86062BD74D69A366BB03F`. Versions: `pywebview` 6.2.1 (with `pythonnet` 3.2.1, `clr_loader` 0.3.1, `bottle`, `proxy_tools`, `cffi`), `pyinstaller` 6.22.3 (`setuptools` 84.2.1 comes in as its dependency, but the spec excludes `pkg_resources` and `setuptools` from the exe). `test_tpweb_packaging.py` checks that everything the spec lists exists.

To try it with an isolated HOME (it does not touch `~\.transcriberpro`):

```bat
set USERPROFILE=C:\test\home & set HOME=%USERPROFILE%
%B%\dist\TranscriberProWeb.exe --ui web            :: native window
%B%\dist\TranscriberProWeb.exe --ui web --no-browser   :: prints the address
```

The exe is "onefile": at every start it extracts itself into `%TEMP%\_MEI…` (removed on a normal exit; it can be left behind if the process is killed).

## What was done and measured (reports in `docs/webui_rapporti/`)

| Round | Result |
|---|---|
| **P14** (`P14_GUSCIO_WINDOWS.md`) | First package: **~3.0 GB**, build 724 s; **it did not start**: `ModuleNotFoundError: No module named 'pkg_resources.extern'` from `pyi_rth_pkgres.py` |
| **P15** (`P15_RAPPORTO_WINDOWS.md`) | Spec without `pkg_resources`/`setuptools`: **1129 MB**, build 196 s, it starts (page after 18 s), close with the queue working 2.6 s |
| **P16** (`P16_PACCHETTO.md`) | What was heavy: `torch` 964 MB (`cublasLt64_12` 532, `cusparse64_12` 288, `cublas64_12` 105, `nvJitLink` 39), `cublasLt64_13` 456 + `cublas64_13` 52 at the root, `bitsandbytes` 176 MB (10 `libbitsandbytes_cuda1xx` DLLs), then `numpy.libs` 21, `PIL` 13, `cryptography` 10, `hf_xet` 9.5, `lxml` 7… ≈ 1.5 GB of CUDA/torch |
| **P17** (`P17_RAPPORTO_WINDOWS.md`) | `drop_heavy` filter + `excludes`: **70 MB**, build 68 s, **window after 2.7 s**, queue page, close with the queue working (X → Yes) in **2.2 s** with the lock removed and no leftover `_MEI`; adding a file with the native dialog works |
| **2026-10-28** (this document) | Rebuilt from `master` `93286e8`: 70.3 MB; started with `--no-browser` it prints the address in 2.1 s, the page answers HTTP 200, no leftover process |

## What is NOT tested (and what the code already tells us)

1. **Real processing from the exe: not tested, and as it stands it almost certainly does not work.** The queue launches every file through `FileRunner` (`core/jobs/file_runner.py`): `[sys.executable, '-m', 'core.pipeline_cli', args.json]`. In the exe `sys.executable` is the exe itself, not a Python, and `core.pipeline_cli` needs the environment with torch/CUDA/ctranslate2/transformers (excluded from the spec). It must be decided **how the exe finds the Python environment** (a `venv` set in the settings, or a folder next to the exe) and `FileRunner` must use that interpreter when the program is "frozen" (`sys.frozen`). The same applies to the other subprocesses (GGUF translation, gender correction, glossary, sync, env check).
2. **Code signing and antivirus:** the exe is unsigned; an unsigned PyInstaller onefile is often flagged by SmartScreen and by some antivirus products. Not tried on other PCs.
3. **Updates:** no mechanism (the exe does not update itself; the code inside is a copy of `core/`, `utils/`, `tpweb/`).
4. **No WebView2:** the browser fallback exists (20 s watchdog) but was not tested inside the exe on a PC without WebView2.
5. **Handling of `~/.transcriberpro` and `models/`** from the exe (where it looks for models and caches when it is not in the project folder).
6. **GPU/drivers:** the exe does not ship CUDA; it depends entirely on the external environment of point 1.
7. **Library Scanner key:** `utils/config.py` still contains the default value of `library_scanner_api_key` and it is inside the exe: the owner must rotate it before the exe is made public (this is why the Release is a draft).

## Recommended next steps

1. Decide the distribution strategy: (a) light exe + an external Python environment installed by the installer (`install.bat`), (b) full exe with torch/CUDA (>3 GB, discarded for now), (c) stay with `Lancia Transcriptor Web.vbs` on the `venv` (already working, no exe).
2. If (a): make `FileRunner` and the other subprocess launchers find the interpreter when `sys.frozen`; test real processing with a short file; test with a GPU.
3. Rotate the Library Scanner key and remove the default value from the code (`utils/config.py`) before any publication.
4. Code signing, a test on a clean PC without Python (SmartScreen/antivirus), a test without WebView2.
5. Decide how it is updated (a new Release? an installer?).
