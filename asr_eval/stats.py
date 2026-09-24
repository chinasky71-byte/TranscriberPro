"""
Statistica del banco: WER per film, bootstrap a due livelli (film, poi
finestre), Wilcoxon esatto dei segni con ranghi (anche con ex aequo),
applicazione delle regole di decisione congelate.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

from decision_rules import DECISION_RULES

# films: {film: [(err_prod, err_ch, n_ref), ...]}  una tupla per finestra
Paired = Dict[str, List[Tuple[int, int, int]]]


def film_gain(wins: Sequence[Tuple[int, int, int]]) -> Optional[float]:
    n = sum(w[2] for w in wins)
    if n == 0:
        return None
    return (sum(w[0] for w in wins) - sum(w[1] for w in wins)) / n


def film_wer(wins: Sequence[Tuple[int, int]]) -> Optional[float]:
    n = sum(w[1] for w in wins)
    return sum(w[0] for w in wins) / n if n else None


def mean_gain(films: Paired) -> Optional[float]:
    gains = [g for g in (film_gain(w) for w in films.values()) if g is not None]
    return sum(gains) / len(gains) if gains else None


def bootstrap_gain(films: Paired, n_boot: int = 10_000, seed: int = 0,
                   level: float = 0.95) -> Tuple[Optional[float], Optional[float]]:
    """IC percentile del guadagno medio per film; ricampiona i film e poi le
    finestre dentro ciascun film estratto (appaiato fra i due motori)."""
    keys = [k for k, w in films.items() if w]
    if not keys:
        return None, None
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        gains = []
        for _k in range(len(keys)):
            wins = films[keys[rng.randrange(len(keys))]]
            sample = [wins[rng.randrange(len(wins))] for _ in range(len(wins))]
            g = film_gain(sample)
            if g is not None:
                gains.append(g)
        if gains:
            stats.append(sum(gains) / len(gains))
    stats.sort()
    a = (1 - level) / 2
    lo = stats[int(a * (len(stats) - 1))]
    hi = stats[int(round((1 - a) * (len(stats) - 1)))]
    return lo, hi


def _avg_ranks(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def wilcoxon_exact(x: Sequence[float]) -> Tuple[float, float, int]:
    """Test dei segni con ranghi, esatto, bilaterale. Zeri scartati (metodo
    di Wilcoxon). Ritorna (W+, p, n_effettivo)."""
    d = [float(v) for v in x if v != 0]
    n = len(d)
    if n == 0:
        return 0.0, 1.0, 0
    ranks = _avg_ranks([abs(v) for v in d])
    r2 = [int(round(2 * r)) for r in ranks]
    w2 = sum(r for r, v in zip(r2, d) if v > 0)
    total = sum(r2)
    dist = [0] * (total + 1)
    dist[0] = 1
    for r in r2:
        for s in range(total, r - 1, -1):
            dist[s] += dist[s - r]
    tot = 2 ** n
    p_le = sum(dist[:w2 + 1]) / tot
    p_ge = sum(dist[w2:]) / tot
    return w2 / 2, min(1.0, 2 * min(p_le, p_ge)), n


def min_p_wilcoxon(n: int) -> float:
    return min(1.0, 2 / 2 ** n) if n > 0 else 1.0


def guard_violations(prod: Dict, ch: Dict, rules: Dict = DECISION_RULES) -> List[str]:
    """prod/ch: {'halluc_per_h', 'missed_pct', 'names_pct'} aggregati sul gruppo."""
    out = []
    hp, hc = prod.get('halluc_per_h'), ch.get('halluc_per_h')
    if hp is not None and hc is not None:
        if hc > hp * (1 + rules['halluc_max_rel_increase']) and hc - hp > rules['halluc_max_abs_increase_per_h']:
            out.append(f"allucinazioni {hc:.2f}/h contro {hp:.2f}/h")
    mp, mc = prod.get('missed_pct'), ch.get('missed_pct')
    if mp is not None and mc is not None and mc - mp > rules['missed_max_increase_pts']:
        out.append(f"battute perse {mc:.2f}% contro {mp:.2f}%")
    np_, nc = prod.get('names_pct'), ch.get('names_pct')
    if np_ is not None and nc is not None and np_ - nc > rules['names_max_drop_pts']:
        out.append(f"nomi {nc:.2f}% contro {np_:.2f}%")
    return out


def decide_en(main: Paired, secondary: Paired, prod_guard: Dict, ch_guard: Dict,
              prod_wer_main: Optional[float], n_failed: int,
              rules: Dict = DECISION_RULES) -> Dict:
    res = {'n_films_main': len(main), 'n_films_secondary': len(secondary)}
    g = mean_gain(main)
    lo, hi = bootstrap_gain(main, rules['bootstrap_n'], rules['bootstrap_seed'], rules['ci_level'])
    w, p, n_eff = wilcoxon_exact([film_gain(v) for v in main.values() if film_gain(v) is not None])
    g2 = mean_gain(secondary)
    res.update(gain=g, ci_lo=lo, ci_hi=hi, wilcoxon_w=w, wilcoxon_p=p, wilcoxon_n=n_eff,
               wilcoxon_min_p=min_p_wilcoxon(n_eff), gain_secondary=g2)
    reasons = []
    if n_failed > rules['max_failed_windows']:
        res['verdict'] = 'NON_VALUTABILE'
        res['reasons'] = [f"{n_failed} finestre fallite: rilanciare il run"]
        return res
    if len(main) < rules['min_films_main_en']:
        res['verdict'] = 'INSUFFICIENTE'
        res['reasons'] = [f"solo {len(main)} film nel gruppo principale (< {rules['min_films_main_en']})"]
        return res
    if lo is None or lo <= 0:
        reasons.append("IC del guadagno non interamente sopra 0")
    rel = (g / prod_wer_main) if (g is not None and prod_wer_main) else None
    if g is None or not (g >= rules['min_gain_abs'] or (rel is not None and rel >= rules['min_gain_rel'])):
        reasons.append("vantaggio sotto 1,5 punti e sotto 10% relativo")
    reasons += guard_violations(prod_guard, ch_guard, rules)
    if rules['secondary_same_sign'] and (g2 is None or g is None or (g2 > 0) != (g > 0)):
        reasons.append("segno diverso (o assente) nel gruppo secondario")
    res['verdict'] = 'CAMBIO_PROPOSTO' if not reasons else 'PAREGGIO'
    res['reasons'] = reasons
    return res


def decide_it(films: Paired, origin: Dict[str, str], prod_guard: Dict, ch_guard: Dict,
              prod_wer: Optional[float], n_failed: int, rules: Dict = DECISION_RULES) -> Dict:
    res = {'n_films': len(films)}
    g = mean_gain(films)
    lo, hi = bootstrap_gain(films, rules['bootstrap_n'], rules['bootstrap_seed'], rules['ci_level'])
    gains = {k: film_gain(v) for k, v in films.items()}
    w, p, n_eff = wilcoxon_exact([x for x in gains.values() if x is not None])
    by_origin = {}
    for o in ('doppiato', 'nato_ita'):
        sub = {k: v for k, v in films.items() if origin.get(k) == o}
        by_origin[o] = mean_gain(sub)
    res.update(gain=g, ci_lo=lo, ci_hi=hi, wilcoxon_w=w, wilcoxon_p=p, wilcoxon_n=n_eff,
               wilcoxon_min_p=min_p_wilcoxon(n_eff), gain_by_origin=by_origin, gain_by_film=gains)
    if n_failed > rules['max_failed_windows']:
        res.update(verdict='NON_VALUTABILE', reasons=[f"{n_failed} finestre fallite: rilanciare il run"])
        return res
    reasons = guard_violations(prod_guard, ch_guard, rules)
    if len(films) >= rules['min_films_it']:
        if lo is None or lo <= 0:
            reasons.append("IC del guadagno non interamente sopra 0")
        rel = (g / prod_wer) if (g is not None and prod_wer) else None
        if g is None or not (g >= rules['min_gain_abs'] or (rel is not None and rel >= rules['min_gain_rel'])):
            reasons.append("vantaggio sotto 1,5 punti e sotto 10% relativo")
        res['verdict'] = 'CAMBIO_PROPOSTO' if not reasons else 'PAREGGIO'
    else:
        signs = [x > 0 for x in gains.values() if x is not None]
        origin_signs = [x > 0 for x in by_origin.values() if x is not None]
        coherent = bool(signs) and len(set(signs)) == 1 and len(origin_signs) == 2 \
            and len(set(origin_signs + signs)) == 1
        if not coherent:
            reasons.append("segno non uguale in ogni film e nei due gruppi (doppiati/nati in italiano)")
        res['verdict'] = ('INDICATIVO_SFIDANTE' if coherent and signs[0] and not reasons
                          else 'INDICATIVO_PRODUZIONE' if coherent and not signs[0]
                          else 'INDICATIVO_PAREGGIO')
        reasons.insert(0, f"solo {len(films)} film con riferimento verificato (< {rules['min_films_it']}): SOLO INDICATIVO")
    res['reasons'] = reasons
    return res
