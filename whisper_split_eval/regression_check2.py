"""Regressione sul CODICE FINALE (GPU): inglese v5 bit-identico e italiano con lingue di default == off salvato."""
import json
from pathlib import Path
H = Path(__file__).resolve().parent
L = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
en_ok = True
detail = []
for wid in ('01-yes-day-2021', '02-predators-2010'):
    a = L(H / 'work_full5_runs' / 'on' / f'{wid}.json')['segments']; b = L(H / 'work_ctl2_en' / 'on' / f'{wid}.json')['segments']
    en_ok &= (a == b); detail.append(f'{wid}: {len(a)} seg, identico={a == b}')
wid = '09-wristcutters-a-love-story-2007'
a = L(H / 'work_full5_runs' / 'off' / f'{wid}.json')['segments']; b = L(H / 'work_ctl2_it' / 'on' / f'{wid}.json')['segments']
it_ok = (a == b)
detail.append(f'wristcutters: {len(a)} seg, on(lingue di default) == off: {it_ok}')
(H / 'work_it2' / 'regression_check.json').write_text(json.dumps({'en_regression_ok': en_ok, 'it_default_ok': it_ok, 'detail': detail}), encoding='utf-8')
print(en_ok, it_ok, detail)
