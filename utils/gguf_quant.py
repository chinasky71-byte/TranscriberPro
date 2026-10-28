# -*- coding: utf-8 -*-
"""Contabilita' della VRAM delle quantizzazioni GGUF di TranslateGemma-12B.

Modulo PURO: solo libreria standard, niente torch, niente llama_cpp, nessuna
lettura della GPU. Chi chiama passa i numeri (l'installer, il preflight, il
traduttore).

ADR-009 ha lasciato un solo motore di traduzione, TranslateGemma-12B GGUF:
non c'e' piu' un percorso da SCEGLIERE (bf16 / NF4 / GGUF / NLLB) e quindi non
c'e' piu' un selettore. Restano due domande, e questo modulo risponde a
entrambe:

  1. quanta VRAM serve per una data quantizzazione, con n_parallel sequenze di
     contesto (`gguf_need_gib`) — la usano il preflight del job e l'installer;
  2. qual e' il nome canonico di una quantizzazione scritta a mano in config
     (`normalize_quant`).

I numeri sono MISURATI sui file veri del 12B (banco di fase 3, RTX 3060 12 GB,
4 sequenze x 512 token): pesi 6,80 / 5,60 / 5,27 GiB per Q4_K_M / Q3_K_M /
IQ3_M; picco di VRAM del processo (oltre la base di 649 MiB gia' occupata)
8.528 / 7.277 / 6.807 MiB = 8,33 / 7,11 / 6,65 GiB. Lo scarto fra picco e
(pesi + KV 0,75 GiB) e' 0,78 / 0,76 / 0,63 GiB: COMPUTE_BUFFER_GIB lo copre.
SAFETY_MARGIN_GIB e' una scelta, non una misura.
"""

QUANT_PREFERENCE = ('Q4_K_M', 'Q3_K_M', 'IQ3_M')

# Dimensione dei pesi (GiB) per quantizzazione: MISURATA sui file veri del 12B.
QUANT_WEIGHTS_GIB = {'Q4_K_M': 6.80, 'Q3_K_M': 5.60, 'IQ3_M': 5.27}

# Quantizzazione di default quando la config non dice niente (o dice 'auto',
# che era il vecchio valore: la scelta automatica non esiste piu').
DEFAULT_QUANT = 'Q4_K_M'

# KV cache di Gemma3-12B in f16: 48 layer x 8 teste KV x 256 dim x 2 (K,V) x
# 2 byte = ~0,375 MiB per token (limite superiore: gli strati a finestra
# locale ne usano meno).
KV_GIB_PER_TOKEN = 0.375 / 1024
# Buffer di calcolo di llama.cpp + contesto CUDA: 0,8 GiB, scarto MISURATO fra
# il picco del banco e pesi + KV (0,78 / 0,76 / 0,63 GiB).
COMPUTE_BUFFER_GIB = 0.8
# Margine fisso sopra il picco misurato (altri driver/schede, n_parallel
# diversi). Su WDDM uno sconfinamento in RAM di sistema non da' errore: solo
# 4-5 volte piu' lento.
SAFETY_MARGIN_GIB = 0.4

# Sequenze parallele del motore GGUF e contesto per sequenza (prompt ~150 token
# + risposta max 160). Regolano la KV cache, cioe' il picco di VRAM.
DEFAULT_N_PARALLEL = 4
DEFAULT_CTX_PER_SEQ = 512


def gguf_need_gib(quant: str, n_parallel: int = DEFAULT_N_PARALLEL,
                  ctx_per_seq: int = DEFAULT_CTX_PER_SEQ) -> float:
    """VRAM (GiB) per tenere tutto su GPU: pesi + KV cache di n_parallel x
    ctx_per_seq token + buffer + margine."""
    w = QUANT_WEIGHTS_GIB[normalize_quant(quant)]
    return (w + max(1, n_parallel) * max(1, ctx_per_seq) * KV_GIB_PER_TOKEN
            + COMPUTE_BUFFER_GIB + SAFETY_MARGIN_GIB)


def normalize_quant(name) -> str:
    """Nome canonico di una quantizzazione: 'q4_k_m' -> 'Q4_K_M'.

    Vuoto, None e i vecchi 'auto' diventano DEFAULT_QUANT: la scelta automatica
    per VRAM e' stata rimossa con ADR-009, e una config che la chiede non deve
    impedire il caricamento. Un nome sconosciuto solleva ValueError con
    l'elenco degli ammessi: un errore di battitura in config si vede subito,
    invece di scaricare la quantizzazione sbagliata in silenzio.
    """
    s = str(name or '').strip().upper()
    if not s or s == 'AUTO':
        return DEFAULT_QUANT
    if s not in QUANT_WEIGHTS_GIB:
        raise ValueError(
            f"Quantizzazione GGUF sconosciuta: {name!r}. "
            f"Ammesse: {', '.join(QUANT_WEIGHTS_GIB)}")
    return s
