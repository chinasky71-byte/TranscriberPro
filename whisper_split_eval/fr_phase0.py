"""
FRANCESE fase 0 (28/09/2026): i timestamp per parola di whisper-large-v3-french sono utilizzabili dallo split?
Statistiche sui segmenti NATIVI (work_fr_runs/raw): parole a durata zero, parole lunghe, ordine, segmenti vuoti,
e (se presente) lo stesso per Whisper large-v3 generico (work_fr_runs_v3/raw).
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe fr_phase0.py
"""
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stats(path):
    r = json.loads(path.read_text(encoding='utf-8'))
    segs = r['segments']
    W = [w for s in segs for w in s['words']]
    d = [w['end'] - w['start'] for w in W]
    sd = [s['end'] - s['start'] for s in segs]
    return {
        'seg': len(segs), 'parole': len(W),
        'car/seg': round(st.mean(len(s['text']) for s in segs)),
        'seg>6s': sum(1 for x in sd if x > 6), 'seg>84car': sum(1 for s in segs if len(s['text']) > 84),
        'dur0': sum(1 for x in d if x <= 0.001), 'parola>2s': sum(1 for x in d if x > 2),
        'parola>5s': sum(1 for x in d if x > 5), 'med parola': round(st.median(d), 2),
        'non_monot': sum(1 for a, b in zip(W, W[1:]) if b['start'] < a['start'] - 0.01),
        'seg_senza_parole': sum(1 for s in segs if not s['words']),
        'pause>=1s': sum(1 for a, b in zip(W, W[1:]) if b['start'] - a['end'] >= 1.0),
    }


for root in ('work_fr_runs', 'work_fr_runs_v3'):
    files = sorted((HERE / root / 'raw').glob('*.json'))
    if not files:
        continue
    print(f'== {root}')
    for f in files:
        print(f'  {f.stem[:32]:32s}', stats(f))
