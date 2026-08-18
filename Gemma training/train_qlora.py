"""
QLoRA su TranslateGemma-12B — misura sulla 3060, addestramento altrove
=======================================================================
Ciclo di addestramento scritto a mano invece che con `trl`: gli esempi sono
cortissimi (130 token mediani) e servono due cose che una libreria generalista
renderebbe opache — il MASCHERAMENTO del prompt e il conteggio esatto dei token
utili, che è ciò da cui si estrapola il costo su una scheda a noleggio.

Due punti su cui questo script è deliberato:

1. LA PERDITA SI CALCOLA SOLO SULLA BATTUTA ITALIANA. Il prompt è per due terzi
   un preambolo fisso del produttore, identico in ogni esempio: addestrarci
   sopra insegnerebbe al modello a ripetere il proprio preambolo, e diluirebbe
   il gradiente che ci interessa su dieci volte più token. I token di prompt
   vengono messi a -100.

2. IL PROMPT È QUELLO DI PRODUZIONE, preambolo del vendor incluso. Addestrare su
   una forma e interrogare su un'altra è il modo più semplice di buttare via un
   fine-tuning: il modello imparerebbe a rispondere a una domanda che nessuno
   gli farà.

Uso:
    venv\\Scripts\\python corpus\\train_qlora.py --misura        (solo throughput)
    venv\\Scripts\\python corpus\\train_qlora.py --passi 200     (prova vera)
"""

import argparse
import json
import math
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

MODELLO = "google/translategemma-12b-it"
IGNORA = -100


def hf_token():
    try:
        from utils.config import get_config
        return get_config().get_huggingface_token() or None
    except Exception:
        return None


def carica(nome, quanti=0):
    p = os.path.join(SCRIPT_DIR, nome)
    fuori = []
    with open(p, encoding="utf-8") as f:
        for riga in f:
            if riga.strip():
                fuori.append(json.loads(riga))
                if quanti and len(fuori) >= quanti:
                    break
    return fuori


def prepara(esempi, proc, max_len):
    """Da coppia a (input_ids, labels) con il prompt mascherato."""
    tok = proc.tokenizer
    fuori = []
    for r in esempi:
        conv = [{"role": "user", "content": [{
            "type": "text", "source_lang_code": "en",
            "target_lang_code": "it",
            "text": f"{r['istruzione']}\n{r['en']}"}]}]
        prompt = proc.apply_chat_template(conv, tokenize=False,
                                          add_generation_prompt=True)
        id_prompt = tok(prompt, add_special_tokens=False)["input_ids"]
        id_target = tok(r["it"] + "<end_of_turn>",
                        add_special_tokens=False)["input_ids"]
        ids = (id_prompt + id_target)[:max_len]
        lab = ([IGNORA] * len(id_prompt) + id_target)[:max_len]
        if len(ids) < 4 or all(x == IGNORA for x in lab):
            continue
        fuori.append((ids, lab))
    return fuori


def lotti(dati, dim, pad_id):
    """Batch ordinati per lunghezza: riduce il riempimento senza packing."""
    import torch
    dati = sorted(dati, key=lambda x: len(x[0]))
    for i in range(0, len(dati), dim):
        pezzo = dati[i:i + dim]
        lung = max(len(x[0]) for x in pezzo)
        ids = torch.full((len(pezzo), lung), pad_id, dtype=torch.long)
        lab = torch.full((len(pezzo), lung), IGNORA, dtype=torch.long)
        att = torch.zeros((len(pezzo), lung), dtype=torch.long)
        for j, (a, b) in enumerate(pezzo):
            ids[j, :len(a)] = torch.tensor(a)
            lab[j, :len(b)] = torch.tensor(b)
            att[j, :len(a)] = 1
        yield ids, lab, att


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="train.jsonl")
    ap.add_argument("--esempi", type=int, default=2000)
    ap.add_argument("--max-len", type=int, default=192)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--accumulo", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rango", type=int, default=16)
    ap.add_argument("--passi", type=int, default=30)
    ap.add_argument("--misura", action="store_true",
                    help="niente salvataggio: serve solo il throughput")
    args = ap.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForImageTextToText, AutoProcessor,
                              BitsAndBytesConfig)

    token = hf_token()
    proc = AutoProcessor.from_pretrained(MODELLO, token=token)
    tok = proc.tokenizer
    tok.padding_side = "right"          # in addestramento il padding va a destra
    pad_id = tok.pad_token_id or tok.eos_token_id

    print("Preparo gli esempi...")
    dati = prepara(carica(args.train, args.esempi), proc, args.max_len)
    token_utili = sum(sum(1 for x in l if x != IGNORA) for _, l in dati)
    token_tot = sum(len(i) for i, _ in dati)
    print(f"  {len(dati)} esempi | {token_tot:,} token".replace(",", ".") +
          f" di cui {token_utili:,} con gradiente".replace(",", ".") +
          f" ({token_utili * 100 // max(token_tot, 1)}%)\n")

    print(f"Carico {MODELLO} in NF4...")
    modello = AutoModelForImageTextToText.from_pretrained(
        MODELLO, token=token, device_map="auto",
        # `dtype` NON è ridondante con `bnb_4bit_compute_dtype`: senza,
        # bitsandbytes forza float16 su norm ed embedding, e su Gemma3 le
        # attivazioni scalate per sqrt(hidden_size) superano il massimo di
        # float16 — logit NaN e generazione di soli <pad>. Vedi engine.py.
        dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16),
    )
    modello = prepare_model_for_kbit_training(
        modello, use_gradient_checkpointing=True)
    modello.config.use_cache = False

    lora = LoraConfig(
        r=args.rango, lora_alpha=args.rango * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        # Solo le proiezioni di attenzione: rango basso e superficie ristretta
        # sono la difesa contro l'oblio. TranslateGemma è addestrato con RL
        # CONTRO la letteralità, ed è il motivo per cui vince sullo stile:
        # un adattamento aggressivo disferebbe proprio quello.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    modello = get_peft_model(modello, lora)
    allenabili = sum(p.numel() for p in modello.parameters() if p.requires_grad)
    totali = sum(p.numel() for p in modello.parameters())
    print(f"  parametri addestrabili: {allenabili:,}".replace(",", ".") +
          f" su {totali:,}".replace(",", ".") +
          f" ({allenabili / totali * 100:.3f}%)")
    print(f"  VRAM dopo il caricamento: "
          f"{torch.cuda.memory_allocated() / 1024**3:.2f} GB\n")

    ott = torch.optim.AdamW(
        [p for p in modello.parameters() if p.requires_grad], lr=args.lr)
    modello.train()

    passo = 0
    visti = 0
    picco = 0
    t0 = time.time()
    perdite = []
    for ids, lab, att in lotti(dati, args.batch, pad_id):
        ids, lab, att = (ids.to(modello.device), lab.to(modello.device),
                         att.to(modello.device))
        out = modello(input_ids=ids, attention_mask=att, labels=lab)
        (out.loss / args.accumulo).backward()
        perdite.append(out.loss.item())
        visti += int(att.sum().item())
        picco = max(picco, torch.cuda.max_memory_allocated())

        if len(perdite) % args.accumulo == 0:
            torch.nn.utils.clip_grad_norm_(
                [p for p in modello.parameters() if p.requires_grad], 1.0)
            ott.step()
            ott.zero_grad(set_to_none=True)
            passo += 1
            el = time.time() - t0
            media = sum(perdite[-args.accumulo:]) / args.accumulo
            print(f"  passo {passo:>4} | perdita {media:6.3f} | "
                  f"{visti / el:7.0f} token/s | {el / passo:5.2f} s/passo | "
                  f"picco {picco / 1024**3:.2f} GB")
            if passo >= args.passi:
                break

    el = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"  MISURA SULLA 3060")
    print(f"  token al secondo    : {visti / el:.0f}")
    print(f"  secondi per passo   : {el / max(passo, 1):.2f} "
          f"(batch {args.batch} x accumulo {args.accumulo})")
    print(f"  picco VRAM          : {picco / 1024**3:.2f} GB su 12")
    token_epoca = token_tot / len(dati) * 200000
    ore = token_epoca / max(visti / el, 1) / 3600
    print(f"  un'epoca su 200.000 coppie: {token_epoca / 1e6:.1f}M token, "
          f"{ore:.1f} ore a questo ritmo")
    print(f"{'=' * 70}")

    if not args.misura:
        dest = os.path.join(SCRIPT_DIR, "lora_prova")
        modello.save_pretrained(dest)
        print(f"\n  Adattatore salvato in {dest}")


if __name__ == "__main__":
    main()
