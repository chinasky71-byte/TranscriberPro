"""Controllo descrittivo INDIPENDENTE dalle liste di regole: quota di blocchi che finiscono su DET/ADP/CCONJ/SCONJ/AUX (spaCy fr_core_news_lg).
Si esegue con il venv di gender_eval: gender_eval\.venv_spacy\Scripts\python.exe pos_check_fr.py <set>"""
import json, sys, re
from pathlib import Path
import spacy

HERE = Path(__file__).resolve().parent
setname = sys.argv[1] if len(sys.argv) > 1 else 'taratura'
data = json.loads((HERE / 'work_fr' / f'blocks_{setname}.json').read_text(encoding='utf-8'))
nlp = spacy.load('fr_core_news_lg', disable=['ner', 'lemmatizer'])
BAD = {'DET', 'ADP', 'CCONJ', 'SCONJ', 'AUX'}
tot = {}
for wid, arms in data.items():
    for arm, texts in arms.items():
        docs = list(nlp.pipe([re.sub(r'\s+', ' ', t).strip() for t in texts], batch_size=64))
        n = bad = 0
        for d in docs:
            toks = [t for t in d if not t.is_punct and not t.is_space]
            if not toks:
                continue
            n += 1
            bad += toks[-1].pos_ in BAD
        a = tot.setdefault(arm, [0, 0]); a[0] += bad; a[1] += n
        print(f"{wid[:28]:28s} {arm:14s} blocchi {n:5d}  finiscono su DET/ADP/CONG/AUX: {bad:4d} ({bad / max(1, n):.1%})")
print('\nTOTALE')
for arm, (b, n) in tot.items():
    print(f"  {arm:14s} {b:5d} / {n:5d} = {b / max(1, n):.1%}")

(HERE / 'work_fr' / f'pos_{setname}.json').write_text(json.dumps({
    'pos_ratio': round(tot['regole_fr'][0] / max(1, tot['regole_fr'][1]) / max(1e-9, tot['originale'][0] / max(1, tot['originale'][1])), 4),
    'pos_detail': '; '.join(f"{a} {b}/{n}={b / max(1, n):.1%}" for a, (b, n) in tot.items())}, ensure_ascii=False), encoding='utf-8')
