# Registro del lavoro Linux / AMD

**Prossimo passo:** F4e (Library Scanner con server finto), poi F6. F5 (Vulkan) è sul branch `linux-amd/f5-vulkan` (PR impilata su questa).

Aggiorna questo file a ogni fase, in cima i più recenti. Formato per voce: data, fase, cosa è stato fatto, comandi e risultati dei test, PR/commit, cosa **non** è verificato, domande aperte per il proprietario.

---

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

