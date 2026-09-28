"""
FRANCESE (28/09/2026): analisi dei blocchi che restano "a meta' frase" con lo split per frasi (braccio 'on' della
conferma). SOLO LETTURA dei dati: nessuna modifica alle regole (la conferma e' chiusa; se si fa un nuovo giro le
regole si toccano guardando solo la taratura).

Per ogni coppia di blocchi segnata 'midcut' dalla metrica (split_eval/midcut.py, lang='fr') classifica il taglio:
  confine_nativo   -> il blocco finisce dove finisce un segmento nativo di Whisper (confine VAD / chunk <= 30 s):
                      lo split per frasi lavora DENTRO un segmento e non puo' spostarlo
  formatter        -> il taglio non coincide con la fine di una parola dei segmenti (lo fa il SubtitleFormatter)
  <tipo>           -> taglio dello split: comma / func / word / conj / clause / sent_weak (core/whisper_sentence_split)
e per i tagli dello split se la frase che contiene il taglio supera 84 caratteri (taglio obbligato) o no.
Stampa conteggi, esempi per categoria, e la stessa metrica sui sottotitoli professionali (rumore della metrica).
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe midcut_deep_fr.py [--set conferma] [--n 12]
"""
import argparse
import collections
import json
import random
from pathlib import Path

import common as C

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'work_fr_runs'


def one(s):
    return ' '.join(s.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', default='conferma')
    ap.add_argument('--n', type=int, default=12)
    a = ap.parse_args()
    NS = C.new_split_mod()
    MC = C.midcut_mod()
    sel = {i['id'] for i in json.loads((HERE / 'work_fr' / 'selection_fr.json').read_text(encoding='utf-8'))['items']
           if i['set'] == a.set}
    cats = collections.Counter()
    forced = collections.Counter()
    ex = collections.defaultdict(list)
    pro_ex = []
    n_blocks = 0
    for w in C.read_jsonl(HERE / 'work_fr' / 'windows.jsonl'):
        if w['win_id'] not in sel:
            continue
        raw = json.loads((RUNS / 'raw' / f"{w['win_id']}.json").read_text(encoding='utf-8'))['segments']
        on = json.loads((RUNS / 'on' / f"{w['win_id']}.json").read_text(encoding='utf-8'))['segments']
        native_end = {round(s['words'][-1]['end'], 3) for s in raw if s.get('words')}
        words = [x for s in on for x in s['words']]
        by_end = {}
        for k, x in enumerate(words):
            by_end.setdefault(round(x['end'], 3), k)
        # fine frase per il calcolo "frase > 84 car"
        is_sent = [NS.boundary_type(words[k]['word'], words[k + 1]['word'] if k + 1 < len(words) else None, 'fr')
                   in (NS.SENT, NS.SENT_WEAK) or round(words[k]['end'], 3) in native_end for k in range(len(words))]
        bl = C.formatter_blocks(on)
        n_blocks += len(bl)
        flags = MC.midcut_flags(bl, 'fr')
        for i, f in enumerate(flags):
            if f != 'midcut':
                continue
            t = round(bl[i]['end'], 3)
            k = by_end.get(t)
            if k is None:
                # l'SRT arrotonda al millisecondo: cerca la parola piu' vicina entro 2 ms
                cand = [kk for e, kk in by_end.items() if abs(e - t) <= 0.002]
                k = cand[0] if cand else None
            pair = f"{w['win_id'][:10]} | {one(bl[i]['text'])[-55:]} || {one(bl[i + 1]['text'])[:45]}"
            if k is None or k + 1 >= len(words):
                cat = 'formatter'
            elif round(words[k]['end'], 3) in native_end:
                cat = 'confine_nativo'
            else:
                cat = NS.boundary_type(words[k]['word'], words[k + 1]['word'], 'fr')
                # lunghezza della frase che contiene il taglio
                s0 = k
                while s0 > 0 and not is_sent[s0 - 1]:
                    s0 -= 1
                s1 = k + 1
                while s1 < len(words) - 1 and not is_sent[s1]:
                    s1 += 1
                ln = len(one(''.join(x['word'] for x in words[s0:s1 + 1])))
                forced['frase>84' if ln > 84 else 'frase<=84'] += 1
                forced[f'{cat}|' + ('frase>84' if ln > 84 else 'frase<=84')] += 1
            cats[cat] += 1
            ex[cat].append(pair)
        # rumore della metrica: professionali
        pb = [{'start': c['s'], 'end': c['e'], 'text': c['text']} for c in w['cues'] if not (c.get('music') or c.get('sound_only'))]
        for i, f in enumerate(MC.midcut_flags(pb, 'fr')):
            if f == 'midcut':
                pro_ex.append(f"{w['win_id'][:10]} | {one(pb[i]['text'])[-55:]} || {one(pb[i + 1]['text'])[:45]}")
    tot = sum(cats.values())
    print(f"blocchi {n_blocks}, a meta' frase {tot} ({tot / max(1, n_blocks):.1%})")
    for c, n in cats.most_common():
        print(f"  {c:15s} {n:5d}  {n / max(1, tot):.1%}")
    print('tagli dello split per lunghezza della frase:', dict(forced))
    rng = random.Random(7)
    for c, _ in cats.most_common():
        print(f"\n--- {c}: esempi")
        for e in rng.sample(ex[c], min(a.n, len(ex[c]))):
            print('  ', e)
    print(f"\n--- professionali a meta' frase: {len(pro_ex)}; esempi")
    for e in rng.sample(pro_ex, min(a.n, len(pro_ex))):
        print('  ', e)


if __name__ == '__main__':
    main()
