"""
COMET sulle unita' fuse, braccio A e braccio B nello STESSO run.
Gira SOLO nel venv dedicato venv_comet (unbabel-comet pinna numpy<2, come
spiegato in mt_eval/score_qe.py), su GPU: lanciarlo a coda libera, tramite
    venv\\Scripts\\python.exe split_eval\\run_split_bench.py score --comet
che verifica prima che la GPU sia libera.

Metodo come mt_eval/score_qe.py: download_model(... saving_directory=
models/.cache/comet), load_from_checkpoint, predict(batch_size, gpus).
Default: Unbabel/wmt22-comet-da (CON riferimento: e' la metrica di record;
al primo uso lo scarica, ~2,3 GB). CometKiwi (senza riferimento, gia' in
cache) solo come diagnostica: mette ultimo il traduttore umano.

Input  : units_<motore>.jsonl {id, source, a, b, reference}
Output : comet_<motore>.jsonl {id, a, b}
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF_MODELS = {"Unbabel/wmt22-comet-da"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="Unbabel/wmt22-comet-da")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    with open(args.units, encoding="utf-8") as f:
        units = [json.loads(l) for l in f if l.strip()]
    needs_ref = args.model in REF_MODELS
    if needs_ref:
        units = [u for u in units if u.get("reference")]
    print(f"Unita' da valutare: {len(units)} (modello {args.model})")
    if not units:
        return 0

    cfg = os.path.expanduser("~/.transcriberpro/config.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            tok = json.load(f).get("huggingface_token")
        if tok:
            os.environ.setdefault("HF_TOKEN", tok)

    from comet import download_model, load_from_checkpoint
    path = download_model(args.model, saving_directory=os.path.join(ROOT, "models", ".cache", "comet"))
    model = load_from_checkpoint(path)
    import torch
    gpus = 1 if torch.cuda.is_available() else 0

    def rows(side):
        return [{"src": u["source"], "mt": u[side], **({"ref": u["reference"]} if needs_ref else {})}
                for u in units]

    data = rows("a") + rows("b")                   # un solo predict: stesso run per i due bracci
    out = model.predict(data, batch_size=args.batch, gpus=gpus, progress_bar=True)
    scores = out["scores"] if isinstance(out, dict) else out.scores
    n = len(units)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for u, sa, sb in zip(units, scores[:n], scores[n:]):
            f.write(json.dumps({"id": u["id"], "a": round(float(sa), 5), "b": round(float(sb), 5),
                                "model": args.model}) + "\n")
    os.replace(tmp, args.out)
    print(f"Output: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
