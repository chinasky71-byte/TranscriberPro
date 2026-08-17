"""
Estrae un campione rappresentativo dal banco su film.

Il film intero (1873 blocchi) costerebbe circa sette ore con il modello più
lento: per un confronto fra motori bastano poche centinaia di blocchi, purché
siano distribuiti su tutta la durata invece che presi dall'inizio — le prime
scene non rappresentano il film.

Il campionamento è a passo costante lungo la timeline: copre apertura, corpo
centrale e finale nella stessa proporzione, ed è riproducibile.

Uso:
    venv\\Scripts\\python mt_eval\\sample_film.py --n 400
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRONG = re.compile(
    r"cazz|merd|stronz|fanculo|porc[oa]|troi|figa|coglion|puttan|inculat|"
    r"bastard|vaffa|fott|incazz|minchi", re.I)
EN_PROF = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|bastard|cunt|dick|prick|"
    r"motherfuck\w*|goddamn)\b", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="filmset_deadpool2.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--n", type=int, default=400)
    args = ap.parse_args()

    src = os.path.join(SCRIPT_DIR, args.src)
    out = os.path.join(SCRIPT_DIR,
                       args.out or args.src.replace(".jsonl", "_sample.jsonl"))

    items = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    items.sort(key=lambda d: d["start"])
    n = min(args.n, len(items))
    step = len(items) / n
    picked = [items[int(i * step)] for i in range(n)]

    for i, p in enumerate(picked, 1):
        p["id"] = i

    with open(out, "w", encoding="utf-8") as f:
        for p in picked:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    dur = sum(p["end"] - p["start"] for p in picked) / n
    src_len = sum(len(p["source"].replace("\n", " ")) for p in picked) / n
    ref_len = sum(len(p["reference"].replace("\n", " ")) for p in picked) / n
    prof_en = sum(1 for p in picked if EN_PROF.search(p["source"]))
    prof_it = sum(1 for p in picked if STRONG.search(p["reference"]))
    over_cpl = sum(1 for p in picked
                   if any(len(l) > 42 for l in p["reference"].split("\n")))
    over_cps = sum(1 for p in picked if (p["end"] - p["start"]) > 0
                   and len(p["reference"].replace("\n", " "))
                   / (p["end"] - p["start"]) > 17.0)

    print(f"Campione: {n} blocchi su {len(items)} "
          f"(dal minuto {picked[0]['start'] / 60:.0f} al "
          f"{picked[-1]['end'] / 60:.0f})")
    print(f"  durata media blocco : {dur:.2f}s")
    print()
    print("BERSAGLIO DI STILE — cosa fa il traduttore professionista")
    print(f"  caratteri, inglese  : {src_len:.1f}")
    print(f"  caratteri, italiano : {ref_len:.1f}   rapporto {ref_len / src_len:.2f}")
    print(f"  righe oltre 42 car  : {over_cpl * 100 // n}%")
    print(f"  blocchi oltre 17 CPS: {over_cps * 100 // n}%")
    print(f"  turpiloquio         : {prof_it}/{prof_en} blocchi volgari resi "
          f"con una volgarità")
    print(f"\nScritto: {out}")


if __name__ == "__main__":
    main()
