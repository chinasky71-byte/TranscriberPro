"""
Metriche per finestra: allineamento Levenshtein a parole con backtrace
S/D/I, WER normalizzato, WERc, battute perse, allucinazioni, nomi, numeri,
tempi, statistiche descrittive di punteggiatura.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import normalize as nz

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from split_eval import midcut as mc  # noqa: E402  (modulo puro: solo re)


def midcut_fields(prefix: str, st: Optional[Dict]) -> Dict:
    """Colonne '<prefix>_midcut', '_n', '_den' da split_eval.midcut.midcut_stats."""
    if not st or not st.get('n_blocks'):
        return {f'{prefix}_midcut': None, f'{prefix}_midcut_n': 0, f'{prefix}_midcut_den': 0}
    return {f'{prefix}_midcut': round(st['rate'], 4), f'{prefix}_midcut_n': st['n_midcut'],
            f'{prefix}_midcut_den': st['n_blocks']}

C, S, D, I = 'C', 'S', 'D', 'I'


def align(ref: Sequence[str], hyp: Sequence[str]) -> List[Tuple[str, int, int]]:
    """Allineamento a costo minimo (S=D=I=1). Ritorna ops (op, i_ref, j_hyp),
    -1 dove l'indice non si applica. Parita': diagonale, poi D, poi I."""
    vocab: Dict[str, int] = {}
    r = [vocab.setdefault(t, len(vocab)) for t in ref]
    h = [vocab.setdefault(t, len(vocab)) for t in hyp]
    n, m = len(r), len(h)
    prev = list(range(m + 1))
    back = [bytearray(b'I' * (m + 1))]
    back[0][0] = ord('C')
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        row = bytearray(m + 1)
        row[0] = ord('D')
        ri = r[i - 1]
        for j in range(1, m + 1):
            diag = prev[j - 1] + (0 if ri == h[j - 1] else 1)
            dele = prev[j] + 1
            ins = cur[j - 1] + 1
            if diag <= dele and diag <= ins:
                cur[j] = diag
                row[j] = ord('C') if ri == h[j - 1] else ord('S')
            elif dele <= ins:
                cur[j] = dele
                row[j] = ord('D')
            else:
                cur[j] = ins
                row[j] = ord('I')
        back.append(row)
        prev = cur
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        op = chr(back[i][j]) if (i > 0 and j > 0) else ('D' if i > 0 else 'I')
        if op in (C, S):
            ops.append((op, i - 1, j - 1))
            i -= 1
            j -= 1
        elif op == D:
            ops.append((D, i - 1, -1))
            i -= 1
        else:
            ops.append((I, -1, j - 1))
            j -= 1
    ops.reverse()
    return ops


def count_ops(ops) -> Dict[str, int]:
    c = {C: 0, S: 0, D: 0, I: 0}
    for op, _, _ in ops:
        c[op] += 1
    return c


# ── token con tempi ──────────────────────────────────────────────────────

def ref_tokens(cues: List[Dict], lang: str) -> List[Dict]:
    """Token del riferimento dalle battute NON musicali."""
    out = []
    for ci, cue in enumerate(cues):
        if cue.get('music'):
            continue
        for t in nz.normalize_text(cue['text'], lang):
            out.append({'tok': t, 'cue': ci, 's': cue['s'], 'e': cue['e']})
    return out


def hyp_tokens(segments: List[Dict], lang: str) -> List[Dict]:
    """Token dell'ipotesi con i tempi delle parole (o spalmati sul segmento
    se il segmento non ha parole)."""
    out = []
    for seg in sorted(segments, key=lambda s: float(s['start'])):
        words = seg.get('words') or []
        if words:
            raw = [str(w['word']) for w in words]
            for tok, wi in nz.normalize_line_words(raw, lang):
                out.append({'tok': tok, 's': float(words[wi]['start']), 'e': float(words[wi]['end'])})
        else:
            raw = str(seg.get('text', '')).split()
            s0, s1 = float(seg['start']), float(seg['end'])
            step = (s1 - s0) / max(1, len(raw))
            for tok, wi in nz.normalize_line_words(raw, lang):
                out.append({'tok': tok, 's': s0 + wi * step, 'e': s0 + (wi + 1) * step})
    return out


def drop_music_hyp(htoks: List[Dict], cues: List[Dict], margin: float = 0.2) -> List[Dict]:
    """Toglie le parole dell'ipotesi cadute negli intervalli delle battute ♪
    (salvo che cadano anche in una battuta parlata)."""
    music = [(c['s'] - margin, c['e'] + margin) for c in cues if c.get('music')]
    speech = [(c['s'], c['e']) for c in cues if not c.get('music')]
    if not music:
        return htoks
    out = []
    for t in htoks:
        mid = 0.5 * (t['s'] + t['e'])
        in_music = any(a <= mid <= b for a, b in music)
        in_speech = any(a <= mid <= b for a, b in speech)
        if in_music and not in_speech:
            continue
        out.append(t)
    return out


# ── energia ──────────────────────────────────────────────────────────────

def low_energy_threshold(rms_db) -> Optional[float]:
    if rms_db is None or len(rms_db) == 0:
        return None
    vals = sorted(float(x) for x in rms_db)
    p95 = vals[min(len(vals) - 1, int(0.95 * len(vals)))]
    return max(-60.0, p95 - 30.0)


def mean_db(rms_db, frame_s: float, t0: float, t1: float) -> Optional[float]:
    if rms_db is None or len(rms_db) == 0:
        return None
    a = max(0, int(t0 / frame_s))
    b = min(len(rms_db), max(a + 1, int(t1 / frame_s) + 1))
    seg = [float(x) for x in rms_db[a:b]]
    return sum(seg) / len(seg) if seg else None


def _dist_to_cues(t0: float, t1: float, cues: List[Dict]) -> float:
    best = float('inf')
    for c in cues:
        if t1 < c['s']:
            d = c['s'] - t1
        elif t0 > c['e']:
            d = t0 - c['e']
        else:
            d = 0.0
        best = min(best, d)
    return best


# ── punteggio di una finestra ─────────────────────────────────────────────

def score_window(cues: List[Dict], segments: List[Dict], lang: str, *,
                 names: Optional[set] = None, rms_db=None, frame_s: float = 0.05,
                 dur_s: Optional[float] = None) -> Dict:
    names = names or set()
    rt = ref_tokens(cues, lang)
    ht = drop_music_hyp(hyp_tokens(segments, lang), cues)

    ops_n = align([t['tok'] for t in rt], [t['tok'] for t in ht])
    cn = count_ops(ops_n)

    rk = nz.filter_fillers_collapse([t['tok'] for t in rt], lang)
    hk = nz.filter_fillers_collapse([t['tok'] for t in ht], lang)
    rtc = [rt[i] for i in rk]
    htc = [ht[j] for j in hk]
    ops = align([t['tok'] for t in rtc], [t['tok'] for t in htc])
    cc = count_ops(ops)

    ref_op = ['D'] * len(rtc)
    ref_hyp = [-1] * len(rtc)
    for op, i, j in ops:
        if i >= 0:
            ref_op[i] = op
            ref_hyp[i] = j

    # battute perse
    by_cue: Dict[int, List[int]] = {}
    for i, t in enumerate(rtc):
        by_cue.setdefault(t['cue'], []).append(i)
    n_cues_ge3 = 0
    n_missed = 0
    for ci, idxs in by_cue.items():
        if len(idxs) < 3:
            continue
        n_cues_ge3 += 1
        hit = sum(1 for i in idxs if ref_op[i] == C)
        if hit / len(idxs) < 0.20:
            n_missed += 1

    # allucinazioni: run di >=3 inserzioni consecutive, lontane dalle battute, a bassa energia
    thr = low_energy_threshold(rms_db)
    runs = []
    cur = []
    for op, i, j in ops:
        if op == I:
            cur.append(j)
        elif op in (C, S):
            if len(cur) >= 3:
                runs.append(cur)
            cur = []
    if len(cur) >= 3:
        runs.append(cur)
    halluc_events = []
    for run in runs:
        t0 = min(htc[j]['s'] for j in run)
        t1 = max(htc[j]['e'] for j in run)
        if _dist_to_cues(t0, t1, cues) < 1.5:
            continue
        e = mean_db(rms_db, frame_s, t0, t1)
        if thr is not None and e is not None and e >= thr:
            continue
        halluc_events.append({'t0': round(t0, 2), 't1': round(t1, 2), 'n': len(run),
                              'text': ' '.join(htc[j]['tok'] for j in run)})
    ref_joined = ' ' + ' '.join(t['tok'] for t in rt) + ' '
    hyp_all = [t['tok'] for t in ht]
    for a, b, ph in nz.find_phantoms(hyp_all, lang):
        if f' {ph} ' in ref_joined:
            continue
        t0, t1 = ht[a]['s'], ht[b - 1]['e']
        if any(ev['t0'] <= t0 and t1 <= ev['t1'] for ev in halluc_events):
            continue
        halluc_events.append({'t0': round(t0, 2), 't1': round(t1, 2), 'n': b - a, 'text': ph})

    # nomi e numeri
    names_total = sum(1 for t in rtc if t['tok'] in names)
    names_hit = sum(1 for i, t in enumerate(rtc) if t['tok'] in names and ref_op[i] == C)
    num_total = sum(1 for t in rtc if nz.is_number_token(t['tok'], lang))
    num_hit = sum(1 for i, t in enumerate(rtc) if nz.is_number_token(t['tok'], lang) and ref_op[i] == C)

    # tempi: battute dopo >=1 s senza battute
    diffs = []
    sorted_cues = sorted(range(len(cues)), key=lambda k: cues[k]['s'])
    prev_end = None
    for ci in sorted_cues:
        c = cues[ci]
        gap = c['s'] - (prev_end if prev_end is not None else 0.0)
        prev_end = c['e'] if prev_end is None else max(prev_end, c['e'])
        if gap < 1.0 or ci not in by_cue:
            continue
        i0 = by_cue[ci][0]
        if ref_op[i0] in (C, S) and ref_hyp[i0] >= 0:
            diffs.append(htc[ref_hyp[i0]]['s'] - c['s'])

    seg_texts = [str(s.get('text', '')).strip() for s in segments if str(s.get('text', '')).strip()]
    cue_texts = [nz.strip_markup(c['text']).strip() for c in cues if not c.get('music')]
    cue_texts = [t for t in cue_texts if t]

    def _end_punct(ts):
        return round(sum(1 for t in ts if t[-1] in '.!?…') / len(ts), 3) if ts else None

    def _cap_start(ts):
        return round(sum(1 for t in ts if t.lstrip('-–— "«¿¡')[:1].isupper()) / len(ts), 3) if ts else None

    n_ref_c = len(rtc)
    return {
        'n_ref': len(rt), 'n_hyp': len(ht),
        'S': cn[S], 'D': cn[D], 'I': cn[I],
        'wer': (cn[S] + cn[D] + cn[I]) / len(rt) if rt else None,
        'n_ref_c': n_ref_c, 'n_hyp_c': len(htc),
        'Sc': cc[S], 'Dc': cc[D], 'Ic': cc[I], 'Cc': cc[C],
        'werc': (cc[S] + cc[D] + cc[I]) / n_ref_c if n_ref_c else None,
        'n_cues_ge3': n_cues_ge3, 'n_missed': n_missed,
        'n_halluc': len(halluc_events), 'halluc_words': sum(e['n'] for e in halluc_events),
        'halluc_detail': halluc_events,
        'energy_available': thr is not None,
        'names_total': names_total, 'names_hit': names_hit,
        'num_total': num_total, 'num_hit': num_hit,
        'n_timing': len(diffs),
        'timing_med_abs_s': round(statistics.median(abs(d) for d in diffs), 3) if diffs else None,
        'timing_med_s': round(statistics.median(diffs), 3) if diffs else None,
        'hit_mask': ''.join('1' if o == C else '0' for o in ref_op),
        'hyp_end_punct': _end_punct(seg_texts), 'hyp_cap_start': _cap_start(seg_texts),
        'ref_end_punct': _end_punct(cue_texts), 'ref_cap_start': _cap_start(cue_texts),
        'dur_s': dur_s,
        # frasi spezzate (split_eval/midcut.py): segmenti grezzi del motore e
        # battute del riferimento; i blocchi del formatter li aggiunge asr_bench
        **midcut_fields('hyp', mc.midcut_stats(
            [{'start': float(s['start']), 'end': float(s['end']), 'text': str(s.get('text', ''))}
             for s in segments], lang)),
        **midcut_fields('ref', mc.midcut_stats(cues, lang)),
    }
