# -*- coding: utf-8 -*-
"""
Fase 3 — Stadio A (venv spaCy): analizza le ipotesi NLLB del corpus film
col selettore di produzione e salva i token di genere riferiti al parlante.

Legge results/film_detail_nllb_ft_film_1a_persona.tsv (output di
measure_film_gender.py) e produce results/rewrite_targets.json:
    [{"i": <row index>, "tokens": [["andato","M"], ...]}, ...]

Uso (venv spaCy):
    ./gender_eval/.venv_spacy/Scripts/python.exe gender_eval/analyze_rewrite_targets.py
"""
import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS = SCRIPT_DIR / "results"

spec = importlib.util.spec_from_file_location(
    'gender_line_selector', PROJECT_ROOT / 'core' / 'gender_line_selector.py')
sel = importlib.util.module_from_spec(spec)
sys.modules['gender_line_selector'] = sel
spec.loader.exec_module(sel)

if not sel.available():
    sys.exit("spaCy non disponibile")

import argparse
ap = argparse.ArgumentParser(); ap.add_argument('--tag', default='nllb_ft_film_1a_persona')
ap.add_argument('--person', choices=['1','2'], default='1')
a = ap.parse_args()
detail = RESULTS / f"film_detail_{a.tag}.tsv"
rows = list(csv.DictReader(open(detail, encoding='utf-8'), delimiter='\t'))
out = []
for i, r in enumerate(rows):
    fn = sel.addressee_gendered_tokens if a.person == '2' else sel.speaker_gendered_tokens
    toks = fn(r['nllb_hyp'])
    out.append({'i': i, 'tokens': toks})
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(rows)}", flush=True)

with open(RESULTS / f'rewrite_targets_{a.tag}.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)

n_with = sum(1 for o in out if o['tokens'])
print(f"Analizzate {len(rows)} ipotesi NLLB: {n_with} con forme 1ª persona rilevate")
print(f"Output: {RESULTS / 'rewrite_targets.json'}")
