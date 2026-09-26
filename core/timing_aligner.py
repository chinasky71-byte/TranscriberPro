# -*- coding: utf-8 -*-
"""
Allineamento temporale di un SRT sfasato su una traccia di riferimento — SOLO tempi, nessun LLM.
File: core/timing_aligner.py

Il riferimento (sottotitoli inglesi incorporati o segmenti Whisper) e l'SRT da correggere raccontano gli stessi
dialoghi, quindi le loro "maschere di parlato" (1 dove qualcuno parla, 0 altrove) combaciano una volta trovata la
trasformazione giusta. Si stima:
  1. GLOBALE: scala + offset. Correlazione incrociata (FFT) delle maschere, per una serie di rapporti di framerate
     noti (25/23,976 ...) e poi una scala fine. Copre offset costanti, deriva lineare e cambi di framerate.
  2. A TRATTI: un offset per ogni battuta con Viterbi (costo fisso per cambiare offset, cambi all'indietro vietati
     oltre il vuoto fra due battute: l'ordine delle battute non puo' invertirsi). Copre tagli, pubblicita', versioni
     con scene aggiunte o tolte.
Durate e pause interne dell'SRT restano invariate (a meno della scala): cambia solo dove il file "atterra".
Nessuna dipendenza da Qt, torch o GPU: solo numpy; secondi per un episodio.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

DT = 0.05  # risoluzione delle maschere (s)
FPS_RATIOS = (1.0, 25 / 23.976, 23.976 / 25, 24 / 23.976, 23.976 / 24, 25 / 24, 24 / 25)
Interval = Tuple[float, float]


@dataclass
class AlignResult:
    """new_intervals[i] = (start, end) corretti della battuta i (stesso ordine dell'input)."""
    new_intervals: List[Interval]
    scale: float
    offset: float                      # offset globale (s) dopo la scala
    piece_offsets: List[float]         # offset a tratti per battuta (s), da sommare al globale
    n_pieces: int
    coverage: List[float]              # frazione di ciascuna battuta coperta dal parlato di riferimento (0..1)
    mean_coverage: float
    low_coverage: int                  # battute con copertura < 0.2 (foreign dialogue, canzoni, o matching dubbio)
    density: float = 0.0               # quota della finestra dell'SRT occupata dal parlato di riferimento (copertura "per caso")
    lift: float = 0.0                  # (copertura - densita') / (1 - densita'): 1 = perfetta, ~0 = come a caso
    notes: List[str] = field(default_factory=list)


def _mask(intervals: Sequence[Interval], n: int) -> np.ndarray:
    m = np.zeros(n)
    for a, b in intervals:
        i, j = int(round(a / DT)), int(round(b / DT))
        if j > 0 and i < n:
            m[max(i, 0):min(j, n)] = 1.0
    return m


def _best_offset(intervals: Sequence[Interval], ref_fft, size: int, n: int, maxlag: float) -> Tuple[float, float]:
    """Offset (s) che massimizza la sovrapposizione delle battute con la maschera di riferimento, e il punteggio."""
    m = _mask(intervals, n)
    cc = np.fft.irfft(ref_fft * np.conj(np.fft.rfft(m, size)), size)
    lags = np.arange(-int(maxlag / DT), int(maxlag / DT) + 1)
    vals = cc[lags % size]
    k = int(np.argmax(vals))
    return float(lags[k] * DT), float(vals[k])


def _global_fit(ext: Sequence[Interval], ref_fft, size: int, n: int, maxlag: float) -> Tuple[float, float, float]:
    best = (-1.0, 1.0, 0.0)
    for r in FPS_RATIOS:
        off, sc = _best_offset([(a * r, b * r) for a, b in ext], ref_fft, size, n, maxlag)
        if sc > best[0]:
            best = (sc, r, off)
    r0 = best[1]
    for r in r0 * (1 + np.arange(-0.002, 0.00201, 0.0001)):
        off, sc = _best_offset([(a * r, b * r) for a, b in ext], ref_fft, size, n, maxlag)
        if sc > best[0]:
            best = (sc, float(r), off)
    return best[1], best[2], best[0]


def _piecewise(ext: Sequence[Interval], ref_mask: np.ndarray, span: float, step: float, lam: float, tol: float,
               center: Optional[np.ndarray] = None, band: float = 1.0) -> Tuple[np.ndarray, float]:
    """Viterbi su offset discreti per battuta. Ricompensa = secondi di battuta sovrapposti al parlato di riferimento;
    cambiare offset costa `lam`; un cambio all'indietro e' ammesso solo fino alla pausa fra le due battute (+tol)."""
    offs = np.arange(-span, span + 1e-9, step)
    K, N = len(offs), len(ext)
    n = len(ref_mask)
    cs = np.concatenate([[0.0], np.cumsum(ref_mask)]) * DT
    reward = np.empty((N, K))
    for i, (a, b) in enumerate(ext):
        s = np.clip(np.round((a + offs) / DT).astype(int), 0, n)
        e = np.clip(np.round((b + offs) / DT).astype(int), 0, n)
        reward[i] = cs[e] - cs[s]
        if center is not None:                       # raffinamento: solo entro +-band dal percorso grossolano
            reward[i][np.abs(offs - center[i]) > band + 1e-9] = -1e6
    score = reward[0].copy()
    back = np.empty((N, K), dtype=np.int32)
    ar = np.arange(K)
    for i in range(1, N):
        gap = max(0.0, ext[i][0] - ext[i - 1][1]) + tol
        allowed = np.searchsorted(offs, offs + gap, side='right') - 1   # a <= b + gap
        pm = np.maximum.accumulate(score)
        am = np.maximum.accumulate(np.where(score >= pm, ar, 0))   # indice del massimo del prefisso
        move = pm[allowed] - lam
        use_move = move > score
        back[i] = np.where(use_move, am[allowed], ar)
        score = np.where(use_move, move, score) + reward[i]
    k = int(np.argmax(score))
    best_score = float(score[k])
    path = np.empty(N, dtype=np.int32)
    path[-1] = k
    for i in range(N - 1, 0, -1):
        k = back[i][k]
        path[i - 1] = k
    return offs[path], best_score


def _coverage(intervals: Sequence[Interval], cs: np.ndarray, n: int) -> List[float]:
    out = []
    for a, b in intervals:
        i, j = int(round(a / DT)), int(round(b / DT))
        i, j = min(max(i, 0), n), min(max(j, 0), n)
        out.append(float((cs[j] - cs[i]) / max(b - a, DT)))
    return out


def align(ext_intervals: Sequence[Interval], ref_intervals: Sequence[Interval], *, max_global_offset: float = 600.0,
          piece_span: float = 300.0, coarse_step: float = 0.4, piece_step: float = 0.1, switch_cost: float = 6.0, order_tol: float = 0.5,
          log: Optional[Callable[[str], None]] = None) -> Optional[AlignResult]:
    """Stima le nuove posizioni delle battute `ext_intervals` (ordinate nel tempo) rispetto a `ref_intervals`.
    Ritorna None se manca materiale (nessuna battuta o riferimento vuoto)."""
    ext = [(float(a), float(b)) for a, b in ext_intervals]
    ref = [(float(a), float(b)) for a, b in ref_intervals if b > a]
    if not ext or not ref:
        return None
    end = max(max(b for _, b in ref), max(b for _, b in ext) * 1.05) + max_global_offset + 60.0
    n = int(end / DT)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    ref_mask = _mask(ref, n)
    ref_fft = np.fft.rfft(ref_mask, size)

    scale0, offset0, _ = _global_fit(ext, ref_fft, size, n, max_global_offset)
    # La scala globale, con offset che cambiano a tratti, puo' essere un compromesso ("a scalini" per inseguire un salto).
    # Si riprovano scale vicine con un Viterbi GROSSOLANO (finestra ampia: gli offset cumulati di piu' salti possono
    # superare di molto l'offset globale) e si tiene la scala col punteggio migliore; quella globale resta preferita
    # salvo un miglioramento netto. Poi un Viterbi FINE entro +-1 s dal percorso grossolano.
    best = None
    for k in (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6):
        sc = scale0 * (1 + k * 0.0004)
        off = offset0 if k == 0 else _best_offset([(a * sc, b * sc) for a, b in ext], ref_fft, size, n, max_global_offset)[0]
        g_k = [(a * sc + off, b * sc + off) for a, b in ext]
        per_k, val = _piecewise(g_k, ref_mask, piece_span, coarse_step, switch_cost, order_tol)
        if best is None or val > best[0] + switch_cost / 2:
            best = (val, sc, off, g_k, per_k)
    _, scale, offset, g, coarse = best
    notes = []
    if float(np.max(np.abs(coarse))) >= piece_span - 2 * coarse_step:
        notes.append("offset a tratti al limite della finestra: possibile allineamento incompleto")
    fine_span = float(np.max(np.abs(coarse))) + 2.0
    per, _ = _piecewise(g, ref_mask, fine_span, piece_step, switch_cost, order_tol, center=coarse, band=1.0)
    cs = np.concatenate([[0.0], np.cumsum(ref_mask)]) * DT
    new = [(a + o, b + o) for (a, b), o in zip(g, per)]
    cov = _coverage(new, cs, n)
    lo_t = max(0, int(min(a for a, _ in new) / DT))
    hi_t = min(n, int(max(b for _, b in new) / DT))
    density = float(min(0.95, ref_mask[lo_t:hi_t].mean())) if hi_t > lo_t else 0.0
    mean_cov = float(np.mean(cov))
    lift = (mean_cov - density) / (1.0 - density)
    changes = int(np.count_nonzero(np.abs(np.diff(per)) > 1e-6))
    if abs(scale - 1.0) > 1e-4:
        notes.append(f"scala {scale:.5f}")
    res = AlignResult(new, scale, offset, [float(x) for x in per], changes + 1, cov, float(np.mean(cov)),
                      int(sum(c < 0.2 for c in cov)), density=density, lift=lift, notes=notes)
    if log:
        log(f"  Allineamento globale: scala {scale:.5f}, offset {offset:+.2f} s; tratti con offset diverso: {res.n_pieces}; "
            f"copertura media del parlato {res.mean_coverage:.0%} (a caso: {res.density:.0%}, indice {res.lift:.2f}); battute con poca copertura: {res.low_coverage}/{len(ext)}.")
    return res
