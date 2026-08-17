"""
Il punteggio QE predice dove il motore sbaglia? — validazione della Fase 1
==========================================================================
Domanda: instradare verso un motore più costoso i blocchi con punteggio QE
basso migliora davvero la qualità, o è rumore?

Il tetto teorico lo conosciamo: con un oracolo perfetto (che sa in anticipo
quale motore vincerà su ogni blocco) l'MQM medio scende da 4,27 a 2,85, cioè
un 33% di margine. La domanda vera è quanto di quel margine un segnale
DISPONIBILE A RUNTIME riesce a catturare.

Confronta tre strategie a parità di quota instradata:
  - QE       : i blocchi con punteggio COMET-Kiwi più basso
  - ORACOLO  : i blocchi dove il secondo motore vince davvero (tetto)
  - CASO     : campionamento casuale (pavimento, media su 200 estrazioni)

Se QE non stacca il caso, il routing non funziona e il piano ibrido va fermato.

Gira nel venv di PRODUZIONE: legge solo file JSONL, nessuna dipendenza COMET.

Uso:
    venv\\Scripts\\python mt_eval\\validate_routing.py \\
        --gemba gemba_nllb_vs_aya.jsonl --qe qe_tr_nllb_finetuned.jsonl
"""

import argparse
import json
import os
import random
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEVERITY = {"minor": 1, "major": 5, "critical": 10}
QUOTAS = (0.10, 0.20, 0.30, 0.40, 0.50)


def load_jsonl(path):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def mqm(errors):
    return sum(SEVERITY.get(e["severity"], 1) for e in errors)


def spearman(xs, ys):
    """Correlazione di rango: non assume una relazione lineare, che qui non
    c'è (il punteggio QE è compresso in alto)."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemba", required=True)
    ap.add_argument("--qe", required=True)
    ap.add_argument("--label-b", default="motore LLM")
    args = ap.parse_args()

    rows = load_jsonl(args.gemba)
    qe = {d["id"]: d["qe"] for d in load_jsonl(args.qe)}
    rows = [r for r in rows if r["id"] in qe]
    n = len(rows)
    if n < 30:
        sys.exit(f"Troppi pochi segmenti in comune: {n}")

    base = [mqm(r["errors_a"]) for r in rows]      # motore di partenza (NLLB)
    other = [mqm(r["errors_b"]) for r in rows]     # motore di destinazione
    scores = [qe[r["id"]] for r in rows]

    m_base = sum(base) / n
    m_other = sum(other) / n
    m_oracle = sum(min(a, b) for a, b in zip(base, other)) / n

    print("=" * 68)
    print(f"  VALIDAZIONE DEL SEGNALE DI INSTRADAMENTO — {n} segmenti")
    print("=" * 68)
    print(f"  MQM solo motore base   : {m_base:5.2f}")
    print(f"  MQM solo {args.label_b:14}: {m_other:5.2f}")
    print(f"  MQM oracolo perfetto   : {m_oracle:5.2f}   (tetto)")
    print()

    # 1 — il punteggio QE correla con gli errori realmente trovati?
    rho = spearman([-s for s in scores], base)
    print(f"  Correlazione di rango QE ↔ errori MQM del motore base: {rho:+.3f}")
    print("    (positiva = punteggio basso dove ci sono più errori: è ciò che serve)")
    if rho < 0.15:
        print("    ATTENZIONE: correlazione debole, il segnale è poco informativo.")
    print()

    # 2 — quanto margine cattura, contro oracolo e caso
    order_qe = sorted(range(n), key=lambda i: scores[i])          # QE crescente
    order_or = sorted(range(n), key=lambda i: other[i] - base[i])  # guadagno reale

    def routed(idx_set):
        return sum(other[i] if i in idx_set else base[i]
                   for i in range(n)) / n

    rng = random.Random(20260817)
    print(f"  {'quota':>6}{'QE':>9}{'oracolo':>10}{'caso':>9}"
          f"{'% margine':>12}")
    print(f"  {'-' * 46}")
    verdict_rows = []
    for q in QUOTAS:
        k = max(1, int(n * q))
        m_qe = routed(set(order_qe[:k]))
        m_or = routed(set(order_or[:k]))
        m_rand = sum(routed(set(rng.sample(range(n), k)))
                     for _ in range(200)) / 200
        share = ((m_base - m_qe) / (m_base - m_oracle) * 100
                 if m_base > m_oracle else 0.0)
        verdict_rows.append((q, m_qe, m_or, m_rand, share))
        print(f"  {q * 100:5.0f}%{m_qe:9.2f}{m_or:10.2f}{m_rand:9.2f}"
              f"{share:11.0f}%")

    best = min(verdict_rows, key=lambda r: r[1])
    gain_vs_base = (m_base - best[1]) / m_base * 100
    gain_vs_rand = (best[3] - best[1]) / best[3] * 100

    print()
    print("  VERDETTO")
    print(f"    quota migliore        : {best[0] * 100:.0f}%")
    print(f"    MQM                   : {m_base:.2f} → {best[1]:.2f} "
          f"({gain_vs_base:+.0f}%)")
    print(f"    stacco dal caso       : {gain_vs_rand:+.0f}%")
    print(f"    margine catturato     : {best[4]:.0f}% del possibile")
    print()
    if gain_vs_rand < 3:
        print("    → Il segnale NON funziona: instradare con QE equivale a")
        print("      scegliere a caso. Il piano ibrido va fermato.")
    elif best[4] < 25:
        print("    → Segnale debole: guadagno reale ma piccolo. Valutare se")
        print("      vale il costo del secondo motore.")
    else:
        print("    → Il segnale funziona: l'instradamento con QE cattura una")
        print("      quota sostanziale del margine. Procedere.")
    print("=" * 68)


if __name__ == "__main__":
    main()
