"""
Traduce il set di valutazione con il motore LLM del package
============================================================
Non passa da core/translator.py: prova il package nuovo in isolamento, così
una misura negativa non costa un'integrazione già fatta.

Le traduzioni NLLB fine-tuned prodotte da translate.py vengono riusate come
bozza (modalità refine) e come rete di fallback, evitando di tenere due
modelli in VRAM contemporaneamente su una GPU da 12 GB.

Uso:
    venv\\Scripts\\python mt_eval\\translate_llm.py --model aya-expanse-8b
    venv\\Scripts\\python mt_eval\\translate_llm.py --model aya-expanse-8b \\
        --mode refine --name aya_refine
    venv\\Scripts\\python mt_eval\\translate_llm.py --model aya-expanse-8b \\
        --limit 24 --name smoke
"""

import argparse
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

EVALSET = os.path.join(SCRIPT_DIR, "evalset.jsonl")
DEFAULT_DRAFT = os.path.join(SCRIPT_DIR, "tr_nllb_finetuned.jsonl")

CPS = 17.0
MIN_DUR = 1.0


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="aya-expanse-8b")
    ap.add_argument("--mode", default="translate",
                    choices=["translate", "refine"])
    ap.add_argument("--draft", default=DEFAULT_DRAFT,
                    help="JSONL usato come bozza (refine) e come fallback")
    ap.add_argument("--name", default=None)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    name = args.name or f"{args.model}_{args.mode}"
    out_jsonl = os.path.join(SCRIPT_DIR, f"tr_{name}.jsonl")

    from core.llm_subtitle_translator.engine import get_engine, unload_engine
    from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
    from core.llm_subtitle_translator.translator import SubtitleLLMTranslator
    from core.llm_subtitle_translator import postprocess

    items = sorted(load_jsonl(EVALSET), key=lambda x: x["id"])
    if args.limit:
        items = items[:args.limit]

    drafts = {}
    if os.path.isfile(args.draft):
        drafts = {d["id"]: d["text"] for d in load_jsonl(args.draft)}
        print(f"Bozza/fallback: {args.draft} ({len(drafts)} blocchi)")
    elif args.mode == "refine":
        sys.exit(f"Modalità refine ma bozza assente: {args.draft}")

    units = []
    durations = {}
    for it in items:
        visible = len(it["source"].replace("\n", " "))
        dur = max(MIN_DUR, visible / CPS)
        durations[it["id"]] = dur
        units.append(SubtitleUnit(
            id=it["id"],
            text=it["source"],
            duration=dur,
            is_dialogue="\n" in it["source"] and "- " in it["source"],
        ))

    # Le bozze NLLB sono già calcolate, quindi il "traduttore di riserva" qui
    # è una semplice ricerca per testo. Va però indicizzata anche riga per
    # riga: l'orchestratore spezza i blocchi di dialogo in un'unità per
    # battuta, e chiederebbe il fallback su "Grazie.", non sull'intero
    # "- Grazie.\n- Come posso aiutarla?".
    from core.llm_subtitle_translator.postprocess import DASH_PREFIX

    by_text = {}
    for it in items:
        draft = drafts.get(it["id"], "")
        by_text[it["source"]] = draft
        src_lines = [DASH_PREFIX.sub("", l).strip()
                     for l in it["source"].split("\n") if l.strip()]
        dst_lines = [DASH_PREFIX.sub("", l).strip()
                     for l in draft.split("\n") if l.strip()]
        if len(src_lines) > 1 and len(src_lines) == len(dst_lines):
            for s, d in zip(src_lines, dst_lines):
                by_text.setdefault(s, d)

    def fallback(texts):
        return [by_text.get(t, by_text.get(t.strip(), "")) for t in texts]

    print(f"\nModello: {args.model} | modalità: {args.mode} | "
          f"batch {args.batch} | {len(units)} blocchi\n")

    engine = get_engine(args.model, log_callback=lambda m: print(f"  {m}"))
    translator = SubtitleLLMTranslator(
        engine=engine,
        fallback=fallback if drafts else None,
        batch_size=args.batch,
        log_callback=lambda m: print(m),
        mode=args.mode,
    )

    t0 = time.time()
    results = translator.translate(units)
    elapsed = time.time() - t0

    unload_engine()

    st = postprocess.stats(results, durations)
    n = len(units)
    empty = sum(1 for u in units if not results.get(u.id, "").strip())
    copy = sum(1 for u in units
               if results.get(u.id, "").strip() == u.text.strip())

    print(f"\n  tempo totale             : {elapsed / 60:.1f} min "
          f"({elapsed / n:.1f}s per blocco)")
    print(f"  righe oltre 42 caratteri : {st['over_cpl_pct']:.0f}%")
    print(f"  blocchi oltre 17 CPS     : {st['over_cps_pct']:.0f}%")
    print(f"  identici all'inglese     : {copy}/{n}")
    print(f"  vuoti                    : {empty}/{n}")
    print(f"  contatori retry/fallback : {translator.stats}")
    if translator.issue_counts:
        print(f"  controlli scattati       : "
              f"{dict(sorted(translator.issue_counts.items(), key=lambda x: -x[1]))}")
        print("    (il prefisso ~ indica una segnalazione, non un bloccante)")

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps({"id": u.id, "text": results.get(u.id, "")},
                               ensure_ascii=False) + "\n")
    print(f"\nOutput: {out_jsonl}")

    print("\n--- primi esempi ---")
    for u in units[:6]:
        print(f"\nEN : {u.text}")
        if args.mode == "refine":
            print(f"BOZ: {drafts.get(u.id, '')}")
        print(f"IT : {results.get(u.id, '')}")


if __name__ == "__main__":
    main()
