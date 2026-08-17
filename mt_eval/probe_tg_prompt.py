"""
TranslateGemma può ricevere le regole del sottotitolo?
=======================================================
Sul banco reale TranslateGemma traduce meglio di tutti ma sbaglia da
sottotitolatore: produce battute lunghe 1,15 volte l'originale (il
professionista sta a 0,94) e censura l'88% del turpiloquio.

L'ipotesi è che non sia un limite del modello ma un'istruzione mancante: gira
con `prompt_style="mt"`, cioè il prompt nativo del produttore — "traduci
questo testo" — e non vede mai le regole di condensazione e di registro che su
Aya hanno portato le volgarità da 6/30 a 26/30.

L'ostacolo è che il suo chat template è rigido: costruisce lui l'istruzione di
traduzione a partire da `source_lang_code`/`target_lang_code` e non prevede un
ruolo di sistema. Questo script confronta tre vie:

  A  nativo          — il template del produttore, così com'è (riferimento)
  B  nativo + regole — le regole infilate nel campo `text`, prima del testo
  C  formato grezzo  — si scavalca il template e si costruisce un turno chat
                       Gemma3 a mano, con le regole come istruzione

Il rischio di B è che il modello traduca le istruzioni invece di applicarle;
quello di C è che, uscendo dalla forma su cui è stato addestrato, perda la
qualità di traduzione che è il suo unico vantaggio. Si misura, non si indovina.

Uso:
    venv\\Scripts\\python mt_eval\\probe_tg_prompt.py --n 40
"""

import argparse
import json
import os
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

STRONG_IT = re.compile(
    r"cazz|merd|stronz|fanculo|porc[oa]|troi|figa|coglion|puttan|inculat|"
    r"bastard|vaffa|fott|incazz|minchi", re.I)
PROF_EN = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|cunt|dick|prick|"
    r"motherfuck\w*|goddamn)\b", re.I)

# Volutamente corte: il campo `text` viene inglobato in un'istruzione di
# traduzione, e più regole si aggiungono più cresce il rischio che il modello
# le traduca invece di applicarle.
RULES_SHORT = (
    "Rendi come sottotitolo italiano: più breve dell'originale, "
    "senza riempitivi, e conserva le parolacce con parolacce italiane "
    "(fuck→cazzo, shit→merda, asshole→stronzo). Traduci solo la battuta:"
)

RULES_FULL = """\
Sei un adattatore di sottotitoli italiani. Adatta la battuta seguente:
- più corta dell'originale inglese, eliminando riempitivi e ripetizioni
- italiano parlato naturale, mai calcato sull'inglese
- le volgarità NON si attenuano: fuck→cazzo, shit→merda, asshole→stronzo,
  motherfucker→figlio di puttana, fuck you→vaffanculo
- niente spiegazioni, solo la battuta adattata"""


def load(path, n):
    p = path if os.path.isabs(path) else os.path.join(SCRIPT_DIR, path)
    items = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    # Metà blocchi volgari (il difetto peggiore) e metà lunghi (il secondo).
    prof = [d for d in items if PROF_EN.search(d["source"])]
    longs = sorted((d for d in items if d not in prof),
                   key=lambda d: -len(d["source"]))
    half = n // 2
    return (prof[:half] + longs[:n - min(half, len(prof))])[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="filmset_deadpool2_sample.jsonl")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--batch", type=int, default=8)
    args = ap.parse_args()

    items = load(args.set, args.n)
    print(f"Campione: {len(items)} blocchi "
          f"({sum(1 for d in items if PROF_EN.search(d['source']))} volgari)\n")

    import torch
    from core.llm_subtitle_translator.engine import get_engine, unload_engine

    engine = get_engine("translategemma-12b",
                        log_callback=lambda m: print(f"  {m}"))
    proc = engine.processor

    def gen(conversations, raw_prompts=None):
        """Genera da conversazioni (template nativo) o da prompt già resi."""
        if raw_prompts is not None:
            inputs = engine.tokenizer(
                raw_prompts, return_tensors="pt", padding=True,
                add_special_tokens=False).to(engine.model.device)
            inputs = {k: v for k, v in inputs.items()
                      if k in ("input_ids", "attention_mask")}
        else:
            inputs = proc.apply_chat_template(
                conversations, tokenize=True, add_generation_prompt=True,
                return_dict=True, return_tensors="pt", padding=True,
            ).to(engine.model.device)
            inputs = dict(inputs)
        with torch.no_grad():
            out = engine.model.generate(
                **inputs, max_new_tokens=120, do_sample=False,
                pad_token_id=engine.tokenizer.pad_token_id)
        new = out[:, inputs["input_ids"].shape[1]:]
        return [t.strip() for t in
                engine.tokenizer.batch_decode(new, skip_special_tokens=True)]

    def run_variant(name, build_conv=None, build_raw=None):
        outs = []
        t0 = time.time()
        for i in range(0, len(items), args.batch):
            chunk = items[i:i + args.batch]
            if build_raw:
                outs += gen(None, [build_raw(d["source"]) for d in chunk])
            else:
                outs += gen([build_conv(d["source"]) for d in chunk])
        return name, outs, time.time() - t0

    variants = []
    variants.append(run_variant(
        "A nativo",
        build_conv=lambda t: engine.mt_messages(t)))
    variants.append(run_variant(
        "B nativo+regole",
        build_conv=lambda t: engine.mt_messages(f"{RULES_SHORT}\n{t}")))
    variants.append(run_variant(
        "C formato grezzo",
        build_raw=lambda t: (
            f"<bos><start_of_turn>user\n{RULES_FULL}\n\n{t}"
            f"<end_of_turn>\n<start_of_turn>model\n")))

    unload_engine()

    src_len = sum(len(d["source"].replace("\n", " ")) for d in items) / len(items)
    ref_len = sum(len(d["reference"].replace("\n", " ")) for d in items) / len(items)
    prof_src = [d for d in items if PROF_EN.search(d["source"])]
    ref_prof = sum(1 for d in prof_src if STRONG_IT.search(d["reference"]))

    print(f"\n{'=' * 70}")
    print(f"  {'variante':<20}{'car':>7}{'x EN':>8}{'turpiloquio':>14}{'tempo':>9}")
    print(f"  {'-' * 58}")
    print(f"  {'PROFESSIONISTA':<20}{ref_len:7.1f}{ref_len / src_len:8.2f}"
          f"{f'{ref_prof}/{len(prof_src)}':>14}{'—':>9}")
    print(f"  {'-' * 58}")
    for name, outs, el in variants:
        by_id = {d["id"]: o for d, o in zip(items, outs)}
        ln = sum(len(o.replace("\n", " ")) for o in outs) / len(outs)
        hit = sum(1 for d in prof_src if STRONG_IT.search(by_id[d["id"]]))
        print(f"  {name:<20}{ln:7.1f}{ln / src_len:8.2f}"
              f"{f'{hit}/{len(prof_src)}':>14}{el:8.0f}s")
    print(f"{'=' * 70}\n")

    print("Esempi sui blocchi volgari:")
    for d in prof_src[:5]:
        print(f"\n  EN  : {d['source'].replace(chr(10), ' / ')[:64]}")
        print(f"  PRO : {d['reference'].replace(chr(10), ' / ')[:64]}")
        for name, outs, _ in variants:
            o = {x['id']: y for x, y in zip(items, outs)}[d["id"]]
            print(f"  {name:<5}: {o.replace(chr(10), ' / ')[:64]}")

    out_path = os.path.join(SCRIPT_DIR, "probe_tg_prompt.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "items": [{"id": d["id"], "source": d["source"],
                       "reference": d["reference"]} for d in items],
            "variants": {name: outs for name, outs, _ in variants},
        }, f, ensure_ascii=False, indent=1)
    print(f"\nDettaglio: {out_path}")


if __name__ == "__main__":
    main()
