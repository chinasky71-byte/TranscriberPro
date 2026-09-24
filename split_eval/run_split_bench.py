"""
split_eval - banco delle FRASI SPEZZATE (misura midcut + A/B di traduzione)
File: split_eval/run_split_bench.py

Uso (dalla cartella Transcriber_Pro, SEMPRE col venv principale):

    set PYTHONIOENCODING=utf-8
    venv\\Scripts\\python.exe split_eval\\run_split_bench.py <sottocomando> ...

Sottocomandi:
    midcut      quota di blocchi a meta' frase: sub professionali, segmenti
                ASR e blocchi del formatter (solo CPU)
    build       SRT sorgente come in produzione + unita' ricomposte (CPU; puo'
                leggere dal disco Z: per estrarre il sub ITA di riferimento)
    translate   UN motore, bracci A e B nello stesso processo (GPU: rifiuta se
                la GPU e' occupata o se gira Transcriber Pro)
    score       punteggi per finestra -> work/scores_split.csv (CPU);
                --comet (GPU, venv_comet) e --llm-judge (API A PAGAMENTO) facoltativi
    report      statistica e verdetto secondo decision_rules_split.py (CPU)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for _p in (str(ROOT), str(ASR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sandbox  # noqa: E402,F401  (per primo fra i moduli del banco)
import asr_bench as AB  # noqa: E402
import runners as RN  # noqa: E402

from split_eval import rules_select  # noqa: E402
DRS = rules_select.load()
from split_eval import midcut as MC  # noqa: E402
from split_eval import score_split as SS  # noqa: E402
from split_eval import translate_arms as TA  # noqa: E402

DEFAULT_WORK = HERE / 'work'


def emit(msg: str) -> None:
    print(msg, flush=True)


def _rate(st: Dict) -> str:
    if not st or not st.get('n_blocks'):
        return '-'
    return (f"{100 * st['n_midcut'] / st['n_blocks']:5.2f}% ({st['n_midcut']}/{st['n_blocks']})"
            f" [+puntini {st['n_ellipsis_cont']}, +,;: {st['n_softend_cont']}]")


def _sum(stats: List[Dict]) -> Dict:
    keys = ('n_blocks', 'n_midcut', 'n_ellipsis_cont', 'n_softend_cont', 'n_noend')
    return {k: sum(s.get(k, 0) for s in stats) for k in keys}


def midcut_report(asr_work: Path, with_formatter: bool = True) -> Dict:
    out: Dict = {'pro_subs': {}, 'windows': {}, 'hyp': {}}
    audit = AB.read_json(asr_work / 'audit.json', {}) or {}
    for key, e in sorted((audit.get('films') or {}).items()):
        for s in e.get('subs', []):
            p = asr_work / 'subs' / key / f"{s['index']}.srt"
            if not p.exists():
                continue
            lang = 'en' if s['lang'] == 'eng' else ('it' if s['lang'] == 'ita' else None)
            if not lang:
                continue
            bl = MC.srt_blocks(p.read_text(encoding='utf-8', errors='replace'))
            out['pro_subs'][f"{key}#{s['index']}"] = {'lang': lang, 'kind': s.get('kind'), **MC.midcut_stats(bl, lang)}
    wins = AB.read_jsonl(asr_work / 'windows.jsonl')
    for lang in ('en', 'it'):
        st = [MC.midcut_stats(w.get('cues', []), lang) for w in wins if w['lang'] == lang]
        if st:
            out['windows'][lang] = _sum(st)
    hyp_root = asr_work / 'hyp'
    wmap = {w['win_id']: w for w in wins}
    for hd in sorted(hyp_root.glob('*__*')) if hyp_root.exists() else []:
        raw, fmt = [], []
        for hp in sorted(hd.glob('*.json')):
            h = AB.read_json(hp)
            w = wmap.get(h.get('win_id'))
            if not w or h.get('status') not in ('ok', 'partial'):
                continue
            segs = h.get('segments') or []
            raw.append(MC.midcut_stats(segs, w['lang']))
            if with_formatter and segs:
                fmt.append(MC.midcut_stats(MC.formatter_blocks(segs), w['lang']))
        out['hyp'][hd.name] = {'segments': _sum(raw), 'formatter': _sum(fmt) if fmt else None, 'n_windows': len(raw)}
    return out


def cmd_midcut(args) -> int:
    rep = midcut_report(args.asr_work, not args.no_formatter)
    emit("MIDCUT — quota di blocchi che finiscono a meta' frase (definizione principale)")
    emit("\n(c) sottotitoli professionali, film interi:")
    for k, v in rep['pro_subs'].items():
        emit(f"   {k:<28} {v['lang']} {v['kind']:<9} {_rate(v)}")
    if rep['windows']:
        emit("\n(c) battute di riferimento delle finestre (windows.jsonl):")
        for lang, v in rep['windows'].items():
            emit(f"   {lang}: {_rate(v)}")
    else:
        emit("\n(c) windows.jsonl assente: finestre non ancora preparate (asr_eval plan + prepare)")
    if rep['hyp']:
        emit("\n(a) segmenti grezzi e (b) blocchi del formatter per motore/braccio:")
        for k, v in rep['hyp'].items():
            emit(f"   {k:<18} fin={v['n_windows']:<4} segmenti {_rate(v['segments'])}")
            emit(f"   {'':<18}          formatter {_rate(v['formatter'])}")
    else:
        emit("(a)/(b) nessuna ipotesi in asr_eval/work/hyp: lanciare prima asr_eval run")
    RN.write_json_atomic(args.work / 'midcut.json', rep)
    emit(f"\n✅ {args.work / 'midcut.json'}")
    return 0


def cmd_build(args) -> int:
    cfg = json.loads(args.recompose_config) if args.recompose_config else None
    films = [f.strip().lower() for f in args.films.split(',')] if args.films else None
    rows = TA.build(args.work, args.asr_work, args.asr, cfg, extract_it=not args.no_extract_it,
                    allow_pending_it=args.allow_pending_it, films=films, emit=emit)
    return 0 if rows else 2


def cmd_translate(args) -> int:
    return TA.translate(args.work, args.engine, limit=args.limit, llm_unit_budget=args.llm_unit_budget, emit=emit)


def cmd_score(args) -> int:
    SS.score(args.work, emit)
    engines = sorted(p.name for p in (args.work / 'out').glob('*') if p.is_dir()) if (args.work / 'out').exists() else []
    if args.comet:
        for e in engines:
            rc = SS.run_comet(args.work, e, args.comet_model, emit)
            if rc:
                emit(f"❌ COMET fallito su {e} (exit {rc})")
                return rc
        SS.score(args.work, emit)        # riaggrega con COMET
    if args.llm_judge:
        for e in engines:
            SS.run_gemba(args.work, e, args.provider, args.judge_limit, emit)
    return 0


def cmd_report(args) -> int:
    if not (args.work / 'scores_split.csv').exists():
        emit("❌ scores_split.csv mancante: lancia 'score' prima")
        return 2
    txt = SS.build_report(args.work)
    RN.write_text_atomic(args.work / 'report_split.txt', txt)
    emit(txt)
    return 0


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', type=Path, default=DEFAULT_WORK)
    p.add_argument('--asr-work', type=Path, default=TA.ASR_WORK, help="cartella work del banco asr_eval")
    sub = p.add_subparsers(dest='cmd', required=True)
    sm = sub.add_parser('midcut', help="misura midcut (CPU)")
    sm.add_argument('--no-formatter', action='store_true', help="salta i blocchi del formatter (b)")
    sb = sub.add_parser('build', help="SRT sorgente + unita' ricomposte (CPU)")
    sb.add_argument('--asr', default=DRS.ASR_SOURCE, help=f"ipotesi da tradurre (default {DRS.ASR_SOURCE})")
    sb.add_argument('--films', default=None)
    sb.add_argument('--recompose-config', default=None, help="JSON che sovrascrive recompose.DEFAULT_CONFIG")
    sb.add_argument('--no-extract-it', action='store_true', help="non estrarre dal video il sub ITA mancante")
    sb.add_argument('--allow-pending-it', action='store_true',
                    help="usa anche sub ITA con provenienza non ancora confermata")
    st = sub.add_parser('translate', help="un motore, bracci A e B (GPU)")
    st.add_argument('--engine', required=True, choices=sorted(TA.EXPECTED_CLASS))
    st.add_argument('--arm', default='both', choices=['both'],
                    help="A e B girano SEMPRE insieme nello stesso processo (stesso modello caricato)")
    st.add_argument('--limit', type=int, default=0)
    st.add_argument('--llm-unit-budget', default='span', choices=['span', 'prod'],
                    help="solo 'llm': budget caratteri delle unita' fuse (span = 84 x blocchi; prod = tetto 84)")
    sc = sub.add_parser('score', help="punteggi (CPU); COMET/GEMBA solo con i flag")
    sc.add_argument('--comet', action='store_true', help="COMET per unita' (GPU, venv_comet)")
    sc.add_argument('--comet-model', default='Unbabel/wmt22-comet-da')
    sc.add_argument('--llm-judge', action='store_true', help="GEMBA-MQM con mt_eval/run_gemba.py (A PAGAMENTO)")
    sc.add_argument('--provider', default='anthropic', choices=['anthropic', 'openai'])
    sc.add_argument('--judge-limit', type=int, default=0)
    sub.add_parser('report', help="statistica e verdetto (CPU)")
    args = p.parse_args(argv[1:])
    args.work = Path(args.work).resolve()
    args.asr_work = Path(args.asr_work).resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    return {'midcut': cmd_midcut, 'build': cmd_build, 'translate': cmd_translate, 'score': cmd_score,
            'report': cmd_report}[args.cmd](args)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv))
