# Registro: TranslateGemma a pesi GGUF per schede da 8 GB

Piu' recenti in alto. Obiettivo: far girare TranslateGemma-12B anche su schede da 8-12 GB (e su AMD/Vulkan) con pesi GGUF
quantizzati eseguiti da llama-cpp-python, **lasciando invariato il comportamento sulle schede grandi**. Il percorso GGUF sta
dietro `llm_translator_gguf_enabled` (default **False**) finche' il banco di qualita' (fase 3) non lo promuove.

Regole di flusso: una PR per fase; implementa, prova, revisione critica separata in sola lettura, correggi. Niente toccato:
APP_VERSION, CHANGELOG, README, requirements*, pin (ctranslate2 4.6.0, llama-cpp-python 0.3.34), percorso NVIDIA.

## 2026-10-23 · Fase 1 — codice del percorso GGUF (PR #14)

**Fatto**
- `utils/translator_path_select.py`: funzione pura `choose_translator_path(free_gib, backend, ...)` -> `bf16 | nf4 | gguf:<quant> | nllb`
  con un codice di motivo stabile. Soglie e ingombri sono costanti con nome e commento.
- `core/llm_subtitle_translator/gguf_engine.py`: `GGUFEngine`, sottoclasse di `SubtitleLLMEngine` (stessa interfaccia: `spec.max_batch`,
  `mt_messages`, `generate`, `unload`, `log`). `mt_messages` e `spec` sono ereditati, non copiati: il prompt e' identico per costruzione.
  Decodifica greedy a basso livello con piu' sequenze nello stesso `llama_decode` (cache KV unificata); `n_parallel` sequenze x 512 token.
  Il prompt e' reso da `render_prompt()` (chat template di TranslateGemma riprodotto), non dal template incorporato nel GGUF.
- `core/llm_subtitle_translator/path_router.py`: legge backend, VRAM libera, GGUF presenti, ruota di llama-cpp-python; decide; scrive il percorso
  e, per NLLB, il motivo. Ripiego sempre dichiarato: caricamento GGUF fallito -> percorso storico se la VRAM lo regge, altrimenti NLLB-FT.
- `core/translator.py`: `LLMSubtitleTranslator._acquire_engine()` (flag spento = la stessa chiamata a `get_engine` di prima, stessi argomenti, il
  router non viene nemmeno importato), `_translate_via_nllb_ft()` (ripiego), `cleanup()` scarica anche il motore GGUF se esiste.
- Config: `llm_translator_gguf_enabled` (False), `llm_translator_gguf_dir`, `llm_translator_gguf_quant` ('auto'), `llm_translator_gguf_parallel` (4),
  `llm_translator_nf4_min_free_gb` (10.5). 15 chiavi `gg_*` in EN e IT.

**Punti delicati**
1. **Soglia NF4 = 10,5 GiB liberi, non 12.** Una scheda "da 12 GB" ha 12,0 GiB *totali* e meno di liberi (desktop): con soglia 12 finirebbe sempre sul
   GGUF, cambiando cio' che oggi funziona in NF4 (picco misurato 10.133 MiB = 9,9 GiB a batch 12; 10,56 GiB a batch 16). E' una scelta derivata dalla misura, ma e' un numero mio: da confermare in fase 3.
2. **Le soglie per il GGUF sono stime, non misure**: pesi 7,3 / 5,9 / 5,4 GiB (dimensioni dichiarate nell'incarico), KV cache 0,375 MiB/token (calcolo
   dall'architettura Gemma3-12B, limite superiore), buffer di calcolo 0,5 GiB, margine fisso 0,4 GiB (i GB dichiarati potrebbero essere decimali). Una scheda da 8 GB (7,0-7,6 GiB liberi) entra con Q3_K_M solo a
   `n_parallel` <= 4 e con poco desktop; altrimenti IQ3_M. La fase 3 misura il picco reale e sostituisce questi numeri.
3. Il prompt NON passa dal template Jinja del GGUF: un GGUF convertito puo' portare il template generico di Gemma3 (senza codici lingua) e il modello
   riceverebbe un prompt diverso da quello del training, senza errori.
4. Un GGUF con architettura diversa da `gemma3` viene rifiutato al caricamento (altrimenti: testo senza senso e nessun errore).
5. Un adattatore LoRA configurato esclude il GGUF (il GGUF e' gia' fuso: l'adattatore non verrebbe applicato).
6. Un motore gia' caricato (file precedente della coda) si riusa senza ridecidere: la VRAM libera "di adesso" non comprende i pesi che il motore
   stesso occupa.
7. Un prompt piu' lungo del contesto per sequenza esce **vuoto** (va ai livelli L2/L3), mai troncato.
8. Su AMD/Vulkan (ruota Vulkan, marcatore `venv/llama_backend.txt`) senza torch GPU: backend `vulkan`, solo GGUF o NLLB; su ROCm con torch: bf16 se entra,
   mai NF4 (niente bitsandbytes).

**Test eseguiti**
- `python -m pytest linux_tests -q` (senza torch, senza GPU, senza modelli) -> **385 passed, 14 skipped** (prima: 308 passed, 6 skipped).
- Con GGUF veri, su CPU, llama-cpp-python 0.3.34 (ruota CPU), `TP_TEST_GGUF_GEMMA3` = `gemma-3-270m-it-Q8_0` (stessa ARCHITETTURA di TranslateGemma, 270M),
  `TP_TEST_GGUF_OTHER` = Qwen2.5-0.5B-Instruct Q4_K_M, `TP_TEST_TG_TEMPLATE` = chat_template.jinja ufficiale: **65 passed**. Dimostrano: il prompt reso e'
  uguale al template ufficiale su 360 combinazioni (30 codici lingua x 6 testi x 2 budget); la decodifica a 4 sequenze coincide con il greedy dell'API alta di
  llama-cpp-python; lo stesso prompt in slot diversi da la stessa risposta; scarico/ricarico; architettura sbagliata rifiutata; `SubtitleLLMTranslator`
  (validatore, retry singolo) lavora con il motore GGUF.
- Flag spento: test che `get_engine` e' chiamato una volta con gli stessi argomenti, che ne' `path_router` ne' `gguf_engine` vengono importati, che la GPU non
  viene letta, che `cleanup()` e' identico. Schede da 10,5 a 48 GiB con flag acceso: stesso esito del motore storico su 376 valori di VRAM.

**Revisione critica separata (sola lettura)**: nessun bloccante. Corretti: messaggi delle eccezioni passati da `tr()` (6 chiavi `gg_err_*`); `RLock` fra
`generate()` e `unload()`; margine VRAM; commenti sul picco NF4 (9,9 GiB, non 10,1); `ensure_torch_lib_on_path()` prima dell'import di llama_cpp;
VRAM libera illeggibile -> percorso storico (non NLLB); messaggi sul GGUF solo a chi ne ha bisogno; ramo di ripiego irraggiungibile tolto; `cleanup()` scarica
i due motori in modo indipendente; log quando il contesto accorcia la risposta; test con `monkeypatch` sulle `sys.modules` e nuovi test (decode fallito, scarico
idempotente, esclusione generate/unload, VRAM illeggibile). **Non corretti, dichiarati**: (a) con il flag acceso, ROCm con meno di 20 GiB e senza ruota Vulkan e il
caso solo-CPU vanno a NLLB-FT (master tentava NF4/CPU): scelta voluta e scritta nel log; (b) un GGUF gia' caricato si riusa anche se cambiano
cartella/quant/parallel finche' non c'e' `cleanup()`; (c) `LANGUAGES` ha i 160 codici base, il template 581 con le regioni (identico per tutti i codici di
`LANGUAGE_CODES`); (d) il log nativo di llama.cpp e' muto per il processo; (e) con piu' GPU Vulkan llama.cpp potrebbe usare anche la iGPU mentre il router
dimensiona sulla piu' grande; (f) il ripiego NLLB ricarica i pesi a ogni file.

**Non verificato**
- Nessuna prova su GPU (NVIDIA, AMD, Vulkan) ne' su Windows+CUDA con torch e llama.cpp nello stesso processo: ne' velocita' ne' VRAM di picco reali del GGUF.
- Nessuna prova con i pesi veri di TranslateGemma-12B (ne' la qualita' di Q4_K_M/Q3_K_M/IQ3_M): il modello da 270M non traduce, prova il percorso.
- Il KV unificato con la finestra scorrevole di Gemma3 e' provato solo sul 270M (stessa architettura, altre dimensioni).
- GUI Windows, pipeline su video reale, interazione con il serbatoio Qwen (L3).

**Domande per l'utente**
- Conferma della soglia NF4 a 10,5 GiB (vedi punto 1) e di `n_parallel` = 4 come valore di partenza.
