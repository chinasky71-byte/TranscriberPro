# -*- coding: utf-8 -*-
"""Scelta del percorso del traduttore LLM (TranslateGemma-12B) in base alla VRAM libera e al backend.

Modulo PURO: solo libreria standard, niente torch ne' llama_cpp, niente lettura di GPU. Chi chiama passa i numeri
(vedi core/llm_subtitle_translator/path_router.py). Stesso schema di utils/llm_model_select.py.

Percorsi possibili:
  bf16        pesi bfloat16 (~24 GB), transformers: comportamento storico per le schede grandi
  nf4         pesi a 4 bit con bitsandbytes (8.401 MiB di pesi, picco misurato 10.133 MiB = 9,9 GiB a batch 12), solo NVIDIA/CUDA
  gguf:<q>    pesi GGUF a quantizzazione spinta eseguiti con llama.cpp (llama-cpp-python), per le schede da 8-12 GB
              e, su AMD/Vulkan, unica via senza bitsandbytes
  nllb        NLLB fine-tuned, ripiego dichiarato all'utente

Regole (con il percorso GGUF acceso; con il flag spento il router non passa di qui e vale il motore storico):
  1. backend cuda o rocm e VRAM libera >= bf16_min_free_gb          -> bf16
  2. backend cuda        e VRAM libera >= nf4_min_free_gb           -> nf4
  3. backend cuda/rocm/vulkan, almeno un GGUF presente che ENTRA    -> gguf:<quant migliore che entra>
  4. altrimenti                                                      -> nllb
"Entra" = pesi del GGUF + ingombro di esecuzione (KV cache + buffer di calcolo) <= VRAM libera. Niente offload parziale:
un modello a meta' su GPU e meta' su CPU e' piu' lento di NLLB e non e' stato misurato.

VALORI PROVVISORI: soglie e ingombri qui sotto sono stime (dimensioni dei file GGUF dichiarate dall'utente, costi di
KV cache calcolati dall'architettura Gemma3-12B) e NON misure. Li sostituisce il banco di qualita' (fase 3).
"""
from dataclasses import dataclass
from typing import Iterable, Optional

BF16 = 'bf16'
NF4 = 'nf4'
GGUF = 'gguf'
NLLB = 'nllb'

# Ordine di preferenza (qualita' decrescente, ingombro decrescente). Con quant='auto' si prende la prima che entra.
QUANT_PREFERENCE = ('Q4_K_M', 'Q3_K_M', 'IQ3_M')

# Dimensione dei pesi (GiB) per quantizzazione. Stime del file GGUF del 12B (da misurare sui file reali: fase 2).
QUANT_WEIGHTS_GIB = {'Q4_K_M': 7.3, 'Q3_K_M': 5.9, 'IQ3_M': 5.4}

# KV cache di Gemma3-12B in f16: 48 layer x 8 teste KV x 256 dim x 2 (K,V) x 2 byte = ~0,375 MiB per token (limite
# superiore: gli strati a finestra locale ne usano meno). Buffer di calcolo di llama.cpp a n_ubatch 512: stima 0,5 GiB.
KV_GIB_PER_TOKEN = 0.375 / 1024
COMPUTE_BUFFER_GIB = 0.5
# Margine fisso sopra la stima: i pesi sono dichiarati in GB (forse decimali, quindi ~7% sopra il valore in GiB) e il
# buffer di calcolo e' una stima. Su WDDM uno sconfinamento in RAM di sistema non da errore: solo 4-5 volte piu' lento.
SAFETY_MARGIN_GIB = 0.4

# Soglia NF4: il picco misurato a batch 12 e' 10.133 MiB = 9,9 GiB; a batch 16 (tetto attuale, il gestore adattivo parte da
# 12) 10.817 MiB = 10,56 GiB (mt_eval/vram_probe.py, commento in engine.py). 10,5 GiB LIBERI e' quindi una soglia
# prudente per il batch di partenza, non una garanzia al tetto. NON 12: una scheda "da 12 GB" ha 12,0 GiB TOTALI e ne ha sempre meno di liberi (desktop), quindi con
# 12 finirebbe sempre sul GGUF cambiando il comportamento di oggi, dove funziona in NF4.
DEFAULT_NF4_MIN_FREE_GIB = 10.5
DEFAULT_BF16_MIN_FREE_GIB = 20.0     # = ModelSpec.bf16_min_free_gb del motore storico

# Sequenze parallele del motore GGUF e contesto per sequenza (prompt ~150 token + risposta max 160).
DEFAULT_N_PARALLEL = 4
DEFAULT_CTX_PER_SEQ = 512

BACKENDS = ('cuda', 'rocm', 'vulkan', 'cpu')


@dataclass(frozen=True)
class PathChoice:
    """kind: bf16 | nf4 | gguf | nllb. quant: solo per gguf. reason: codice stabile (per i test e i log)."""
    kind: str
    quant: Optional[str] = None
    reason: str = ''
    need_gib: Optional[float] = None

    @property
    def label(self) -> str:
        return f'{GGUF}:{self.quant}' if self.kind == GGUF else self.kind


def gguf_need_gib(quant: str, n_parallel: int = DEFAULT_N_PARALLEL, ctx_per_seq: int = DEFAULT_CTX_PER_SEQ) -> float:
    """VRAM (GiB) che serve per tenere tutto su GPU: pesi + KV cache di n_parallel x ctx_per_seq token + buffer."""
    w = QUANT_WEIGHTS_GIB[quant]
    return (w + max(1, n_parallel) * max(1, ctx_per_seq) * KV_GIB_PER_TOKEN + COMPUTE_BUFFER_GIB
            + SAFETY_MARGIN_GIB)


def normalize_quant(name: Optional[str]) -> str:
    """'q3_k_m' -> 'Q3_K_M'; 'auto', vuoto o None -> 'auto'."""
    s = str(name or '').strip().upper()
    return 'auto' if s in ('', 'AUTO') else s


def choose_translator_path(free_gib: Optional[float], backend: str, *,
                           gguf_available: Iterable[str] = (),
                           quant: str = 'auto',
                           bf16_min_free_gib: float = DEFAULT_BF16_MIN_FREE_GIB,
                           nf4_min_free_gib: float = DEFAULT_NF4_MIN_FREE_GIB,
                           n_parallel: int = DEFAULT_N_PARALLEL,
                           ctx_per_seq: int = DEFAULT_CTX_PER_SEQ) -> PathChoice:
    """Percorso da usare. `free_gib` None o <= 0 (VRAM sconosciuta/nessuna GPU) -> nllb.

    `gguf_available`: quantizzazioni di cui esiste il file (es. ['Q3_K_M', 'IQ3_M']).
    `quant`: 'auto' = la migliore che entra; un nome = SOLO quella (se manca o non entra -> nllb, mai un'altra in silenzio).
    """
    b = (backend or 'cpu').lower()
    if b not in BACKENDS:
        b = 'cpu'
    if not free_gib or free_gib <= 0 or b == 'cpu':
        return PathChoice(NLLB, reason='no_gpu')
    if b in ('cuda', 'rocm') and free_gib >= bf16_min_free_gib:
        return PathChoice(BF16, reason='vram_bf16')
    if b == 'cuda' and free_gib >= nf4_min_free_gib:
        return PathChoice(NF4, reason='vram_nf4')

    wanted = normalize_quant(quant)
    present = {normalize_quant(q) for q in gguf_available}
    candidates = [q for q in QUANT_PREFERENCE if q in present]
    if wanted != 'auto':
        if wanted not in QUANT_WEIGHTS_GIB:
            return PathChoice(NLLB, reason='quant_unknown')
        candidates = [wanted] if wanted in present else []
    if not candidates:
        return PathChoice(NLLB, reason='gguf_missing')
    for q in candidates:
        need = gguf_need_gib(q, n_parallel, ctx_per_seq)
        if need <= free_gib:
            return PathChoice(GGUF, quant=q, reason='vram_gguf', need_gib=need)
    return PathChoice(NLLB, reason='vram_too_low',
                      need_gib=min(gguf_need_gib(q, n_parallel, ctx_per_seq) for q in candidates))
