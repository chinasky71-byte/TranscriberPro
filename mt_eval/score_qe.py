"""
Punteggio di quality estimation (COMET-Kiwi) sulle traduzioni
==============================================================
Gira nel venv DEDICATO `venv_comet`, non in quello di produzione:
`unbabel-comet` pinna numpy < 2.0 e retrocederebbe numpy 2.3.5 → 1.26.4,
rompendo torch/ctranslate2/faster-whisper. Stesso motivo per cui NeMo vive in
`venv_canary`.

COMET-Kiwi è *reference-free*: dà un punteggio 0-1 a ogni coppia
(originale, traduzione) senza bisogno di una traduzione umana. È quello che
serve a runtime per decidere quali blocchi far rifare a un motore migliore.

Uso:
    venv_comet\\Scripts\\python mt_eval\\score_qe.py --tr tr_nllb_finetuned.jsonl
    venv_comet\\Scripts\\python mt_eval\\score_qe.py --tr ... --out qe_nllb.jsonl

Output: JSONL {"id": int, "qe": float}
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
EVALSET = os.path.join(SCRIPT_DIR, "evalset.jsonl")

# Il modello di riferimento è `Unbabel/wmt22-cometkiwi-da`, ma il repo è gated
# e richiede di accettare la licenza sulla pagina del modello. In attesa,
# `wmt21-comet-qe-da` è della stessa famiglia (reference-free), una generazione
# più vecchia e quindi più debole: se il segnale di instradamento si vede con
# questo, con CometKiwi si vedrà almeno altrettanto. È una validazione
# conservativa, non un ripiego che gonfia il risultato.
MODEL = "zwhe99/wmt21-comet-qe-da"
MODEL_PREFERRED = "Unbabel/wmt22-cometkiwi-da"


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def hf_token():
    """Il repo è gated: serve il token già salvato nella config dell'app."""
    cfg = os.path.expanduser("~/.transcriberpro/config.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            return json.load(f).get("huggingface_token") or None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tr", required=True,
                    help="JSONL delle traduzioni da valutare")
    ap.add_argument("--src", default=EVALSET,
                    help="JSONL con i campi source/id")
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--model", default=MODEL,
                    help=f"default {MODEL}; il preferito è {MODEL_PREFERRED} "
                         f"ma richiede di accettare la licenza su HuggingFace")
    args = ap.parse_args()

    tr_path = args.tr if os.path.isabs(args.tr) else os.path.join(SCRIPT_DIR, args.tr)
    out_path = args.out or os.path.join(
        SCRIPT_DIR, "qe_" + os.path.basename(tr_path))

    sources = {d["id"]: d["source"] for d in load_jsonl(args.src)}
    trans = {d["id"]: d.get("text", d.get("reference", ""))
             for d in load_jsonl(tr_path)}
    ids = sorted(i for i in sources if i in trans)
    print(f"Segmenti da valutare: {len(ids)}")

    token = hf_token()
    if token:
        os.environ.setdefault("HF_TOKEN", token)

    from comet import download_model, load_from_checkpoint

    print(f"Modello: {args.model}")
    path = download_model(args.model, saving_directory=os.path.join(
        ROOT_DIR, "models", ".cache", "comet"))
    model = load_from_checkpoint(path)

    data = [{"src": sources[i], "mt": trans[i]} for i in ids]
    import torch
    gpus = 1 if torch.cuda.is_available() else 0
    out = model.predict(data, batch_size=args.batch, gpus=gpus,
                        progress_bar=True)

    scores = out["scores"] if isinstance(out, dict) else out.scores
    with open(out_path, "w", encoding="utf-8") as f:
        for i, s in zip(ids, scores):
            f.write(json.dumps({"id": i, "qe": round(float(s), 5)}) + "\n")

    avg = sum(scores) / len(scores)
    lo = sorted(scores)[: max(1, len(scores) // 10)]
    print(f"\n  punteggio medio      : {avg:.4f}")
    print(f"  media del 10% peggiore: {sum(lo) / len(lo):.4f}")
    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    main()
