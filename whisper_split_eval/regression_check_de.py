"""
TEDESCO (28/09/2026): regressione OFFLINE del modulo con le regole tedesche su inglese, italiano e FRANCESE (acceso in v1.27.0).
Lo split e' una funzione pura dei segmenti nativi: si ricalcola con il modulo ATTUALE dai segmenti raw salvati e si
confronta con i run GPU 'on' registrati con il modulo precedente (inglese v5: work_full5_runs, 9 file; italiano
round 2: work_it2_runs, 8 file). Deve essere bit-identico. L'audio di quei banchi e' stato cancellato il 26/09, per
questo il controllo non e' su GPU (dichiarato nella regola).
Scrive work_fr/regression_check.json.
"""
import json
from pathlib import Path

import common as C
import analyze as A

H = Path(__file__).resolve().parent


def check(runs, lang):
    ok, det, n = True, [], 0
    for f in sorted((runs / 'on').glob('*.json')):
        raw_p = runs / 'raw' / f.name
        if not raw_p.exists():
            continue
        on = json.loads(f.read_text(encoding='utf-8'))['segments']
        raw = json.loads(raw_p.read_text(encoding='utf-8'))['segments']
        exp = C.round_segments([p for s in raw for p in A.split_new(s, lang=lang)])
        same = exp == on
        ok &= same
        n += len(raw)
        det.append(f"{f.stem[:30]}: {'identico' if same else 'DIVERSO'}")
    return ok, n, det


en_ok, en_n, en_det = check(H / 'work_full5_runs', 'en')
it_ok, it_n, it_det = check(H / 'work_it2_runs', 'it')
fr_ok, fr_n, fr_det = check(H / 'work_fr_runs', 'fr')
res = {'en_regression_ok': en_ok, 'it_default_ok': it_ok and fr_ok, 'fr_regression_ok': fr_ok,
       'detail': [f'inglese {en_n} segmenti nativi'] + en_det + [f'italiano {it_n} segmenti nativi'] + it_det
                 + [f'francese {fr_n} segmenti nativi'] + fr_det}
(H / 'work_de' / 'regression_check.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
print(en_ok, it_ok, fr_ok)
print('\n'.join(res['detail']))
