# Registro del lavoro Linux / AMD

**Prossimo passo:** F4e (Library Scanner con server finto), poi F6. F5 (Vulkan) è sul branch `linux-amd/f5-vulkan` (PR impilata su questa).

Aggiorna questo file a ogni fase, in cima i più recenti. Formato per voce: data, fase, cosa è stato fatto, comandi e risultati dei test, PR/commit, cosa **non** è verificato, domande aperte per il proprietario.

---

## 2026-10-23 — F5: Vulkan per llama.cpp (branch `linux-amd/f5-vulkan`, impilato su `linux-amd/f4a-install-sh`)
File cambiati: `install.sh`, `install.ps1`, `utils/llm_model_select.py`, `glossary_engine/glossary_qwen_gpu_cli.py`, nuovo `linux_tests/test_llama_backend.py`.
- **Installer:** `--gpu-backend=auto|cuda|vulkan|rocm|cpu` (Windows `-GpuBackend`). Senza opzione: comportamento di sempre. `auto` solo su richiesta. `cpu` = `--no-gpu`; `vulkan` = torch CPU + ruota Vulkan di llama-cpp-python 0.3.34 (+ controllo del loader Vulkan e pacchetti suggeriti); `rocm` rifiutato (F6 su Linux, F8 su Windows). Combinare `--no-gpu` con `vulkan` è un errore.
- **Marcatore** `venv/llama_backend.txt` (cpu|vulkan), scritto dall'installer; `utils/llm_model_select.detect_vram_mib()` lo legge (senza importare llama_cpp): **solo `vulkan`** passa a `backend='vulkan'`; assente o altro testo = `cuda` come oggi. Con un venv riusato che ha il marcatore, l'esecuzione di default rimette la ruota CUDA e toglie il marcatore.
- **Glossario GPU:** `_free_vram_mb()` usa ancora `nvidia-smi` per primo; ripiego su `gpu_detect` (`vram_free_mib`) solo se non risponde.
- **Test:** `python -m pytest linux_tests -q` → **114 passed** (28 nuovi: marcatore, NVIDIA invariata, AMD con/senza marcatore, ripiego del glossario).
- **Prove nella VM (Ubuntu 24.04, lavapipe, senza GPU reale):** `mesa-vulkan-drivers` → `vulkaninfo` vede llvmpipe; ruota Vulkan installata; **llama.cpp ignora i dispositivi di tipo CPU** salvo `GGML_VK_VISIBLE_DEVICES=0` (solo aiuto di prova, non nel codice del prodotto). Con quella variabile: `llama_supports_gpu_offload()` True, Qwen2.5-0.5B Q4_K_M, 25/25 layer su Vulkan0, 8 token generati. `./install.sh --gpu-backend=vulkan --yes` sul venv esistente → exit 0, marcatore `vulkan`, selfcheck senza KO. L'app, senza GPU reale, non conta VRAM (gpu_detect esclude llvmpipe): corretto.
- **Ritorno al default (verificato):** `./install.sh --yes` sullo stesso venv → "ripristino la ruota CUDA (il venv aveva la ruota vulkan)", ruota CUDA di llama reinstallata, torch 2.8.0+cu126, `venv/llama_backend.txt` rimosso, `llama_backend_marker()` = `cuda`. Il selfcheck finale dà exit 1 (torch.cuda, ctranslate2 CUDA, llama): **atteso** in una VM senza GPU/driver NVIDIA.
- **Punto aperto emerso (Linux + NVIDIA, non verificabile qui):** con la ruota CUDA `import llama_cpp` fallisce con `libcudart.so.12` (poi `libcublas.so.12`) non trovate: le librerie ci sono in `venv/.../site-packages/nvidia/*/lib` ma non nel percorso del loader. Su Windows se ne occupa `utils/cuda_dll_path.py` (PATH); su Linux serve l'equivalente (`LD_LIBRARY_PATH` o preload) per il glossario/gender corrector. Da affrontare in F7 con una macchina NVIDIA Linux; non toccato qui (non è un cambio sul percorso Windows).
- **Non verificato:** `install.ps1` (nessun PowerShell nella VM, solo rilettura del diff: le righe NVIDIA di default sono invariate); qualsiasi GPU AMD/Intel reale (prestazioni, driver Mesa/AMDVLK); la ruota CUDA di llama senza GPU NVIDIA; Python 3.12.
- **Domande per il proprietario:** (1) con marcatore `cpu` e GPU NVIDIA presente, la scelta del modello resta quella storica (backend cuda): va bene? (2) provare `-GpuBackend vulkan` su un PC Windows con GPU AMD/Intel quando possibile.


## 2026-10-23 — F4 (parziale): prova reale su Ubuntu 24.04 (VM cloud, senza GPU)
Branch `linux-amd/f4a-install-sh`. Nessun file di codice modificato finora (solo questo registro).
- **F4b, test:** `pip install -r linux_tests/requirements.txt` + `python -m pytest linux_tests -q` (Python 3.13.16, Ubuntu 24.04.5) → **86 passed** in 2,15 s. Primo risultato su Linux reale: nessun difetto di test o codice.
- **F4c, `gpu_detect`:** `python utils/gpu_detect.py --json` senza GPU → `gpus: []`, `recommended_backend: cpu`, `errors: []`, 0,09 s. Vulkan: "loader presente, dispositivi non verificati (vulkaninfo assente)". Non verificato con GPU o `vulkaninfo`/lavapipe reali.
- **F4a, `install.sh`:**
  - `bash -n install.sh` OK; `--check` da root rifiuta correttamente (rc=2); da utente non root gira, trova Python 3.11.17 e ffmpeg, segnala Tesseract mancante (rc=2) e stampa il comando apt.
  - I pacchetti apt del comando suggerito esistono su Ubuntu 24.04 (serve `apt-get update` su VM fresca); installati senza errori. Il comando contiene un doppio spazio dopo `-y` (PYPKG vuoto): innocuo.
  - `./install.sh --no-gpu --yes`: creazione del venv OK; **tutti i download pip falliti per la rete della VM** (403 dal proxy per `download.pytorch.org`, `abetlen.github.io`, `huggingface.co`; passa solo PyPI). **Non completata, non verificata.** Osservazione: se le ruote CPU falliscono lo script prosegue con `requirements.txt` (+cu126, ~3 GB) senza chiedere.
- **Rete sbloccata** dal proprietario (accesso completo): rilancio completo di F4a e F4d.
- **F4a completata:** `./install.sh --no-gpu --yes` (utente non root, venv nuovo, ruote CPU di torch 2.8.0+cpu e llama-cpp-python 0.3.34) → **exit 0**, selfcheck `RISULTATO: tutto il necessario funziona`, nessun KO. L'avviso `ERROR: pip's dependency resolver...` nel log è **cosmetico**: viene dall'installazione della ruota CPU di llama con `--no-deps` prima delle sue dipendenze, che arrivano dopo con `requirements.txt`.
- **F4d completata:** `QT_QPA_PLATFORM=offscreen`, `HOME` temporaneo, `main.py` con `QApplication.exec` sostituito da un ciclo di 3 s → `MainWindow` visibile in 6,7 s, tema `theme.qss.tpl` (32775 caratteri), 2 font caricati; solo due avvisi attesi (venv NLP/spaCy assente, chiave TMDB assente), nessuna eccezione.
- **Limiti di queste prove:** la VM aveva **già Python 3.11** (3.11.17); su un Ubuntu 24.04 standard `install.sh` sceglierebbe la 3.12, ramo **non verificato** (né a runtime). Fedora/dnf/pacman/zypper **non provati**. F4e (Library Scanner) non fatta. Nessuna GPU.
- **Domande per il proprietario:** (1) con `--no-gpu`, se la ruota CPU di torch fallisce lo script ripiega su cu126 (~3 GB) senza chiedere: deve fermarsi? (2) accettare il ramo Python 3.12 come "provato solo in installazione"?

