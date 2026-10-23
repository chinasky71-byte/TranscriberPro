# Registro del lavoro Linux / AMD

**Prossimo passo:** F4a, prova reale di `install.sh` su una VM Linux (vedi `docs/HANDOFF_CLOUD_LINUX_AMD.md`, sezione 4).

Aggiorna questo file a ogni fase, in cima i più recenti. Formato per voce: data, fase, cosa è stato fatto, comandi e risultati dei test, PR/commit, cosa **non** è verificato, domande aperte per il proprietario.

---

## 2026-10-23 — Punto di partenza (sessione locale di Claude Code)
- Versione dell'app: 1.34.17 (`65cab33`). Fasi F0-F3 e il rilevamento GPU sono completati e pubblicati (tabella nel documento di consegna, sezione 2).
- Test portabili: `python -m pytest linux_tests -q` → 86 passed su Windows (anche in un venv con sole pytest, psutil, requests, pillow). Mai eseguiti su Linux.
- Non verificato su hardware reale: `install.sh`, `run.sh`, `gpu_detect` con sysfs/lspci/vulkaninfo reali, qualunque componente su GPU AMD/Intel.
- Domande aperte per il proprietario: nessuna.
