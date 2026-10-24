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
  2. backend cuda, VRAM libera >= nf4_min_free_gb, e gguf_before_nf4 SPENTO -> nf4   (regola storica)
  3. backend cuda/rocm/vulkan, almeno un GGUF presente che ENTRA    -> gguf:<quant migliore che entra>
  4. backend cuda e VRAM libera >= nf4_min_free_gb (con gguf_before_nf4 acceso: nessun GGUF utilizzabile) -> nf4
  5. altrimenti                                                      -> nllb
`gguf_before_nf4` (default SPENTO, vedi DEFAULT_GGUF_BEFORE_NF4): spento = regola storica (NF4 prima del GGUF), provata uguale al
motore storico per VRAM libera >= 10,5 GiB; e' anche l'opzione per FORZARE NF4 senza una nuova versione. Acceso = il GGUF e'
preferito a NF4 sulle schede da 10-20 GiB (nel banco di fase 3 Q4_K_M e' non inferiore a NF4 con margine 3 punti e ~14 volte
piu' veloce): l'accensione di default richiede l'ok esplicito del proprietario (glossario misurato, prova reale su Windows).
Con la scelta automatica si considerano solo Q4_K_M (>= gguf_min_free_gib['Q4_K_M'], 10 GiB) e IQ3_M (>= 7,5 GiB): Q3_K_M,
piu' grande e non migliore di IQ3_M nel banco, resta selezionabile solo chiedendola per nome.
"Entra" = pesi del GGUF + ingombro di esecuzione (KV cache + buffer di calcolo) <= VRAM libera. Niente offload parziale:
un modello a meta' su GPU e meta' su CPU e' piu' lento di NLLB e non e' stato misurato.

PESI E INGOMBRI: dal banco di fase 3 (RTX 3060 12 GB, Windows, 4 sequenze x 512 token): pesi reali 6,80 / 5,60 / 5,27 GiB; picco di
VRAM del processo (oltre la base di 649 MiB gia' occupata) 8.528 / 7.277 / 6.807 MiB = 8,33 / 7,11 / 6,65 GiB. Lo scarto fra picco
e (pesi + KV 0,75 GiB) e' 0,78 / 0,76 / 0,63 GiB: COMPUTE_BUFFER_GIB lo copre. Il margine SAFETY_MARGIN_GIB e la soglia NF4
restano scelte (non misure). Una sola scheda e un solo driver: su 8 GB nessuna misura diretta.
"""
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

BF16 = 'bf16'
NF4 = 'nf4'
GGUF = 'gguf'
NLLB = 'nllb'

# Quantizzazioni riconosciute (nomi dei file GGUF e `quant` forzata) e quelle della scelta automatica, in ordine di preferenza
# (qualita' decrescente, ingombro decrescente): con quant='auto' si prende la prima che entra.
QUANT_PREFERENCE = ('Q4_K_M', 'Q3_K_M', 'IQ3_M')
AUTO_QUANTS = ('Q4_K_M', 'IQ3_M')

# Soglie minime di VRAM LIBERA (GiB) per quantizzazione, scelte dal proprietario in linea di principio partendo dal picco misurato
# (Q4_K_M +8,33 GiB, IQ3_M +6,65 GiB): sono un pavimento; vale il maggiore fra questo e l'ingombro stimato (che cresce con
# n_parallel). Configurabili. Una RTX 3060 da 12 GB con il desktop ha ~11,3 GiB liberi: cade su Q4_K_M.
DEFAULT_GGUF_MIN_FREE_GIB = {'Q4_K_M': 10.0, 'IQ3_M': 7.5}

# Dimensione dei pesi (GiB) per quantizzazione: MISURATA sui file veri del 12B (fase 2, `verify`).
QUANT_WEIGHTS_GIB = {'Q4_K_M': 6.80, 'Q3_K_M': 5.60, 'IQ3_M': 5.27}

# KV cache di Gemma3-12B in f16: 48 layer x 8 teste KV x 256 dim x 2 (K,V) x 2 byte = ~0,375 MiB per token (limite
# superiore: gli strati a finestra locale ne usano meno). Buffer di calcolo di llama.cpp + contesto CUDA: 0,8 GiB, scarto MISURATO
# fra il picco del banco e pesi + KV (0,78 / 0,76 / 0,63 GiB).
KV_GIB_PER_TOKEN = 0.375 / 1024
COMPUTE_BUFFER_GIB = 0.8
# Margine fisso sopra il picco misurato (altri driver/schede, n_parallel diversi). Su WDDM uno sconfinamento in RAM di sistema non da errore: solo 4-5 volte piu' lento.
SAFETY_MARGIN_GIB = 0.4

# Soglia NF4: il picco misurato a batch 12 e' 10.133 MiB = 9,9 GiB; a batch 16 (tetto attuale, il gestore adattivo parte da
# 12) 10.817 MiB = 10,56 GiB (mt_eval/vram_probe.py, commento in engine.py). 10,5 GiB LIBERI e' quindi una soglia
# prudente per il batch di partenza, non una garanzia al tetto. NON 12: una scheda "da 12 GB" ha 12,0 GiB TOTALI e ne ha sempre meno di liberi (desktop), quindi con
# 12 finirebbe sempre sul GGUF cambiando il comportamento di oggi, dove funziona in NF4.
DEFAULT_NF4_MIN_FREE_GIB = 10.5
DEFAULT_BF16_MIN_FREE_GIB = 20.0     # = ModelSpec.bf16_min_free_gb del motore storico
DEFAULT_GGUF_BEFORE_NF4 = False

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
                           gguf_before_nf4: bool = DEFAULT_GGUF_BEFORE_NF4,
                           gguf_min_free_gib: Optional[Mapping[str, float]] = None,
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
    nf4_fits = b == 'cuda' and free_gib >= nf4_min_free_gib
    if nf4_fits and not gguf_before_nf4:
        return PathChoice(NF4, reason='vram_nf4')

    floors = DEFAULT_GGUF_MIN_FREE_GIB if gguf_min_free_gib is None else gguf_min_free_gib

    def required(q):
        return max(gguf_need_gib(q, n_parallel, ctx_per_seq), floors.get(q, 0.0))

    wanted = normalize_quant(quant)
    present = {normalize_quant(q) for q in gguf_available}
    candidates = [q for q in AUTO_QUANTS if q in present]
    if wanted != 'auto':
        if wanted not in QUANT_WEIGHTS_GIB:
            return PathChoice(NLLB, reason='quant_unknown')
        candidates = [wanted] if wanted in present else []
    if not candidates:
        return PathChoice(NF4, reason='vram_nf4') if nf4_fits else PathChoice(NLLB, reason='gguf_missing')
    for q in candidates:
        need = required(q)
        if need <= free_gib:
            return PathChoice(GGUF, quant=q, reason='vram_gguf', need_gib=need)
    if nf4_fits:
        return PathChoice(NF4, reason='vram_nf4')        # nessun GGUF entra ma NF4 si': e' la strada storica
    return PathChoice(NLLB, reason='vram_too_low',
                      need_gib=min(required(q) for q in candidates))
