"""
Finestre NUOVE per la prova confermativa v2 (decision_rule_v2.py), senza
toccare asr_eval/work (sola lettura) e senza modificare il codice di asr_eval.

  copy     copia in work_fresh/ SOLO audit.json, audit_overrides.json, subs/
  plan     asr_bench.build_plan con, IN MEMORIA: seme WINDOW_RULES['seed'] =
           20260925 e candidati filtrati: esclusa ogni finestra che si
           sovrapponga (stesso film, margine 10 s = pad 5 s + ricerca
           sincronia 3 s + 2 s) a una delle 140 finestre di
           asr_eval/work/windows.jsonl (che includono le 107 di valutazione e
           le 33 di tuning della v1). Solo EN, gruppi main + secondary
           (esclusi dev archive/skylines = tuning v1, report_only macbeth).
           win_id con tag 'fNN' per non confonderli con quelli del banco.
  prepare  asr_bench.cmd_prepare su work_fresh (sandbox config + guardia GPU,
           estrazione audio + Demucs vocals + sincronia + chunk).

Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe fresh_bench.py copy|plan|prepare
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for p in (str(ASR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import asr_bench as AB  # noqa: E402  (importa per primo sandbox)

SRC_WORK = ASR / 'work'
WORK = HERE / 'work_fresh'
SEED = 20260925
MARGIN_S = 10.0
GROUPS = ('main', 'secondary')


def used_intervals():
    used = {}
    for l in (SRC_WORK / 'windows.jsonl').read_text(encoding='utf-8').splitlines():
        if l.strip():
            w = json.loads(l)
            used.setdefault(w['film'], []).append((float(w['t0']), float(w['t1'])))
    return used


def overlaps(a, b, used_list, margin=MARGIN_S):
    return any(not (b <= u0 - margin or a >= u1 + margin) for u0, u1 in used_list)


def cmd_copy(_a) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for f in ('audit.json', 'audit_overrides.json'):
        shutil.copyfile(SRC_WORK / f, WORK / f)
    if not (WORK / 'subs').exists():
        shutil.copytree(SRC_WORK / 'subs', WORK / 'subs')
    print('copiati audit.json, audit_overrides.json, subs/ ->', WORK)
    return 0


def cmd_plan(_a) -> int:
    AB.DR.WINDOW_RULES['seed'] = SEED            # solo in memoria
    used = used_intervals()
    W = AB.W
    orig_cw = W.candidate_windows
    orig_sel = W.select_windows
    stats = {}

    def sel(cues, duration, lang, rules, seed_key, n_extra=0):
        ul = used.get(seed_key, [])

        def cw(c, r):
            all_c = orig_cw(c, r)
            keep = [(a, b) for a, b in all_c if not overlaps(a, b, ul)]
            stats[seed_key] = {'candidati': len(all_c), 'esclusi_sovrapposti': len(all_c) - len(keep),
                               'finestre_usate': len(ul)}
            return keep
        W.candidate_windows = cw
        try:
            return orig_sel(cues, duration, lang, rules, seed_key, n_extra)
        finally:
            W.candidate_windows = orig_cw

    W.select_windows = sel
    try:
        audit = AB.read_json(WORK / 'audit.json')
        plan = AB.build_plan(WORK, audit)
    finally:
        W.select_windows = orig_sel
    keep = {}
    dropped = []
    for fl, p in plan['film_langs'].items():
        if p['lang'] != 'en' or p['group'] not in GROUPS:
            dropped.append(f"{fl} (gruppo {p['group']})")
            continue
        wins = []
        for w in p['windows']:
            if w['role'] != 'test':
                continue
            assert not overlaps(w['t0'], w['t1'], used.get(p['film'], [])), w['win_id']
            w = dict(w, tag=f"f{w['idx']:02d}", win_id=f"en__{p['film']}__f{w['idx']:02d}")
            wins.append(w)
        p = dict(p, windows=wins, n_valid_bands=len(wins))
        keep[fl] = p
    plan = {'schema': plan['schema'], 'film_langs': keep, 'blocked': [],
            'fresh': {'seed': SEED, 'margin_s': MARGIN_S, 'groups': GROUPS, 'dropped_film_langs': dropped,
                      'blocked_original': plan['blocked'], 'overlap_stats': stats}}
    AB.RN.write_json_atomic(WORK / 'plan.json', plan)
    n = 0
    for fl, p in keep.items():
        n += len(p['windows'])
        print(f"  {fl:<42} {p['group']:<10} finestre {len(p['windows'])}  {stats.get(p['film'])}")
    print(f"scartati: {dropped}")
    print(f"totale finestre nuove: {n} su {len(keep)} film")
    return 0


def cmd_prepare(_a) -> int:
    AB.DR.WINDOW_RULES['seed'] = SEED
    ns = argparse.Namespace(work=WORK, allow_blocked=True, films=None, force=False)
    return AB.cmd_prepare(ns)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['copy', 'plan', 'prepare'])
    a = ap.parse_args()
    return {'copy': cmd_copy, 'plan': cmd_plan, 'prepare': cmd_prepare}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
