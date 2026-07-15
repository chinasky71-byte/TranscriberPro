# -*- coding: utf-8 -*-
"""
A/B end-to-end su un episodio reale (default VM S01E01):
  A = traduzione NLLB completa dell'SRT inglese (come STEP 6 pipeline);
  B = A + GenderCorrectorV2 via CLI subprocess (STEP 6.5 di produzione).
Scoring su TUTTI i candidati del ground-truth (P1 + P2) dell'episodio,
con le forme correct/wrong derivate dal sub professionale.

Uso: ./venv/Scripts/python.exe gender_eval/ab_test_episode.py [--episode S01E01]
"""
import argparse
import csv
import json
import re
import string
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))
RESULTS = SCRIPT_DIR / "results"

_STRIP = str.maketrans(string.punctuation, ' ' * len(string.punctuation))
_TS = re.compile(r'(\d+)\s*\n([\d:,\.]+)\s*-->\s*([\d:,\.]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|\Z)',
                 re.MULTILINE)


def ts2s(ts):
    h, m, rest = ts.replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse(path):
    txt = Path(path).read_text(encoding='utf-8', errors='replace')
    return [(m.group(2).strip(), m.group(3).strip(),
             re.sub(r'\s+', ' ', re.sub(r'<[^>]+>|\[[^\]]+\]', '', m.group(4))).strip())
            for m in _TS.finditer(txt) if m.group(4).strip()]


def flip(w):
    w = w.lower()
    return (w[:-1] + 'o') if w.endswith('a') else ((w[:-1] + 'a') if w.endswith('o') else None)


def score(cues, gt_rows):
    ok = wrong = nf = 0
    for r in gt_rows:
        t0 = ts2s(r['start'])
        best = None
        for (s, e, txt) in cues:
            if abs(ts2s(s) - t0) < 1.0:
                best = txt
                break
        if best is None:
            nf += 1
            continue
        words = set(best.replace('’', "'").lower().translate(_STRIP).split())
        c, w = r['marker'].lower(), flip(r['marker'])
        if not w:
            nf += 1
        elif c in words and w not in words:
            ok += 1
        elif w in words:
            wrong += 1
        else:
            nf += 1
    return ok, wrong, nf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode', default='S01E01')
    args = ap.parse_args()

    ep = args.episode
    video = next(Path('V:/Veronica Mars/Season 1').glob(f'*{ep}*.mkv'))
    stem = video.stem
    eng_srt = SCRIPT_DIR / 'film_groundtruth' / '_tmp' / f'{stem}.eng.srt'
    if not eng_srt.exists():
        sys.exit(f"SRT inglese mancante: {eng_srt}")

    # A: traduzione NLLB completa
    cues = parse(eng_srt)
    print(f"Episodio {ep}: {len(cues)} cue inglesi da tradurre")
    from eval_gender_accuracy import translate_nllb_ft
    from utils.config import get_config
    cfg = get_config()
    hyps = translate_nllb_ft([c[2] for c in cues], 16,
                             cfg.get('nllb_num_beams', 7),
                             cfg.get('nllb_finetuned_model_path', ''))
    srt_a = RESULTS / f'ab_{ep}_A.srt'
    with open(srt_a, 'w', encoding='utf-8') as f:
        for i, ((s, e, _), h) in enumerate(zip(cues, hyps), 1):
            f.write(f"{i}\n{s} --> {e}\n{h}\n\n")
    print(f"A salvato: {srt_a}")

    # B: corrector v2 via CLI di produzione
    srt_b = RESULTS / f'ab_{ep}_B.srt'
    args_json = RESULTS / f'ab_{ep}_args.json'
    args_json.write_text(json.dumps({
        'input_srt': str(srt_a), 'output_srt': str(srt_b),
        'video_path': str(video)}), encoding='utf-8')
    print("Eseguo GenderCorrectorV2 (CLI di produzione)...")
    proc = subprocess.run(
        [str(PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe'),
         '-m', 'core.gender_corrector_cli', str(args_json)],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(PROJECT_ROOT), timeout=3600)
    for line in (proc.stdout or '').splitlines():
        if any(k in line for k in ('candidate', 'Correzione', 'Selettore', 'Genere')):
            print(f"  {line.strip()}")
    if proc.returncode != 0 or not srt_b.exists():
        sys.exit(f"Corrector fallito (exit {proc.returncode})\n{proc.stdout[-800:]}")

    # Scoring su GT P1+P2 dell'episodio
    gt_rows = []
    for d in ('film_groundtruth', 'film_groundtruth_p2'):
        for tsv in (SCRIPT_DIR / d).glob(f'*{ep}*.tsv'):
            with open(tsv, encoding='utf-8') as f:
                for r in csv.DictReader(f, delimiter='\t'):
                    if r['gender'] in ('F', 'M'):
                        r['person'] = '1' if d == 'film_groundtruth' else '2'
                        gt_rows.append(r)
    print(f"\nGround-truth: {len(gt_rows)} candidati (P1+P2)")

    ca, cb = parse(srt_a), parse(srt_b)
    for gset, label in ((gt_rows, 'TUTTI'),
                        ([r for r in gt_rows if r['gender'] == 'F'], 'FEMMINILI'),
                        ([r for r in gt_rows if r['gender'] == 'M'], 'MASCHILI')):
        a = score(ca, gset)
        b = score(cb, gset)
        am = a[0] + a[1]
        bm = b[0] + b[1]
        pa = a[0] / am * 100 if am else 0
        pb = b[0] / bm * 100 if bm else 0
        print(f"  {label:10s}: A (solo NLLB) {pa:5.1f}% ({a[0]}/{am})  ->  "
              f"B (+corrector) {pb:5.1f}% ({b[0]}/{bm})")


if __name__ == '__main__':
    main()
