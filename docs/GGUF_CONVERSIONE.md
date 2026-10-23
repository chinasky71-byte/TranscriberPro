# Conversione di TranslateGemma-12B in GGUF

Guida per produrre i file GGUF del percorso llama.cpp del traduttore (vedi `docs/HANDOFF_LOG_GGUF_TRANSLATOR.md`). Si fa **in locale**: i pesi fine-tuned sono in una cartella dell'utente e non nel repository. Lo script è `scripts_manutenzione/gguf_convert.py` (`python scripts_manutenzione/gguf_convert.py plan` stampa tutto quello che segue con i numeri).

## 1. Compatibilità: che llama.cpp usare

- `llama-cpp-python` **0.3.34** (pin del prodotto, **non cambia**) vendorizza llama.cpp al commit **`e3546c794`** (CHANGELOG di llama-cpp-python: «update llama.cpp to ggml-org/llama.cpp@e3546c794»).
- L'architettura **Gemma3 è supportata** da quel runtime: provato in cloud caricando e generando con un GGUF Gemma3 da 270M (stessa architettura, finestra scorrevole compresa) con la ruota 0.3.34, 4 sequenze in parallelo.
- Per la **sola conversione e quantizzazione** si usano gli strumenti dello **stesso commit**, così il file e il runtime del prodotto parlano la stessa versione del formato. Non serve una versione più recente.
- `convert_hf_to_gguf.py` a quel commit gestisce `Gemma3ForConditionalGeneration` (la classe di TranslateGemma): esporta il solo testo; la torre visiva si esporta solo con `--mmproj`, che qui **non** serve.

```bash
git clone https://github.com/ggml-org/llama.cpp
git -C llama.cpp checkout e3546c794
cmake -S llama.cpp -B llama.cpp/build -DCMAKE_BUILD_TYPE=Release          # senza CUDA: bastano le CPU
cmake --build llama.cpp/build --config Release --target llama-quantize llama-imatrix -j     # (per l'imatrix su GPU: -DGGML_CUDA=ON)
```

Su Windows con Visual Studio i binari finiscono in `build\bin\Release\`: lo script li cerca in entrambi i posti. I comandi sotto sono bash; in PowerShell usa `$S = "python scripts_manutenzione\gguf_convert.py"` e `& python ...`, e passa a `verify` i file uno per uno (il glob non si espande).

Ambiente Python **separato** da quello dell'app (il convertitore vuole `torch==2.11` CPU e transformers):

```bash
python -m venv venv_gguf
venv_gguf/bin/pip install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt transformers peft   # Windows: venv_gguf\Scripts\pip
```

## 2. Risorse (STIME, non misure)

| Cosa | Dimensione |
|---|---|
| GGUF bf16 (12B × 2 byte; il tipo nativo di Gemma3, default di `convert`) | ~22 GiB (~24 GB decimali) |
| Q4_K_M / Q3_K_M / IQ3_M | ~6,6 / ~5,3 / ~5,0 GiB (7,1 / 5,7 / 5,4 GB decimali) |
| Q8_0 (base dell'imatrix, vedi §4) | ~11,7 GiB |
| **Disco totale** (bf16 + 3 quantizzati + Q8_0, senza merge) | **~50 GiB** |
| RAM per `merge` (modello bf16 intero, torre visiva compresa) | ~26-28 GiB; disco: +~22 GiB per il modello fuso; senza `merge` la conversione legge a mmap (non misurato; 32 GB di RAM consigliati) |

I GB dichiarati nell'incarico (7,3 / 5,9 / 5,4) sono decimali: in GiB sono più bassi, quindi il selettore (`utils/translator_path_select.py`, che li usa come GiB) è prudente. **`verify` stampa le dimensioni REALI**: vanno riportate in `QUANT_WEIGHTS_GIB`.

## 3. Passi

Se la cartella dei pesi è **già fusa** (es. `translategemma-12b-it-finale`, come da `llm_translator_model_path`) salta il passo `merge`.

```bash
S="python scripts_manutenzione/gguf_convert.py"
# 0) solo se base e adattatore LoRA sono separati (venv_gguf con transformers+peft). Controlla che l'adattatore sia stato applicato davvero
#    (lo script lo verifica su un peso q_proj e non scrive nulla se non cambia) e confronta l'uscita prima/dopo su qualche riga. Il delta LoRA si arrotonda in bf16.
$S merge --base <base-12b> --adapter <cartella-lora> --out <12b-fuso>
# (convert, quantize, imatrix: con venv_gguf; corpus e verify --smoke: con il venv dell'app)
# 1) HF -> GGUF bf16 (con venv_gguf: usa il Python che lo lancia) (serve tokenizer.model nella cartella)
$S convert --model <12b-fuso> --llama-cpp llama.cpp --out gguf/translategemma-12b-it-finale-bf16.gguf
# 2) Q8_0 (base dell'imatrix) e quantizzati senza imatrix (Q4_K_M, Q3_K_M)
$S quantize --llama-cpp llama.cpp --gguf gguf/translategemma-12b-it-finale-bf16.gguf --outdir gguf --quants Q8_0
# 3) imatrix (vedi §4), poi i quantizzati con imatrix
$S quantize --llama-cpp llama.cpp --gguf gguf/translategemma-12b-it-finale-bf16.gguf --outdir gguf \
            --quants Q4_K_M,Q3_K_M,IQ3_M --imatrix gguf/imatrix.gguf
# 4) controllo: architettura gemma3, quantizzazione, dimensione reale; --smoke traduce una riga
$S verify gguf/*-Q4_K_M.gguf gguf/*-Q3_K_M.gguf gguf/*-IQ3_M.gguf
```

I file prodotti si chiamano `<nome>-<QUANT>.gguf`: copiali in `models/translategemma-12b-gguf/` (o nella cartella di `llm_translator_gguf_dir`) e il router li riconosce da soli.

## 4. imatrix: cosa è, su quali dati

La matrice di importanza dice a `llama-quantize` quali pesi pesano di più sull'uscita, e si calcola facendo girare il modello su testo di calibrazione. IQ3_M e Q3_K_M ne traggono di norma vantaggio (qualità attesa migliore, **non misurata**); Q4_K_M poco. llama.cpp la impone solo a IQ1/IQ2/IQ3_XXS: IQ3_M senza imatrix si può produrre (lo script avvisa) e, se non hai ancora le coppie, serve come confronto.

- **Dati**: coppie inglese→italiano di sottotitoli **reali, in formato training**, fornite da te (file UTF-8, una per riga, `inglese<TAB>italiano`, `\n` letterale per le righe doppie). Alcune centinaia (default fino a 1000, minimo 100). **Non devono essere le battute del banco di qualità** (fase 3): la calibrazione sul materiale di prova gonfierebbe i risultati.
- `corpus` rende ogni coppia nel formato **esatto** del motore (prompt di TranslateGemma + risposta italiana + `<end_of_turn>`), non testo generico; `imatrix` passa `--parse-special` a llama-imatrix, altrimenti `<start_of_turn>`/`<end_of_turn>`/`<bos>` diventerebbero testo ordinario. llama-imatrix spezza il corpus in blocchi di 512 token senza rispettare i confini delle coppie (e antepone un BOS a ogni blocco):

```bash
# `corpus` e `verify --smoke` importano il codice dell'app: si lanciano con il Python del venv dell'app (non con venv_gguf)
$S corpus --pairs coppie_calibrazione.tsv --out gguf/calibrazione.txt
$S imatrix --llama-cpp llama.cpp --gguf gguf/translategemma-12b-it-finale-Q8_0.gguf --corpus gguf/calibrazione.txt \
           --out gguf/imatrix.gguf --ngl 0        # su CPU; con una GPU grande: --ngl 99
```

Si calcola dal **Q8_0** (11,7 GiB) invece che dal f16 (22 GiB) perché entra in RAM/VRAM più piccole con un'approssimazione trascurabile per questo scopo. Tempo di calcolo: **non misurato**.

## 5. Cosa NON è verificato

- La conversione è provata end-to-end (convert → imatrix → quantize → verify → generazione con il motore del prodotto) solo su un Gemma3 da **270M** (`docs/HANDOFF_LOG_GGUF_TRANSLATOR.md`, fase 2), non sul 12B: risorse e tempi reali sono da misurare sulla tua macchina.
- Qualità dei quantizzati: la misura la fa il banco di fase 3.
