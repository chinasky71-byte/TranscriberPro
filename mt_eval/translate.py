"""
Produce le traduzioni del set di valutazione con un motore della pipeline
=========================================================================
Non chiama il modello direttamente: costruisce un vero file SRT dal set,
lo passa a `translate_file()` e rilegge l'output. In questo modo la misura
comprende TUTTO il percorso di produzione — parsing, dash flags, masking,
batch adattivo, post-processing — e non solo la qualità grezza del modello.

I timestamp sono sintetici ma realistici: la durata di ogni blocco è calcolata
a 17 caratteri al secondo (il limite di reading speed della guida Netflix
italiana), così il budget caratteri per blocco è quello vero.

Uso:
    venv\\Scripts\\python mt_eval\\translate.py --engine nllb_finetuned
    venv\\Scripts\\python mt_eval\\translate.py --engine aya

Output: mt_eval/tr_<engine>.jsonl   {"id", "text"}
        mt_eval/tr_<engine>_out.srt (SRT tradotto grezzo, per ispezione)
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

CPS = 17.0          # reading speed massima, guida di stile italiana Netflix
MIN_DUR = 1.0       # durata minima di un blocco (anti-flash)
GAP = 0.12          # spazio tra blocchi consecutivi


def load_evalset():
    items = []
    with open(EVALSET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return sorted(items, key=lambda x: x["id"])


def fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(items, path):
    """Un blocco per segmento, indice = id del set."""
    t = 0.0
    blocks = []
    for item in items:
        text = item["source"]
        visible = len(text.replace("\n", " "))
        dur = max(MIN_DUR, visible / CPS)
        blocks.append(f"{item['id']}\n"
                      f"{fmt_ts(t)} --> {fmt_ts(t + dur)}\n"
                      f"{text}\n")
        t += dur + GAP
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return t


def parse_srt(path):
    """Restituisce {indice: testo}. Parser minimale: l'output del translator
    conserva indici e timestamp per contratto."""
    out = {}
    with open(path, encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n")
    for block in content.split("\n\n"):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        if "-->" not in lines[1]:
            continue
        out[idx] = "\n".join(lines[2:]).strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    help="nllb | nllb_finetuned | aya | claude | openai")
    ap.add_argument("--name", default=None,
                    help="nome del file di output (default: engine)")
    args = ap.parse_args()

    name = args.name or args.engine
    src_srt = os.path.join(SCRIPT_DIR, f"tr_{name}_in.srt")
    out_srt = os.path.join(SCRIPT_DIR, f"tr_{name}_out.srt")
    out_jsonl = os.path.join(SCRIPT_DIR, f"tr_{name}.jsonl")

    items = load_evalset()
    total_s = build_srt(items, src_srt)
    print(f"SRT sorgente: {src_srt}")
    print(f"  {len(items)} blocchi, durata simulata {total_s / 60:.1f} min\n")

    from core.translator import get_translator

    print(f"Motore: {args.engine}")
    t0 = time.time()
    translator = get_translator(model_type=args.engine)
    translator.set_log_callback(lambda m: print(f"  {m}"))

    ok = translator.translate_file(
        input_path=src_srt,
        output_path=out_srt,
        src_lang="en",
        tgt_lang="it",
    )
    elapsed = time.time() - t0

    try:
        translator.cleanup()
    except Exception as exc:
        print(f"  cleanup: {exc}")

    if not ok:
        sys.exit("translate_file ha restituito False")

    translated = parse_srt(out_srt)
    print(f"\nTradotti {len(translated)}/{len(items)} blocchi "
          f"in {elapsed / 60:.1f} minuti")

    missing = [it["id"] for it in items if it["id"] not in translated]
    if missing:
        print(f"ATTENZIONE: {len(missing)} blocchi mancanti: {missing[:10]}")

    # Diagnostica a costo zero: quanti blocchi violano i vincoli di leggibilità
    # e quanti sono usciti identici alla fonte inglese (mancata traduzione).
    over_cpl = over_cps = untranslated = empty = 0
    for item in items:
        text = translated.get(item["id"], "")
        if not text.strip():
            empty += 1
            continue
        if text.strip() == item["source"].strip():
            untranslated += 1
        if any(len(line) > 42 for line in text.split("\n")):
            over_cpl += 1
        visible_src = len(item["source"].replace("\n", " "))
        dur = max(MIN_DUR, visible_src / CPS)
        if len(text.replace("\n", " ")) / dur > CPS:
            over_cps += 1

    n = len(items)
    print(f"\n  righe oltre 42 caratteri : {over_cpl:>4} / {n} "
          f"({over_cpl / n * 100:.0f}%)")
    print(f"  blocchi oltre 17 CPS     : {over_cps:>4} / {n} "
          f"({over_cps / n * 100:.0f}%)")
    print(f"  identici all'inglese     : {untranslated:>4} / {n} "
          f"({untranslated / n * 100:.0f}%)")
    print(f"  vuoti                    : {empty:>4} / {n}")

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(
                {"id": item["id"], "text": translated.get(item["id"], "")},
                ensure_ascii=False) + "\n")
    print(f"\nOutput: {out_jsonl}")


if __name__ == "__main__":
    main()
