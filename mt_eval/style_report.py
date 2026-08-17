"""
Aderenza al bersaglio di stile del traduttore professionista
=============================================================
Misura quanto l'output di ogni motore somiglia, NELLE SCELTE DI MESTIERE, alla
traccia italiana professionale del film — non nelle parole scelte.

La distinzione è il punto di tutto il banco. Confrontare parola per parola con
una singola traduzione umana è l'errore del chrF: penalizza rese diverse ma
altrettanto valide, ed è il motivo per cui a luglio TranslateGemma-4B risultò
peggiore di quanto fosse. Quello che invece si può confrontare senza ambiguità
è il comportamento professionale misurabile:

  - quanto CONDENSA (rapporto caratteri italiano/inglese)
  - se rispetta i 42 caratteri per riga
  - a che reading speed si attesta (con i TEMPI VERI del film)
  - se conserva il turpiloquio invece di attenuarlo

Uso:
    venv\\Scripts\\python mt_eval\\style_report.py --set filmset_deadpool2_sample.jsonl
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CPL_MAX = 42
CPS_MAX = 17.0

STRONG_IT = re.compile(
    r"cazz|merd|stronz|fanculo|porc[oa]|troi|figa|coglion|puttan|inculat|"
    r"bastard|vaffa|fott|incazz|minchi", re.I)
PROF_EN = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|bastard|cunt|dick|prick|"
    r"motherfuck\w*|goddamn)\b", re.I)

ENGINES = [
    ("nllb", "NLLB fine-tuned"),
    ("aya", "Aya Expanse 8B"),
    ("tg", "TranslateGemma 12B"),
]


def load(path):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def measure(items, texts):
    n = len(items) or 1
    chars = cpl = cps = copied = empty = 0
    prof_src = prof_hit = 0
    for it in items:
        t = texts.get(it["id"], "")
        if not t.strip():
            empty += 1
            continue
        flat = t.replace("\n", " ")
        chars += len(flat)
        if any(len(l) > CPL_MAX for l in t.split("\n")):
            cpl += 1
        dur = max(0.001, float(it["end"]) - float(it["start"]))
        if len(flat) / dur > CPS_MAX:
            cps += 1
        if flat.strip() == it["source"].replace("\n", " ").strip():
            copied += 1
        if PROF_EN.search(it["source"]):
            prof_src += 1
            if STRONG_IT.search(t):
                prof_hit += 1
    src_chars = sum(len(it["source"].replace("\n", " ")) for it in items) / n
    return {
        "chars": chars / max(n - empty, 1),
        "ratio": (chars / max(n - empty, 1)) / max(src_chars, 1),
        "cpl": cpl * 100.0 / n,
        "cps": cps * 100.0 / n,
        "copied": copied,
        "empty": empty,
        "prof": (prof_hit, prof_src),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="filmset_deadpool2_sample.jsonl")
    ap.add_argument("--prefix", default="tr_film",
                    help="prefisso dei file di traduzione: tr_film, tr_otto")
    args = ap.parse_args()

    items = load(args.set)
    n = len(items)
    src_chars = sum(len(it["source"].replace("\n", " ")) for it in items) / n

    rows = []
    ref = measure(items, {it["id"]: it["reference"] for it in items})
    for key, label in ENGINES:
        filename = f"{args.prefix}_{key}.jsonl"
        path = os.path.join(SCRIPT_DIR, filename)
        if not os.path.isfile(path):
            print(f"  assente, salto: {filename}")
            continue
        texts = {d["id"]: d["text"] for d in load(path)}
        rows.append((label, measure(items, texts)))

    print("=" * 76)
    print(f"  ADERENZA AL BERSAGLIO DI STILE — {n} blocchi, tempi reali")
    print(f"  Sorgente inglese: {src_chars:.1f} caratteri per blocco")
    print("=" * 76)
    print(f"  {'':<22}{'car':>7}{'x EN':>8}{'>42car':>9}{'>17CPS':>9}"
          f"{'turpiloquio':>13}")
    print(f"  {'-' * 66}")
    ph, ps = ref["prof"]
    print(f"  {'PROFESSIONISTA':<22}{ref['chars']:7.1f}{ref['ratio']:8.2f}"
          f"{ref['cpl']:8.0f}%{ref['cps']:8.0f}%{f'{ph}/{ps}':>13}")
    print(f"  {'-' * 66}")
    for label, m in rows:
        ph, ps = m["prof"]
        print(f"  {label:<22}{m['chars']:7.1f}{m['ratio']:8.2f}"
              f"{m['cpl']:8.0f}%{m['cps']:8.0f}%{f'{ph}/{ps}':>13}")

    print()
    print("  DISTANZA DAL PROFESSIONISTA (più vicino a zero = meglio)")
    print(f"  {'':<22}{'Δ rapporto':>12}{'Δ CPS':>10}{'Δ turpiloquio':>15}")
    print(f"  {'-' * 60}")
    rph, rps = ref["prof"]
    for label, m in rows:
        ph, ps = m["prof"]
        d_prof = (ph / max(ps, 1) - rph / max(rps, 1)) * 100
        print(f"  {label:<22}{m['ratio'] - ref['ratio']:+12.2f}"
              f"{m['cps'] - ref['cps']:+9.0f}%{d_prof:+14.0f}%")

    print()
    print("  Il rapporto è la metrica che sorprende: il professionista rende")
    print("  l'italiano PIÙ CORTO dell'inglese (0,93-0,95 su due film), mentre")
    print("  l'istinto sarebbe di allungarlo. Condensare è il mestiere, e i")
    print("  motori che ci si avvicinano non lo fanno per caso.")
    print("=" * 76)


if __name__ == "__main__":
    main()
