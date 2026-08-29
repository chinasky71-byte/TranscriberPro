"""
Probe: riscrittore LLM vincolato + guardia anti-allucinazione (Fase 3, Gender V2.5)
====================================================================================
Prototipo isolato, nessuna integrazione in pipeline. Verifica due cose che oggi
non esistono nel codice di produzione:

1. `rewrite_messages()` (core/llm_subtitle_translator/prompt_builder.py) — un
   secondo passaggio "correggi senza inventare" che parte da una bozza NLLB già
   tradotta invece che dal source puro. Il rischio è che il modello, messo in un
   compito diverso dalla traduzione pura, aggiunga contenuto invece di limitarsi
   a correggere — esattamente ciò che il caso isolato sotto (id 172, "for
   generations" → "fin dalla fondazione di questo regno" su TranslateGemma)
   dimostra essere un rischio reale per QUESTO modello.

2. `hallucination_guard.check_added_content()` — un giudizio Claude per-segmento
   che intercetta un'aggiunta anche breve, cosa che `too_long` in validator.py
   (soglia 2.4x) non fa.

L'input è sempre la bozza NLLB (mai quella TranslateGemma, che ha già
allucinato quella riga): l'obiettivo è verificare che il riscrittore, partendo
da un input pulito, non introduca l'errore — non "correggere" TGemma.

Uso:
    venv\\Scripts\\python mt_eval\\probe_rewrite_guard.py --n 15
"""
import argparse
import json
import os
import random
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

BENCH = os.path.join(SCRIPT_DIR, "filmset_knightsmagic_ep01.jsonl")
TR_NLLB = os.path.join(SCRIPT_DIR, "tr_knightsmagic_ep01_nllb.jsonl")
ISOLATED_ID = 172   # "My family's been Knightsmiths for generations."


def load_bench():
    bench = {}
    with open(BENCH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            bench[d["id"]] = d
    nllb = {}
    with open(TR_NLLB, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            nllb[d["id"]] = d["text"]
    return bench, nllb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15,
                    help="campione totale INCLUSO il caso isolato")
    ap.add_argument("--seed", type=int, default=20260829)
    args = ap.parse_args()

    bench, nllb = load_bench()
    ids = [ISOLATED_ID] + sorted(
        rid for rid in random.Random(args.seed).sample(
            [i for i in bench if i != ISOLATED_ID], args.n - 1))
    print(f"Campione: {len(ids)} blocchi (incluso il caso isolato id={ISOLATED_ID})\n")

    from core.llm_subtitle_translator.engine import get_engine, unload_engine
    from core.llm_subtitle_translator.prompt_builder import rewrite_messages
    from core.llm_subtitle_translator import hallucination_guard as hg
    from utils.config import get_config

    engine = get_engine("translategemma-12b",
                        log_callback=lambda m: print(f"  {m}"))

    import anthropic
    key = get_config().get("claude_api_key") or None
    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    rows = []
    for rid in ids:
        d = bench[rid]
        src_en = d["source"]
        draft_it = nllb[rid]
        msgs = rewrite_messages(src_en, draft_it, budget=0, loader="gemma3")
        rewritten = engine.generate([msgs], max_new_tokens=200)[0].strip()
        rows.append({"id": rid, "source": src_en, "draft_nllb": draft_it,
                     "rewritten": rewritten})

    unload_engine()

    print("\n=== Riscrittura (TranslateGemma, rewrite_messages) ===\n")
    for r in rows:
        changed = r["rewritten"] != r["draft_nllb"]
        print(f"[{r['id']}] {'MODIFICATA' if changed else 'invariata'}")
        print(f"  EN     : {r['source']!r}")
        print(f"  NLLB   : {r['draft_nllb']!r}")
        if changed:
            print(f"  REWRITE: {r['rewritten']!r}")
        print()

    print("=== Guardia anti-allucinazione (Claude, per segmento) ===\n")
    n_flagged, n_checked = 0, 0
    out_path = os.path.join(SCRIPT_DIR, "probe_rewrite_guard_results.jsonl")
    with open(out_path, "w", encoding="utf-8") as out_f:
        for r in rows:
            verdict = hg.check_added_content(client, r["source"], r["rewritten"])
            n_checked += 1
            flagged = bool(verdict.get("added_content"))
            n_flagged += flagged
            final = r["draft_nllb"] if flagged else r["rewritten"]
            print(f"[{r['id']}] added_content={flagged}"
                  + (f"  added_text={verdict.get('added_text')!r}" if flagged else ""))
            out_f.write(json.dumps({**r, "guard_verdict": verdict,
                                    "final_after_guard": final},
                                   ensure_ascii=False) + "\n")

    print(f"\nTotale: {n_checked} segmenti, {n_flagged} bloccati dalla guardia "
          f"({n_flagged * 100 // max(n_checked, 1)}%)")
    print(f"Dettagli: {out_path}")


if __name__ == "__main__":
    main()
