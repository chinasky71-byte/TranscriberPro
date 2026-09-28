"""FRANCESE (28/09/2026): tipo dei tagli "a meta' frase" (metrica midcut, lang='fr') per braccio: attuale (off),
split per frasi (on), professionali. Tipo dal TESTO dei blocchi (fine blocco e parola iniziale del successivo),
con le stesse funzioni del modulo: comma (virgola/trattino), clause (; :), conj (prima di congiunzione),
func (dopo articolo/preposizione/pronome/ausiliare), word (altro). Solo lettura.
Uso: set PYTHONIOENCODING=utf-8 & ..\venv\Scripts\python.exe midcut_types_fr.py [--set conferma]"""
import argparse, collections, json
from pathlib import Path
import common as C

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(); ap.add_argument('--set', default='conferma'); a = ap.parse_args()
NS = C.new_split_mod(); MC = C.midcut_mod()
sel = {i['id'] for i in json.loads((HERE / 'work_fr' / 'selection_fr.json').read_text(encoding='utf-8'))['items'] if i['set'] == a.set}
res = {k: collections.Counter() for k in ('attuale', 'nuovo', 'professionale')}
nb = collections.Counter()
for w in C.read_jsonl(HERE / 'work_fr' / 'windows.jsonl'):
    if w['win_id'] not in sel:
        continue
    L = lambda m: json.loads((HERE / 'work_fr_runs' / m / f"{w['win_id']}.json").read_text(encoding='utf-8'))['segments']
    arms = {'attuale': C.formatter_blocks(L('off')), 'nuovo': C.formatter_blocks(L('on')),
            'professionale': [{'start': c['s'], 'end': c['e'], 'text': c['text']} for c in w['cues'] if not (c.get('music') or c.get('sound_only'))]}
    for arm, bl in arms.items():
        nb[arm] += len(bl)
        for i, f in enumerate(MC.midcut_flags(bl, 'fr')):
            if f != 'midcut':
                continue
            A = ' '.join(MC.clean_lines(bl[i]['text'])).split()
            B = ' '.join(MC.clean_lines(bl[i + 1]['text'])).split()
            t = NS.boundary_type(' ' + A[-1], ' ' + B[0], 'fr') if A and B else 'word'
            res[arm][t] += 1
for arm, c in res.items():
    tot = sum(c.values())
    strict = c['word'] + c['func']
    print(f"{arm:13s} blocchi {nb[arm]:6d} | a meta' frase {tot:5d} ({tot / nb[arm]:.1%}) | "
          + ', '.join(f"{k} {v}" for k, v in c.most_common())
          + f" | SENZA punteggiatura ne' congiunzione (word+func): {strict} ({strict / nb[arm]:.1%})")
