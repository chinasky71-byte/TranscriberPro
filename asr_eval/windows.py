"""
Scelta delle finestre (solo dal riferimento: nessun criterio usa l'output
dei motori), inviluppo RMS e stima dello sfasamento audio/sottotitoli.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import normalize as nz

FRAME_S = 0.05


def pause_points(cues: Sequence[Dict], min_pause: float) -> List[float]:
    """Punti medi delle pause >= min_pause fra zone coperte da battute."""
    iv = sorted((c['s'], c['e']) for c in cues)
    merged: List[List[float]] = []
    for s, e in iv:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    pts = []
    for a, b in zip(merged, merged[1:]):
        if b[0] - a[1] >= min_pause:
            pts.append(0.5 * (a[1] + b[0]))
    return pts


def window_stats(cues: Sequence[Dict], lang: str) -> Dict:
    n = len(cues)
    words = sum(len(nz.normalize_text(c['text'], lang)) for c in cues if not c.get('music'))
    return {
        'n_cues': n, 'n_words': words,
        'music_frac': sum(1 for c in cues if c.get('music')) / n if n else 0.0,
        'sound_frac': sum(1 for c in cues if c.get('sound_only')) / n if n else 0.0,
        'italic_frac': sum(1 for c in cues if c.get('italic')) / n if n else 0.0,
    }


def window_valid(st: Dict, rules: Dict) -> bool:
    return (st['n_words'] >= rules['min_ref_words'] and st['music_frac'] <= rules['max_music_frac']
            and st['sound_frac'] <= rules['max_sound_frac'] and st['italic_frac'] <= rules['max_italic_frac'])


def cues_inside(cues: Sequence[Dict], t0: float, t1: float) -> List[Dict]:
    return [c for c in cues if c['s'] >= t0 and c['e'] <= t1]


def candidate_windows(cues: Sequence[Dict], rules: Dict) -> List[Tuple[float, float]]:
    pts = pause_points(cues, rules['min_pause_s'])
    lo, hi = rules['target_s'] - rules['tol_s'], rules['target_s'] + rules['tol_s']
    out = []
    for i, a in enumerate(pts):
        best = None
        for b in pts[i + 1:]:
            d = b - a
            if d > hi:
                break
            if d >= lo and (best is None or abs(d - rules['target_s']) < abs(best - a - rules['target_s'])):
                best = b
        if best is not None:
            out.append((a, best))
    return out


def select_windows(cues: Sequence[Dict], duration: float, lang: str, rules: Dict,
                   seed_key: str, n_extra: int = 0) -> List[Dict]:
    """Una finestra valida per fascia (10 fasce fra 4% e 94% della durata),
    scelta a caso con seme fisso; n_extra finestre in piu' (ruolo 'dev')
    scelte fra le valide rimaste, senza sovrapposizioni."""
    rng = random.Random(f"{rules['seed']}:{seed_key}:{lang}")
    r0, r1 = rules['range']
    a0, a1 = r0 * duration, r1 * duration
    band_w = (a1 - a0) / rules['n_bands']
    cands = []
    for t0, t1 in candidate_windows(cues, rules):
        if t0 < a0 or t1 > a1:
            continue
        inside = cues_inside(cues, t0, t1)
        st = window_stats(inside, lang)
        if window_valid(st, rules):
            cands.append({'t0': round(t0, 3), 't1': round(t1, 3), 'band': int((t0 - a0) // band_w), **st})
    chosen: List[Dict] = []

    def free(c):
        return all(c['t1'] <= w['t0'] or c['t0'] >= w['t1'] for w in chosen)

    for band in range(rules['n_bands']):
        pool = [c for c in cands if c['band'] == band and free(c)]
        if pool:
            w = dict(rng.choice(pool), role='test')
            chosen.append(w)
    rest = [c for c in cands if free(c)]
    rng.shuffle(rest)
    extra = []
    for c in rest:
        if len(extra) >= n_extra:
            break
        if free(c):
            w = dict(c, role='dev')
            chosen.append(w)
            extra.append(w)
    chosen.sort(key=lambda w: w['t0'])
    return chosen


# ── energia e sfasamento ───────────────────────────────────────────────────

def rms_db_from_array(y: np.ndarray, sr: int, frame_s: float = FRAME_S) -> np.ndarray:
    hop = int(round(sr * frame_s))
    n = len(y) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    fr = y[:n * hop].astype(np.float64).reshape(n, hop)
    rms = np.sqrt(np.mean(fr * fr, axis=1))
    return (20 * np.log10(rms + 1e-10)).astype(np.float32)


def rms_db_from_wav(path: Path, frame_s: float = FRAME_S) -> np.ndarray:
    import soundfile as sf
    y, sr = sf.read(str(path), dtype='float32', always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return rms_db_from_array(y, sr, frame_s)


def speech_mask(rms_db: np.ndarray) -> np.ndarray:
    if len(rms_db) == 0:
        return np.zeros(0, dtype=bool)
    p95 = float(np.percentile(rms_db, 95))
    return rms_db > max(-50.0, p95 - 20.0)


def cue_mask(cues: Sequence[Dict], n: int, origin: float, frame_s: float = FRAME_S) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for c in cues:
        a = int(max(0, (c['s'] - origin) / frame_s))
        b = int(min(n, (c['e'] - origin) / frame_s + 1))
        if b > a:
            m[a:b] = True
    return m


def _phi(x: np.ndarray, y: np.ndarray) -> float:
    n11 = float(np.sum(x & y))
    n10 = float(np.sum(x & ~y))
    n01 = float(np.sum(~x & y))
    n00 = float(np.sum(~x & ~y))
    den = np.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    return (n11 * n00 - n10 * n01) / den if den > 0 else 0.0


def estimate_offset(items: Sequence[Tuple[np.ndarray, Sequence[Dict], float]], rules: Dict,
                    frame_s: float = FRAME_S) -> Dict:
    """items: (rms_db dell'audio, battute con tempi del film, tempo-film del
    primo campione audio). Convenzione: tempo_audio = tempo_sub + offset.
    Ritorna offset migliore, accordo phi (a quello e a offset 0)."""
    step = int(round(rules['step_s'] / frame_s))
    max_k = int(round(rules['search_s'] / frame_s))
    prepared = []
    for rms, cues, origin in items:
        sp = speech_mask(rms)
        cm = cue_mask(cues, len(rms), origin, frame_s)
        prepared.append((sp, cm))
    best = (-2.0, 0)
    phi0 = None
    scores = {}
    for k in range(-max_k, max_k + 1, max(1, step)):
        xs, ys = [], []
        for sp, cm in prepared:
            n = len(sp)
            if k >= 0:
                xs.append(cm[:n - k] if k else cm)
                ys.append(sp[k:])
            else:
                xs.append(cm[-k:])
                ys.append(sp[:n + k])
        x = np.concatenate(xs) if xs else np.zeros(0, bool)
        y = np.concatenate(ys) if ys else np.zeros(0, bool)
        ph = _phi(x, y)
        scores[k] = ph
        if k == 0:
            phi0 = ph
        if ph > best[0]:
            best = (ph, k)
    # Plateau: se le battute coprono piu' del parlato, piu' spostamenti hanno
    # lo stesso accordo; si prende il centro del tratto contiguo al massimo.
    ks = sorted(scores)
    i = ks.index(best[1])
    lo = hi = i
    while lo - 1 >= 0 and scores[ks[lo - 1]] >= best[0] - 0.002:
        lo -= 1
    while hi + 1 < len(ks) and scores[ks[hi + 1]] >= best[0] - 0.002:
        hi += 1
    off = float(ks[(lo + hi) // 2] * frame_s)
    return {'offset_s': round(off, 3), 'phi': round(float(best[0]), 4),
            'phi_at_zero': round(float(phi0 or 0.0), 4),
            'apply_s': round(off, 3) if abs(off) > rules['correct_if_abs_gt_s'] else 0.0,
            'ok': bool(best[0] >= rules['min_agreement'])}
