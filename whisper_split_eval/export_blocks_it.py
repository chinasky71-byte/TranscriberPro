"""Esporta i blocchi (formatter di produzione) dei 4 bracci sui file italiani di un set, per il controllo POS con spaCy."""
import json, sys
import common as C
import analyze as A

setname = sys.argv[1] if len(sys.argv) > 1 else 'taratura'
HERE = C.HERE
sel = {i['id'] for i in json.loads((HERE / 'work_it' / 'selection_it.json').read_text(encoding='utf-8'))['items'] if i['set'] == setname}
O = C.orig_split_mod().orig_split
out = {}
for w in C.read_jsonl(HERE / 'work_it' / 'windows.jsonl'):
    if w['win_id'] not in sel:
        continue
    raw = json.loads((HERE / 'work_it_runs' / 'raw' / f"{w['win_id']}.json").read_text(encoding='utf-8'))
    on = json.loads((HERE / 'work_it_runs' / 'on' / f"{w['win_id']}.json").read_text(encoding='utf-8'))
    arms = {
        'originale': [p for s in raw['segments'] for p in O(s)],
        'regole_en': [p for s in raw['segments'] for p in A.split_new(s, lang='en')],
        'regole_it': on['segments'],
    }
    rec = {}
    for k, sg in arms.items():
        rec[k] = [b['text'] for b in C.formatter_blocks(C.round_segments(sg))]
    rec['professionale'] = [c['text'] for c in w['cues'] if not (c.get('music') or c.get('sound_only'))]
    out[w['win_id']] = rec
(HERE / 'work_it' / f'blocks_{setname}.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print({k: {a: len(v) for a, v in r.items()} for k, r in out.items()})
