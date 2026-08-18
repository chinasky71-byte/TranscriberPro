"""
Dalle coppie al dataset: deduplicazione, divisione e formato di addestramento
=============================================================================
Prende `coppie.jsonl` e `film.jsonl` e produce i tre insiemi pronti per QLoRA.

LA DIVISIONE È PER OPERA, NON PER FRASE. Prendere frasi a caso e dividerle
80/20 metterebbe lo stesso film — stessi personaggi, stessa terminologia, e
soprattutto lo STESSO eventuale difetto di allineamento — da entrambe le parti.
Il modello verrebbe premiato per aver imparato il difetto, e il punteggio
sembrerebbe migliore del vero.

Per le SERIE l'opera è la serie intera, non l'episodio: episodi della stessa
serie condividono cast, terminologia e traduttore, quindi dividerli
significherebbe rifare lo stesso errore un livello più in basso.

La scelta delle opere da tenere fuori è STRATIFICATA, non casuale, su due assi
che sappiamo contare:
  - il rapporto italiano/inglese, che separa i sottotitoli adattati per la
    lettura (~0,94) dalle trascrizioni del doppiaggio (>1,05);
  - il tipo, film o episodio.
Un 5% preso a caso potrebbe pescare quasi solo una delle due famiglie.

Uso:
    venv\\Scripts\\python corpus\\make_dataset.py
    venv\\Scripts\\python corpus\\make_dataset.py --coppie-max 200000
"""

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEED = 20260818

CPS_MAX = 17.0
CPL_MAX = 42
MAX_RIPETIZIONI = 3      # quante volte la stessa battuta inglese può entrare


def budget_caratteri(inizio, fine):
    """Lo spazio che quella battuta ha davvero sullo schermo.

    Stesso calcolo di `SubtitleUnit.budget`: si insegna al modello a
    rispettare il numero che gli verrà dato al momento della traduzione.
    """
    durata = max(0.001, float(fine) - float(inizio))
    return max(12, min(int(durata * CPS_MAX), CPL_MAX * 2))


def opera(relativo):
    """La prima componente del percorso: la cartella del film o della serie."""
    return relativo.split("/")[0]


def famiglia(rapporto):
    if rapporto is None:
        return "ignoto"
    return "adattato" if rapporto < 1.0 else "doppiaggio"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coppie", default="coppie.jsonl")
    ap.add_argument("--registro", default="film.jsonl")
    ap.add_argument("--out", default=".")
    ap.add_argument("--coppie-max", type=int, default=200000,
                    help="tetto sull'insieme di addestramento")
    ap.add_argument("--modello", default="translategemma-12b",
                    help="da quale modello prendere la forma del prompt")
    ap.add_argument("--quota-test", type=float, default=0.05)
    ap.add_argument("--quota-valid", type=float, default=0.05)
    args = ap.parse_args()

    rng = random.Random(SEED)

    reg = {}
    with open(os.path.join(SCRIPT_DIR, args.registro), encoding="utf-8") as f:
        for riga in f:
            if riga.strip():
                r = json.loads(riga)
                reg[r["relativo"]] = r

    coppie = []
    with open(os.path.join(SCRIPT_DIR, args.coppie), encoding="utf-8") as f:
        for riga in f:
            if riga.strip():
                coppie.append(json.loads(riga))
    print(f"Coppie grezze: {len(coppie):,}".replace(",", "."))

    # --- deduplicazione con tetto ------------------------------------------
    # Togliere del tutto i doppioni falserebbe la distribuzione: «Sì.» e
    # «Cosa?» ricorrono davvero con quella frequenza. Ma lasciarli tutti
    # spreca capacità su nulla. Si mette un tetto.
    visti = Counter()
    esatti = set()
    tenute = []
    for c in coppie:
        chiave = (c["en"].strip().lower(), c["it"].strip().lower())
        if chiave in esatti:
            continue
        if visti[chiave[0]] >= MAX_RIPETIZIONI:
            continue
        esatti.add(chiave)
        visti[chiave[0]] += 1
        tenute.append(c)
    print(f"Dopo deduplicazione: {len(tenute):,}".replace(",", ".") +
          f"  (-{len(coppie) - len(tenute):,})".replace(",", "."))

    # --- raggruppamento per opera ------------------------------------------
    per_opera = defaultdict(list)
    for c in tenute:
        per_opera[opera(c["film"])].append(c)

    meta = {}
    for rel, r in reg.items():
        o = opera(rel)
        if o not in meta:
            meta[o] = {"rapporti": [], "tipo": r.get("tipo", "film")}
        if r.get("rapporto"):
            meta[o]["rapporti"].append(r["rapporto"])
    for o, m in meta.items():
        m["rapporto"] = (sum(m["rapporti"]) / len(m["rapporti"])
                         if m["rapporti"] else None)

    opere = sorted(per_opera)
    print(f"Opere distinte: {len(opere)}")

    # --- divisione stratificata --------------------------------------------
    strati = defaultdict(list)
    for o in opere:
        m = meta.get(o, {})
        strati[(famiglia(m.get("rapporto")), m.get("tipo", "film"))].append(o)

    train_o, valid_o, test_o = [], [], []
    for chiave, elenco in sorted(strati.items()):
        rng.shuffle(elenco)
        n = len(elenco)
        n_test = max(1, int(round(n * args.quota_test))) if n >= 4 else 0
        n_val = max(1, int(round(n * args.quota_valid))) if n >= 4 else 0
        test_o += elenco[:n_test]
        valid_o += elenco[n_test:n_test + n_val]
        train_o += elenco[n_test + n_val:]

    def raccogli(elenco_opere):
        fuori = []
        for o in elenco_opere:
            fuori += per_opera[o]
        rng.shuffle(fuori)
        return fuori

    train = raccogli(train_o)
    valid = raccogli(valid_o)
    test = raccogli(test_o)

    if args.coppie_max and len(train) > args.coppie_max:
        train = train[:args.coppie_max]

    # --- formato di addestramento ------------------------------------------
    # Il prompt deve essere IDENTICO a quello che il modello riceverà in
    # produzione, altrimenti si addestra su una forma e si interroga su
    # un'altra. Qui: il budget in caratteri, che è l'istruzione misurata come
    # efficace, e i codici lingua che il chat template di TranslateGemma
    # richiede.
    # Il testo dell'istruzione NON si riscrive qui: lo costruisce lo stesso
    # codice che gira in produzione (`SubtitleLLMEngine.mt_messages`), così le
    # due forme non possono divergere. Duplicare la stringa aveva già prodotto
    # uno scarto reale — la clausola sul turpiloquio, che in produzione viene
    # aggiunta solo sulle battute volgari, nel dataset non compariva mai:
    # si sarebbe addestrato senza e interrogato con, proprio sulla categoria
    # dove quella clausola era stata misurata come necessaria.
    sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
    from core.llm_subtitle_translator.engine import SubtitleLLMEngine
    motore = SubtitleLLMEngine(args.modello)   # non carica i pesi
    print(f"\nPrompt costruito con: {motore.spec.label}")

    def formatta(c):
        b = budget_caratteri(c["inizio"], c["fine"])
        msg = motore.mt_messages(c["en"], "en", "it", budget=b)
        testo = msg[0]["content"][0]["text"] if isinstance(
            msg[0]["content"], list) else msg[0]["content"]
        # `testo` è "<istruzioni>\n<battuta>": si separa per tenere
        # i due campi distinti, ma la ricomposizione in addestramento rende
        # esattamente questa stringa.
        istruzione, _, battuta = testo.rpartition("\n")
        if not istruzione:
            istruzione, battuta = "", testo
        return {
            "istruzione": istruzione,
            "en": battuta,
            "it": c["it"],
            "budget": b,
            "film": c["film"],
        }

    out_dir = os.path.join(SCRIPT_DIR, args.out)
    os.makedirs(out_dir, exist_ok=True)
    for nome, dati, opere_ins in (("train", train, train_o),
                                  ("valid", valid, valid_o),
                                  ("test", test, test_o)):
        p = os.path.join(out_dir, f"{nome}.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for c in dati:
                f.write(json.dumps(formatta(c), ensure_ascii=False) + "\n")
        car_en = sum(len(c["en"]) for c in dati) / max(len(dati), 1)
        print(f"  {nome:<6} {len(dati):>8,} coppie".replace(",", ".") +
              f" da {len(opere_ins):>4} opere | "
              f"{car_en:.0f} caratteri inglesi in media")

    # Nessuna opera può stare in due insiemi: la garanzia va verificata, non
    # data per scontata.
    assert not (set(train_o) & set(test_o)), "opera in train E test"
    assert not (set(train_o) & set(valid_o)), "opera in train E valid"
    assert not (set(valid_o) & set(test_o)), "opera in valid E test"
    print("\n  Nessuna opera compare in due insiemi: verificato.")

    with open(os.path.join(out_dir, "divisione.json"), "w",
              encoding="utf-8") as f:
        json.dump({"train": train_o, "valid": valid_o, "test": test_o},
                  f, ensure_ascii=False, indent=1)
    print(f"  Divisione salvata in {out_dir}/divisione.json")


if __name__ == "__main__":
    main()
