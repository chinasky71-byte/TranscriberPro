# Prova completa su Linux con GPU AMD

Lista di tutto ciò che serve provare su una macchina Linux con scheda AMD. **Nessuna parte è mai stata provata su hardware AMD**: ogni voce è un'ipotesi da confermare o smentire. Per ogni prova annota **OK / FAIL / SALTATO**, la GPU usata (sì/no) e, se fallisce, il testo dell'errore.

Regole: non scrivere mai password, chiavi o token nel rapporto. Il file `amd_smoke_report.txt` è già anonimizzato; i log in `~/.transcriberpro/logs/` possono contenere percorsi dei tuoi file: guardali prima di inviarli.

## 0. Prima di iniziare

- Distribuzione e versione: `cat /etc/os-release | head -3`
- Kernel: `uname -r`
- Scheda e generazione: `rocminfo | grep gfx` (se manca `rocminfo`: `python3 utils/gpu_detect.py --amd`)
  - `gfx12xx` RDNA4 · `gfx11xx` RDNA3 (RX 7000) · `gfx103x` RDNA2 (RX 6000) · `gfx101x` RDNA1 (RX 5000) · `gfx9xx` Vega/Instinct
- Gruppi: `id -nG` deve contenere `render` e `video` (altrimenti `sudo usermod -aG render,video $USER` e nuovo login)
- Per vedere se la GPU lavora, tieni un secondo terminale con: `watch -n1 rocm-smi --showuse --showmemuse` (o `radeontop`)
- Spazio libero: almeno 40 GB (modelli e ambienti)

## 1. Installazione

| # | Prova | Comando | Esito atteso |
|---|---|---|---|
| 1.1 | Controllo prerequisiti | `./install.sh --gpu-backend=rocm --check` | messaggi chiari, exit 0 (o l'elenco di cosa manca) |
| 1.2 | Installazione | `./install.sh --gpu-backend=rocm --system-deps --yes` | exit 0 in una sola esecuzione, selfcheck senza KO (~12 GB di download) |
| 1.3 | Scheda RDNA1 o più vecchia | `./install.sh --gpu-backend=vulkan --system-deps --yes` | exit 0 (solo il glossario userà la GPU) |

Se 1.2 fallisce: copia le ultime 40 righe dell'output.

## 2. Rilevamento e rapporto di fumo

| # | Prova | Comando | Esito atteso |
|---|---|---|---|
| 2.1 | Rilevamento | `venv/bin/python utils/gpu_detect.py --json` | la tua scheda in `gpus`, `amd_family` giusta, `recommended_backend` |
| 2.2 | Rapporto di fumo | `venv/bin/python scripts_manutenzione/amd_smoke_test.py --whisper` | file `amd_smoke_report.txt`; `torch.cuda.is_available()` vero, calcolo su GPU riuscito, ctranslate2 vede il dispositivo, Whisper tiny trascrive |
| 2.3 | Con modello llama (facoltativo) | stesso comando con `--gguf percorso/modello.gguf` | 5 token generati con livelli su Vulkan |

## 3. L'app si apre

| # | Prova | Come | Esito atteso |
|---|---|---|---|
| 3.1 | Avvio | `./run.sh` | finestra visibile, nessun errore nel terminale |
| 3.2 | Etichetta GPU | guarda sotto "Pronto" | nome della tua scheda **in rosso** (AMD); "CPU only" = rilevamento non riuscito |
| 3.3 | Monitor risorse | pannello centrale in basso | GPU e VRAM con valori coerenti |

## 4. Elaborazione vera, step per step

Usa un video breve (1-2 minuti, con parlato **in inglese**). Le modifiche alla configurazione si fanno dalle Impostazioni dell'app, oppure a app chiusa in `~/.transcriberpro/config.json`. Per ogni prova guarda `rocm-smi`: durante lo step la GPU deve mostrare uso e VRAM crescenti.

| # | Step | Come provarlo | GPU attesa | Note |
|---|---|---|---|---|
| 4.1 | **Whisper** (ctranslate2) | `transcription_engine_mode` = `faster-whisper` | sì | **il test più importante**: cerca crash o blocchi nei log |
| 4.2 | **Qwen3-ASR** | `transcription_engine_mode` = `qwen3` | sì (bf16) | su RDNA2 attesa lentezza |
| 4.3 | Canary (solo inglese) | `transcription_engine_mode` = `canary` | no, CPU | NeMo non ha ROCm: è previsto che fallisca o vada su CPU; non serve insistere |
| 4.4 | Modalità automatica | `transcription_engine_mode` = `auto` | sì | come lo userebbe un utente |
| 4.5 | **Separazione voce** (Demucs) e **diarizzazione** (pyannote) | attive nelle opzioni del job | sì | possono richiedere un token Hugging Face per pyannote: se manca, annotalo e salta |
| 4.6 | Punteggiatura | attiva di default | sì | |
| 4.7 | **Traduzione NLLB** | `translation_model` = `nllb_finetuned` | sì | |
| 4.8 | **Traduzione TranslateGemma** (LLM) | `translation_model` = `llm` | sì (4 bit con bitsandbytes) | su RDNA2 attesa lentezza |
| 4.9 | **Glossario** (Qwen2.5, llama.cpp) | Strumenti → Glossario | sì, via **Vulkan** | scarica il modello (circa 9 GB per il 14B) |
| 4.10 | OCR e genere | opzioni del job | no, CPU | solo per confermare che non si rompe nulla |

Per ogni prova di 4.1-4.9, annota: tempo impiegato, picco di VRAM (da `rocm-smi`), se il file `.srt` finale è corretto e se compaiono errori `HIP`, `hipblas`, `out of memory`, `segmentation fault` o `Aborted` nei log.

## 5. Coda e interfaccia

| # | Prova | Esito atteso |
|---|---|---|
| 5.1 | Coda con 2 file brevi | il secondo parte dopo il primo, nessun blocco |
| 5.2 | Tasto Canc su un file in attesa | il file esce dalla coda |
| 5.3 | Tasto Ferma durante un job | il job si ferma e la GPU viene liberata (`rocm-smi`) |

## 6. Cosa mandare indietro

1. Esito di ogni riga delle tabelle (OK / FAIL / SALTATO + una frase).
2. Output dei comandi della sezione 0.
3. `amd_smoke_report.txt` (anonimizzato).
4. Per ogni FAIL: le righe di errore e il log più recente in `~/.transcriberpro/logs/`.
5. Se hai impostato `HSA_OVERRIDE_GFX_VERSION` a mano, scrivilo: l'app non la sostituisce.

## 7. Risultati attesi per generazione (ipotesi)

| Scheda | Whisper | Qwen3-ASR / TranslateGemma | NLLB, Demucs, pyannote | Glossario |
|---|---|---|---|---|
| RDNA4, RDNA3 | GPU | GPU | GPU | GPU (Vulkan) |
| RDNA2 (override automatico) | GPU | GPU ma lento (bf16) | GPU | GPU (Vulkan) |
| RDNA1 e precedenti | CPU | CPU | CPU | GPU (Vulkan) |
