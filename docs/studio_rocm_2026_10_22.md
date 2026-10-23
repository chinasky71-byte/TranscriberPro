# Studio di fattibilità: GPU AMD con ROCm in Transcriber Pro

Data: 22/10/2026. Lo studio è stato fatto senza modificare il codice: ho letto il codice e i requirements e ho cercato lo stato attuale di ROCm sul web.
Non ho potuto provare nulla su hardware AMD, perché qui c'è solo una RTX 3060. Ogni affermazione su ROCm cita la sua fonte, e la sezione 6 elenca cosa resta da verificare.

---

## 0. In breve

- **Qwen3-ASR, allineamento, diarizzazione, Demucs e NLLB-FT girano su PyTorch.** PyTorch ha ruote ROCm ufficiali e `torch.cuda.*` funziona anche su ROCm, tramite HIP. Questa parte è fattibile. Whisper invece **non** gira su PyTorch: usa ctranslate2.
- **I nodi veri sono tre.**
  1. **ctranslate2 (Whisper per fr/de/es).** Supporta ROCm solo dalla 4.7.0, con ruote distribuite come zip nelle release di GitHub. Il progetto invece è bloccato alla **4.6.0**: la 4.7.x causa un crash (std::abort) dentro PyQt6.
  2. **whisperx.** Fino alla 3.8.6 richiede `torch~=2.8.0`. Su Windows non esiste una ruota ROCm di torch 2.8. Su Linux la ruota `2.8.0+rocm6.4` esiste, ma AMD non l'ha validata per le Radeon.
  3. **Su Windows ROCm è ancora parziale.** AMD dichiara che su Windows è supportato solo PyTorch, non tutto lo stack ROCm, con Python 3.12 e batch LLM pari a 1 come configurazione ufficiale.
- **Canary (NeMo) non ha supporto ROCm documentato.** Va considerato solo NVIDIA.
- **Raccomandazione:** non fare il porting completo adesso. Si può fare un sottoinsieme a basso costo, cioè rilevare la GPU senza dipendere dal marchio e usare llama.cpp in Vulkan. Poi, solo quando ci sarà una macchina AMD vera per provare, si può aggiungere un profilo **Linux + ROCm sperimentale** con requirements separati. **Windows + ROCm è da rimandare.**

---

## 1. Inventario delle librerie che usano la GPU o dipendono da CUDA

| Libreria (pin) | Dove | Uso della GPU nel progetto |
|---|---|---|
| torch / torchaudio `2.8.0+cu126` | venv principale (`requirements.txt:20,31-32`), venv_canary (`requirements-canary.txt:5,162`) | Qwen3-ASR, NLLB-FT, TranslateGemma, pyannote, Demucs, allineamento whisperx, punteggiatura, speaker gender |
| ctranslate2 `4.6.0` (con faster-whisper 1.2.1) | venv principale (`requirements.txt:37`) | Whisper `int8_float16` su `cuda` |
| whisperx `3.8.1` | venv principale | solo allineamento (`core/aligner.py:87,130,142`, cioè wav2vec2 su torch) |
| llama-cpp-python `0.3.34` | venv principale (`requirements.txt:21,24,33`), indice `cu124` e `--only-binary` | Qwen2.5 GGUF per glossario, gender, serbatoio L3, sync |
| bitsandbytes `0.49.2` | venv principale | NF4 per TranslateGemma 12B, int8 per NLLB se la VRAM è poca |
| pyannote.audio `4.0.4`, demucs `4.0.1`, qwen-asr `0.0.6` (transformers 4.57.6) | venv principale | solo torch, nessun kernel CUDA proprio |
| torchcodec `0.10.0` | venv principale | decodifica su CPU |
| nvidia-ml-py (pynvml) `13.590.48` | venv principale | monitor VRAM e batch adattivo |
| NeMo `3.0.0` (+ `cuda-bindings`, `nv-one-logger`) | venv_canary | Canary-Qwen-2.5B, bf16 su `cuda` |
| onnxruntime `1.24.3` | venv principale | **solo CPU** (Silero VAD di faster-whisper, `main.py:42`). Nel codice del progetto non c'è nessun `CUDAExecutionProvider`. **Non riguarda ROCm.** |
| spaCy/thinc (venv_nlp), sentence-transformers/LaBSE (venv_glossary con `torch==2.14.0+cpu`), Tesseract | venv separati | **solo CPU.** Non riguardano ROCm. |

Una nota a margine: il pin `torchcodec 0.10.0` con `torch 2.8.0` non rispetta la tabella di compatibilità ufficiale (0.10 va con torch 2.10, 0.7 con torch 2.8) ([torchcodec README](https://github.com/meta-pytorch/torchcodec/blob/main/README.md)). Con un aggiornamento di torch bisogna riallinearlo.

---

## 2. Stato di ROCm per ciascuna libreria (ottobre 2026)

### 2.1 Quadro generale di ROCm

| Voce | Stato | Fonte |
|---|---|---|
| Ultima ROCm | **10.0.0** (25/08/2026), costruita su TheRock, dopo la 7.14. La 10.1 è già sugli indici delle ruote. | [Phoronix](https://phoronix.com/news/AMD-ROCm-10.0), [matrice 10.0.0](https://rocm.docs.amd.com/en/docs-10.0.0/compatibility/compatibility-matrix.html) |
| GPU consumer ufficiali (matrice 10.0) | RDNA4: RX 9070 XT/9070/GRE, RX 9060 XT/9060, RX 9050. RDNA3: RX 7900 XTX/XT/GRE, RX 7800 XT, RX 7700 XT/7700, RX 7600. **RDNA2: solo PRO W6800 e V620 (gfx1030), nessuna RX 6000.** | [matrice 10.0.0](https://rocm.docs.amd.com/en/docs-10.0.0/compatibility/compatibility-matrix.html) |
| Distro Linux (Radeon) | Ubuntu 26.04, 24.04.4, 22.04.5; RHEL 10.2 e 9.8 | stessa fonte |
| Windows | Windows 11 25H2 con driver Adrenalin 26.8.1 (matrice 10.0). Sulle pagine Radeon il canale "ufficiale" documentato è ancora la **7.2.1**, con PyTorch 2.9.1 e **solo Python 3.12**. | [matrice 10.0.0](https://rocm.docs.amd.com/en/docs-10.0.0/compatibility/compatibility-matrix.html), [installazione PyTorch su Windows](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html) |
| Limiti ufficiali su Windows | "On Windows, only Pytorch is supported, not the entire ROCm stack"; "Only Python 3.12 is supported"; "only LLM batch sizes of 1 are officially supported"; nessun training; WDAG e Smart App Control vanno disattivati | [Limitations](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/limitations/limitationsrad.html) |
| RDNA2 consumer (RX 6800/6900) | Non ufficiale. Su Linux funziona di solito con `HSA_OVERRIDE_GFX_VERSION=10.3.0`. Su Windows le ruote ufficiali non vedono la gfx1030. | [Debian AI](https://lists.debian.org/debian-ai/2022/07/msg00052.html), [TheRock #1719](https://github.com/ROCm/TheRock/issues/1719), [RCOm-windows-gfx1030](https://github.com/ssubedir/RCOm-windows-gfx1030) |

### 2.2 Libreria per libreria

| Libreria | Supporto ROCm | Linux | Windows | Compatibile con i pin attuali? | Fonti |
|---|---|---|---|---|---|
| **torch/torchaudio** | Ufficiale | `2.8.0+rocm6.4` (cp311) esiste su download.pytorch.org. ROCm 6.4.4 su Linux copre RX 9070/9060 e RX 7900/7800/7700 XT, **ma non la RX 7600**. **Per le Radeon AMD indica torch 2.6 come "production", mentre la 2.8 è descritta come "nightly… not tested extensively by AMD".** La 2.7 stable è dichiarata "Not supported for Radeon 7000 series". Le build più nuove sono `2.10–2.13+rocm7.1` e `2.11–2.14+rocm10.x`. | **Non esiste nessuna ruota torch 2.8 ROCm.** repo.radeon 7.2.1 ha solo `torch 2.9.1`, cp312. TheRock stable ha `torch 2.11–2.14+rocm10.x` per **cp311** `win_amd64`, ma torchaudio solo in versione **2.11**. | Linux: **sì**, con 2.8.0+rocm6.4. Windows: **no**, serve un salto a 2.9.1 (Py 3.12) o a 2.11 (Py 3.11). | [rocm6.4/torch](https://download.pytorch.org/whl/rocm6.4/torch/), [rocm7.1/torch](https://download.pytorch.org/whl/rocm7.1/torch/), [matrice Linux 6.4.4](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-6.4.4/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html), [repo.radeon 7.2.1](https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/), [TheRock stable torch](https://stable.repo.amd.com/rocm/whl-next/torch/), [TheRock torchaudio](https://stable.repo.amd.com/rocm/whl-next/torchaudio/) |
| **ctranslate2** | **Ufficiale dalla 4.7.0** (03/02/2026, "Introduce AMD GPU support with ROCm HIP"). Le ruote **non sono su PyPI**: sono negli asset `rocm-python-wheels-Linux.zip` e `-Windows.zip` di ogni release. Build per gfx1030/1100/1101/1102/1150/1151/1200/1201. Linux contro ROCm 7.2 di sistema (auditwheel esclude `/opt/rocm/lib`), Windows con `rocm_sdk` 7.2 o 10.0 in pip. Ultima versione: 4.8.3 (13/10/2026) con "Fix Windows ROCm Translator hangs and DLL loading". Flash attention non è supportata. | ruote presenti | ruote presenti, ma correzioni recenti per blocchi e DLL | **No.** Il pin 4.6.0 non ha ROCm, e la 4.7.x è vietata nel progetto per il crash in PyQt6. | [Release](https://github.com/OpenNMT/CTranslate2/releases), [PR #1989](https://github.com/OpenNMT/CTranslate2/pull/1989), [README](https://github.com/OpenNMT/CTranslate2/blob/master/README.md), [script build Linux](https://github.com/OpenNMT/CTranslate2/blob/master/python/tools/prepare_build_environment_linux_rocm.sh), [script build Windows](https://github.com/OpenNMT/CTranslate2/blob/master/python/tools/prepare_build_environment_windows_rocm.sh), [CI](https://github.com/OpenNMT/CTranslate2/blob/master/.github/workflows/ci.yml) |
| faster-whisper / whisperx | Non hanno backend propri: dipendono da ctranslate2 e torch. **whisperx 3.8.6 (l'ultima) richiede ancora `torch~=2.8.0` e `torchaudio~=2.8.0`.** Nel progetto whisperx si usa **solo** in `core/aligner.py` (`load_align_model`, `load_audio`, `align`), cioè wav2vec2 su torch e transformers. Per questo installarlo con `--no-deps` sopra un torch più nuovo è una strada praticabile. | ok con torch 2.8 ROCm; se fallisce, `--no-deps` con torch nuovo | serve `--no-deps` | Linux sì. Windows solo forzando le dipendenze. | [PyPI whisperx](https://pypi.org/project/whisperx/) |
| Alternativa: whisper.cpp | Ha backend HIP e Vulkan. Su AMD Vulkan viene descritto come "nearly as fast" di HIP e più semplice da installare. Non esistono immagini HIP ufficiali. Richiederebbe di scrivere un nuovo motore. | sì | sì (Vulkan) | n/a | [Medium](https://medium.com/@abhshk/running-gpu-accelerated-whisper-on-an-amd-gpu-no-nvidia-required-e27ea20b2ccd), [voxtype](https://www.mintlify.com/peteonrails/voxtype/features/gpu-acceleration) |
| **llama-cpp-python** | Ruote precompilate ufficiali: `whl/rocm72` (Linux), `whl/hip-radeon` (Linux e Windows), `whl/vulkan` (Linux e Windows). Da sorgente si compila con `GGML_HIP=on` o `GGML_VULKAN=on`. **La 0.3.34 c'è in tutti e tre gli indici**, quindi la regola Alder Lake (niente 0.3.35) si può mantenere. | sì | sì | **Sì** | [README](https://github.com/abetlen/llama-cpp-python/blob/main/README.md), [hip-radeon](https://abetlen.github.io/llama-cpp-python/whl/hip-radeon/llama-cpp-python/), [rocm72](https://abetlen.github.io/llama-cpp-python/whl/rocm72/llama-cpp-python/), [vulkan](https://abetlen.github.io/llama-cpp-python/whl/vulkan/llama-cpp-python/) |
| **bitsandbytes** | 0.49.0: "Experimental support for AMD devices" nelle ruote PyPI, solo Linux. 0.49.2 (il pin attuale) aggiunge blocksize 64 e una build ROCm 7.2. **0.50.0 (25/07/2026): ROCm dichiarato stabile, con ruote Windows ROCm.** 0.50.2 (27/08): ROCm 10.0. Documentazione: "All features are supported for both consumer RDNA and Data Center CDNA". Windows: gfx1100/1101/1102/1150/1151/1200/1201 (ROCm 7.2.1), più RDNA1/2 con 7.14 e 10.0. | sì | sì (≥0.50) | Il pin 0.49.2 è sperimentale e solo Linux. Serve ≥0.50.x. | [Installazione](https://huggingface.co/docs/bitsandbytes/installation), [Release](https://github.com/bitsandbytes-foundation/bitsandbytes/releases) |
| pyannote.audio, demucs, qwen-asr, NLLB/transformers | Solo torch, senza kernel CUDA propri, quindi in teoria seguono torch ROCm. Non ho trovato una dichiarazione ufficiale di supporto ROCm per nessuno dei quattro (**non verificato**). Su RDNA2 bf16 non ha accelerazione hardware: Qwen3-ASR e TranslateGemma usano bf16. | probabile | probabile | sì | n/a |
| torchcodec | Ruote CPU su PyPI per Linux e Windows. Le ruote GPU sono solo CUDA. Deve combaciare con la versione di torch (0.7 con 2.8, 0.11 con 2.11). | CPU | CPU | da riallineare | [README](https://github.com/meta-pytorch/torchcodec/blob/main/README.md) |
| onnxruntime | Il ROCm EP è stato **rimosso nella 1.23** ("Users are recommended to use Migraphx or Vitis AI EPs"). AMD supporta ORT 1.29 e MIGraphX 2.17 su ROCm 10. **Il progetto usa ORT solo su CPU, quindi non serve fare nulla.** | n/a | n/a | n/a | [note 1.23.0](https://newreleases.io/project/pypi/onnxruntime/release/1.23.0), [commit](https://github.com/microsoft/onnxruntime/commit/c2ec3b734bb1816421fbf5dc6d8e162671aa0cd8) |
| **NeMo / Canary** | La documentazione elenca fra i prerequisiti "access to an NVIDIA GPU for model training" (si parla di training, non di inferenza). Non esiste documentazione su ROCm, e il venv dipende da `cuda-bindings` e `nv-one-logger`. **Da considerare non supportato e non provato, cioè solo NVIDIA.** | non provato | non provato | n/a | [NeMo Speech docs](https://docs.nvidia.com/nemo/speech/nightly/starthere/intro.html) |
| pynvml, sostituto | `amdsmi` (Python) ha `amdsmi_get_gpu_vram_usage` e `amdsmi_get_gpu_memory_usage`, ma solo su Linux; sotto WSL è "Experimental". Su Windows nativo non ho trovato un equivalente Python. | amdsmi | nessuno trovato | da riscrivere | [amdsmi Python](https://rocm.docs.amd.com/projects/amdsmi/en/docs-6.1.0/py-interface_readme_link.html), [amdsmi WSL](https://rocm.docs.amd.com/projects/amdsmi/en/latest/how-to/amdsmi-wsl-mode.html) |

---

## 3. Audit del codice: punti specifici di NVIDIA e CUDA

Nota generale: su ROCm `torch.cuda.is_available()` restituisce True, il device si chiama ancora `"cuda"`, e `mem_get_info`, `get_device_properties`, `empty_cache` e `synchronize` sono mappati su HIP. **La maggior parte delle chiamate `torch.cuda.*` resta valida.** Ciò che smette di funzionare è tutto quello che passa da **nvidia-smi, pynvml, indici cu12x o DLL CUDA**.

### 3.1 Punti bloccanti: l'utente AMD non arriva nemmeno alla GPU

| File:riga | Cosa fa oggi | Cosa cambierebbe |
|---|---|---|
| `install.ps1:114-136` | Senza `nvidia-smi` segnala "Driver NVIDIA" come problema bloccante e propone `-NoGpu`, cioè ruote CPU. Controlla anche il driver NVIDIA ≥528/560. | Rilevare il fornitore della GPU (WMI `Win32_VideoController.Name`; **non** usare `AdapterRAM`, che è a 32 bit e si ferma a 4 GB) e aggiungere un ramo AMD con un controllo della versione di Adrenalin. |
| `install.ps1:287-310`, `install.sh:53-55,124-139` | Il ramo `-NoGpu`/`--no-gpu` installa le ruote CPU di torch e llama | Aggiungere i rami `-Amd`/`--rocm` e `--vulkan` (vedi 4.C) |
| `install.ps1:333`, `install.sh:152` | Legge la VRAM da `nvidia-smi` per scegliere Qwen 14B o 7B | Lettura della VRAM indipendente dal fornitore |
| `requirements.txt:20-24,31-33` | Indici `cu126` e `cu124`, `--only-binary`, torch `+cu126`, llama da `cu124` | Creare un **`requirements-rocm.txt`** separato, senza toccare il file NVIDIA validato. Indici `rocm6.4` (Linux) o TheRock, e llama `rocm72`/`hip-radeon`/`vulkan`. |
| `requirements.txt:37` (ctranslate2==4.6.0) | 4.6.0 non ha ROCm | ROCm richiede ≥4.7, quindi bisogna riaprire il problema del crash in PyQt6 (vedi 5) |
| `requirements.txt:57` (bitsandbytes==0.49.2) | ROCm sperimentale, solo Linux | ≥0.50.x nel profilo ROCm |
| `requirements-canary.txt:5,29,162` | `cu126`, `cuda-bindings` | Canary non va offerto su AMD |

### 3.2 Punti che degradano su CPU in silenzio (i più insidiosi)

| File:riga | Effetto su AMD | Correzione |
|---|---|---|
| `utils/llm_model_select.py:41-57` (`nvidia-smi` alla riga 50) e `utils/config.py:998-1005` | `detect_vram_mib()` restituisce None, quindi `n_gpu_layers=0`: **Qwen gira su CPU anche con una ruota HIP o Vulkan installata.** Fa eccezione il caso di un percorso modello configurato a mano (`config.py:995`, che usa -1). | Rilevare la VRAM con `rocm-smi`/`amd-smi` su Linux, oppure con `torch.cuda.get_device_properties(0).total_memory` in un sottoprocesso. |
| `glossary_engine/glossary_qwen_gpu_cli.py:63-71,102` | La VRAM libera risulta None, quindi l'avviso viene saltato. Nessun crash. | Effetto minore: stesso helper indipendente dal fornitore |
| `utils/resource_monitor.py:11-15,63-69,84-119` e `gui/widgets.py:17,78-79,263,269,336` | pynvml non parte, quindi il monitor mostra 0% e 0 GB di VRAM | Livello di astrazione `gpu_info`: pynvml, poi amdsmi (Linux), poi `torch.cuda.mem_get_info` |
| `utils/adaptive_batch_manager.py:23,71-78,321-336,427-462,513` | La cascata pynvml → `torch.cuda.mem_get_info(0)` → psutil continua a funzionare, perché `mem_get_info` è a livello di device. Però pynvml era stato scelto perché "vede allocazioni ctranslate2": va verificato che hipMemGetInfo veda anche la VRAM di ct2-HIP. Il costo per batch (`beam×0.15 GB`, riga 352/373) è stato tarato sulla RTX 3060. | Ritarare il batch su una scheda AMD |

### 3.3 Punti da adattare (funzionano in parte o vanno verificati)

| File:riga | Nota |
|---|---|
| `core/engines/faster_whisper_engine.py:49,264-283` (`device="cuda"`, `compute_type="int8_float16"`) | Con ct2 ROCm il nome del device dovrebbe restare `cuda` (non verificato). **Il supporto a `int8_float16` su HIP non è verificato.** Un vecchio fork (arlo-phoenix) segnalava bf16 disattivato e int8 parziale ([README_ROCM](https://github.com/arlo-phoenix/CTranslate2-rocm/blob/rocm/README_ROCM.md)). Se non funziona, si ripiega su `float16`, che usa circa 1,5 GB di VRAM in più. |
| `scripts_manutenzione/selfcheck_env.py:81-93` | Stampa `torch.version.cuda`, che su ROCm è None. Va aggiunto `torch.version.hip`. `ct2.get_cuda_device_count()` va verificato sulla build HIP. Il messaggio di errore cita il "driver NVIDIA". |
| `utils/cuda_dll_path.py` (usato da `core/gender_rewriter.py:192`, `core/gender_corrector.py:25`, `core/fallback_translate_cli.py:184`, `core/subtitle_synchronizer.py:37`, `glossary_engine/glossary_qwen_extract.py:55`, `glossary_engine/glossary_qwen_gpu_cli.py:120`) | Su Windows aggiunge `torch\lib` al PATH per `cudart64_12`/`cublas64_12`. Con la ruota `hip-radeon` le DLL necessarie sono `amdhip64`/hipBLAS: **non verificato se siano incluse.** Con la ruota Vulkan non serve nulla. Su Linux la funzione non fa nulla già oggi. |
| `core/llm_subtitle_translator/engine.py:58` (`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`) | Non è verificato che ROCm legga questa variabile o richieda `PYTORCH_HIP_ALLOC_CONF`. Nel caso peggiore l'impostazione viene ignorata. |
| `core/llm_subtitle_translator/engine.py:400-424`, `core/translator.py:1074,1197` (BitsAndBytesConfig NF4/int8) | Richiede bitsandbytes ≥0.50 con ROCm. NF4 in bf16 su RDNA2 è lento. |
| `core/engines/qwen3_asr_engine.py:86,183,305`, `core/engines/canary_engine.py:344-345`, `core/engines/canary_cli.py:66` | bf16: RDNA3 e RDNA4 lo supportano, RDNA2 non ha accelerazione hardware. Bene: flash_attention_2 **non** è usato (`qwen3_asr_engine.py:186`) e nel codice non ci sono xformers. |
| Gestione degli OOM e dello sconfinamento WDDM (`core/translator.py:1393,1491`, `core/llm_subtitle_translator/translator.py:141,238`, `core/engines/canary_cli.py:93`, `core/engines/faster_whisper_engine.py:70-75,532`) | Su **Linux** ROCm restituisce un OOM vero (`torch.OutOfMemoryError`), non lo sconfinamento in RAM condivisa. Quindi i rami OOM, mai raggiunti in produzione, diventerebbero percorsi reali, e per ct2 un OOM resta fatale. Su **Windows** anche AMD passa da WDDM: il comportamento è probabilmente simile a quello attuale (non verificato). |

### 3.4 Punti innocui o cosmetici

- `core/diarizer.py:182-183,875-876`: flag TF32, che su ROCm si impostano senza effetto.
- `core/pipeline.py:2039,2047` e `core/subtitle_synchronizer.py:1906`: `_cuda_clearCublasWorkspaces` e `ipc_collect`, già dentro try/except.
- `core/engine_router.py:221-222`, `core/translator.py:1058,1177,1642`, `core/llm_subtitle_translator/engine.py:298`: `torch.cuda.mem_get_info()`, che funziona via HIP. Su Windows ROCm va verificato.
- Commenti e testi che citano CUDA/NVIDIA: vanno aggiornati solo nei messaggi rivolti all'utente.

---

## 4. Conclusioni: fattibilità per scenario

### Componenti e scenari

| Funzione | (A) Linux + ROCm | (B) Windows + ROCm | (C) Ripiego Vulkan + CPU |
|---|---|---|---|
| Qwen3-ASR (en/it) | **Sì, probabile** (torch) | Probabile, ma solo con torch ≥2.9.1 o 2.11 | CPU (molto lento) |
| Whisper (ct2): fr/de/es, lingue fuori dal set di Qwen3, ripiego automatico per qualsiasi errore di Qwen3/Canary (`core/engine_router.py:8-21`), ripiego S1 del Sync (`core/sync_cli.py:7-8`) | **Condizionato** a ct2 ≥4.8.3 ROCm, alla verifica del crash in PyQt6 e al supporto di int8_float16 | Condizionato e più rischioso (fix "hangs" del 13/10) | CPU int8 (già supportato oggi) |
| Canary (en, opzionale) | **No** | **No** | No |
| Allineamento whisperx | Sì (torch) | Sì ma whisperx `--no-deps` | CPU |
| Diarizzazione pyannote | Probabile | Probabile (con torch nuovo + torchcodec riallineato) | CPU |
| Demucs | Probabile | Probabile | CPU |
| NLLB-FT (fp16) | Probabile | Probabile; batch LLM=1 "ufficiale" solo per LLM | CPU |
| TranslateGemma 12B NF4 | Con bnb ≥0.50 | Con bnb ≥0.50 Windows ROCm | No in pratica (troppo lento) |
| Glossario, gender, L3, sync (llama.cpp) | **Sì** (rocm72 o vulkan, 0.3.34) | **Sì** (vulkan o hip-radeon, 0.3.34) | **Sì (Vulkan)** |
| OCR (Tesseract) e spaCy | Sì (CPU, nessun cambio) | Sì | Sì |
| Monitor VRAM e batch adattivo | Da riscrivere (amdsmi/torch) | Da riscrivere (solo torch) | n/a |

### Sforzo, rischi e raccomandazione

| | (A) Linux + ROCm | (B) Windows + ROCm | (C) Vulkan + CPU |
|---|---|---|---|
| Distro e GPU tipiche | Ubuntu 24.04/22.04, RX 7900/7800/7700 XT, RX 9070/9060. La RX 7600 compare solo nella matrice 10.0, non in quelle 6.4.4 e 7.2.1. Le RX 6000 non sono ufficiali (override). | Windows 11, RX 7900 XTX/7700, RX 9070/9060 XT (ufficiali con 7.2.1). Altre solo con TheRock. | qualsiasi GPU con driver Vulkan |
| Pila consigliata | torch **2.8.0+rocm6.4** (mantiene i pin di whisperx, transformers e qwen-asr), ct2 ROCm (zip GitHub), bnb ≥0.50, llama `rocm72` o `vulkan` | torch 2.11+rocm10 cp311 (TheRock) oppure 2.9.1 cp312 (ufficiale), torchaudio 2.11, torchcodec 0.11, whisperx `--no-deps`, bnb ≥0.50, llama `vulkan` | torch CPU, llama `vulkan` |
| Sforzo stimato | 6-10 giornate (installer e requirements-rocm 2; astrazione GPU 2; ct2/Whisper 1-2; taratura batch 1-2; prove 1-2) **più** sessioni su macchina AMD | 10-15 giornate, con un aggiornamento di torch che ricade anche sul ramo NVIDIA, se si vuole un solo pin | 1-2 giornate |
| Rischi principali | 0) **Nessuna combinazione validata da AMD per le Radeon comprende torch 2.8.** Se la 2.8.0+rocm6.4 dà problemi, si passa a torch rocm7.x o 10.x con whisperx `--no-deps`. 1) ct2 ≥4.7 e crash in PyQt6, attenuato perché Whisper gira in sottoprocesso (`core/pipeline_cli.py`). 2) **Due runtime HIP nello stesso processo**: torch include HIP 6.4, mentre la ruota ct2 Linux è compilata contro ROCm 7.2 di sistema (rischio da provare, non un guasto certo). Allinearsi a torch rocm7.x riapre però il pin di whisperx. 3) int8_float16 su HIP. 4) OOM veri al posto dello sconfinamento WDDM. | Tutti quelli di (A), più: stack "only PyTorch" su Windows, Py 3.12 ufficiale contro il 3.11 del progetto, fix ct2 Windows molto recenti, nessun pynvml o amdsmi, torch diverso dal ramo NVIDIA da mantenere. Inoltre TheRock divide torch in pacchetti per architettura (`amd-torch-device-gfxXXXX`, e bnb usa gli extra `device-gfx1100`), quindi l'installer deve riconoscere il target gfx della scheda. | Prestazioni: tutto ciò che non è llama gira circa 10 volte più lento |
| **Raccomandazione** | **Fare, ma dopo, solo come "sperimentale"**, e solo quando c'è una macchina AMD vera da usare per le prove | **Non fare ora.** Rivalutare tra 6-12 mesi, quando AMD pubblicherà Windows ROCm 10.x come canale Radeon ufficiale e whisperx non richiederà più torch 2.8. | **Fare per primo**, perché costa poco e prepara anche (A) |

### Ordine proposto

1. **(C) senza rischi per NVIDIA.** Creare un helper `utils/gpu_info.py` che rilevi fornitore e VRAM con la cascata nvidia-smi/pynvml, poi rocm-smi/amd-smi, poi torch, poi None, e usarlo in `llm_model_select`, nel monitor e nell'installer. Aggiungere al fianco di `-NoGpu` l'opzione `-Vulkan`, che installa llama 0.3.34 dall'indice `vulkan`. Il ramo NVIDIA resta identico.
2. **(A) Linux + ROCm sperimentale.** `requirements-rocm.txt` e `install.sh --rocm`. Canary va disattivato in GUI quando `torch.version.hip` è valorizzato. Se Whisper/ct2 non passa il test 1 qui sotto, Whisper resta su CPU. Perdono la GPU fr/de/es, le lingue fuori dal set di Qwen3, i ripieghi su Whisper e il ripiego S1 del Sync. Il percorso normale per en/it usa Qwen3 su torch e non viene toccato.
3. **(B)** Solo se arrivano richieste reali.

### Prova minima su una macchina AMD vera

Su Linux, Ubuntu 24.04, con una RX 7900 o una RX 9070:
1. **ct2 ROCm dentro un processo PyQt6**: `WhisperModel(device="cuda", compute_type="int8_float16")` e poi `"float16"`, su un file di 5 minuti, dentro `pipeline_cli` e anche nel processo principale. È il test che decide se Whisper si può usare.
2. Torch e ct2 nello **stesso processo** (Whisper seguito da allineamento whisperx), per verificare il conflitto fra runtime HIP 6.4 e 7.2.
3. Qwen3-ASR bf16 su 10 minuti, confrontando tempo e WER con la RTX 3060 (rif. banchi `pipeline_bench/`).
4. pyannote e Demucs su un episodio.
5. NLLB-FT fp16 e TranslateGemma NF4 (bnb 0.50) su un file, con verifica che l'output sia identico o equivalente a quello NVIDIA.
6. llama 0.3.34 `rocm72` contro `vulkan`: velocità in token/s sul 14B o 7B.
7. Batch adattivo: forzare un OOM vero e controllare che il recupero funzioni.

Una macchina cloud Instinct (MI300) serve a validare lo stack software, ma **non** l'esperienza su RDNA consumer e Windows.

---

## 5. Note di coerenza con le regole del progetto

- **ctranslate2 4.6.0** è una regola permanente. Il profilo ROCm la violerebbe per forza, perché il supporto ROCm esiste solo da 4.7.0 in poi. La proposta è di tenerlo separato in `requirements-rocm.txt`, lasciando 4.6.0 su NVIDIA. Va però deciso se il crash della 4.7.x in PyQt6 dipende solo da CUDA, perché è legato all'inizializzazione lazy del contesto CUDA. Se dipendesse solo da CUDA, su HIP potrebbe non presentarsi, ma **è un'ipotesi da provare**. Dalla 4.8.2 è stata anche tolta la dipendenza a runtime da setuptools.
- **llama-cpp-python 0.3.34** resta invariato: la versione esiste negli indici `rocm72`, `hip-radeon` e `vulkan`.
- Le euristiche di batch tarate sulla RTX 3060 non si possono riusare alla cieca su AMD. Serve una nuova taratura con misure, coerente con la regola sulle euristiche imprevedibili.

---

## 6. Cosa NON ho potuto verificare

- Esecuzione reale di qualsiasi componente su GPU AMD, perché qui c'è solo NVIDIA.
- Il comportamento di ct2 ROCm con `int8_float16`, il nome del device (`cuda`), `get_cuda_device_count()` e la convivenza con torch rocm6.4 nello stesso processo.
- Se il crash della 4.7.x in PyQt6 si ripete su HIP.
- Il supporto ufficiale ROCm di pyannote, Demucs, qwen-asr e NeMo: non ho trovato dichiarazioni né in un senso né nell'altro. NeMo chiede una "NVIDIA GPU" solo per il training.
- Se torch 2.8.0+rocm6.4, che AMD non ha validato per le Radeon, regge l'intera pipeline.
- Quali DLL includa la ruota `hip-radeon` di llama-cpp-python su Windows.
- Se `PYTORCH_CUDA_ALLOC_CONF` viene letta su ROCm, e se `mem_get_info` è affidabile su Windows ROCm.
- Un equivalente Python di pynvml su Windows nativo per AMD.
- Lo stato "ufficiale" di Windows ROCm 10.x per le Radeon. La matrice 10.0 elenca Windows 11 25H2, ma la guida d'installazione Radeon cita ancora la 7.2.1 con Py 3.12.
- I numeri di prestazione (Vulkan contro HIP, AMD contro RTX 3060): esistono solo dati di terzi su hardware diverso.


## Verifiche del 22/10/2026 dopo la revisione (da leggere prima del resto)

Quattro affermazioni dello studio sono state ricontrollate con richieste dirette ai repository (nessuna GPU AMD usata):

| Affermazione | Esito |
|---|---|
| torch 2.8.0 con ROCm | **Confermato**: ruote `torch-2.8.0+rocm6.3` e `+rocm6.4` per cp311 Linux x86_64 su download.pytorch.org; `torchaudio-2.8.0+rocm6.4` idem. Non esiste una ruota rocm7.0 di torch 2.8.0. |
| ctranslate2 con ROCm | **Confermato**: le release 4.7.2, 4.8.0, 4.8.1, 4.8.2, 4.8.3 di OpenNMT/CTranslate2 hanno gli asset `rocm-python-wheels-Linux.zip` e `rocm-python-wheels-Windows.zip` (ruote su GitHub, non su pip). Il progetto e' fermo alla 4.6.0 (4.7.x crashava dentro PyQt6): il primo test decisivo resta Whisper con la ruota ROCm dentro PyQt6. |
| bitsandbytes con ROCm dalla 0.50 | Esiste la 0.50.2 su PyPI (il progetto ha la 0.49.2); il supporto ROCm stabile della 0.50 resta da verificare nelle note di rilascio, non e' stato controllato qui. |
| llama-cpp-python 0.3.34 per ROCm/HIP/Vulkan | **CORREZIONE**: sull'indice di abetlen esistono ruote precompilate 0.3.34 per **Vulkan** (`whl/vulkan`, manylinux x86_64) oltre a cpu, cu124 e cu125; **NON esistono cartelle `rocm` o `hip`** (404). Per ROCm/HIP serve una compilazione da sorgente (SDK ROCm, cmake, compilatore), quindi per un utente comune il ripiego pratico e' Vulkan. |

**Qwen3-ASR** (`qwen_asr` 0.0.6, il motore principale per inglese e italiano): nessuna dipendenza rigida da `flash_attn` o `triton`; usa `transformers` 4.57.6 e le funzioni di attenzione di transformers (`flash_attention_2` e' solo un'opzione, con `sdpa`/`eager` come alternative). Quindi su ROCm la parte Qwen3-ASR e' "probabilmente fattibile", ma anche questo va provato su hardware AMD vero.

### Che cosa ottiene un utente AMD a ciascun passo
1. **Ripiego Vulkan (1-2 giornate):** mette su GPU solo il **glossario** (llama.cpp), che si costruisce di rado. Trascrizione, traduzione, Demucs e diarizzazione restano su CPU, circa 10 volte piu' lente. E' un lavoro preparatorio, **non** "supporto AMD".
2. **Linux con ROCm sperimentale (6-10 giornate):** da qui l'utente AMD ha davvero la GPU per trascrizione e traduzione. Richiede un insieme di pin separato per ROCm (torch 2.8.0+rocm6.4, torchaudio, torchcodec legato a torch, pyannote, whisperx senza dipendenze, bitsandbytes 0.50, ctranslate2 ROCm da GitHub), scelto da un'opzione dell'installer come per `-NoGpu`, senza toccare il percorso NVIDIA.
3. **Windows con ROCm (10-15 giornate, rischio alto):** da non fare ora.
