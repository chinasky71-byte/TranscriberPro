"""
FRANCESE, taratura (28/09/2026): split attuale vs split per frasi (lang='fr') sui segmenti NATIVI dei 3 file di
TARATURA (work_fr_runs/raw), solo CPU. Stampa midcut (metrica split_eval/midcut.py con CONT_WORDS 'fr'), densita',
durate, blocchi lunghi, e N esempi di tagli a meta' frase rimasti e di tagli subito dopo parola funzionale.
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe tune_fr.py [--examples 25]
"""
import argparse
import json
import random
from pathlib import Path

import common as C
import analyze as A

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'work_fr_runs' / 'raw'


def bstats(blocks, dur):
    n = len(blocks)
    ch = [len(' '.join(b['text'].split())) for b in blocks]
    d = [b['end'] - b['start'] for b in blocks]
    return {'blocchi': n, 'per_min': round(n / (dur / 60), 2), 'gt84': sum(c > 84 for c in ch),
            'gt2righe': sum(len([l for l in b['text'].split('\n') if l.strip()]) > 2 for b in blocks),
            'gt9s': sum(x > 9 for x in d), 'lt1s': sum(x < 1 for x in d), 'lt15s': sum(x < 1.5 for x in d)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--examples', type=int, default=20)
    a = ap.parse_args()
    O = C.orig_split_mod().orig_split
    NS = C.new_split_mod()
    sel = json.loads((HERE / 'work_fr' / 'selection_fr.json').read_text(encoding='utf-8'))
    ids = [i['id'] for i in sel['items'] if i['set'] == 'taratura']
    tot = {k: [0, 0] for k in ('old', 'new')}
    ex_mid, ex_func = [], []
    for wid in ids:
        raw = json.loads((RUNS / f'{wid}.json').read_text(encoding='utf-8'))
        dur = max(s['end'] for s in raw['segments'])
        res = {}
        for arm, fn in (('old', O), ('new', lambda s: A.split_new(s, lang='fr'))):
            segs = C.round_segments([p for s in raw['segments'] for p in fn(s)])
            bl = C.formatter_blocks(segs)
            st = C.midcut_stats(bl, 'fr')
            tot[arm][0] += st['n_midcut']
            tot[arm][1] += st['n_blocks']
            res[arm] = (st, bstats(bl, dur))
            if arm == 'new':
                flags = C.midcut_mod().midcut_flags(bl, 'fr')
                for i, f in enumerate(flags):
                    if f == 'midcut':
                        ex_mid.append(f"{wid[:6]} | {' '.join(bl[i]['text'].split())[-60:]} || {' '.join(bl[i + 1]['text'].split())[:50]}")
                for s in raw['segments']:
                    pieces = A.split_new(s, lang='fr')
                    for p, q in zip(pieces, pieces[1:]):
                        t = NS.boundary_type(p['words'][-1]['word'], q['words'][0]['word'], 'fr')
                        if t in (NS.FUNC, NS.WORD):
                            ex_func.append(f"{wid[:6]} [{t}] ...{p['text'][-50:]} | {q['text'][:40]}")
        print(f"== {wid}")
        for arm in ('old', 'new'):
            st, bs = res[arm]
            print(f"   {arm}: midcut {st['n_midcut']}/{st['n_blocks']} = {st['rate']:.3f} | {bs}")
    for arm in ('old', 'new'):
        print(f"TOTALE {arm}: midcut {tot[arm][0]}/{tot[arm][1]} = {tot[arm][0] / max(1, tot[arm][1]):.3f}")
    rng = random.Random(1)
    print(f"\n--- tagli a meta' frase rimasti (nuovo): {len(ex_mid)}; campione")
    for e in rng.sample(ex_mid, min(a.examples, len(ex_mid))):
        print('  ', e)
    print(f"\n--- tagli dopo parola funzionale/qualunque (nuovo): {len(ex_func)}; campione")
    for e in rng.sample(ex_func, min(a.examples, len(ex_func))):
        print('  ', e)


if __name__ == '__main__':
    main()
