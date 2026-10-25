# Validazione AMD — 24/10/2026

Esecuzione della checklist `docs/PROVA_AMD_COMPLETA.md` su Linux + GPU AMD.
Le prove GUI (Sezioni 3 e 5) sono state **saltate per decisione dell'utente**
(nessun display nella sessione di test).

## Ambiente (Sezione 0)

| Voce | Valore |
|---|---|
| Distribuzione | Ubuntu 26.04.1 LTS |
| Kernel | 7.0.0-38-generic |
| GPU | **Radeon RX 9060 XT 16 GB — gfx1200, RDNA4, ROCm "official"** |
| IGPU | Radeon Graphics gfx1036 (RDNA2) — non usata per i calcoli |
| `/dev/kfd` | accessibile all’utente che esegue i test |
| Gruppi | `render`, `video`, `sudo` presenti |
| Driver | `amdgpu` caricato — **mai modificato** |
| ROCm di sistema | assente (`/opt/rocm`, `rocminfo`); non necessario: le wheel portano il runtime |
| Libdrm | `libdrm_amdgpu.so.1` presente; warning `amdgpu.ids` cosmetico |
| Spazio iniziale | 110 GB liberi |
| Python | solo 3.14.4 di sistema → installato CPython 3.12.15 standalone in `.tools/` |

Versioni effettive: Python 3.12.15, torch 2.10.0+rocm7.0 (HIP 7.0.51831),
ctranslate2 4.8.3, transformers 4.57.6, faster-whisper 1.2.1, llama_cpp 0.3.34,
soundfile 0.13.1, ffmpeg 8.0.1, tesseract 5.5.0 (eng+ita+osd), mkvtoolnix 97.

## Sezione 1 — Installazione

| # | Prova | Esito | Note |
|---|---|---|---|
| 1.1 | `install.sh --gpu-backend=rocm --check` | **OK** | exit 0 dopo l'installazione di Python 3.12; prima: KO su python/ffmpeg/tesseract |
| 1.2 | `install.sh --gpu-backend=rocm --yes` | **OK** | exit 0, venv 15 GB, selfcheck senza KO, ~12 GB scaricati. Nessun sudo, nessun pacchetto di sistema toccato dallo script |
| 1.3 | Fallback Vulkan (RDNA1 o precedente) | **SALTATO** | scheda RDNA4: non serve |

Dipendenze di sistema installate a parte (utente, `apt`, **solo 15 pacchetti
nuovi, zero upgrade**): ffmpeg, mkvtoolnix, tesseract-ocr + ita/eng.
Nessun pacchetto mesa/libdrm/amdgpu/kernel/xorg/wayland è stato toccato.

## Sezione 2 — Rilevamento e smoke test

| # | Prova | Esito | Dettaglio |
|---|---|---|---|
| 2.1 | `gpu_detect.py --json` | **OK** | RX 9060 XT, gfx1200, RDNA4, official; backend consigliato `rocm` |
| 2.2 | `amd_smoke_test.py --whisper` | **OK** | torch/HIP ok (matmul 0.268 s), ctranslate2 2 device, bf16/fp16/int8, llama.cpp Vulkan `gpu_offload=true`, Whisper tiny su GPU ok |
| 2.3 | GGUF/Vulkan | **OK (coperto da 4.8)** | TranslateGemma GGUF Q4_K_M caricato ed eseguito su Vulkan |

Rapporto: `amd_smoke_report.txt`.

## Sezione 3 — App GUI

`SALTATO` integralmente su decisione dell'utente (nessun display).

## Sezione 4 — Elaborazione reale

Input: `samples/prova_amd_test.mp4` (130,6 s, audio inglese a due voci).
Atteso: `samples/testo_atteso.txt`.

| # | Step | Esito | Tempo | Picco VRAM | Note |
|---|---|---|---|---|---|
| 4.1 | **Whisper large-v3** (`faster-whisper`) | **OK** | 29–32 s | **9207 MiB** | auto-detect `en`; 23 blocchi SRT; **similarità 98,8%** (solo "thirty percent"→"30%") |
| 4.2 | **Qwen3-ASR-1.7B** | **OK** | 44 s | **7254 MiB** | bf16; **similarità 99,5%** |
| 4.3 | Canary | **OK (fallback)** | 31 s | ~9 GB | NeMo/ROCm non disponibile → fallback automatico a Faster-Whisper, come previsto |
| 4.4 | Modalità `auto` | **OK** | 45 s | ~7 GB | lingua `und` → Qwen3 auto-detect |
| 4.5 | Demucs + pyannote | **OK / SALTATO** | 29 s | ~9 GB | Demucs gira su GPU; diarizzazione saltata: token HF assente (modelli gated 401), job completato |
| 4.6 | Punteggiatura | **OK** | — | — | Whisper/Qwen3 producono punteggiatura nativa; restorer non necessario |
| 4.7 | **NLLB-200-3.3B** | **OK** | 64–69 s | **12857 MiB** | en→it, `residual source language: 0`, traduzione corretta |
| 4.8 | **TranslateGemma-12B GGUF Q4_K_M** | **OK** | 62–66 s | **9454 MiB** | llama.cpp su **Vulkan**, 4 sequenze parallele, residual 0 |
| 4.9 | Glossario (Qwen2.5-14B) | **SALTATO** | — | — | workflow GUI su più episodi + GGUF ~9 GB; la parte Vulkan è coperta da 4.8 |
| 4.10 | OCR PGS/VOBSUB + genere | **SALTATO** | — | — | il sample non ha sottotitoli bitmap; gender richiede diarizzazione/token |

Nessun errore `out of memory`, `segmentation fault` o `Aborted` nei test
eseguiti **dopo i fix** sotto. Restano warning MIOpen innocui
(`IsEnoughWorkspace`) e i warning torch su flash/mem-efficient attention ROCm
sperimentale.

## Sezione 5 — Coda e interfaccia

`SALTATO` (5.1–5.3): richiede la GUI. La coda headless (`core.queue_runner`)
è stata comunque usata per tutti i test e ha funzionato (stato, log, exit code).

## Sezione 6 — Difetti trovati e corretti

Tre problemi reali bloccavano la pipeline su AMD. Correzioni committate sul
branch `test/amd-rocm-validazione`.

### 1. `torchaudio.info` rimosso in torchaudio 2.10
`core/audio_processor.py` usava `torchaudio.info` in modalità batched. Con
torchaudio 2.10 l'attributo non esiste più: `AttributeError` mascherato da
"no chunks created", pipeline ferma prima della trascrizione.
**Fix:** `soundfile.info` (dipendenza già presente).

### 2. SIGSEGV di ctranslate2 se torch inizializza il contesto HIP per primo
Con ROCm, se Demucs o i controlli VRAM (`torch.cuda.mem_get_info`) toccano la
GPU prima della prima inferenza Whisper, `ctranslate2` 4.8.3 va in SIGSEGV
(exit -11) in `encode()`, anche in `detect_language()`.
Riprodotto in forma minimale; invertendo l'ordine nessun crash.
**Fix:** `utils/ct2_bootstrap.py` — `ctranslate2.get_cuda_device_count()`
all'inizio di `core/pipeline_cli.main()`, prima di importare la pipeline.
Costo pochi ms, nessun modello caricato. Disattivabile con
`TP_SKIP_CT2_INIT=1`.

### 3. NLLB distribuito sull'iGPU → `HIP error: invalid device function`
`device_map="auto"` spalmava NLLB tra device 0 (gfx1200) e device 1
(gfx1036). L'iGPU non ha i kernel compilati: ogni batch falliva e veniva
saltato, ma la pipeline dichiarava successo salvando un `.it.srt` in inglese.
**Fix:** `device_map={"": 0}` per NLLB base e fine-tuned (`core/translator.py`).
NLLB-3.3B fp16 (~6,6 GB) entra su una sola GPU.

### 4. Falso positivo di successo della traduzione (corretto)
`translate_file` ritornava `True` anche quando **tutti** i batch fallivano e i
blocchi restavano in inglese (osservato con l'errore HIP del punto 3: 41/46
righe residue, exit 0, `.it.srt` in inglese). Il ciclo assorbiva ogni
eccezione ("Batch skipped"), l'audit contava i blocchi residui ma il valore
non era usato, e il `return True` finale non guardava nulla.
**Fix:** nuova chiave `translation_max_untranslated_pct` (default **80**),
errori GPU fatali non piu' assorbiti, audit eseguito prima di scrivere il
file; stesso criterio per il traduttore LLM. La pipeline, su `False`,
conserva il file in lingua originale e segna il job come fallito.
Test: `linux_tests/test_translation_success_gate.py`.

## Stato macchina

- Nessuna modifica a driver, kernel, mesa, xorg, wayland, systemd o Steam.
- Nessun riavvio.
- File creati fuori dal repo: `~/.transcriberpro/config.json` e log
  (previsti dall'app). Tutto il resto è dentro il repo: `venv/`, `models/`
  (33 GB), `.tools/`, `.test_logs/` (artefatti, ignorati da git).
- Disco: 34 GB liberi al termine.
