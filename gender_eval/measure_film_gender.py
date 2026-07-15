# -*- coding: utf-8 -*-
"""
Misura la gender accuracy di NLLB fine-tuned sulla PRIMA PERSONA usando il
ground-truth estratto dai film (build_film_groundtruth.py).

Per ogni candidato del TSV (marker = forma italiana corretta, es. "arrabbiata"):
  1. genera la forma "sbagliata" flippando la desinenza di genere (-a ↔ -o);
     i marker non flippabili (invariabili, irregolari) vengono SKIPPATI;
  2. traduce la sorgente inglese con NLLB-FT (stessi parametri pipeline);
  3. metrica stile MuST-SHE: la traduzione contiene la forma corretta →
     CORRECT; contiene la forma sbagliata → WRONG; nessuna delle due →
     NOT_FOUND (fuori dal term coverage, tipico quando NLLB parafrasa).

Output: accuratezza su forme F e M in 1ª persona + TSV dettagliato.

NOTA: il genere qui NON è deducibile dal testo inglese ("I went..."):
l'accuratezza attesa di NLLB sul femminile è vicino a 0 (default maschile).
Questo è il numero che la Fase 1+3 (speaker gender map + riscrittura) deve
alzare — la controparte 1ª persona della baseline MT-GenEval.

Uso (venv APP, serve torch/transformers — NON il venv spaCy):
    ./venv/Scripts/python.exe gender_eval/measure_film_gender.py
    ./venv/Scripts/python.exe gender_eval/measure_film_gender.py --limit 10
"""
import argparse
import csv
import json
import re
import string
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = SCRIPT_DIR / "film_groundtruth"
RESULTS = SCRIPT_DIR / "results"

_STRIP_PUNCT = str.maketrans(string.punctuation, ' ' * len(string.punctuation))


def norm_words(line: str) -> set:
    line = line.replace('’', "'").lower().translate(_STRIP_PUNCT)
    return set(line.split())


def flip_gender(word: str):
    """Ritorna la controparte di genere flippando la desinenza, o None se
    non flippabile in modo affidabile (invariabili, irregolari, plurali)."""
    w = word.lower()
    if len(w) < 3:
        return None
    if w.endswith('a'):
        return w[:-1] + 'o'
    if w.endswith('o'):
        return w[:-1] + 'a'
    return None   # -e invariabile (felice), forme irregolari: skip


def load_candidates(limit_per_file: int = 0):
    """Carica tutti i TSV del ground-truth. Ritorna lista di dict."""
    cands = []
    for tsv in sorted(GT_DIR.glob("*.tsv")):
        with open(tsv, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        if limit_per_file:
            rows = rows[:limit_per_file]
        for r in rows:
            r['file'] = tsv.stem
            cands.append(r)
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='max candidati totali (smoke)')
    ap.add_argument('--batch-size', type=int, default=16)
    ap.add_argument('--tag', default='nllb_ft_film_1a_persona')
    args = ap.parse_args()

    cands = load_candidates()
    # tieni solo candidati con marker flippabile e genere noto
    usable = []
    for c in cands:
        if c['gender'] not in ('F', 'M'):
            continue
        wrong = flip_gender(c['marker'])
        if not wrong:
            continue
        c['correct_form'] = c['marker'].lower()
        c['wrong_form'] = wrong
        usable.append(c)
    if args.limit:
        usable = usable[:args.limit]

    n_f = sum(1 for c in usable if c['gender'] == 'F')
    n_m = len(usable) - n_f
    print(f"Candidati totali: {len(cands)} | usabili (marker flippabile): "
          f"{len(usable)} (F:{n_f} M:{n_m})")

    # --- Traduzione NLLB (riusa la stessa funzione dell'harness MT-GenEval) ---
    from eval_gender_accuracy import translate_nllb_ft
    from utils.config import get_config
    cfg = get_config()
    model_path = cfg.get('nllb_finetuned_model_path', '')
    num_beams = cfg.get('nllb_num_beams', 7)
    if not model_path or not Path(model_path).exists():
        sys.exit(f"Modello NLLB-FT non trovato: {model_path}")
    print(f"Generazione: beams={num_beams}")

    texts = [c['eng_source'] for c in usable]
    hyps = translate_nllb_ft(texts, args.batch_size, num_beams, model_path)

    # --- Scoring ---
    stats = {'F': {'correct': 0, 'wrong': 0, 'not_found': 0},
             'M': {'correct': 0, 'wrong': 0, 'not_found': 0}}
    RESULTS.mkdir(exist_ok=True)
    detail_tsv = RESULTS / f"film_detail_{args.tag}.tsv"
    with open(detail_tsv, 'w', encoding='utf-8') as f:
        f.write("file\tstart\tgender\tcorrect_form\twrong_form\tesito\t"
                "ita_reference\teng_source\tnllb_hyp\n")
        for c, hyp in zip(usable, hyps):
            words = norm_words(hyp)
            has_c = c['correct_form'] in words
            has_w = c['wrong_form'] in words
            if has_c and not has_w:
                esito = 'CORRECT'
            elif has_w:
                esito = 'WRONG'
            else:
                esito = 'NOT_FOUND'
            stats[c['gender']][esito.lower() if esito != 'NOT_FOUND' else 'not_found'] += 1
            f.write(f"{c['file'][:40]}\t{c['start']}\t{c['gender']}\t"
                    f"{c['correct_form']}\t{c['wrong_form']}\t{esito}\t"
                    f"{c['ita_reference']}\t{c['eng_source']}\t{hyp}\n")

    def acc(g):
        s = stats[g]
        tot = s['correct'] + s['wrong']
        return (s['correct'] / tot if tot else 0.0), tot

    acc_f, tot_f = acc('F')
    acc_m, tot_m = acc('M')
    cov = (tot_f + tot_m) / len(usable) if usable else 0

    print()
    print("=" * 62)
    print(f"  1ª PERSONA (film ground-truth) — {args.tag}")
    print("=" * 62)
    print(f"  Accuratezza FEMMINILE : {acc_f*100:6.2f}%  "
          f"({stats['F']['correct']}/{tot_f} misurabili, "
          f"{stats['F']['not_found']} not-found)")
    print(f"  Accuratezza MASCHILE  : {acc_m*100:6.2f}%  "
          f"({stats['M']['correct']}/{tot_m} misurabili, "
          f"{stats['M']['not_found']} not-found)")
    print(f"  Term coverage         : {cov*100:6.2f}%")
    print("=" * 62)
    print(f"  Dettaglio: {detail_tsv}")

    with open(RESULTS / f"results_{args.tag}.json", 'w', encoding='utf-8') as f:
        json.dump({'tag': args.tag, 'stats': stats,
                   'accuracy_f': acc_f, 'accuracy_m': acc_m,
                   'coverage': cov, 'n_usable': len(usable)},
                  f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
