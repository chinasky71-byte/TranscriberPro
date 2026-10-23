# Passaggio di consegne: Linux e GPU AMD (per Claude nel cloud)

Documento scritto il 23/10/2026 da una sessione locale di Claude Code, per una sessione Claude nel cloud (con la propria VM Linux) che deve **proseguire il lavoro di compatibilità Linux/AMD di Transcriber Pro** mentre il proprietario non ha a disposizione una macchina Linux con GPU AMD. Leggilo tutto prima di toccare qualcosa. Il repository è pubblico: <https://github.com/chinasky71-byte/TranscriberPro>.

## 0. Regole d'ingaggio (non negoziabili)

1. **Sicurezza e credenziali.** Non scrivere mai nel repository chiavi, token, password, indirizzi privati o dati personali. Non chiedere né usare credenziali del proprietario. Il token Hugging Face, le chiavi TMDB/OMDb/OpenSubtitles e simili si impostano a mano dall'utente e non servono per nessuna delle fasi sotto.
2. **Branch e pull request.** Lavora su un branch per fase (`linux-amd/f4a-install-sh`, ...) e apri una pull request in italiano. **Non fare push su `master`**: la release (versione, CHANGELOG, README) la fa il proprietario. Un commit per cambiamento logico; messaggi in italiano.
3. **Non rompere l'esistente.** Il percorso **Windows + NVIDIA** è quello in produzione e deve restare identico: ogni modifica deve essere a prova di regressione su quel percorso (stessi valori, stessi comandi). Cambi minimi, niente refactoring non richiesti, niente "euristiche" il cui esito non è prevedibile: ogni regola scritta e commentata nel codice.
4. **Onestà sui limiti.** Nella VM non c'è una GPU AMD. Tutto ciò che richiede una GPU AMD reale si **prepara e si prova per quanto possibile** (installazione, import, risoluzione dei pacchetti, rilevamento, test con uscite simulate), poi si lascia a una **checklist di prova per l'utente** (sezione 6). Non dichiarare mai "funziona su AMD" senza una prova su hardware AMD: scrivi "preparato, non verificato su hardware".
5. **Niente download grandi senza motivo.** Per le prove usa modelli minuscoli (es. un GGUF da poche centinaia di MB) e mai i modelli di produzione (14B, NLLB da 3,3B ecc.).
6. **Lingua.** Documentazione, commenti e messaggi per l'utente in italiano; identificatori e comandi nella forma originale.
7. **Sincronizzazione con il proprietario (due scrittori, un repository).** Il proprietario sviluppa in una cartella locale e la copia nel repository con degli script che sovrascrivono i file diversi. Per non perdere il tuo lavoro: i tuoi cambi entrano in `master` **solo** tramite PR fuse dal proprietario, che prima di ogni sua release fa `git pull` e copia nella cartella locale i file toccati dai tuoi commit. Perciò: non lasciare PR aperte a lungo, tieni i commit piccoli e descrivi nel PR **quali file** hai cambiato.
8. **Se non puoi fare push** (l'app GitHub di Claude potrebbe non essere installata sul repository, o il tuo ambiente non ha permessi di scrittura): lavora su un fork, oppure consegna nella sessione una patch (`git diff`/`git format-patch`) e il testo da aggiungere a `docs/HANDOFF_LOG_LINUX_AMD.md`, che il proprietario applica. Non cercare di aggirare i permessi.
9. **Pin da non toccare sul percorso NVIDIA:** `ctranslate2==4.6.0` (la 4.7.x causava un crash silenzioso con `WhisperModel()` dentro PyQt6), `llama-cpp-python==0.3.34` (la 0.3.35 crasha sulla CPU del proprietario), `onnxruntime` importato **prima** di PyQt6, nessuna inizializzazione CUDA prima di `WhisperModel`. Sono regole del progetto, non preferenze.

## 1. Che cos'è il progetto (in breve)

Transcriber Pro è un'app desktop PyQt6 (Python 3.11) che trascrive video (Whisper/Qwen3-ASR/Canary), diarizza (pyannote), traduce i sottotitoli (NLLB fine-tuned, TranslateGemma, Claude/OpenAI) e costruisce glossari per show con un LLM locale (Qwen2.5 GGUF via `llama-cpp-python`). Modello di esecuzione: GUI + sottoprocessi (`core/*_cli.py`) per isolare le GPU. Oggi supporta **Windows con GPU NVIDIA (CUDA)** o CPU; il lavoro in corso estende a **Linux** e a **GPU AMD/Intel**.

File chiave per questo lavoro:

| Percorso | Ruolo |
|---|---|
| `utils/platform_compat.py` | Differenze Windows/Linux in un posto solo (`venv_python`, `no_window_flags`, `kill_tree`, `find_tool`, `is_foreign_windows_path`) |
| `utils/gpu_detect.py` | Rilevamento GPU multi-vendor (NVIDIA/AMD/Intel), backend disponibili e consigliato; CLI `python utils/gpu_detect.py [--json\|--vram\|--backend]` |
| `utils/llm_model_select.py` | Scelta del Qwen 14B/7B in base alla VRAM (oggi conta solo NVIDIA/CUDA, con `backend='cuda'`) |
| `utils/path_map.py` | Corrispondenza percorsi del Library Scanner server→cartelle montate (Linux) |
| `install.ps1`, `install.sh`, `run.sh` | Installer/lanciatori (Windows e Linux) |
| `scripts_manutenzione/selfcheck_env.py` | Controllo dell'ambiente a fine installazione |
| `requirements*.txt` | Pin (torch `2.8.0+cu126`, ruote CUDA di llama: percorso NVIDIA) |
| `docs/studio_rocm_2026_10_22.md` | **Studio di fattibilità ROCm (leggilo: contiene fonti e verifiche)** |
| `linux_tests/` | Test portabili (senza GPU, senza Qt): `python -m pytest linux_tests -q` |

## 2. Fasi già completate (con commit)

| Versione | Commit | Cosa è stato fatto |
|---|---|---|
| 1.34.6 | `3ed828f` | `utils/platform_compat.py` + test-lint di piattaforma |
| 1.34.7 | `a47be08` | Migrati i punti Windows-only (venv, `CREATE_NO_WINDOW`, `taskkill`→`kill_tree` con psutil) |
| 1.34.8 | `0c0e7ef` | `glossary_engine/` portabile (il bridge Qwen carica `platform_compat` da file) |
| 1.34.9 | `0ba8e17` | `Config.get()` ignora i percorsi con lettera di unità fuori da Windows |
| 1.34.10 | `733fff5` | `install.ps1` scarica da solo `ita`/`eng` di Tesseract |
| 1.34.11 | `0eee5a3` | `install.ps1 -NoGpu`: ruota CPU di llama-cpp-python |
| 1.34.12 | `1194f5b` | `find_tool` (Tesseract/MKVToolNix fuori PATH), torch CPU con `-NoGpu`, indirizzo di default del Library Scanner |
| 1.34.13 | `b676aab` | **Linux fase 3:** `install.sh`/`run.sh`, mappa percorsi Library Scanner (`library_scanner_path_map`), selfcheck portabile, notifica `notify-send`, `pywin32` solo Windows, `.gitattributes` |
| 1.34.14 | `660536b` | `LICENSE`, `NOTICE.md`, chiave TMDB tolta dal codice |
| 1.34.15 | `19e34db` | Scelta del Qwen per VRAM (14B ≥12 GB, 7B ripiego), opzione installer `-QwenSize` |
| 1.34.16 | `3141198` | `install.sh --with-models --qwen-size=auto\|7b\|14b` |
| 1.34.17 | `65cab33` | `utils/gpu_detect.py` (rilevamento GPU multi-vendor) |

Verificato sul serio (con l'installer su un PC Windows pulito senza GPU): installazione, idempotenza, avvio GUI, selfcheck. **Mai eseguito su una macchina Linux reale:** `install.sh`, `run.sh`, il selfcheck su Linux, `gpu_detect` con sysfs/`lspci`/`vulkaninfo` reali, `path_map` in uso, `notify-send`.

## 3. Fatti da conoscere (già verificati, non rifarli)

- **PyTorch ROCm:** esistono ruote ufficiali `torch-2.8.0+rocm6.3` e `+rocm6.4` (cp311 Linux x86_64) e `torchaudio-2.8.0+rocm6.4` su `download.pytorch.org/whl/rocmX.Y`. Non esiste `rocm7.0` per torch 2.8.0.
- **ctranslate2 con ROCm:** le release 4.7.2–4.8.3 di OpenNMT/CTranslate2 hanno gli asset `rocm-python-wheels-Linux.zip` e `-Windows.zip` (ruote su GitHub, **non su pip**). Il progetto sul percorso NVIDIA resta alla 4.6.0.
- **llama-cpp-python 0.3.34:** sull'indice `https://abetlen.github.io/llama-cpp-python/whl/` ci sono ruote precompilate per `cpu`, `cu124`, `cu125` e **`vulkan`** (Linux x86_64 e Windows). **Non esistono** cartelle `rocm`/`hip`: per HIP serve compilare da sorgente.
- **bitsandbytes:** esiste la 0.50.2 su PyPI (il progetto ha la 0.49.2); il supporto ROCm stabile della 0.50 non è stato verificato.
- **Qwen3-ASR** (`qwen_asr` 0.0.6): nessuna dipendenza rigida da `flash_attn`/`triton`; usa le funzioni di attenzione di transformers.
- **Canary/NeMo:** nessun supporto ROCm (solo NVIDIA).
- **Il vero consumo di Qwen/llama.cpp è raro:** in produzione serve solo per la **costruzione del glossario per-show** (e, a certe condizioni, per il serbatoio L3 di traduzione). Trascrizione, traduzione, Demucs e diarizzazione girano su PyTorch/ctranslate2: per una GPU AMD ci vuole **ROCm**, Vulkan non basta.
- Per l'elenco completo di cosa funzionerebbe su AMD, rischi e stime vedi `docs/studio_rocm_2026_10_22.md`.

## 4. Fasi da fare (in ordine) e come

Per ogni fase: branch dedicato, test in `linux_tests/`, PR con i risultati e con l'aggiornamento di `docs/HANDOFF_LOG_LINUX_AMD.md` (sezione 7).

### F4 — Prova reale su Linux (nessuna GPU necessaria)
**Obiettivo:** far girare per davvero ciò che finora è stato solo scritto.
- **F4a. `install.sh`.** Su una VM Ubuntu LTS (poi, se possibile, anche Fedora): `./install.sh --check`, poi `./install.sh --no-gpu --yes`. Correggi i bug reali (nomi dei pacchetti per apt/dnf/pacman/zypper, `venv` mancante, Python 3.11/3.12, `sed` GNU, `trap`, `mktemp`). Python 3.11 non è nei repository di Ubuntu 24.04: valuta `uv`/`pyenv` o il ramo 3.12 (le ruote di tutti i pin esistono per cp311/cp312/cp313, ma **3.12 non è verificato a runtime**: dichiaralo). Criterio: `./install.sh --no-gpu --yes` termina e il selfcheck (`scripts_manutenzione/selfcheck_env.py --no-gpu`) non ha KO bloccanti.
- **F4b. Test.** `pip install -r linux_tests/requirements.txt` (pytest, psutil, requests, pillow: nessun torch né Qt) e `python -m pytest linux_tests -q`. Su Windows (venv minimo con queste sole dipendenze) i test sono **86 passed**; **su Linux non sono mai stati eseguiti**: un primo fallimento può essere un difetto del test, non del codice (distinguilo e correggi il test o il codice di conseguenza). Il lint di piattaforma (`test_platform_lint.py`) ha una baseline esatta: se la modifica cambia i pattern vietati, aggiorna `BASELINE` con motivazione.
- **F4c. `gpu_detect` reale.** `python utils/gpu_detect.py --json` sulla VM (senza GPU: report vuoto o solo device software, backend `cpu`): verifica che non scriva su stderr, non sia lento (<2 s), non conti llvmpipe come GPU. Se la VM ha una GPU di qualsiasi marca, confronta con `lspci`, `/sys/class/drm/card*/device/`, `vulkaninfo --summary` e correggi i parser sulle uscite **reali** (salva le uscite reali come fixture nei test).
- **F4d. Avvio dell'app.** Con `QT_QPA_PLATFORM=offscreen` (o `xvfb-run -a`): importa i moduli principali e istanzia la finestra principale con una config isolata (`HOME` temporanea); l'obiettivo è scovare import/percorsi/stile specifici di Windows. Non servono modelli. Ricorda che il tema usa `gui/theme.qss.tpl` generato a runtime.
- **F4e. Library Scanner.** Verifica `utils/path_map.py` e il campo "Cartelle montate" (visibile solo fuori da Windows) con un server finto.

### F5 — Vulkan per llama.cpp (glossario su GPU AMD/Intel, senza ROCm)
**Obiettivo:** far usare la GPU ai glossari su qualunque GPU con driver Vulkan. È una fase **preparatoria**: non mette su GPU trascrizione e traduzione (quelle richiedono F6).
1. **Selezione del backend nell'installer**, in `install.sh` e `install.ps1`: opzione `--gpu-backend auto|cuda|vulkan|rocm|cpu` (Windows: `-GpuBackend`), con `auto` = `python utils/gpu_detect.py --backend` (usa il Python di sistema, solo libreria standard). Il ramo `cuda` non cambia di una virgola.
2. **Ruota Vulkan di llama:** `pip install --force-reinstall --no-deps --only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/vulkan llama_cpp_python==0.3.34` (stesso schema già usato per la ruota CPU in `install.ps1`; resta il pin 0.3.34). Prerequisito di sistema: libreria Vulkan (`libvulkan1` + driver Mesa su Linux).
3. **Come l'app sa quale llama è installato:** l'installer scrive un marcatore (es. `llama_backend.txt` accanto al venv, o lo si ricava da `llama_cpp` a runtime) e `utils/llm_model_select.detect_vram_mib()` passa dal solo `backend='cuda'` al backend effettivo (`usable_vram_mib(rep, backend=...)`). Senza marcatore resta il comportamento di oggi.
4. **Prova nella VM:** installa `mesa-vulkan-drivers` (device software lavapipe), forza `TP_GPU_FORCE_BACKEND=vulkan`, scarica **un GGUF minuscolo** pubblico e verifica che `llama_cpp` si importi, carichi il modello con `n_gpu_layers` > 0 e generi qualche token. Le prestazioni con lavapipe non significano nulla: si prova solo che la ruota carica e che l'offload non crasha.
5. **Canale GPU del glossario** (`glossary_engine/glossary_qwen_gpu_cli.py`): oggi legge la VRAM libera con `nvidia-smi` (riga ~66): sostituire con `gpu_detect` (campo `vram_free_mib`), mantenendo il valore invariato per NVIDIA.

### F6 — Insieme di pin ROCm (Linux) e smoke test per l'utente
**Obiettivo:** poter installare l'app su una macchina AMD con un solo comando e avere un test di fumo da far girare all'utente.
1. **`requirements-rocm.txt`** (separato, selezionato da `--gpu-backend rocm`; **il percorso NVIDIA non si tocca**): `torch==2.8.0+rocm6.4`, `torchaudio==2.8.0+rocm6.4` (indice `https://download.pytorch.org/whl/rocm6.4`), `torchcodec` compatibile con quel torch, `bitsandbytes` (0.50.x), `whisperx` installato con `--no-deps` (il progetto lo usa solo in `core/aligner.py`), il resto come `requirements.txt` senza le righe `+cu126`. Verifica la risoluzione **senza GPU** con `pip install --dry-run --ignore-installed --only-binary=:all: --target <tmp> --platform manylinux_2_28_x86_64 --python-version 3.11 -r requirements-rocm.txt` (e per 3.12), e importa torch ROCm nella VM (`torch.version.hip` valorizzato, `torch.cuda.is_available()` falso senza GPU: è normale).
2. **ctranslate2 ROCm:** scarica l'asset `rocm-python-wheels-Linux.zip` della release più recente (4.8.x), controlla i tag delle ruote (cp311/cp312, manylinux) e che `import ctranslate2` funzioni nella VM; annota che **il primo test decisivo su hardware AMD è Whisper con ctranslate2 ROCm dentro PyQt6** (il pin 4.6.0 esiste proprio perché 4.7.x crashava lì sul percorso NVIDIA).
3. **Installer:** ramo `--gpu-backend rocm` in `install.sh`: controlli (`/dev/kfd` accessibile, gruppi `render`/`video`, driver amdgpu), niente installazione di ROCm di sistema (si descrive e basta), messaggi chiari. `gpu_detect` ha già `/dev/kfd`/`rocminfo`.
4. **`scripts_manutenzione/amd_smoke_test.py`** (da scrivere): raccoglie `gpu_detect --json`, versioni di torch/HIP, un piccolo calcolo su GPU, `ctranslate2.get_supported_compute_types('cuda')`, un `llama_cpp` Vulkan di 5 token, e (opzionale) una trascrizione di 10 secondi con un Whisper `tiny`; scrive un unico file di testo `amd_smoke_report.txt` senza dati personali, da rimandare agli sviluppatori. Deve gestire con grazia ogni componente mancante.

### F7 — Punti del codice che assumono NVIDIA (generalizzare con prudenza)
Elenco rilevato (file:riga indicative, ricontrolla): `utils/resource_monitor.py` e `gui/widgets.py` (pynvml per i grafici di VRAM/GPU); `utils/adaptive_batch_manager.py` (pynvml + costo per batch tarato su RTX 3060); `utils/cuda_dll_path.py` (DLL CUDA 12 di torch, solo Windows) e i suoi chiamanti (`core/subtitle_synchronizer.py`, `core/gender_rewriter.py`, `core/gender_corrector.py`, `core/fallback_translate_cli.py`, `glossary_engine/glossary_qwen_gpu_cli.py`, `glossary_engine/glossary_qwen_extract.py`); `scripts_manutenzione/selfcheck_env.py` (`torch.version.cuda`, messaggi "driver NVIDIA", `ct2.get_cuda_device_count`); `install.ps1` (driver NVIDIA obbligatorio, righe ~114-136); `requirements.txt` (`cu126`/`cu124`, `nvidia-ml-py`). Regola: dove `torch.cuda.*` funziona anche su ROCm (HIP) **non toccarlo**; sostituisci solo ciò che legge `nvidia-smi`/pynvml o stampa messaggi NVIDIA, usando `gpu_detect` come unica fonte, con ripiego "nessun dato" invece di errori. Ogni cambio con test.

### F8 — Windows + ROCm
**Da non fare ora** (stima 10-15 giornate, rischio alto: PyTorch ROCm su Windows richiede Python 3.12, torch ≥2.11, modelli di scheda specifici). Riconsiderare solo dopo l'esito di F6 su hardware.

## 5. Come lavorare nella VM

```bash
git clone https://github.com/chinasky71-byte/TranscriberPro.git && cd TranscriberPro
git checkout -b linux-amd/f4a-install-sh
python3 -m venv /tmp/tp-venv && . /tmp/tp-venv/bin/activate && pip install -r linux_tests/requirements.txt
python -m pytest linux_tests -q            # su Windows: 86 passed; su Linux mai eseguiti
python utils/gpu_detect.py --json          # rilevamento GPU
bash -n install.sh && ./install.sh --check # controllo prerequisiti, nessuna modifica
```
- Modifiche ai file esistenti: piccole e mirate. Nel repository i file di testo sono LF (`.gitattributes`); lo script `install.sh`/`run.sh` devono restare eseguibili (`git update-index --chmod=+x`).
- `linux_tests/` contiene **copie** dei test del proprietario (i suoi originali stanno fuori dal repository): se aggiungi o correggi un test, mettilo lì e segnalalo nel PR.
- Non sono disponibili qui: PyQt6 con display reale, GPU, modelli, server del Library Scanner. Usa `offscreen`, simulazioni e fixture.

## 6. Checklist di prova per l'utente su una macchina AMD (da completare in F6)

Quando l'utente avrà una macchina Linux con GPU AMD: (1) `./install.sh --gpu-backend rocm --check`; (2) `python utils/gpu_detect.py --json` e incollare l'uscita; (3) `./install.sh --gpu-backend rocm --yes`; (4) `python scripts_manutenzione/amd_smoke_test.py` e inviare `amd_smoke_report.txt`; (5) avviare l'app (`./run.sh`) e trascrivere un file di 1 minuto con Whisper; (6) se crasha, inviare `~/.transcriberpro/logs/` più recente. La sessione cloud deve preparare questi passi in modo che l'utente debba solo eseguirli e incollare i risultati.

## 7. Come riportare lo stato

Mantieni `docs/HANDOFF_LOG_LINUX_AMD.md` (o, se non puoi fare push, il testo da passare al proprietario): per ogni fase, data, cosa è stato fatto, esito dei test (comando e risultato), PR/commit, cosa **non** è verificato e le domande aperte per il proprietario. Una sezione "Prossimo passo" in cima, sempre aggiornata.
