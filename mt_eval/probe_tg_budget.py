"""
Il difetto che resta a TranslateGemma è la lunghezza. Si può dirgli il budget?
=============================================================================
Il giudizio su A Man Called Otto — film senza turpiloquio, quindi senza il
difetto che le regole hanno già risolto — isola quello che resta:

    accuracy   NLLB 14,2   TranslateGemma 17,2   (+3,0)
    style      NLLB 53,5   TranslateGemma 66,5   (+13,0)
    critici    NLLB 11     TranslateGemma  7

Capisce quanto NLLB, sbaglia meno gravemente di NLLB, e perde lo stesso: perché
scrive battute troppo lunghe. Rapporto 1,09 volte l'inglese contro lo 0,94 del
professionista, e un terzo dei blocchi oltre i 17 caratteri al secondo.

Le regole generiche ("più breve dell'originale, senza riempitivi") hanno spostato
il rapporto da 1,15 a 1,12: quasi niente. L'ipotesi qui è che a un modello non
serva un aggettivo, serva un NUMERO — il budget di caratteri che quella battuta
ha davvero, calcolato dalla sua durata sullo schermo a 17 CPS. È l'informazione
che il percorso "adapt" già passa (SubtitleUnit.budget) e che il percorso "mt"
non ha mai passato.

Tre varianti, sugli stessi blocchi:

  A  nessuna regola      — il prompt nativo (riferimento)
  B  regola generica     — quella attualmente in MODEL_SPECS
  C  budget esplicito    — "Massimo N caratteri", con N dalla durata reale

Uso:
    venv\\Scripts\\python mt_eval\\probe_tg_budget.py --n 60
"""

import argparse
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

CPS_MAX = 17.0
CPL_MAX = 42

REGOLA_GENERICA = (
    "Rendi come sottotitolo italiano: più breve dell'originale, "
    "senza riempitivi. Traduci solo la battuta:"
)


def budget_caratteri(item):
    """Quanti caratteri stanno sullo schermo in quella battuta, a 17 CPS.

    Due righe da 42 sono il tetto fisico qualunque sia la durata: è lo stesso
    calcolo di SubtitleUnit.budget, ripetuto qui perché il banco deve poter
    girare senza importare mezzo progetto.
    """
    dur = max(0.001, float(item["end"]) - float(item["start"]))
    return max(12, min(int(dur * CPS_MAX), CPL_MAX * 2))


def carica(path, n):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    items = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    # I blocchi dove il budget morde: quelli in cui l'inglese già sfiora il
    # limite. Su una battuta di tre parole non c'è niente da condensare e la
    # misura non direbbe nulla.
    stretti = [d for d in items
               if len(d["source"].replace("\n", " ")) > budget_caratteri(d) * 0.7]
    return sorted(stretti, key=lambda d: -len(d["source"]))[:n]


def misura(items, testi):
    n = len(items)
    tot = sfora_cpl = sfora_budget = 0
    for d, t in zip(items, testi):
        flat = t.replace("\n", " ")
        tot += len(flat)
        if any(len(r) > CPL_MAX for r in t.split("\n")):
            sfora_cpl += 1
        if len(flat) > budget_caratteri(d):
            sfora_budget += 1
    src = sum(len(d["source"].replace("\n", " ")) for d in items) / n
    return tot / n, (tot / n) / src, sfora_cpl * 100.0 / n, sfora_budget * 100.0 / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="filmset_otto_sample.jsonl")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--batch", type=int, default=12)
    args = ap.parse_args()

    items = carica(args.set, args.n)
    print(f"Campione: {len(items)} blocchi stretti "
          f"(budget medio {sum(budget_caratteri(d) for d in items) / len(items):.0f} "
          f"caratteri)\n")

    import torch
    from core.llm_subtitle_translator.engine import get_engine, unload_engine

    engine = get_engine("translategemma-12b",
                        log_callback=lambda m: print(f"  {m}"))
    proc = engine.processor

    def genera(testi):
        out = []
        for i in range(0, len(testi), args.batch):
            chunk = testi[i:i + args.batch]
            conv = [[{"role": "user", "content": [{
                "type": "text", "source_lang_code": "en",
                "target_lang_code": "it", "text": t}]}] for t in chunk]
            inputs = proc.apply_chat_template(
                conv, tokenize=True, add_generation_prompt=True,
                return_dict=True, return_tensors="pt", padding=True,
            ).to(engine.model.device)
            with torch.no_grad():
                gen = engine.model.generate(
                    **dict(inputs), max_new_tokens=160, do_sample=False,
                    pad_token_id=engine.tokenizer.pad_token_id)
            nuovi = gen[:, inputs["input_ids"].shape[1]:]
            out += [t.strip() for t in engine.tokenizer.batch_decode(
                nuovi, skip_special_tokens=True)]
        return out

    varianti = []
    for nome, costruisci in (
        ("A nessuna regola", lambda d: d["source"]),
        ("B regola generica", lambda d: f"{REGOLA_GENERICA}\n{d['source']}"),
        ("C budget esplicito", lambda d: (
            f"Rendi come sottotitolo italiano in non più di "
            f"{budget_caratteri(d)} caratteri, tagliando i riempitivi. "
            f"Traduci solo la battuta:\n{d['source']}")),
    ):
        t0 = time.time()
        out = genera([costruisci(d) for d in items])
        varianti.append((nome, out, time.time() - t0))
        print(f"  {nome} fatta in {time.time() - t0:.0f}s")

    unload_engine()

    print(f"\n{'=' * 74}")
    print(f"  {'variante':<22}{'car':>7}{'x EN':>8}{'>42car':>9}"
          f"{'oltre budget':>15}{'tempo':>9}")
    print(f"  {'-' * 66}")
    c, r, cpl, bud = misura(items, [d["reference"] for d in items])
    print(f"  {'PROFESSIONISTA':<22}{c:7.1f}{r:8.2f}{cpl:8.0f}%{bud:14.0f}%"
          f"{'—':>9}")
    print(f"  {'-' * 66}")
    for nome, out, el in varianti:
        c, r, cpl, bud = misura(items, out)
        print(f"  {nome:<22}{c:7.1f}{r:8.2f}{cpl:8.0f}%{bud:14.0f}%{el:8.0f}s")
    print(f"{'=' * 74}\n")

    print("Esempi sui blocchi più lunghi:")
    for k in range(4):
        d = items[k]
        print(f"\n  budget {budget_caratteri(d)} caratteri")
        print(f"  EN  : {d['source'].replace(chr(10), ' / ')[:76]}")
        print(f"  PRO : {d['reference'].replace(chr(10), ' / ')[:76]}")
        for nome, out, _ in varianti:
            print(f"  {nome[:1]}   : {out[k].replace(chr(10), ' / ')[:76]}")

    path = os.path.join(SCRIPT_DIR, "probe_tg_budget.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "items": [{"id": d["id"], "source": d["source"],
                       "reference": d["reference"],
                       "budget": budget_caratteri(d)} for d in items],
            "varianti": {nome: out for nome, out, _ in varianti},
        }, f, ensure_ascii=False, indent=1)
    print(f"\nDettaglio: {path}")


if __name__ == "__main__":
    main()
