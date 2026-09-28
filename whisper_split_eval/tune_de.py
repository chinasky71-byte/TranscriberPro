"""TEDESCO, taratura (28/09/2026): split attuale vs split per frasi (lang='de') sui segmenti NATIVI dei 3 file di
TARATURA (work_de_runs/raw), solo CPU. Misura principale: TAGLI NUDI (naked_cuts.py); midcut informativo; densita',
blocchi lunghi; N esempi di tagli nudi rimasti (nuovo) con il tipo di confine delle regole.
Uso: set PYTHONIOENCODING=utf-8 & ..\venv\Scripts\python.exe tune_de.py [--examples 30]"""
import argparse, collections, json, random
from pathlib import Path
import common as C, analyze as A, naked_cuts as NK

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(); ap.add_argument('--examples', type=int, default=30); a = ap.parse_args()
O = C.orig_split_mod().orig_split
NS = C.new_split_mod()
sel = json.loads((HERE / 'work_de' / 'selection_de.json').read_text(encoding='utf-8'))
ids = [i['id'] for i in sel['items'] if i['set'] == 'taratura']
tot = {k: collections.Counter() for k in ('old', 'new')}
ex, cuttypes = [], collections.Counter()
for wid in ids:
    raw = json.loads((HERE / 'work_de_runs' / 'raw' / f'{wid}.json').read_text(encoding='utf-8'))
    dur = max(s['end'] for s in raw['segments'])
    for arm, fn in (('old', O), ('new', lambda s: A.split_new(s, lang='de'))):
        segs = C.round_segments([p for s in raw['segments'] for p in fn(s)])
        bl = C.formatter_blocks(segs)
        nk = NK.naked_stats(bl, 'de'); mc = C.midcut_stats(bl, 'de')
        d = [b['end'] - b['start'] for b in bl]
        t = tot[arm]
        t['blocchi'] += len(bl); t['nudi'] += nk['n_naked']; t['midcut'] += mc['n_midcut']
        t['gt84'] += sum(len(' '.join(b['text'].split())) > 84 for b in bl); t['gt9s'] += sum(x > 9 for x in d)
        t['lt1s'] += sum(x < 1 for x in d); t['min'] += dur / 60
        print(f"{wid[:28]:28s} {arm}: blocchi {len(bl)}, nudi {nk['rate']:.3f}, midcut {mc['rate']:.3f}")
        if arm == 'new':
            fl = NK.naked_flags(bl, 'de')
            for i, f in enumerate(fl):
                if f:
                    ex.append(f"{wid[:8]} | {' '.join(bl[i]['text'].split())[-55:]} || {' '.join(bl[i + 1]['text'].split())[:40]}")
            for s in raw['segments']:
                ps = A.split_new(s, lang='de')
                for p, q in zip(ps, ps[1:]):
                    cuttypes[NS.boundary_type(p['words'][-1]['word'], q['words'][0]['word'], 'de')] += 1
for arm, t in tot.items():
    print(f"TOTALE {arm}: nudi {t['nudi']}/{t['blocchi']} = {t['nudi'] / t['blocchi']:.3f} | midcut {t['midcut'] / t['blocchi']:.3f} | "
          f">84 {t['gt84']} | >9s {t['gt9s']} | <1s {t['lt1s']} | blocchi/min {t['blocchi'] / t['min']:.2f}")
print('tipi dei tagli interni del nuovo split:', dict(cuttypes))
rng = random.Random(3)
print(f"\n--- tagli nudi rimasti (nuovo): {len(ex)}; campione")
for e in rng.sample(ex, min(a.examples, len(ex))):
    print('  ', e)
