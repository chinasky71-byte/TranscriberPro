"""
Metriche del confronto A/B: chrF (sacrebleu se presente nel venv, altrimenti
implementazione propria equivalente a chrF classico: n-grammi di caratteri
1..6, beta 2, spazi ignorati) e metriche strutturali dei blocchi.

ATTENZIONE (memoria mt_film_bench_2026_08): chrF contro un'unica resa umana
premia la traduzione letterale e penalizza la condensazione. Qui confronta
DUE uscite dello STESSO motore sullo stesso riferimento, quindi il bias di
stile si cancella in buona parte nella differenza A-B; non e' comunque una
misura assoluta di qualita'.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence

CPL = 42
MAX_CHARS = 84
CPS_HIGH = 20.0


def _ngrams(s: str, n: int) -> Counter:
    s = ''.join(s.split())
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf_own(hyp: str, ref: str, order: int = 6, beta: float = 2.0) -> float:
    """chrF 0-100, media aritmetica di precisione e richiamo sugli ordini
    1..order con n-grammi presenti (come sacrebleu CHRF(word_order=0))."""
    precs, recs = [], []
    for n in range(1, order + 1):
        h, r = _ngrams(hyp, n), _ngrams(ref, n)
        if not h or not r:
            continue
        m = sum((h & r).values())
        precs.append(m / sum(h.values()))
        recs.append(m / sum(r.values()))
    if not precs:
        return 0.0
    p, r = sum(precs) / len(precs), sum(recs) / len(recs)
    if p + r == 0:
        return 0.0
    b2 = beta * beta
    return 100.0 * (1 + b2) * p * r / (b2 * p + r)


_SACRE = None


def chrf(hyp: str, ref: str) -> float:
    """chrF di una coppia (sentence-level). sacrebleu se disponibile."""
    global _SACRE
    if _SACRE is None:
        try:
            from sacrebleu.metrics import CHRF
            _SACRE = CHRF()
        except Exception:
            _SACRE = False
    if _SACRE:
        return float(_SACRE.sentence_score(hyp, [ref]).score)
    return chrf_own(hyp, ref)


def chrf_backend() -> str:
    chrf('a', 'a')
    return 'sacrebleu' if _SACRE else 'proprio'


def block_text(b) -> str:
    return ' '.join(str(b.get('text', '') if isinstance(b, dict) else b).split())


def structural(blocks: Sequence[Dict], merged_positions: Optional[set] = None) -> Dict:
    """Metriche strutturali su una lista di blocchi {start, end, text, [drop]}.

    Se merged_positions e' dato, i conteggi 'in_units' si restringono ai
    blocchi che appartengono a unita' fuse (dove A e B possono differire).
    """
    def one(bs):
        n = len(bs)
        empty = sum(1 for b in bs if not block_text(b) and not b.get('drop'))
        dropped = sum(1 for b in bs if b.get('drop'))
        over84 = sum(1 for b in bs if len(block_text(b)) > MAX_CHARS)
        over_cpl = sum(1 for b in bs if any(len(l) > CPL for l in str(b.get('text', '')).split('\n')))
        over_lines = sum(1 for b in bs if len([l for l in str(b.get('text', '')).split('\n') if l.strip()]) > 2)
        cps = []
        for b in bs:
            d = float(b['end']) - float(b['start'])
            t = block_text(b)
            if d > 0 and t:
                cps.append(len(t) / d)
        high = sum(1 for c in cps if c > CPS_HIGH)
        return {'n': n, 'empty': empty, 'dropped': dropped, 'over84': over84, 'over_cpl': over_cpl,
                'over_lines': over_lines, 'cps_high': high,
                'cps_mean': (sum(cps) / len(cps)) if cps else None}
    out = one(list(blocks))
    if merged_positions is not None:
        sub = [b for i, b in enumerate(blocks) if i in merged_positions]
        out['in_units'] = one(sub)
    return out


def imbalance(resplit_report: Dict) -> Dict:
    """Distribuzione dello scostamento di proporzione ai tagli (|frazione IT -
    frazione EN|): proxy delle parole spostate oltre il confine audio."""
    devs = sorted(resplit_report.get('dev') or [])
    if not devs:
        return {'n_cuts': 0, 'mean': None, 'p50': None, 'p90': None, 'max': None}
    q = lambda p: devs[min(len(devs) - 1, int(p * (len(devs) - 1) + 0.5))]
    return {'n_cuts': len(devs), 'mean': sum(devs) / len(devs), 'p50': q(0.5), 'p90': q(0.9), 'max': devs[-1]}


def untranslated_units(src: Dict[int, str], out: Dict[int, str]) -> List[int]:
    """Unita' la cui uscita e' identica (normalizzata) alla sorgente inglese:
    stessa regola di BaseTranslator._is_untranslated (>=5 caratteri
    normalizzati e >=2 parole), copiata perche' translator.py importa torch."""
    import re
    norm = re.compile(r'[^0-9a-zàèéìòóù]')      # = BaseTranslator._AUDIT_NORM_RE
    word = re.compile(r'[A-Za-zÀ-ÿ]+')
    bad = []
    for k, s in src.items():
        ns = norm.sub('', (s or '').lower())
        if len(ns) < 5 or len(word.findall(s or '')) < 2:
            continue
        if norm.sub('', (out.get(k) or '').lower()) == ns:
            bad.append(k)
    return sorted(bad)
