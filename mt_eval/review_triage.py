"""
Quanto rende segnalare all'utente le battute dubbie
====================================================
CometKiwi è stato bocciato come *instradatore* — scegliere per ogni blocco il
motore migliore gli riesce nel 59% dei casi, poco più di una monetina. Ma
instradare e allertare sono due compiti diversi: per instradare serve indovinare
QUALE dei due è migliore; per allertare basta riconoscere che il blocco è
venuto male, e questo è il compito su cui la quality estimation è nata.

Qui si misura il compito giusto. Ordinando i blocchi dal punteggio QE più basso,
si sceglie una soglia (il 5%, il 10%, il 20% peggiore) e si guarda:

  copertura — quanta parte degli errori GRAVI trovati dal giudice finisce
              dentro la selezione. È il numero che dice se la revisione serve.
  precisione— quanta parte della selezione contiene davvero un errore grave.
              È il numero che dice quanto tempo si perde a leggere blocchi sani.

Il termine di paragone onesto NON è zero: è la selezione casuale. Se leggere il
10% dei blocchi a caso trova il 10% degli errori, un segnale che ne trova il 10%
non vale la fatica di implementarlo.

Uso:
    venv\\Scripts\\python mt_eval\\review_triage.py --qe qek_film_nllb.jsonl \\
        --gemba gemba_fnllb_vs_ftg.jsonl --side a
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEIGHT = {"minor": 1, "major": 5, "critical": 10}


def load(path):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qe", required=True, help="JSONL {id, qe}")
    ap.add_argument("--gemba", required=True)
    ap.add_argument("--side", default="a", choices=["a", "b"],
                    help="quale dei due sistemi giudicati corrisponde al QE")
    ap.add_argument("--grave", default="major",
                    choices=["major", "critical"],
                    help="da quale severità in su un blocco è 'da rivedere'")
    args = ap.parse_args()

    qe = {d["id"]: d["qe"] for d in load(args.qe)}
    rows = load(args.gemba)
    key = f"errors_{args.side}"

    floor = ["minor", "major", "critical"].index(args.grave)
    items = []
    for r in rows:
        if r["id"] not in qe:
            continue
        sev = [e.get("severity") for e in r[key]]
        bad = any(["minor", "major", "critical"].index(s) >= floor
                  for s in sev if s in WEIGHT)
        items.append((qe[r["id"]], bad, r["id"]))

    n = len(items)
    total_bad = sum(1 for _, b, _ in items if b)
    if not n or not total_bad:
        sys.exit("Dati insufficienti: nessun blocco con errori di questa gravità.")

    items.sort(key=lambda t: t[0])          # dal peggiore al migliore
    print("=" * 72)
    print(f"  TRIAGE DELLA REVISIONE — {n} blocchi, "
          f"{total_bad} con almeno un errore '{args.grave}' o peggio "
          f"({total_bad * 100 / n:.0f}%)")
    print("=" * 72)
    print(f"  {'si rivede':>10}{'blocchi':>9}{'copertura':>12}"
          f"{'precisione':>12}{'a caso':>10}{'guadagno':>10}")
    print(f"  {'-' * 62}")

    for frac in (0.05, 0.10, 0.15, 0.20, 0.30):
        k = max(1, int(n * frac))
        found = sum(1 for _, b, _ in items[:k] if b)
        cov = found * 100.0 / total_bad
        prec = found * 100.0 / k
        chance = frac * 100
        print(f"  {frac * 100:>9.0f}%{k:>9}{cov:>11.0f}%{prec:>11.0f}%"
              f"{chance:>9.0f}%{cov / chance:>9.1f}x")

    print()
    print("  'a caso' è la copertura che si otterrebbe leggendo la stessa")
    print("  quantità di blocchi presi a sorte. Il guadagno è il rapporto tra")
    print("  le due: sotto 1,5x il segnale non giustifica una funzione.")
    print("=" * 72)


if __name__ == "__main__":
    main()
