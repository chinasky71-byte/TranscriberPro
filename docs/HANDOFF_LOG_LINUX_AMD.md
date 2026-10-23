# Registro del lavoro Linux / AMD

**Prossimo passo:** completare F4a (`./install.sh --no-gpu --yes`) e poi F4d/F4e, F5, F6: **bloccati dalla policy di rete della VM cloud**, che permette solo PyPI (vedi voce del 2026-10-23, F4). Serve consentire `download.pytorch.org`, `abetlen.github.io`, `huggingface.co`, `github.com` (e `objects.githubusercontent.com`) nell'ambiente, oppure fornire le ruote in altro modo.

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
- **Non verificato:** `install.sh --no-gpu` fino in fondo, selfcheck su Linux, F4d, F4e, F5, F6 (richiedono torch, llama-cpp e/o Hugging Face/GitHub).
- **Domande per il proprietario:** (1) si può ampliare la policy di rete dell'ambiente cloud agli host sopra? (2) in `--no-gpu`, se la ruota CPU fallisce lo script deve fermarsi invece di ripiegare su cu126?


## 2026-10-23 — Punto di partenza (sessione locale di Claude Code)
- Versione dell'app: 1.34.17 (`65cab33`). Fasi F0-F3 e il rilevamento GPU sono completati e pubblicati (tabella nel documento di consegna, sezione 2).
- Test portabili: `python -m pytest linux_tests -q` → 86 passed su Windows (anche in un venv con sole pytest, psutil, requests, pillow). Mai eseguiti su Linux.
- Non verificato su hardware reale: `install.sh`, `run.sh`, `gpu_detect` con sysfs/lspci/vulkaninfo reali, qualunque componente su GPU AMD/Intel.
- Domande aperte per il proprietario: nessuna.
