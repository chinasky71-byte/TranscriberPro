"""Conta i token attaccati (senza spazio iniziale) preceduti da un salto temporale >= GAP nei segmenti nativi salvati."""
import glob
import json
import os
import sys

GAP = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
HERE = os.path.dirname(os.path.abspath(__file__))
sets = (('EN v1', 'work/raw'), ('EN v2', 'work_fresh_runs/raw'), ('EN v3', 'work_fresh3_runs/raw'),
        ('EN v4', 'work_full_runs/raw'), ('EN v5', 'work_full5_runs/raw'), ('IT taratura', 'work_it_runs/raw'))
for label, sub in sets:
    n_seg = n_hit = 0
    ex = []
    for f in glob.glob(os.path.join(HERE, sub, '*.json')):
        if 'wristcutters' in f:
            continue
        d = json.load(open(f, encoding='utf-8'))
        for s in d['segments']:
            n_seg += 1
            w = s.get('words') or []
            for k in range(1, len(w)):
                if not w[k]['word'][:1].isspace() and w[k]['start'] - w[k - 1]['end'] >= GAP:
                    n_hit += 1
                    ex.append((os.path.basename(f)[:22], round(w[k]['start'] - w[k - 1]['end'], 1), w[k - 1]['word'] + w[k]['word']))
    print(f"{label:12s} segmenti {n_seg:6d}  token attaccati con salto >= {GAP:.0f} s: {n_hit}  {ex[:3]}")
