"""
Verdetto della prova confermativa (decision_rule_v2.py) sulle finestre NUOVE.
Legge: work_fresh/windows.jsonl (riferimenti), work_fresh_runs/{raw,off,on}/.
Scrive: work_fresh_runs/verdict_v2.json. Solo CPU.

Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe analyze_v2.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import common as C

ASR = C.ROOT / 'asr_eval'
if str(ASR) not in sys.path:
    sys.path.insert(0, str(ASR))

import decision_rule_v2 as R2  # noqa: E402

HERE = Path(__file__).resolve().parent
FRESH = HERE / 'work_fresh'
RUNS = HERE / 'work_fresh_runs'


def norm(t: str) -> str:
    return ' '.join(t.split())


def load(mode, wid):
    return json.loads((RUNS / mode / f'{wid}.json').read_text(encoding='utf-8'))


def blocks_stats(blocks):
    n = len(blocks)
    s = dict(n=n, gt84=0, cps20=0, gt2=0, gt9=0, lt1=0, lt15=0)
    for b in blocks:
        lines = [l for l in b['text'].split('\n') if l.strip()]
        ch = len(' '.join(lines))
        d = b['end'] - b['start']
        s['gt84'] += ch > 84
        s['cps20'] += d > 0 and ch / d > 20
        s['gt2'] += len(lines) > 2
        s['gt9'] += d > 9.0
        s['lt1'] += d < 1.0
        s['lt15'] += d < 1.5
    return s


def main() -> int:
    sha = hashlib.sha256((HERE / 'decision_rule_v2.py').read_bytes()).hexdigest()
    frozen = (HERE / 'decision_rule_v2.sha256').read_text().split()[0]
    print(f"regola v2 sha256 {sha[:16]} ({'INVARIATA' if sha == frozen else 'MODIFICATA!'})")
    import metrics as M
    import analyze as A
    import test_support as TS
    O = C.orig_split_mod().orig_split
    eng_off = TS.engine_method(False)

    wins = C.read_jsonl(FRESH / 'windows.jsonl')
    used = {}
    for w in C.windows():
        used.setdefault(w['film'], []).append((w['t0'], w['t1']))
    n_overlaps = sum(1 for w in wins for u0, u1 in used.get(w['film'], [])
                     if not (w['t1'] <= u0 or w['t0'] >= u1))

    agg = {a: dict(fmt_n=0, fmt_den=0, we=0, wn=0, n=0, gt84=0, cps20=0, gt2=0, gt9=0, lt1=0, lt15=0)
           for a in ('old', 'new')}
    words_identical = True
    native_bad = n_native = 0
    multi_gt9 = single_gt9 = single_gt9_not_old = 0
    off_run_eq = on_run_eq = eng_eq = True
    missing = []
    films = set()
    n_win = 0
    for w in wins:
        try:
            raw, off, on = load('raw', w['win_id']), load('off', w['win_id']), load('on', w['win_id'])
        except FileNotFoundError:
            missing.append(w['win_id'])
            continue
        n_win += 1
        films.add(w['film'])
        segs = {'old': off['segments'], 'new': on['segments']}
        # (e) + coerenza
        exp_off = C.round_segments([p for s in raw['segments'] for p in O(s)])
        exp_on = C.round_segments([p for s in raw['segments'] for p in A.split_new(s)])
        off_run_eq &= (off['segments'] == exp_off)
        on_run_eq &= (on['segments'] == exp_on)
        for s in raw['segments']:
            eng_eq &= (eng_off(s) == O(s))
        # (b') parole
        fw = {a: [(x['start'], x['end'], x['word']) for s in segs[a] for x in s['words']] for a in segs}
        words_identical &= fw['old'] == fw['new']
        # (b') testo per segmento nativo, (d') pezzi
        for s in raw['segments']:
            n_native += 1
            pieces = A.split_new(s)
            if norm(' '.join(p['text'] for p in pieces)) != norm(s['text']):
                native_bad += 1
        old_single = {(p['start'], p['end']) for p in segs['old'] if len(p['words']) == 1}
        for p in segs['new']:
            d = p['end'] - p['start']
            if d > R2.MAX_PIECE_DUR_S:
                if len(p['words']) >= 2:
                    multi_gt9 += 1
                else:
                    single_gt9 += 1
                    if (p['start'], p['end']) not in old_single:
                        single_gt9_not_old += 1
        for a in ('old', 'new'):
            bl = C.formatter_blocks(segs[a])
            st = C.midcut_stats(bl)
            bs = blocks_stats(bl)
            sc = M.score_window(w['cues'], segs[a], 'en', names=set(w.get('names') or []), dur_s=w['dur'])
            g = agg[a]
            g['fmt_n'] += st['n_midcut']
            g['fmt_den'] += st['n_blocks']
            g['we'] += sc['Sc'] + sc['Dc'] + sc['Ic']
            g['wn'] += sc['n_ref_c']
            for k in ('n', 'gt84', 'cps20', 'gt2', 'gt9', 'lt1', 'lt15'):
                g[k] += bs[k]

    def summ(g):
        n = max(1, g['n'])
        return {'fmt_midcut': g['fmt_n'] / max(1, g['fmt_den']), 'werc': g['we'] / max(1, g['wn']),
                'gt84': g['gt84'] / n, 'cps20': g['cps20'] / n, 'n_gt2lines': g['gt2'], 'n_gt9s': g['gt9'],
                'lt1': g['lt1'] / n, 'n_lt1': g['lt1'], 'n_lt15': g['lt15'], 'n_blocks': g['n'], 'raw': g}
    m = {'n_windows': n_win, 'n_films': len(films), 'n_overlaps': n_overlaps, 'missing': missing,
         'old': summ(agg['old']), 'new': summ(agg['new']),
         'words_identical': words_identical, 'native_text_ok': native_bad == 0,
         'native_text_bad': native_bad, 'n_native': n_native,
         'multiword_pieces_gt9s': multi_gt9, 'singleword_pieces_gt9s': single_gt9,
         'singleword_gt9s_not_in_old': single_gt9_not_old,
         'off_identical': off_run_eq and eng_eq,
         'off_identical_detail': f"run GPU off == split originale offline: {off_run_eq}; metodo motore spento == "
                                 f"originale: {eng_eq}; (coerenza) run GPU on == ricostruzione offline: {on_run_eq}",
         'on_run_consistent': on_run_eq, 'rule_sha256': sha}
    v = R2.verdict(m)
    print(f"finestre {n_win}, film {len(films)}, mancanti {len(missing)}")
    for k, (ok, det) in v['criteria'].items():
        print(f"  [{'OK' if ok else 'NO'}] {k}: {det}")
    print(f"VERDETTO v2: {v['verdict']}")
    m['verdict'] = {'criteria': {k: list(x) for k, x in v['criteria'].items()}, 'verdict': v['verdict']}
    (RUNS / 'verdict_v2.json').write_text(json.dumps(m, indent=1, default=str), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
