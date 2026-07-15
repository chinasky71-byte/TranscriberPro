# -*- coding: utf-8 -*-
"""
Baseline del Gender Corrector ATTUALE su MT-GenEval EN→IT.

Prende le ipotesi NLLB già generate (hyp_*_masculine.txt / _feminine.txt),
le impacchetta come SRT (con la sorgente inglese allineata come original_srt),
lancia `GenderCorrectionEngine.correct_file()` e riscrive le ipotesi corrette,
pronte per lo scoring con eval_gender_accuracy.py --mode score.

CAVEAT (onestà metodologica):
- MT-GenEval sono frasi Wikipedia indipendenti, non un film → character_context
  è VUOTO (nessun cast TMDB) e il contesto prev/next tra frasi è rumore.
  Quindi questo misura la capacità del corrector di correggere il genere dal
  SOLO testo inglese sorgente. Sugli errori di MT-GenEval (she/chairwoman →
  "il presidente") è comunque il segnale giusto: se il corrector funziona,
  dovrebbe recuperarli.

Uso:
    python gender_eval/run_corrector_baseline.py --split test
    # poi:
    python gender_eval/eval_gender_accuracy.py --mode score --tag corrector_attuale \
        --hyp-masculine gender_eval/results/corr_test_masculine.txt \
        --hyp-feminine  gender_eval/results/corr_test_feminine.txt
"""
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS = SCRIPT_DIR / "results"


def _ts(i: int) -> str:
    """Timestamp SRT fittizio ma valido, 2s per cue a partire da 0."""
    start = i * 2
    end = start + 1
    def fmt(s):
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{sec:02d},000"
    return f"{fmt(start)} --> {fmt(end)}"


def write_srt(lines, path: Path):
    with open(path, 'w', encoding='utf-8') as f:
        for i, text in enumerate(lines):
            f.write(f"{i+1}\n{_ts(i)}\n{text.strip()}\n\n")


def read_srt_texts(path: Path, n_expected: int):
    """Rilegge i testi da un SRT generato, in ordine di indice."""
    import re
    content = Path(path).read_text(encoding='utf-8')
    pattern = r'(\d+)\s*\n[\d:,]+\s*-->\s*[\d:,]+\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|\Z)'
    out = {}
    for m in re.finditer(pattern, content, re.MULTILINE):
        out[int(m.group(1))] = m.group(2).strip().replace('\n', ' ')
    return [out.get(i+1, '') for i in range(n_expected)]


def load_lines(path: Path):
    with open(path, 'r', encoding='utf-8') as f:
        return [l.rstrip('\n') for l in f]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='test', choices=['test', 'dev'])
    ap.add_argument('--tag', default='corrector_attuale')
    ap.add_argument('--baseline-tag', default='nllb_ft_baseline',
                    help='tag delle ipotesi NLLB da correggere')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    # Import diretto dal file: evita core/__init__.py che carica tutta la
    # pipeline (torchaudio) inutilmente per questo task.
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "gender_corrector_standalone", PROJECT_ROOT / "core" / "gender_corrector.py")
    _gc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_gc)
    GenderCorrectionEngine = _gc.GenderCorrectionEngine
    LLAMA_CPP_AVAILABLE = _gc.LLAMA_CPP_AVAILABLE
    from utils.config import get_config

    if not LLAMA_CPP_AVAILABLE:
        sys.exit("llama-cpp-python non disponibile.")
    cfg = get_config()
    model_path = cfg.get('gender_correction_model_path', '')
    if not model_path or not Path(model_path).exists():
        sys.exit(f"Modello GGUF non trovato: {model_path}")

    data_dir = SCRIPT_DIR / "mt_geneval" / "data" / "sentences" / args.split
    tmp = RESULTS / "corr_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    engine = GenderCorrectionEngine(log_callback=log)

    out_files = {}
    for gender in ('masculine', 'feminine'):
        hyp_it = load_lines(RESULTS / f"hyp_{args.baseline_tag}_{args.split}_{gender}.txt")
        src_en = load_lines(data_dir / f"geneval-sentences-{gender}-{args.split}.en_it.en")
        if args.limit:
            hyp_it, src_en = hyp_it[:args.limit], src_en[:args.limit]
        n = len(hyp_it)
        assert len(src_en) >= n, f"src {len(src_en)} < hyp {n}"
        src_en = src_en[:n]

        it_srt = tmp / f"{gender}_it.srt"
        en_srt = tmp / f"{gender}_en.srt"
        corr_srt = tmp / f"{gender}_corrected.srt"
        write_srt(hyp_it, it_srt)
        write_srt(src_en, en_srt)

        log(f"\n===== Correzione {gender} ({n} frasi) =====")
        ok = engine.correct_file(
            it_srt, corr_srt,
            character_context={},
            original_srt_path=en_srt)
        if not ok:
            sys.exit(f"correct_file fallita su {gender}")

        corrected = read_srt_texts(corr_srt, n)
        out_path = RESULTS / f"corr_{args.split}_{gender}.txt"
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(corrected) + '\n')
        out_files[gender] = out_path
        log(f"Ipotesi corrette salvate: {out_path}")

    engine.cleanup()
    log("\nFatto. Ora valuta con:")
    log(f"  python gender_eval/eval_gender_accuracy.py --mode score --tag {args.tag} \\")
    log(f"      --hyp-masculine {out_files['masculine']} \\")
    log(f"      --hyp-feminine  {out_files['feminine']}")


if __name__ == '__main__':
    main()
