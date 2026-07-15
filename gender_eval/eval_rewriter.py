# -*- coding: utf-8 -*-
"""
Fase 3 — Stadio B (venv APP): valuta i motori di riscrittura sul corpus film.

Flusso per ogni riga del corpus (ipotesi NLLB già generata):
  1. token 1ª persona rilevati dal selettore (rewrite_targets.json, stadio A);
  2. genere target = ground-truth del sub professionale (simula una Speaker
     Gender Map perfetta; la mappa reale è al 95% → l'end-to-end scala di
     conseguenza);
  3. se il testo esprime un genere diverso dal target → riscrivi col motore;
  4. VALIDATORE deterministico: riscritture non plausibili → originale;
  5. ri-scoring con le forme correct/wrong del ground-truth.

Motori: 'rule' (flip morfologico, zero modelli) e 'llm' (GGUF locale).

Uso:
    ./venv/Scripts/python.exe gender_eval/eval_rewriter.py --engines rule
    ./venv/Scripts/python.exe gender_eval/eval_rewriter.py --engines rule,llm
"""
import argparse
import csv
import importlib.util
import json
import string
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
RESULTS = SCRIPT_DIR / "results"

_STRIP_PUNCT = str.maketrans(string.punctuation, ' ' * len(string.punctuation))


def norm_words(line: str) -> set:
    line = line.replace('’', "'").lower().translate(_STRIP_PUNCT)
    return set(line.split())


def load_rewriter_module():
    spec = importlib.util.spec_from_file_location(
        'gender_rewriter', PROJECT_ROOT / 'core' / 'gender_rewriter.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['gender_rewriter'] = mod
    spec.loader.exec_module(mod)
    return mod


def score_row(hyp: str, correct_form: str, wrong_form: str) -> str:
    words = norm_words(hyp)
    has_c = correct_form in words
    has_w = wrong_form in words
    if has_c and not has_w:
        return 'CORRECT'
    if has_w:
        return 'WRONG'
    return 'NOT_FOUND'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engines', default='rule', help='rule,llm')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    rw = load_rewriter_module()

    detail = RESULTS / "film_detail_nllb_ft_film_1a_persona.tsv"
    rows = list(csv.DictReader(open(detail, encoding='utf-8'), delimiter='\t'))
    targets = {o['i']: o['tokens']
               for o in json.load(open(RESULTS / "rewrite_targets.json",
                                       encoding='utf-8'))}
    if args.limit:
        rows = rows[:args.limit]

    engines = []
    for name in args.engines.split(','):
        name = name.strip()
        if name == 'rule':
            engines.append(rw.RuleRewriter())
        elif name == 'llm':
            from utils.config import get_config
            mp = get_config().get('gender_correction_model_path', '')
            eng = rw.LlamaRewriter(mp, log_callback=lambda m: print(m, flush=True))
            if not eng.load():
                sys.exit("LLM non caricabile")
            engines.append(eng)
        else:
            sys.exit(f"Motore sconosciuto: {name}")

    report = {}
    for eng in engines:
        stats = {'F': {'CORRECT': 0, 'WRONG': 0, 'NOT_FOUND': 0},
                 'M': {'CORRECT': 0, 'WRONG': 0, 'NOT_FOUND': 0}}
        esiti = {'rewritten': 0, 'unchanged': 0, 'rejected': 0, 'no_output': 0}
        detail_out = RESULTS / f"rewriter_detail_{eng.name}.tsv"
        with open(detail_out, 'w', encoding='utf-8') as f:
            f.write("gender\tesito_rewrite\tesito_score\tnllb_hyp\tfinal_hyp\n")
            for i, r in enumerate(rows):
                target = r['gender']
                tokens = [tuple(t) for t in targets.get(i, [])]
                final, esito = rw.apply_rewrite(
                    eng, r['nllb_hyp'], r['eng_source'], target, tokens)
                esiti[esito] += 1
                sc = score_row(final, r['correct_form'], r['wrong_form'])
                stats[target][sc] += 1
                f.write(f"{target}\t{esito}\t{sc}\t{r['nllb_hyp']}\t{final}\n")
                if eng.name == 'llm' and (i + 1) % 25 == 0:
                    print(f"  {i+1}/{len(rows)}", flush=True)

        def acc(g):
            s = stats[g]
            tot = s['CORRECT'] + s['WRONG']
            return (s['CORRECT'] / tot if tot else 0.0), s['CORRECT'], tot

        af, cf, tf = acc('F')
        am, cm, tm = acc('M')
        report[eng.name] = {'accuracy_f': af, 'accuracy_m': am,
                            'stats': stats, 'esiti': esiti}
        print()
        print("=" * 62)
        print(f"  MOTORE '{eng.name}' — riscrittura 1ª persona (corpus film)")
        print("=" * 62)
        print(f"  Accuratezza FEMMINILE : {af*100:6.2f}%  ({cf}/{tf})")
        print(f"  Accuratezza MASCHILE  : {am*100:6.2f}%  ({cm}/{tm})")
        print(f"  Esiti: {esiti}")
        print(f"  Dettaglio: {detail_out}")

        if hasattr(eng, 'unload'):
            eng.unload()

    with open(RESULTS / "results_rewriter.json", 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
