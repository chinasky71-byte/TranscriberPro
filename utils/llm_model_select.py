# -*- coding: utf-8 -*-
"""Scelta del GGUF Qwen2.5-Instruct (14B o 7B) in base alla VRAM della GPU.

Modulo PURO: solo libreria standard, niente torch. La VRAM si legge con utils.gpu_detect (nvidia-smi/NVML per NVIDIA,
sysfs/rocm-smi per AMD su Linux, registro di Windows; vedi le regole del backend in quel modulo).
Serve solo come RIPIEGO: chi ha gia' un percorso modello configurato (e il file esiste)
non passa di qui (vedi Config.resolve_llm_model).

Stime VRAM (Q4_K_M, contesto 4096, n_batch 512):
  - 14B: pesi ~9,0 GB (48 layer, ~190 MiB/layer) + KV cache ~0,8 GB + buffer di calcolo/CUDA
         ~1,0-1,5 GB  => ~11 GB totali con offload completo.
  - 7B : pesi ~4,7 GB (28 layer, ~170 MiB/layer) + KV cache ~0,25 GB + buffer ~0,8 GB
         => ~5,8 GB totali con offload completo.
Le schede "da 12 GB" riportano 12282-12288 MiB, le "da 8 GB" ~8188 MiB, le "da 6 GB" ~6144 MiB,
le "da 11 GB" 11264 MiB.
"""
import re
from pathlib import Path
from typing import Optional, Tuple

# Soglie (MiB di VRAM totale) per l'offload COMPLETO (n_gpu_layers = -1).
VRAM_FULL_14B_MIB = 12000   # >= : 14B tutto su GPU (le 12 GB reali superano la soglia; le 11 GB no)
VRAM_FULL_7B_MIB = 6000     # >= : 7B tutto su GPU (6 GB giusti: unico margine, e' il minimo dichiarato)

# Layer e ingombro per layer (MiB) per l'offload PARZIALE sotto soglia.
RESERVE_MIB = 1500          # KV cache + buffer di calcolo + desktop: sottratti prima di contare i layer
MODELS = {
    '14b': {'glob': 'qwen2.5-14b-instruct-q4_k_m*.gguf', 'layers': 48, 'layer_mib': 190},
    '7b': {'glob': 'qwen2.5-7b-instruct-q4_k_m*.gguf', 'layers': 28, 'layer_mib': 170},
}

# Preferenza: 'auto' = soglie VRAM; 'fast' = 7B se c'e' (anche con molta VRAM); 'quality' = 14B se c'e' e la VRAM lo regge.
PREFERENCES = ('auto', 'fast', 'quality')

# Interruttore interno: con False 'fast' si comporta come 'auto'. Da accendere solo dopo le misure di tempo.
FAST_MODE_ENABLED = False


def detect_vram_mib() -> Optional[int]:
    """VRAM totale (MiB) della GPU NVIDIA piu' grande con driver funzionante (gpu_detect.usable_vram_mib con
    backend='cuda', vedi il commento sotto); None se nessuna GPU CUDA, errore o timeout. Con nvidia-smi che risponde e'
    lo stesso valore di sempre: il massimo di `nvidia-smi --query-gpu=memory.total`. Unica differenza voluta: se
    nvidia-smi risponde ma riporta [N/A] per memory.total, si usa la VRAM del registro di Windows / sysfs della stessa
    GPU, quindi il valore puo' essere noto dove prima era None. Le GPU AMD/Intel NON contano (None)."""
    try:
        from .gpu_detect import detect_gpus, usable_vram_mib
        # backend='cuda' (decisione del 22/10): il llama-cpp-python installato e' la ruota CUDA o la CPU; finche' non esiste una
        # ruota Vulkan/HIP supportata dall'installer, contare la VRAM di una GPU AMD/Intel sceglierebbe il 14B con n_gpu_layers=-1
        # su un llama che gira comunque su CPU (piu' lento, il doppio della RAM). Quando arrivera' il backend Vulkan/ROCm si
        # passa a usable_vram_mib(rep) (backend consigliato).
        return usable_vram_mib(detect_gpus(), backend='cuda')
    except Exception:
        return None


def _find_gguf(models_dir, pattern: str) -> Optional[str]:
    """Primo shard (o file singolo) del modello, solo se TUTTI gli shard dichiarati ('-N-of-M') esistono."""
    try:
        d = Path(models_dir)
        files = sorted(d.glob(pattern))
    except Exception:
        return None
    for f in files:
        m = re.search(r'-(\d+)-of-(\d+)\.gguf$', f.name)
        if m:
            if int(m.group(1)) != 1:
                continue
            total = int(m.group(2))
            if all(any(True for _ in d.glob(f.name[:m.start()] + f'-{i:05d}-of-{total:05d}.gguf'))
                   for i in range(1, total + 1)):
                return str(f)
        elif f.suffix == '.gguf':
            return str(f)
    return None


def gpu_layers_for(kind: str, vram_mib: Optional[int]) -> int:
    """n_gpu_layers per llama.cpp: -1 = tutto su GPU, 0 = CPU, N = offload parziale."""
    if not vram_mib or vram_mib <= 0:
        return 0
    full = VRAM_FULL_14B_MIB if kind == '14b' else VRAM_FULL_7B_MIB
    if vram_mib >= full:
        return -1
    spec = MODELS[kind]
    n = int((vram_mib - RESERVE_MIB) // spec['layer_mib'])
    return max(0, min(n, spec['layers'] - 1))


def pick_qwen_model(models_dir, vram_mib: Optional[int],
                    preference: str = 'auto') -> Tuple[Optional[str], int]:
    """(percorso GGUF, n_gpu_layers) oppure (None, 0) se non c'e' nessun Qwen2.5 in models_dir.

    - VRAM >= VRAM_FULL_14B_MIB e 14B presente -> 14B, tutto su GPU.
    - altrimenti, 7B presente -> 7B (tutto su GPU se VRAM >= VRAM_FULL_7B_MIB, parziale/CPU sotto).
    - 7B assente ma 14B presente -> 14B con offload parziale/CPU calcolato sulla VRAM.
    - preference='fast' (solo se FAST_MODE_ENABLED, altrimenti come 'auto'): 7B se presente, altrimenti 14B (offload secondo VRAM). 'auto' e 'quality' coincidono
      (14B solo se la VRAM lo regge, altrimenti 7B); valore sconosciuto -> 'auto'.
    - VRAM None/0 (nessuna GPU) -> stesso modello scelto sopra con n_gpu_layers=0 (CPU).
    """
    p14 = _find_gguf(models_dir, MODELS['14b']['glob'])
    p7 = _find_gguf(models_dir, MODELS['7b']['glob'])
    if preference == 'fast' and FAST_MODE_ENABLED and p7:
        return p7, gpu_layers_for('7b', vram_mib)
    big_enough = bool(vram_mib) and vram_mib >= VRAM_FULL_14B_MIB
    if p14 and big_enough:
        return p14, -1
    if p7:
        return p7, gpu_layers_for('7b', vram_mib)
    if p14:
        return p14, gpu_layers_for('14b', vram_mib)
    return None, 0
