"""
Verdetto della prova confermativa v4 (decision_rule_v5.py) sulle finestre NUOVE.
Legge: work_full5/windows.jsonl (riferimenti), work_full5_runs/{raw,off,on}/.
Scrive: work_full5_runs/verdict_v5.json. Solo CPU.

Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe analyze_v5.py
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

import argparse  # noqa: E402
import importlib  # noqa: E402
_ap = argparse.ArgumentParser()
_ap.add_argument('--set', default='taratura', choices=['taratura', 'conferma'])
_ap.add_argument('--rule', default='decision_rule_it2', help='modulo della regola (nome file senza .py)')
_ARGS = _ap.parse_args()
R2 = importlib.import_module(_ARGS.rule)

HERE = Path(__file__).resolve().parent
FRESH = HERE / 'work_it2'
RUNS = HERE / 'work_it2_runs'


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
    sha = hashlib.sha256((HERE / (_ARGS.rule + '.py')).read_bytes()).hexdigest()
    frozen = (HERE / (_ARGS.rule + '.sha256')).read_text().split()[0]
    print(f"regola v5 sha256 {sha[:16]} ({'INVARIATA' if sha == frozen else 'MODIFICATA!'})")
    import metrics as M
    import analyze as A
    import test_support as TS
    O = C.orig_split_mod().orig_split
    eng_off = TS.engine_method(False)

    allw = C.read_jsonl(FRESH / 'windows.jsonl')
    sel_ids = {i['id'] for i in json.loads((HERE / 'work_it2' / 'selection_it2.json').read_text(encoding='utf-8'))['items']
               if i['set'] == _ARGS.set}
    wins = [w for w in allw if w['win_id'] in sel_ids]
    controls = []
    import select_full as SF
    words = SF.excluded_words()
    n_excluded = sum(1 for w in wins if SF.is_excluded(w['title'], words))
    n_overlaps = 0
    pf = {}
    srt_dir = HERE / 'work_it2' / 'srt'
    srt_dir.mkdir(parents=True, exist_ok=True)

    agg = {a: dict(fmt_n=0, fmt_den=0, we=0, wn=0, n=0, gt84=0, cps20=0, gt2=0, gt9=0, lt1=0, lt15=0)
           for a in ('old', 'new')}
    words_identical = True
    native_bad = n_native = 0
    inword_bad = inword_glitch = 0
    multi_gt9 = single_gt9 = single_gt9_not_old = 0
    off_run_eq = on_run_eq = eng_eq = True
    missing = []
    films = set()
    n_win = 0
    pro = dict(n=0, lt1=0, lt15=0, dur=0.0)
    promid = [0, 0]
    tot_dur = 0.0
    for w in wins:
        try:
            raw, off, on = load('raw', w['win_id']), load('off', w['win_id']), load('on', w['win_id'])
        except FileNotFoundError:
            missing.append(w['win_id'])
            continue
        n_win += 1
        films.add(w['film'])
        tot_dur += w['dur']
        pf[w['win_id']] = dict(pro_n=0, dur=w['dur'])
        _pb = [{'start': c['s'], 'end': c['e'], 'text': c['text']} for c in w['cues'] if not (c.get('music') or c.get('sound_only'))]
        _sp = C.midcut_stats(_pb, 'it')
        promid[0] += _sp['n_midcut']; promid[1] += _sp['n_blocks']
        for cq in w['cues']:
            if cq.get('music') or cq.get('sound_only'):
                continue
            dq = cq['e'] - cq['s']
            pro['n'] += 1
            pf[w['win_id']]['pro_n'] += 1
            pro['lt1'] += dq < 1.0
            pro['lt15'] += dq < 1.5
        segs = {'old': off['segments'], 'new': on['segments']}
        # (e) + coerenza
        exp_off = C.round_segments([p for s in raw['segments'] for p in O(s)])
        exp_on = C.round_segments([p for s in raw['segments'] for p in A.split_new(s, lang='it')])
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
            pieces = A.split_new(s, lang='it')
            joined = pieces[0]['text'] if pieces else ''
            for prev_, pc_ in zip(pieces, pieces[1:]):
                att_ = not pc_['words'][0]['word'][:1].isspace()
                if att_:
                    if pc_['words'][0]['start'] - prev_['words'][-1]['end'] >= 9.0:
                        inword_glitch += 1
                    else:
                        inword_bad += 1
                joined += ('' if att_ else ' ') + pc_['text']
            if norm(joined) != norm(s['text']):
                native_bad += 1
        nw = lambda q: sum(1 for k_, x_ in enumerate(q['words']) if k_ == 0 or x_['word'][:1].isspace())
        old_single = {(p['start'], p['end']) for p in segs['old'] if nw(p) == 1}
        for p in segs['new']:
            d = p['end'] - p['start']
            if d > R2.MAX_PIECE_DUR_S:
                if nw(p) >= 2:
                    multi_gt9 += 1
                else:
                    single_gt9 += 1
                    if (p['start'], p['end']) not in old_single:
                        single_gt9_not_old += 1
        for a in ('old', 'new'):
            bl = C.formatter_blocks(segs[a])
            st = C.midcut_stats(bl, 'it')
            bs = blocks_stats(bl)
            g = agg[a]
            g['fmt_n'] += st['n_midcut']
            g['fmt_den'] += st['n_blocks']
            pf[w['win_id']][a + '_midcut'] = st['n_midcut'] / max(1, st['n_blocks'])
            pf[w['win_id']][a + '_per_min'] = bs['n'] / (w['dur'] / 60.0)
            s2 = [{'start': float(x['start']), 'end': float(x['end']), 'text': str(x.get('text', '')),
                   **({'words': x['words']} if x.get('words') else {})} for x in segs[a]]
            (srt_dir / f"{w['win_id']}.{'attuale' if a == 'old' else 'nuovo'}.srt").write_text(
                C.prodmods_mod().SubtitleFormatter(readability=True).format_srt(s2), encoding='utf-8')
            for k in ('n', 'gt84', 'cps20', 'gt2', 'gt9', 'lt1', 'lt15'):
                g[k] += bs[k]

    def summ(g):
        n = max(1, g['n'])
        return {'fmt_midcut': g['fmt_n'] / max(1, g['fmt_den']), 'werc': g['we'] / max(1, g['wn']),
                'gt84': g['gt84'] / n, 'cps20': g['cps20'] / n, 'n_gt2lines': g['gt2'], 'n_gt9s': g['gt9'],
                'lt1': g['lt1'] / n, 'n_lt1': g['lt1'], 'n_lt15': g['lt15'], 'lt15_share': g['lt15'] / n,
                'per_min': g['n'] / max(1e-9, tot_dur / 60.0), 'n_blocks': g['n'], 'raw': g}
    ctl_ok, ctl_detail = True, []
    for cw in controls:
        try:
            a_, b_ = load('off', cw['win_id']), load('on', cw['win_id'])
        except FileNotFoundError:
            ctl_ok = False
            ctl_detail.append(f"{cw['win_id']}: run mancanti")
            continue
        same = a_['segments'] == b_['segments']
        ctl_ok &= same and len(a_['segments']) > 0
        ctl_detail.append(f"{cw['title']} ({cw['lang']}): {len(a_['segments'])} segmenti, off == on: {same}")
    per_file = {k: {'old_midcut': v['old_midcut'], 'new_midcut': v['new_midcut'], 'new_per_min': v['new_per_min'],
                'old_per_min': v['old_per_min'], 'pro_per_min': v['pro_n'] / (v['dur'] / 60.0)} for k, v in pf.items()}
    m = {'n_windows': n_win, 'n_films': len(films), 'n_overlaps': n_overlaps, 'missing': missing,
         'pro_midcut': promid[0] / max(1, promid[1]),
         'n_excluded_titles': n_excluded, 'per_file': per_file,
         'n_controls': len(controls), 'control_ok': ctl_ok, 'control_detail': '; '.join(ctl_detail),
         'old': summ(agg['old']), 'new': summ(agg['new']),
         'pro': {'n_cues': pro['n'], 'lt1': pro['lt1'] / max(1, pro['n']), 'lt15': pro['lt15'] / max(1, pro['n']),
                 'per_min': pro['n'] / max(1e-9, tot_dur / 60.0), 'tot_dur_s': tot_dur},
         'words_identical': words_identical, 'native_text_ok': native_bad == 0,
         'native_text_bad': native_bad, 'n_native': n_native,
         'multiword_pieces_gt9s': multi_gt9, 'singleword_pieces_gt9s': single_gt9,
         'singleword_gt9s_not_in_old': single_gt9_not_old,
         'off_identical': off_run_eq and eng_eq,
         'off_identical_detail': f"run GPU off == split originale offline: {off_run_eq}; metodo motore spento == "
                                 f"originale: {eng_eq}; (coerenza) run GPU on == ricostruzione offline: {on_run_eq}",
         'on_run_consistent': on_run_eq, 'rule_sha256': sha}
    m['native_text_bad_exact'] = native_bad
    m['inword_cuts_bad'] = inword_bad
    m['inword_cuts_glitch'] = inword_glitch
    for fn, keys in ((f'pos_{_ARGS.set}.json', ('pos_ratio', 'pos_detail')),
                     ('regression_check.json', ('en_regression_ok', 'it_default_ok'))):
        fp = HERE / 'work_it2' / fn
        if fp.exists():
            j = json.loads(fp.read_text(encoding='utf-8'))
            for k in keys:
                m[k] = j.get(k)
    v = R2.verdict(m)
    print(f"finestre {n_win}, film {len(films)}, mancanti {len(missing)}")
    for k, (ok, det) in v['criteria'].items():
        print(f"  [{'OK' if ok else 'NO'}] {k}: {det}")
    print(f"  [info] midcut professionali (it): {m['pro_midcut']:.4f}; rapporto midcut nuova/attuale: {m['new']['fmt_midcut'] / max(1e-9, m['old']['fmt_midcut']):.3f}")
    print(f"VERDETTO v5: {v['verdict']}")
    m['verdict'] = {'criteria': {k: list(x) for k, x in v['criteria'].items()}, 'verdict': v['verdict']}
    (RUNS / f'verdict_it_{_ARGS.set}.json').write_text(json.dumps(m, indent=1, default=str), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
