# -*- coding: utf-8 -*-
"""Etichetta della scheda video per l'interfaccia: nome del modello rilevato e fornitore (colore), oppure 'CPU only'.
Solo logica: il rilevamento vero e' in utils/gpu_detect.py (stdlib, nessuna dipendenza da Qt)."""
from typing import Optional, Tuple

CPU_ONLY = 'CPU only'


def _usable(g) -> bool:
    """GPU che l'app puo' usare: NVIDIA con CUDA; AMD con ROCm o Vulkan. Intel e le altre restano fuori (CPU)."""
    b = getattr(g, 'backends', None) or []
    if getattr(g, 'integrated', None) is True:      # APU/integrata: l'app lavora su CPU
        return False
    if g.vendor == 'nvidia':
        return 'cuda' in b
    if g.vendor == 'amd':
        return 'rocm' in b or 'vulkan' in b
    return False


def _short(name: str) -> str:
    n = ' '.join((name or '').replace('(TM)', '').replace('(R)', '').split())
    return n[:48].rstrip()


def looks_incomplete(report) -> bool:
    """True se il rilevamento sembra parziale (NVIDIA vista ma senza CUDA, es. nvidia-smi lento al primo avvio): conviene rifarlo."""
    try:
        return any(g.vendor == 'nvidia' and 'cuda' not in (g.backends or []) for g in report.gpus)
    except Exception:
        return False


def gpu_badge_info(report=None) -> Tuple[str, str]:
    """(testo, fornitore): fornitore 'nvidia' (verde) | 'amd' (rosso) | 'cpu'. Senza GPU compatibile: ('CPU only', 'cpu').
    Con piu' schede vince quella NVIDIA (poi AMD) con piu' VRAM. Mai eccezioni."""
    try:
        if report is None:
            from utils.gpu_detect import detect_gpus
            report = detect_gpus()
        cands = [g for g in report.gpus if _usable(g)]
        if not cands:
            return CPU_ONLY, 'cpu'
        best = sorted(cands, key=lambda g: (g.vendor == 'nvidia', g.vram_mib or 0), reverse=True)[0]
        name = _short(best.name) or ('NVIDIA GPU' if best.vendor == 'nvidia' else 'AMD GPU')
        return name, best.vendor
    except Exception:
        return CPU_ONLY, 'cpu'
