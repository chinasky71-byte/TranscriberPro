"""
Quanto è lungo davvero un esempio di addestramento
===================================================
Misura la distribuzione dei token sul dataset reale, col tokenizer vero di
TranslateGemma. Serve a due decisioni che cambiano il costo di un fattore, non
di una percentuale:

  1. `max_seq_len`: se il 99° percentile sta a 120 token, addestrare a 512
     significa pagare quattro volte tanto per padding.
  2. se conviene il PACKING. Le battute di un sottotitolo sono cortissime: con
     esempi da poche decine di token, un batch senza packing è quasi tutto
     riempitivo. Il rapporto fra token utili e token totali lo dice.

Uso:
    venv\\Scripts\\python corpus\\token_stats.py
"""

import argparse
import json
import os
import statistics
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

MODELLO = "google/translategemma-12b-it"


def hf_token():
    try:
        from utils.config import get_config
        return get_config().get_huggingface_token() or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="train.jsonl")
    ap.add_argument("--campione", type=int, default=20000)
    args = ap.parse_args()

    percorso = os.path.join(SCRIPT_DIR, args.file)
    righe = []
    with open(percorso, encoding="utf-8") as f:
        for riga in f:
            if riga.strip():
                righe.append(json.loads(riga))
                if len(righe) >= args.campione:
                    break
    print(f"Campione: {len(righe)} esempi da {args.file}\n")

    from transformers import AutoProcessor
    proc = AutoProcessor.from_pretrained(MODELLO, token=hf_token())
    tok = proc.tokenizer

    # La forma esatta che il modello vedrà: istruzione + battuta inglese come
    # ingresso, battuta italiana come bersaglio.
    lun_in, lun_out, lun_tot = [], [], []
    for r in righe:
        conv = [{"role": "user", "content": [{
            "type": "text", "source_lang_code": "en",
            "target_lang_code": "it",
            "text": f"{r['istruzione']}\n{r['en']}"}]}]
        reso = proc.apply_chat_template(conv, tokenize=False,
                                        add_generation_prompt=True)
        a = len(tok(reso, add_special_tokens=False)["input_ids"])
        b = len(tok(r["it"], add_special_tokens=False)["input_ids"])
        lun_in.append(a)
        lun_out.append(b)
        lun_tot.append(a + b)

    def perc(v, q):
        return statistics.quantiles(v, n=100)[q - 1]

    print(f"  {'':<14}{'media':>8}{'p50':>7}{'p90':>7}{'p95':>7}{'p99':>7}{'max':>7}")
    print("  " + "-" * 58)
    for nome, v in (("ingresso", lun_in), ("uscita", lun_out),
                    ("totale", lun_tot)):
        print(f"  {nome:<14}{statistics.mean(v):>8.0f}{perc(v, 50):>7.0f}"
              f"{perc(v, 90):>7.0f}{perc(v, 95):>7.0f}{perc(v, 99):>7.0f}"
              f"{max(v):>7}")

    print()
    for cap in (128, 192, 256, 512):
        dentro = sum(1 for x in lun_tot if x <= cap) * 100.0 / len(lun_tot)
        utile = sum(min(x, cap) for x in lun_tot) / (cap * len(lun_tot)) * 100
        print(f"  max_seq_len {cap:>4}: copre il {dentro:5.1f}% degli esempi | "
              f"token utili {utile:4.1f}% senza packing")

    tot_token = sum(lun_tot)
    print(f"\n  Token totali nel campione: {tot_token:,}".replace(",", "."))
    print(f"  Stima su 200.000 coppie  : "
          f"{int(tot_token / len(righe) * 200000):,}".replace(",", "."))
    print("\n  Con esempi cosi corti il packing non e un'ottimizzazione")
    print("  marginale: e la differenza fra pagare i token utili e pagarne")
    print("  quattro o cinque volte tanti.")


if __name__ == "__main__":
    main()
