"""Logica pura (CPU, testabile) del foglio cieco e del conteggio."""
import importlib.util
import random
import re
from math import comb
from typing import Dict, List, Optional, Sequence, Tuple

import common as C
import decision_rule as R


def load_recompose():
    """core/sentence_recompose.py caricato PER PERCORSO (solo stdlib)."""
    spec = importlib.util.spec_from_file_location('sentence_recompose_bc', C.ROOT / 'core' / 'sentence_recompose.py')
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def norm(t: str) -> str:
    return ' '.join(str(t).split())


def _one_line(t: str) -> str:
    return norm(str(t).replace('\n', ' / '))


def ref_text(SR, cues, start: float, end: float, margin: float = 0.5, max_cues: int = 8) -> str:
    """Sottotitoli professionali (riferimento) che si sovrappongono a [start, end] dell'unita'."""
    out = []
    for s, e, t in cues:
        if min(end + margin, e) - max(start - margin, s) > 0:
            out.append(_one_line(t))
    return ' | '.join(out[:max_cues]) + (' | ...' if len(out) > max_cues else '')


def build_pairs(SR, src_srt, base_srt, ric_srt, meta: Dict, rng: random.Random,
                max_pairs: int, ref_srt=None) -> List[Dict]:
    """Coppie (base, ricomposta) per le UNITA' FUSE in cui le due traduzioni differiscono."""
    src, base, ric = SR.read_srt(src_srt), SR.read_srt(base_srt), SR.read_srt(ric_srt)
    ref_cues = []
    if ref_srt:
        ref_cues = [(SR.ts_to_s(s), SR.ts_to_s(e), t) for _, s, e, t in SR.read_srt(ref_srt)]
    if not (len(src) == len(base) == len(ric)):
        raise ValueError(f"{meta['id']}: numero di blocchi diverso (src {len(src)}, base {len(base)}, ric {len(ric)})")
    blocks = [{'start': SR.ts_to_s(s), 'end': SR.ts_to_s(e), 'text': t} for _, s, e, t in src]
    units, _ = SR.recompose(blocks, {'lang': 'en', 'tgt_lang': 'it'}, skip_tagged=True)
    out = []
    for u in units:
        if not u['merged']:
            continue
        js = u['blocks']
        # ' | ' = confine fra sottotitoli (blocchi), ' / ' = a capo dentro lo stesso sottotitolo
        b_txt = ' | '.join(_one_line(base[j][3]) for j in js)
        r_txt = ' | '.join(_one_line(ric[j][3]) for j in js)
        flat = lambda t: norm(t.replace(' | ', ' ').replace(' / ', ' '))
        if flat(b_txt) == flat(r_txt):
            continue
        prev_en = _one_line(src[js[0] - 1][3]) if js[0] > 0 else ''
        next_en = _one_line(src[js[-1] + 1][3]) if js[-1] + 1 < len(src) else ''
        t_abs = int(u['start']) + int(meta.get('excerpt_start_s', 0))
        out.append({'file': meta['id'], 'title': meta['title'], 'time': f"{t_abs // 3600:d}:{t_abs % 3600 // 60:02d}:{t_abs % 60:02d}",
                    'prev': prev_en, 'en': ' | '.join(_one_line(src[j][3]) for j in js), 'next': next_en,
                    'base': b_txt, 'ric': r_txt,
                    'rif': ref_text(SR, ref_cues, u['start'], u['end']) if ref_srt else ''})
    rng.shuffle(out)
    return out[:max_pairs]


def assemble(pairs_by_file: Dict[str, List[Dict]], seed: int, n_target: int) -> Tuple[List[Dict], Dict]:
    """Mescola le coppie di tutti i file, ne tiene n_target, assegna gli id
    (P001...) e SCAMBIA A/B a caso. Ritorna (coppie con testi A/B, mappatura)."""
    rng = random.Random(seed)
    allp = [p for ps in pairs_by_file.values() for p in ps]
    rng.shuffle(allp)
    allp = allp[:n_target]
    mapping, out = {}, []
    for k, p in enumerate(allp, start=1):
        pid = f"P{k:03d}"
        swap = rng.random() < 0.5
        a, b = (p['ric'], p['base']) if swap else (p['base'], p['ric'])
        mapping[pid] = {'A': 'ricomposta' if swap else 'base', 'B': 'base' if swap else 'ricomposta', 'file': p['file']}
        out.append({**p, 'id': pid, 'A': a, 'B': b})
    return out, mapping


def render_lot(pairs: Sequence[Dict], lot_no: int, n_lots: int) -> str:
    lines = [f"LOTTO {lot_no}/{n_lots} — {len(pairs)} coppie. Per ognuna: quale sottotitolo pubblicheresti, A o B?",
             "COME LEGGERE: ogni coppia e' una frase (o piu') che stava su piu' sottotitoli consecutivi. Il simbolo  |  separa un",
             "sottotitolo dal successivo (compare uno dopo l'altro sullo schermo); il simbolo  /  e' un a capo DENTRO lo stesso",
             "sottotitolo. 'EN' = l'inglese dei sottotitoli della coppia; A e B = la loro traduzione italiana, con gli STESSI",
             "confini |. 'prima' e 'dopo' = il sottotitolo inglese che precede e segue (contesto): la frase puo' iniziare",
             "gia' in 'prima'. 'RIF' = il sottotitolo italiano PROFESSIONALE della stessa scena (puo' essere condensato e non ha",
             "gli stessi confini: serve solo a capire il senso, non e' la risposta giusta). Giudica la traduzione di A e B come li",
             "vedresti scorrere sullo schermo.",
             "",
             "Rispondi nel file giudizi.txt, una riga per coppia:   ID|A|   oppure   ID|B|   oppure   ID|P|  (P = pari)",
             "Se A e/o B ha un DIFETTO VISIBILE (unisce battute di persone diverse, taglio che spezza il senso) aggiungi la lettera",
             "in minuscolo dopo la seconda barra:   P012|B|a   (difetto in A)   P012|A|ab   (difetto in entrambi)   P012|P|",
             "Non conta la lunghezza delle righe ne' i tempi. 'prima'/'dopo' sono solo contesto inglese.", ""]
    for p in pairs:
        lines += [f"--- [{p['id']}] ({p['title'][:38]}, {p['time']}) ---",
                  f"prima: {p['prev']}" if p['prev'] else "prima: -",
                  f"EN   : {p['en']}",
                  f"dopo : {p['next']}" if p['next'] else "dopo : -",
                  f"RIF  : {p['rif']}" if p.get('rif') else "RIF  : (non disponibile per questo file)",
                  f"A    : {p['A']}",
                  f"B    : {p['B']}", ""]
    return '\n'.join(lines)


def parse_judgments(text: str) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """Righe 'ID|pref|flags' -> {id: (pref in A/B/P, flags in 'ab')}. Ritorna anche gli errori."""
    out, errs = {}, []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [x.strip() for x in line.split('|')]
        if len(parts) < 2 or not re.fullmatch(r'P\d{3}', parts[0].upper()):
            errs.append(f"riga {n}: formato non valido: {raw!r}")
            continue
        pid = parts[0].upper()
        pref = parts[1].upper()
        if pref == 'PARI':
            pref = 'P'
        if pref not in ('A', 'B', 'P'):
            if pref == '':
                continue            # riga del modello non ancora compilata
            errs.append(f"riga {n}: preferenza {parts[1]!r} non valida (A, B o P)")
            continue
        flags = ''.join(sorted(set(c for c in (parts[2] if len(parts) > 2 else '').lower() if c in 'ab')))
        if pid in out:
            errs.append(f"riga {n}: {pid} giudicata piu' volte (vale l'ultima)")
        out[pid] = (pref, flags)
    return out, errs


def binom_upper(n: int, k: int) -> float:
    """P(X >= k), X ~ Binomiale(n, 0.5)."""
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n if n > 0 else 1.0


def tally(mapping: Dict, judgments: Dict[str, Tuple[str, str]], rule=R) -> Dict:
    ric = base = tie = 0
    defects_ric = defects_base = 0
    per_file: Dict[str, List[int]] = {}
    for pid, (pref, flags) in judgments.items():
        m = mapping.get(pid)
        if not m:
            continue
        f = per_file.setdefault(m['file'], [0, 0, 0])          # [ricomposta, base, pari]
        if pref == 'P':
            tie += 1
            f[2] += 1
        else:
            arm = m[pref]
            if arm == 'ricomposta':
                ric += 1
                f[0] += 1
            else:
                base += 1
                f[1] += 1
        for letter in flags:
            if m[letter.upper()] == 'ricomposta':
                defects_ric += 1
            else:
                defects_base += 1
    n_j = ric + base + tie
    dec = ric + base
    share = ric / dec if dec else 0.0
    p = binom_upper(dec, ric) if dec else 1.0
    evaluable = {k: v for k, v in per_file.items() if v[0] + v[1] >= rule.FILM_MIN_DECISIVE}
    maj = sum(1 for v in evaluable.values() if v[0] > v[1])
    maj_frac = maj / len(evaluable) if evaluable else 0.0
    defect_rate = defects_ric / n_j if n_j else 0.0
    reasons = []
    if dec < rule.MIN_DECISIVE:
        verdict = 'INSUFFICIENTE'
        reasons.append(f"{dec} giudizi non pari (minimo {rule.MIN_DECISIVE})")
    elif defect_rate > rule.MAX_DEFECT_RATE:
        verdict = 'ARCHIVIA'
        reasons.append(f"difetti visibili della ricomposizione {defects_ric}/{n_j} = {defect_rate:.1%} > {rule.MAX_DEFECT_RATE:.0%}")
    else:
        ok_share = share >= rule.MIN_SHARE and p <= rule.ALPHA
        ok_films = bool(evaluable) and maj_frac >= rule.FILMS_MAJORITY
        if ok_share and ok_films:
            verdict = 'PROMUOVI'
        else:
            verdict = 'ARCHIVIA'
            if not ok_share:
                reasons.append(f"quota ricomposizione {share:.3f} su {dec} non pari, p unilaterale {p:.4f} "
                               f"(richiesti >= {rule.MIN_SHARE} e p <= {rule.ALPHA})")
            if not ok_films:
                reasons.append(f"ricomposizione in maggioranza in {maj}/{len(evaluable)} film "
                               f"(richiesto >= {rule.FILMS_MAJORITY:.0%})")
    return {'verdict': verdict, 'reasons': reasons, 'n_judged': n_j, 'ricomposta': ric, 'base': base, 'pari': tie,
            'share': share, 'p': p, 'defects_ricomposta': defects_ric, 'defects_base': defects_base,
            'defect_rate': defect_rate, 'per_file': per_file, 'films_majority': f"{maj}/{len(evaluable)}"}
