"""
Voto di lingua su più chunk per l'auto-detect (v1.34.31).
File: core/lang_vote.py

Problema (log di Franz, 25/10/2026): con lingua indefinita Qwen3-ASR sondava SOLO il primo chunk (musica,
silenzio o sigla → lingua vuota → "LID inconclusivo") e faster-whisper, in auto-detect, decideva la lingua
chunk per chunk loggando solo la prima ("nn"), con rischio di lingue diverse fra chunk. Qui: scelta di pochi
chunk sparsi lungo il file e voto pesato, per usare UNA lingua per tutto il file.

Modulo puro (solo stdlib): nessun torch/onnxruntime/PyQt6 (v. regola import di `utils`).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Quanti chunk sondare al massimo, e peso minimo (probabilità Whisper) perché un voto conti.
DEFAULT_PROBES = 5
MIN_VOTE_WEIGHT = 0.4
# Secondi di voce minimi perché un chunk valga la pena di essere sondato.
MIN_PROBE_VOICE_S = 3.0

# Whisper emette 'nn' (nynorsk) e 'no' (bokmål) per lo stesso parlato: si votano insieme e si usa 'no'.
# 'jw' è il vecchio codice Whisper del giavanese.
_ALIASES = {'nn': 'no', 'jw': 'jv'}


def normalize_iso(code: Optional[str]) -> Optional[str]:
    c = (code or '').strip().lower()
    return _ALIASES.get(c, c) or None


def spread_indices(n: int, k: int) -> List[int]:
    """Fino a k indici distinti in [0, n), distribuiti in modo uniforme (centri di k fasce uguali)."""
    if n <= 0 or k <= 0:
        return []
    k = min(k, n)
    return sorted({min(n - 1, int((i + 0.5) * n / k)) for i in range(k)})


def select_probe_chunks(paths: Sequence, k: int = DEFAULT_PROBES,
                        voice_s_fn: Optional[Callable[[object], float]] = None,
                        min_voice_s: float = MIN_PROBE_VOICE_S) -> List[int]:
    """Indici dei chunk da sondare: sparsi, preferendo quelli con voce (se voice_s_fn è dato).
    Se nessun chunk ha abbastanza voce, ricade sugli indici sparsi senza filtro."""
    n = len(paths)
    spread = spread_indices(n, k)
    if voice_s_fn is None:
        return spread
    cand = list(range(n)) if n <= k * 3 else spread_indices(n, k * 3)
    return _filter_voiced(paths, cand, voice_s_fn, min_voice_s, k) or spread


def _filter_voiced(paths, cand, voice_s_fn, min_voice_s, k) -> List[int]:
    ok = []
    for i in cand:
        try:
            if voice_s_fn(paths[i]) >= min_voice_s:
                ok.append(i)
        except Exception:
            continue
    return [ok[j] for j in spread_indices(len(ok), k)]


def vote(samples: Sequence[Tuple[Optional[str], float]],
         min_weight: float = MIN_VOTE_WEIGHT) -> Tuple[Optional[str], float]:
    """Lingua vincente = somma dei pesi maggiore. Ignora vuoti e pesi < min_weight.
    Ritorna (iso, quota dei pesi validi) oppure (None, 0.0) se nessun voto è valido."""
    tot: Dict[str, float] = defaultdict(float)
    for lang, w in samples:
        iso = normalize_iso(lang)
        if iso and w >= min_weight:
            tot[iso] += w
    if not tot:
        return None, 0.0
    best = max(tot.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0], best[1] / sum(tot.values())
