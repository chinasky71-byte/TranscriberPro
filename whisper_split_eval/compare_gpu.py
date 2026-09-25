"""
Confronta i run GPU di conferma con la ricostruzione offline:
  work/on/*.json  == split nuovo applicato offline ai segmenti nativi (work/raw)
  work/off/*.json == hyp del banco asr_eval (whisper__vocals) == split attuale

--module PATH: versione del modulo nuovo da usare per il confronto 'on'
(default: core/whisper_sentence_split.py; il run 'on' del 24/09 e' stato
fatto con la v1, copiata nello scratchpad prima della correzione post-hoc
"mai tagliare dentro una parola").
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import common as C


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--module', default=None)
    args = ap.parse_args()
    if args.module:
        NS = C.load_path('_wse_cmp_new', Path(args.module))
    else:
        NS = C.new_split_mod()
    O = C.orig_split_mod().orig_split

    def new(seg):
        try:
            r = NS.sentence_aware_split(seg, 80, 6.0)
            if r is not None and NS.validate_split(seg, r):
                return r
        except Exception:
            pass
        return O(seg)

    res = {}
    for mode in ('on', 'off'):
        d = C.WORK / mode
        same = diff = 0
        for p in sorted(d.glob('*.json')) if d.exists() else []:
            rec = json.loads(p.read_text(encoding='utf-8'))
            raw = json.loads((C.WORK / 'raw' / p.name).read_text(encoding='utf-8'))
            if mode == 'on':
                exp = C.round_segments([x for s in raw['segments'] for x in new(s)])
            else:
                exp = C.bench_hyp(rec['win_id'])['segments']
            if rec['segments'] == exp:
                same += 1
            else:
                diff += 1
                print(f"  {mode}: DIVERSO {rec['win_id']}")
        res[mode] = (same, diff)
        print(f"{mode}: identici {same}, diversi {diff}")
    return 0 if all(v[1] == 0 for v in res.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
