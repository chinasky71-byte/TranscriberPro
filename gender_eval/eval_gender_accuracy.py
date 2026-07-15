# -*- coding: utf-8 -*-
"""
Fase 0 — Harness di valutazione gender accuracy (MT-GenEval EN→IT).

Pipeline:
  1. traduce le frasi inglesi del benchmark MT-GenEval con NLLB fine-tuned
     (stessi parametri della pipeline: beam da config, no_repeat_ngram=3,
      max_length=256, fp16 su GPU);
  2. confronta le forme marcate prodotte con quelle attese usando la metrica
     ufficiale MT-GenEval (word-set: una frase è errata se contiene parole
     esclusive del riferimento del genere sbagliato);
  3. produce le due percentuali: accuratezza sulle forme FEMMINILI e MASCHILI.

Il benchmark counterfactual contiene la stessa frase in variante maschile e
femminile: il sistema viene valutato su entrambe, quindi misura sia il bias
(femminile ≪ maschile) sia la capacità di rispettare il genere indicato nel
testo sorgente.

Uso:
    python gender_eval/eval_gender_accuracy.py                # traduce + valuta (test set)
    python gender_eval/eval_gender_accuracy.py --limit 20     # smoke test
    python gender_eval/eval_gender_accuracy.py --mode score \
        --hyp-masculine out_m.txt --hyp-feminine out_f.txt    # valuta ipotesi esterne
                                                              # (es. output del gender corrector)

Output in gender_eval/results/: ipotesi, results.json, failures_{m,f}.tsv.
"""
import argparse
import json
import re
import string
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = SCRIPT_DIR / "mt_geneval" / "data" / "sentences"

# ---------------------------------------------------------------------------
# Metrica ufficiale MT-GenEval (replica di accuracy_metric.py, Amazon Science)
# con una sola aggiunta: normalizzazione dell'apostrofo tipografico, perché
# NLLB produce a volte ’ mentre i riferimenti usano ' (evita falsi negativi).
# ---------------------------------------------------------------------------

_STRIP_PUNCT = str.maketrans(string.punctuation, ' ' * len(string.punctuation))


def clean_line(line: str) -> str:
    line = line.replace('’', "'").replace('“', '"').replace('”', '"')
    return line.lower().translate(_STRIP_PUNCT).strip()


def get_words(line: str) -> set:
    return set(line.strip().split())


def gender_decision(hyp: str, correct_ref: str, wrong_ref: str):
    """Ritorna (decisione, parole_sbagliate_trovate). Tutte le stringhe già clean."""
    hyp_w, cor_w, wrg_w = get_words(hyp), get_words(correct_ref), get_words(wrong_ref)
    wrong_unique = wrg_w - cor_w
    found_wrong = hyp_w & wrong_unique
    return ('Incorrect' if found_wrong else 'Correct'), found_wrong


# ---------------------------------------------------------------------------
# Caricamento dati benchmark
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r'</?[MF]>')


def load_lines(path: Path) -> list:
    with open(path, 'r', encoding='utf-8') as f:
        return [line.rstrip('\n') for line in f]


def load_benchmark(split: str) -> dict:
    """
    Ritorna {'masculine': {'en': [...], 'it': [...], 'it_annotated': [...]},
             'feminine':  {...}}
    Se i file non annotati non esistono (split dev), la sorgente viene
    derivata da quelli annotati rimuovendo i tag <M>/<F>.
    """
    data = {}
    for gender in ('masculine', 'feminine'):
        plain_en = DATA_DIR / split / f"geneval-sentences-{gender}-{split}.en_it.en"
        plain_it = DATA_DIR / split / f"geneval-sentences-{gender}-{split}.en_it.it"
        ann_en = DATA_DIR / split / "annotated" / f"geneval-sentences-{gender}-{split}.en_it.en"
        ann_it = DATA_DIR / split / "annotated" / f"geneval-sentences-{gender}-{split}.en_it.it"

        if plain_en.exists():
            en = load_lines(plain_en)
        else:
            en = [_TAG_RE.sub('', line) for line in load_lines(ann_en)]
        if plain_it.exists():
            it = load_lines(plain_it)
        else:
            it = [_TAG_RE.sub('', line) for line in load_lines(ann_it)]

        entry = {'en': en, 'it': it}
        if ann_it.exists():
            entry['it_annotated'] = load_lines(ann_it)
        data[gender] = entry

    n_m, n_f = len(data['masculine']['en']), len(data['feminine']['en'])
    if n_m != n_f:
        raise ValueError(f"Benchmark disallineato: {n_m} maschili vs {n_f} femminili")
    return data


# ---------------------------------------------------------------------------
# Traduzione con NLLB fine-tuned (parametri identici a core/translator.py)
# ---------------------------------------------------------------------------

def translate_nllb_ft(texts: list, batch_size: int, num_beams: int,
                      model_path: str, device_choice: str = 'auto') -> list:
    import torch
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    use_gpu = device_choice != 'cpu' and torch.cuda.is_available()
    print(f"Caricamento NLLB fine-tuned da: {model_path}")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer.src_lang = 'eng_Latn'

    if use_gpu:
        free_vram_gb = torch.cuda.mem_get_info()[0] / 1024 ** 3
        print(f"VRAM libera: {free_vram_gb:.1f} GB")
        if free_vram_gb < 7.0:
            raise RuntimeError(
                f"VRAM insufficiente ({free_vram_gb:.1f} GB < 7 GB) per NLLB-3.3B fp16. "
                "Chiudi le app che usano la GPU o usa --device cpu.")
        model = AutoModelForSeq2SeqLM.from_pretrained(
            model_path, dtype=torch.float16, device_map="auto",
            low_cpu_mem_usage=True)
    else:
        print("Esecuzione su CPU (lenta).")
        model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
    model.eval()

    forced_bos = tokenizer.convert_tokens_to_ids('ita_Latn')
    device = next(model.parameters()).device
    out = []
    t0 = time.time()
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inputs = tokenizer(batch, return_tensors="pt", padding=True,
                           truncation=True, max_length=256).to(device)
        with torch.no_grad():
            gen = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos,
                num_beams=num_beams,
                no_repeat_ngram_size=3,
                max_length=256)
        out.extend(tokenizer.batch_decode(gen, skip_special_tokens=True))
        done = min(i + batch_size, len(texts))
        rate = done / max(time.time() - t0, 1e-6)
        eta = (len(texts) - done) / max(rate, 1e-6)
        print(f"  Tradotte {done}/{len(texts)} ({rate:.1f} frasi/s, ETA {eta:.0f}s)",
              flush=True)

    del model
    import gc
    gc.collect()
    if use_gpu:
        torch.cuda.empty_cache()
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_gender(hyps: list, correct_refs: list, wrong_refs: list,
                 sources: list, failures_tsv: Path) -> dict:
    assert len(hyps) == len(correct_refs) == len(wrong_refs), \
        f"Lunghezze diverse: hyp={len(hyps)} ref={len(correct_refs)} ctf={len(wrong_refs)}"
    n_correct = 0
    failures = []
    for idx, (hyp, cor, wrg) in enumerate(zip(hyps, correct_refs, wrong_refs)):
        decision, found_wrong = gender_decision(
            clean_line(hyp), clean_line(cor), clean_line(wrg))
        if decision == 'Correct':
            n_correct += 1
        else:
            failures.append((idx, sources[idx], hyp, ' '.join(sorted(found_wrong))))

    with open(failures_tsv, 'w', encoding='utf-8') as f:
        f.write("index\tsource_en\thypothesis_it\twrong_gender_words_found\n")
        for row in failures:
            f.write('\t'.join(str(c) for c in row) + '\n')

    total = len(hyps)
    return {
        'total': total,
        'correct': n_correct,
        'incorrect': total - n_correct,
        'accuracy': n_correct / total if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Gender accuracy NLLB-FT su MT-GenEval EN→IT")
    ap.add_argument('--mode', choices=['full', 'translate', 'score'], default='full')
    ap.add_argument('--split', choices=['test', 'dev'], default='test')
    ap.add_argument('--limit', type=int, default=0,
                    help='Valuta solo le prime N frasi (smoke test)')
    ap.add_argument('--batch-size', type=int, default=16)
    ap.add_argument('--num-beams', type=int, default=0,
                    help='Default: nllb_num_beams dalla config (7)')
    ap.add_argument('--device', choices=['auto', 'cpu'], default='auto')
    ap.add_argument('--out-dir', type=str, default=str(SCRIPT_DIR / 'results'))
    ap.add_argument('--tag', type=str, default='nllb_ft_baseline',
                    help='Etichetta della configurazione valutata (nei nomi file)')
    ap.add_argument('--hyp-masculine', type=str, default=None,
                    help='(mode=score) file ipotesi per il set maschile, una per riga')
    ap.add_argument('--hyp-feminine', type=str, default=None,
                    help='(mode=score) file ipotesi per il set femminile, una per riga')
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_benchmark(args.split)
    limit = args.limit if args.limit > 0 else None
    if limit:
        for g in data:
            for k in data[g]:
                data[g][k] = data[g][k][:limit]
    n = len(data['masculine']['en'])
    print(f"Benchmark MT-GenEval EN→IT, split={args.split}: {n} frasi per genere")

    hyp_files = {
        'masculine': out_dir / f"hyp_{args.tag}_{args.split}_masculine.txt",
        'feminine': out_dir / f"hyp_{args.tag}_{args.split}_feminine.txt",
    }

    # --- Traduzione ---
    if args.mode in ('full', 'translate'):
        num_beams = args.num_beams
        model_path = None
        if not num_beams or not model_path:
            from utils.config import get_config
            cfg = get_config()
            if not num_beams:
                num_beams = cfg.get('nllb_num_beams', 7)
            model_path = cfg.get('nllb_finetuned_model_path', '')
        if not model_path or not Path(model_path).exists():
            raise FileNotFoundError(f"Modello NLLB fine-tuned non trovato: '{model_path}'")
        print(f"Parametri generazione: beams={num_beams}, no_repeat_ngram=3, max_length=256")

        # Un unico caricamento modello per entrambi i set
        all_texts = data['masculine']['en'] + data['feminine']['en']
        translations = translate_nllb_ft(
            all_texts, args.batch_size, num_beams, model_path, args.device)
        split_at = len(data['masculine']['en'])
        per_gender = {'masculine': translations[:split_at],
                      'feminine': translations[split_at:]}
        for gender, hyp_path in hyp_files.items():
            with open(hyp_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(per_gender[gender]) + '\n')
            print(f"Ipotesi salvate: {hyp_path}")

    if args.mode == 'translate':
        return

    # --- Scoring ---
    if args.mode == 'score':
        if not args.hyp_masculine or not args.hyp_feminine:
            ap.error("--mode score richiede --hyp-masculine e --hyp-feminine")
        hyp_files = {'masculine': Path(args.hyp_masculine),
                     'feminine': Path(args.hyp_feminine)}

    results = {'benchmark': f"MT-GenEval en_it {args.split}", 'tag': args.tag,
               'limit': limit, 'genders': {}}
    for gender, other in (('masculine', 'feminine'), ('feminine', 'masculine')):
        hyps = load_lines(hyp_files[gender])
        if limit:
            hyps = hyps[:limit]
        res = score_gender(
            hyps,
            correct_refs=data[gender]['it'],
            wrong_refs=data[other]['it'],
            sources=data[gender]['en'],
            failures_tsv=out_dir / f"failures_{args.tag}_{args.split}_{gender}.tsv")
        results['genders'][gender] = res

    # Accuratezza combinata (stessa frase corretta in ENTRAMBE le varianti),
    # come nello script ufficiale MT-GenEval.
    m_hyps = load_lines(hyp_files['masculine'])
    f_hyps = load_lines(hyp_files['feminine'])
    if limit:
        m_hyps, f_hyps = m_hyps[:limit], f_hyps[:limit]
    both = 0
    for i in range(len(m_hyps)):
        d_m, _ = gender_decision(clean_line(m_hyps[i]),
                                 clean_line(data['masculine']['it'][i]),
                                 clean_line(data['feminine']['it'][i]))
        d_f, _ = gender_decision(clean_line(f_hyps[i]),
                                 clean_line(data['feminine']['it'][i]),
                                 clean_line(data['masculine']['it'][i]))
        if d_m == d_f == 'Correct':
            both += 1
    results['combined_accuracy'] = both / len(m_hyps) if m_hyps else 0.0

    results_path = out_dir / f"results_{args.tag}_{args.split}.json"
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    fem = results['genders']['feminine']
    mas = results['genders']['masculine']
    print()
    print("=" * 58)
    print(f"  RISULTATI — {args.tag} — MT-GenEval en_it {args.split}")
    print("=" * 58)
    print(f"  Accuratezza forme FEMMINILI : {fem['accuracy']*100:6.2f}%  "
          f"({fem['correct']}/{fem['total']})")
    print(f"  Accuratezza forme MASCHILI  : {mas['accuracy']*100:6.2f}%  "
          f"({mas['correct']}/{mas['total']})")
    print(f"  Accuratezza combinata (M∧F) : {results['combined_accuracy']*100:6.2f}%")
    print("=" * 58)
    print(f"  Dettagli errori: failures_*.tsv in {out_dir}")
    print(f"  JSON: {results_path}")


if __name__ == '__main__':
    main()
