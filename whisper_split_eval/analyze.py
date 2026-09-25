"""
Analisi OFFLINE (solo CPU) dei segmenti nativi salvati da run_whisper.py --mode raw.

Bracci (stessi segmenti nativi, stesso audio):
  none : nessuno split (segmenti nativi = 1 per chunk VAD)
  old  : split attuale (_orig_split.py == metodo del motore con opzione spenta)
  new  : split per confini di frase (core/whisper_sentence_split.py, con lo
         stesso ripiego del motore: risultato non valido -> split attuale)

Comandi:
  diag   [--set tuning|eval|test|all]  tabella di attribuzione dei tagli a
         meta' frase (split / chunk su silenzio / chunk forzato a 30 s) e
         pavimento stimato (frasi che non stanno in 84 car. / 9 s)
  eval   [--set eval]   misure della regola di decisione e verdetto
         (decision_rule.py); scrive work/eval_<set>.json
  tune   come eval ma sul set di tuning, senza verdetto

Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe analyze.py diag --set test
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import common as C

ASR = C.ROOT / 'asr_eval'
if str(ASR) not in sys.path:
    sys.path.insert(0, str(ASR))

import decision_rule as DRULE  # noqa: E402

RAW_DIR = C.WORK / 'raw'
NEAR_S = 0.5


def load_raw(win_id: str) -> Optional[Dict]:
    p = RAW_DIR / f'{win_id}.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def select(set_name: str) -> List[Dict]:
    ws = [w for w in C.windows() if w['lang'] == 'en']
    if set_name == 'eval':
        return [w for w in ws if DRULE.is_eval_window(w)]
    if set_name == 'tuning':
        return [w for w in ws if DRULE.is_tuning_window(w)]
    if set_name == 'test':
        return [w for w in ws if w['role'] == 'test']
    return ws


def split_old(seg):
    return C.orig_split_mod().orig_split(seg)


def split_new(seg, params=None):
    NS = C.new_split_mod()
    try:
        r = NS.sentence_aware_split(seg, 80, 6.0, params=params)
        if r is not None and NS.validate_split(seg, r):
            return r
    except Exception:
        pass
    return split_old(seg)


def arm_segments(raw_segs, arm, params=None):
    out = []
    for s in raw_segs:
        if arm == 'none':
            out.append(dict(s))
        elif arm == 'old':
            out.extend(split_old(s))
        else:
            out.extend(split_new(s, params))
    return out


# ── metriche blocchi ────────────────────────────────────────────────────────

def block_metrics(blocks) -> Dict:
    n = len(blocks)
    gt84 = cps20 = gt2 = gt9 = 0
    for b in blocks:
        lines = [l for l in b['text'].split('\n') if l.strip()]
        chars = len(' '.join(lines))
        dur = b['end'] - b['start']
        gt84 += chars > 84
        cps20 += dur > 0 and chars / dur > 20
        gt2 += len(lines) > 2
        gt9 += dur > 9.0
    return {'n': n, 'gt84': gt84, 'cps20': cps20, 'gt2lines': gt2, 'gt9s': gt9}


# ── attribuzione ────────────────────────────────────────────────────────────

def classify_boundaries(raw: Dict, segs: List[Dict], blocks: List[Dict]) -> Counter:
    """Per ogni blocco del formatter che finisce a meta' frase, da dove viene il
    confine: 'split' (dentro un segmento nativo; sottotipo _vadsil se c'e' un
    confine di parlato VAD interno al chunk entro 0,5 s) / 'chunk_silenzio'
    (confine fra chunk VAD separati da silenzio) / 'chunk_forzato' (chunk
    contigui: taglio a 30 s nel parlato continuo) / 'non_mappato'."""
    MC = C.midcut_mod()
    flags = MC.midcut_flags(blocks, 'en')
    native_first = sorted(float(s['words'][0]['start']) for s in raw['segments'] if s.get('words'))
    words = sorted((float(w['start']), float(w['end'])) for s in raw['segments'] for w in s.get('words') or [])
    starts = [w[0] for w in words]
    chunks = (raw.get('vad') or {}).get('chunks') or []
    inner_speech_bounds = []
    for c in chunks:
        sp = c['speech']
        for a, b in zip(sp[:-1], sp[1:]):
            inner_speech_bounds.append((a[1], b[0]))
    out = Counter()
    for i, f in enumerate(flags):
        if f != 'midcut':
            continue
        t = float(blocks[i + 1]['start'])
        k = bisect.bisect_left(starts, t - 0.002)
        if k >= len(starts) or abs(starts[k] - t) > 0.002:
            out['non_mappato'] += 1
            continue
        is_native = any(abs(t - x) <= 0.002 for x in native_first)
        if is_native:
            prev_end = words[k - 1][1] if k > 0 else None
            # chunk che contiene la parola: primo chunk con start > t -> quello prima
            ci = None
            for j, c in enumerate(chunks):
                if c['start'] - 0.5 <= t:
                    ci = j
            forced = False
            if ci is not None and ci > 0:
                forced = chunks[ci]['start'] - chunks[ci - 1]['end'] <= 0.05
            out['chunk_forzato' if forced else 'chunk_silenzio'] += 1
        else:
            prev_end = words[k - 1][1] if k > 0 else t
            near = any(a - NEAR_S <= t and b + NEAR_S >= prev_end and b >= a
                       for a, b in inner_speech_bounds
                       if abs(a - prev_end) <= NEAR_S or abs(b - t) <= NEAR_S)
            out['split_vadsil' if near else 'split'] += 1
    return out


def sentence_floor(raw: Dict, hard_chars=84, hard_dur=9.0) -> Dict:
    """Frasi (dentro i segmenti nativi, fine frase = confini forti del modulo
    nuovo) che NON possono stare in un pezzo: servono tagli a meta' frase."""
    NS = C.new_split_mod()
    n_sent = n_long = forced_cuts = 0
    for s in raw['segments']:
        ws = s.get('words') or []
        cur = []
        for k, w in enumerate(ws):
            cur.append(w)
            nxt = ws[k + 1]['word'] if k + 1 < len(ws) else None
            if nxt is None or NS.boundary_type(w['word'], nxt) in NS.STRONG_TYPES:
                txt = ''.join(x['word'] for x in cur).strip()
                dur = float(cur[-1]['end']) - float(cur[0]['start'])
                n_sent += 1
                if len(txt) > hard_chars or dur > hard_dur:
                    n_long += 1
                    forced_cuts += max(-(-len(txt) // hard_chars), int(-(-dur // hard_dur))) - 1
                cur = []
    return {'n_sent': n_sent, 'n_long': n_long, 'forced_cuts': forced_cuts}


def cmd_diag(args) -> int:
    ws = select(args.set)
    tot = {a: Counter() for a in ('none', 'old', 'new')}
    agg = {a: Counter() for a in ('none', 'old', 'new')}
    floor = Counter()
    n_win = 0
    one_per_chunk = Counter()
    for w in ws:
        raw = load_raw(w['win_id'])
        if raw is None:
            continue
        n_win += 1
        nch = len((raw.get('vad') or {}).get('chunks') or [])
        one_per_chunk['uguale' if nch == len(raw['segments']) else 'diverso'] += 1
        floor.update(sentence_floor(raw))
        for arm in ('none', 'old', 'new'):
            segs = arm_segments(raw['segments'], arm)
            blocks = C.formatter_blocks(segs)
            st = C.midcut_stats(blocks)
            sg = C.midcut_stats(segs)
            agg[arm].update({'fmt_n': st['n_midcut'], 'fmt_den': st['n_blocks'],
                             'seg_n': sg['n_midcut'], 'seg_den': sg['n_blocks']})
            tot[arm].update(classify_boundaries(raw, segs, blocks))
    print(f"finestre: {n_win} ({args.set});  segmenti nativi == chunk VAD: {dict(one_per_chunk)}")
    print(f"frasi native: {floor['n_sent']}, oltre 84 car./9 s: {floor['n_long']} "
          f"(tagli a meta' frase inevitabili stimati: {floor['forced_cuts']})")
    print(f"{'braccio':6} {'midcut seg':>16} {'midcut blocchi':>18}   attribuzione dei blocchi a meta' frase")
    for arm in ('none', 'old', 'new'):
        a = agg[arm]
        att = tot[arm]
        n = sum(att.values()) or 1
        det = '  '.join(f"{k}={v} ({100 * v / n:.0f}%)" for k, v in sorted(att.items()))
        print(f"{arm:6} {100 * a['seg_n'] / a['seg_den']:6.1f}% ({a['seg_n']}/{a['seg_den']})"
              f" {100 * a['fmt_n'] / a['fmt_den']:6.1f}% ({a['fmt_n']}/{a['fmt_den']})   {det}")
    out = {'set': args.set, 'n_windows': n_win, 'floor': dict(floor), 'one_per_chunk': dict(one_per_chunk),
           'agg': {k: dict(v) for k, v in agg.items()}, 'attrib': {k: dict(v) for k, v in tot.items()}}
    (C.WORK / f'diag_{args.set}.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return 0


# ── eval ────────────────────────────────────────────────────────────────────

def _werc(w, segs) -> Dict:
    import metrics as M
    sc = M.score_window(w['cues'], segs, 'en', names=set(w.get('names') or []), dur_s=w['dur'])
    return {'e': sc['Sc'] + sc['Dc'] + sc['Ic'], 'n': sc['n_ref_c']}


def measure(ws, params=None, with_werc=True) -> Dict:
    films = set()
    res = {a: Counter() for a in ('old', 'new')}
    words_identical = text_identical = True
    max_piece = 0.0
    per_win = []
    posthoc = Counter()   # misure aggiunte DOPO aver visto il verdetto (v. README)
    for w in ws:
        raw = load_raw(w['win_id'])
        if raw is None:
            continue
        films.add(w['film'])
        segs = {'old': C.round_segments(arm_segments(raw['segments'], 'old')),
                'new': C.round_segments(arm_segments(raw['segments'], 'new', params))}
        # parole/testo identici
        fw = {a: [(x['start'], x['end'], x['word']) for s in segs[a] for x in s['words']] for a in segs}
        if fw['old'] != fw['new']:
            words_identical = False
        ft = {a: ' '.join(' '.join(s['text'] for s in segs[a]).split()) for a in segs}
        if ft['old'] != ft['new']:
            text_identical = False
        for s_raw in raw['segments']:
            pn = split_new(s_raw, params)
            po = split_old(s_raw)
            nat = ' '.join(s_raw['text'].split())
            for a, ps in (('old', po), ('new', pn)):
                if ' '.join(' '.join(p['text'] for p in ps).split()) != nat:
                    posthoc[f'{a}_text_ne_native'] += 1
                posthoc[f'{a}_midword_cuts'] += sum(1 for p in ps[1:] if not p['words'][0]['word'][:1].isspace())
            old_single_long = {(p['words'][0]['start'], p['words'][0]['end']) for p in po
                               if len(p.get('words') or []) == 1}
            if len(pn) > 1:
                for p in pn:
                    d = p['end'] - p['start']
                    max_piece = max(max_piece, d)
                    if d > DRULE.MAX_PIECE_DUR_S:
                        same_in_old = (len(p['words']) == 1 and
                                       (p['words'][0]['start'], p['words'][0]['end']) in old_single_long)
                        posthoc['new_pieces_gt9s_single_word_same_in_old' if same_in_old
                                else 'new_pieces_gt9s_due_to_split'] += 1
        row = {'win_id': w['win_id'], 'film': w['film']}
        for a in ('old', 'new'):
            blocks = C.formatter_blocks(segs[a])
            st = C.midcut_stats(blocks)
            sg = C.midcut_stats(segs[a])
            bm = block_metrics(blocks)
            upd = {'fmt_n': st['n_midcut'], 'fmt_den': st['n_blocks'], 'seg_n': sg['n_midcut'],
                   'seg_den': sg['n_blocks'], 'n_seg': len(segs[a]), **bm}
            if with_werc:
                wc = _werc(w, segs[a])
                upd.update({'werc_e': wc['e'], 'werc_n': wc['n']})
            res[a].update(upd)
            row[a] = {'fmt_n': st['n_midcut'], 'fmt_den': st['n_blocks']}
        per_win.append(row)

    def summ(c):
        n = c['n'] or 1
        return {'fmt_midcut': c['fmt_n'] / max(1, c['fmt_den']), 'seg_midcut': c['seg_n'] / max(1, c['seg_den']),
                'werc': (c['werc_e'] / c['werc_n']) if c.get('werc_n') else float('nan'),
                'gt84': c['gt84'] / n, 'cps20': c['cps20'] / n, 'n_gt2lines': c['gt2lines'],
                'n_gt9s': c['gt9s'], 'n_blocks': c['n'], 'n_segments': c['n_seg'], 'raw': dict(c)}
    return {'n_windows': len(per_win), 'n_films': len(films), 'old': summ(res['old']), 'new': summ(res['new']),
            'words_identical': words_identical, 'text_identical': text_identical,
            'new_max_piece_dur': max_piece, 'posthoc': dict(posthoc), 'per_window': per_win}


def off_identical_all() -> bool:
    """Controllo negativo offline su TUTTE le finestre: metodo reale del motore
    con opzione spenta == copia dello split originale (e == hyp del banco)."""
    import test_support as TS
    eng_off = TS.engine_method(False)
    ok = True
    n = 0
    for w in C.windows():
        raw = load_raw(w['win_id'])
        if raw is None:
            continue
        a = [p for s in raw['segments'] for p in eng_off(s)]
        b = [p for s in raw['segments'] for p in split_old(s)]
        if a != b:
            ok = False
        if C.round_segments(b) != C.bench_hyp(w['win_id'])['segments']:
            print(f"  nota: {w['win_id']} diverso dall'hyp del banco (determinismo GPU)")
        n += 1
    print(f"  controllo opzione spenta su {n} finestre: {'IDENTICO' if ok else 'DIVERSO'}")
    return ok


def cmd_eval(args) -> int:
    ws = select(args.set)
    m = measure(ws, with_werc=True)
    if args.cmd == 'eval':
        m['off_identical'] = off_identical_all()
    o, n = m['old'], m['new']
    print(f"finestre {m['n_windows']}, film {m['n_films']} ({args.set})")
    for k in ('fmt_midcut', 'seg_midcut', 'werc', 'gt84', 'cps20', 'n_gt2lines', 'n_gt9s', 'n_blocks', 'n_segments'):
        print(f"  {k:12} attuale {o[k]:.4f}   nuova {n[k]:.4f}" if isinstance(o[k], float)
              else f"  {k:12} attuale {o[k]}   nuova {n[k]}")
    print(f"  parole identiche {m['words_identical']}, testo identico {m['text_identical']}, "
          f"pezzo nuovo piu' lungo {m['new_max_piece_dur']:.2f}s")
    print(f"  post-hoc (aggiunte dopo il primo verdetto): {m['posthoc']}")
    if args.cmd == 'eval':
        v = DRULE.verdict(m)
        for k, (ok, det) in v['criteria'].items():
            print(f"  [{'OK' if ok else 'NO'}] {k}: {det}")
        print(f"VERDETTO: {v['verdict']}")
        m['verdict'] = {'criteria': {k: list(x) for k, x in v['criteria'].items()}, 'verdict': v['verdict']}
    (C.WORK / f"{args.cmd}_{args.set}.json").write_text(json.dumps(m, indent=1, default=str), encoding='utf-8')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['diag', 'eval', 'tune'])
    ap.add_argument('--set', default=None)
    args = ap.parse_args()
    if args.set is None:
        args.set = {'diag': 'test', 'eval': 'eval', 'tune': 'tuning'}[args.cmd]
    return cmd_diag(args) if args.cmd == 'diag' else cmd_eval(args)


if __name__ == '__main__':
    sys.exit(main())
