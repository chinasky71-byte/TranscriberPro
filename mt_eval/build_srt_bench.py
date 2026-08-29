"""
Banco di valutazione da 3 SRT già su disco (EN, motore A, motore B)
====================================================================
Variante di build_film_bench.py per episodi dove le tracce sono già SRT di
testo pulito su disco (non serve ffprobe/OCR, niente traccia bitmap da
riconoscere): riusa senza modifiche parse_srt() e align() da
build_film_bench.py.

Non esiste una traduzione professionale di riferimento per questi file (a
differenza dei film con traccia italiana embedded): il campo "reference"
riporta l'output del primo motore (--ref-engine, default nllb) — un
termine di paragone fra i due motori, non una verità di traduzione.

Uso:
    venv\\Scripts\\python mt_eval\\build_srt_bench.py ^
        --en "...eng.srt" --nllb "...it.srt" --tgemma "...it.gemma.srt" ^
        --name knightsmagic_ep01 --category anime
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from build_film_bench import parse_srt, align  # noqa: E402

# La traccia inglese di questo rip porta markup di stile letterale
# ("<font face=...><b>...</b></font>") su quasi ogni blocco — non è testo
# di dialogo, e un giudice GEMBA lo leggerebbe come parte del source.
_HTML_TAG_RE = re.compile(r"</?(?:font|b|i|u)(?:\s[^>]*)?>", re.IGNORECASE)


def strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", required=True, help="SRT inglese (source)")
    ap.add_argument("--nllb", required=True, help="SRT italiano motore NLLB")
    ap.add_argument("--tgemma", required=True, help="SRT italiano motore TGemma")
    ap.add_argument("--name", required=True, help="suffisso dei file di output")
    ap.add_argument("--category", default="anime")
    ap.add_argument("--ref-engine", choices=["nllb", "tgemma"], default="nllb",
                     help="quale motore va nel campo 'reference' del banco")
    args = ap.parse_args()

    en_blocks = parse_srt(args.en)
    nllb_blocks = parse_srt(args.nllb)
    tgemma_blocks = parse_srt(args.tgemma)
    print(f"EN: {len(en_blocks)} blocchi | NLLB: {len(nllb_blocks)} | "
          f"TGemma: {len(tgemma_blocks)}")

    tagged = sum(1 for _, _, t in en_blocks if _HTML_TAG_RE.search(t))
    if tagged:
        print(f"  ripulito markup <font>/<b>/<i> in {tagged} blocchi EN "
              f"({tagged * 100 // max(len(en_blocks), 1)}%): non e' dialogo")
        en_blocks = [(a, b, strip_html(t)) for a, b, t in en_blocks]

    pairs_nllb = align(en_blocks, nllb_blocks)
    pairs_tgemma = align(en_blocks, tgemma_blocks)
    n_en = max(len(en_blocks), 1)
    print(f"Allineati con NLLB   : {len(pairs_nllb)}/{len(en_blocks)} "
          f"({len(pairs_nllb) * 100 // n_en}%)")
    print(f"Allineati con TGemma : {len(pairs_tgemma)}/{len(en_blocks)} "
          f"({len(pairs_tgemma) * 100 // n_en}%)")

    # Chiave (start, end) del blocco EN sorgente: identica nei due
    # allineamenti perché entrambi partono dagli stessi en_blocks.
    by_key_nllb = {(p["start"], p["end"]): p for p in pairs_nllb}
    by_key_tgemma = {(p["start"], p["end"]): p for p in pairs_tgemma}
    common_keys = sorted(set(by_key_nllb) & set(by_key_tgemma))
    print(f"Intersezione (allineati su ENTRAMBI i motori): {len(common_keys)}")

    ref_map = by_key_nllb if args.ref_engine == "nllb" else by_key_tgemma

    bench, tr_nllb, tr_tgemma = [], [], []
    for i, key in enumerate(common_keys, 1):
        p_nllb, p_tgemma, p_ref = by_key_nllb[key], by_key_tgemma[key], ref_map[key]
        bench.append({
            "id": i, "start": p_ref["start"], "end": p_ref["end"],
            "source": p_ref["source"], "reference": p_ref["reference"],
            "category": args.category,
        })
        tr_nllb.append({"id": i, "text": p_nllb["reference"]})
        tr_tgemma.append({"id": i, "text": p_tgemma["reference"]})

    out_bench = os.path.join(SCRIPT_DIR, f"filmset_{args.name}.jsonl")
    out_nllb = os.path.join(SCRIPT_DIR, f"tr_{args.name}_nllb.jsonl")
    out_tgemma = os.path.join(SCRIPT_DIR, f"tr_{args.name}_tgemma.jsonl")

    for path, rows in ((out_bench, bench), (out_nllb, tr_nllb),
                        (out_tgemma, tr_tgemma)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nScritti ({len(bench)} righe ciascuno):\n  {out_bench}\n"
          f"  {out_nllb}\n  {out_tgemma}")


if __name__ == "__main__":
    main()
