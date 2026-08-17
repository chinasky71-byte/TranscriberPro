"""
Giudice GEMBA-MQM per il confronto A/B tra due motori di traduzione EN->IT
===========================================================================
Perché non chrF: chrF misura la sovrapposizione di caratteri con la reference
e quindi premia la traduzione letterale. L'obiettivo qui è la FLUIDITA', che
per costruzione si allontana dalla reference. GEMBA-MQM invece restituisce
error span TIPIZZATI: la colonna che decide è fluency/style, non un punteggio
aggregato.

Le due traduzioni vengono presentate al giudice in ordine randomizzato e
anonimo (SISTEMA 1 / SISTEMA 2) per evitare il bias di posizione; la mappatura
viene ricostruita a posteriori.

Uso:
    venv\\Scripts\\python mt_eval\\run_gemba.py --a nllb_ft.jsonl --b aya.jsonl
    venv\\Scripts\\python mt_eval\\run_gemba.py --a ... --b ... --limit 10

Input traduzioni: JSONL con {"id": int, "text": str} per riga.
Output: mt_eval/gemba_<A>_vs_<B>.jsonl  + report a schermo.
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
EVALSET = os.path.join(SCRIPT_DIR, "evalset.jsonl")

MODEL = "claude-opus-5"
OPENAI_MODEL = "gpt-4o"
MAX_TOKENS = 8000          # thinking + risposta condividono questo tetto
SEED = 20260816
MAX_WORKERS = 6

# Token al minuto concessi dall'organizzazione. Il tetto è per ORGANIZZAZIONE,
# non per processo: due run in parallelo se lo dividono, e superarlo non
# rallenta le richieste — le RIFIUTA con un 429. Misurato su questo account:
# 30.000 TPM su gpt-4o.
DEFAULT_TPM = 30000
# Costo osservato di un giudizio: ~1.050 token di prompt (di cui ~700 di
# system) più ~90 di risposta. Si arrotonda per eccesso perché il limitatore
# deve prenotare PRIMA di sapere quanto consumerà davvero.
TOKENS_PER_JUDGMENT = 1250

SEVERITY_WEIGHT = {"minor": 1, "major": 5, "critical": 10}

SYSTEM_PROMPT = """\
Sei un revisore professionista di sottotitoli italiani. Valuti traduzioni \
dall'inglese all'italiano di battute di film e serie TV secondo lo schema MQM.

Contesto d'uso: i testi sono blocchi di sottotitolo. Le convenzioni di \
riferimento sono quelle della guida di stile italiana Netflix: massimo 42 \
caratteri per riga e 2 righe, i nomi propri non si traducono, le volgarità \
non si censurano mai e vanno rese con severità equivalente, i riempitivi e le \
ripetizioni vanno condensati invece che tradotti alla lettera, il registro \
deve rispecchiare quello dell'originale.

Per ogni traduzione elenca gli ERROR SPAN che trovi. Ogni errore ha:

- category, una tra:
  * accuracy      — il significato non corrisponde alla fonte
  * fluency       — l'italiano non è corretto o non è naturale
  * style         — italiano corretto ma innaturale per un sottotitolo
  * terminology   — resa incoerente o sbagliata di un termine o nome proprio
  * non_translation — testo lasciato in inglese o output degenerato

- subcategory, una tra:
  accuracy: mistranslation, omission, addition, untranslated
  fluency: grammar, spelling, punctuation, register, unnatural
  style: awkward, literal_calque, verbose, tone_mismatch
  terminology: inconsistent, wrong_term, proper_noun_translated
  non_translation: non_translation

- severity: minor | major | critical
  minor    = si nota ma non ostacola la comprensione
  major    = distorce il senso o suona chiaramente sbagliato
  critical = rende la battuta inutilizzabile

- span: la porzione ESATTA di testo italiano in cui sta l'errore
- explanation: una frase, in italiano

Due indicazioni che contano più delle altre per questa valutazione:

1. "literal_calque" va usata quando la traduzione ricalca la sintassi inglese \
invece di usare la forma che userebbe un italiano: pronomi soggetto \
ridondanti, possessivi ridondanti ("la sua mano" per "the hand"), passivo \
dove l'italiano userebbe l'attivo o il "si" impersonale, "che cosa" al posto \
di "cosa", calchi di espressioni idiomatiche. E' il difetto tipico dei motori \
di traduzione automatica ed è esattamente ciò che questa valutazione deve \
misurare: segnalalo ogni volta che lo vedi, anche quando la frase è \
comprensibile e grammaticalmente corretta.

2. Non penalizzare una traduzione perché si allontana dalla lettera \
dell'originale. Condensare, omettere un riempitivo, cambiare la struttura \
della frase o scegliere un idioma italiano diverso sono scelte CORRETTE se il \
senso e il registro si conservano. Segnala un'omissione solo quando si perde \
informazione che lo spettatore non ricaverebbe altrimenti.

La reference italiana fornita è una traduzione professionale, utile come \
termine di paragone. Non è l'unica resa valida: non segnalare differenze \
dalla reference che non siano errori in sé.

Se una traduzione non ha errori, restituisci una lista vuota. Non inventare \
errori per simmetria tra i due sistemi: è normale che uno ne abbia più \
dell'altro."""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "system_1_errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["accuracy", "fluency", "style",
                                 "terminology", "non_translation"],
                    },
                    "subcategory": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "major", "critical"],
                    },
                    "span": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["category", "subcategory", "severity", "span",
                             "explanation"],
                "additionalProperties": False,
            },
        },
        "system_2_errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["accuracy", "fluency", "style",
                                 "terminology", "non_translation"],
                    },
                    "subcategory": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "major", "critical"],
                    },
                    "span": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["category", "subcategory", "severity", "span",
                             "explanation"],
                "additionalProperties": False,
            },
        },
        "preferred": {
            "type": "string",
            "enum": ["system_1", "system_2", "tie"],
            "description": "Quale sottotitolo pubblicheresti, considerando "
                           "insieme fedeltà e naturalezza.",
        },
        "preference_reason": {"type": "string"},
    },
    "required": ["system_1_errors", "system_2_errors", "preferred",
                 "preference_reason"],
    "additionalProperties": False,
}


def load_translations(path):
    """Legge un JSONL {"id", "text"} e restituisce {id: text}."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            out[int(item["id"])] = item["text"]
    return out


def load_evalset(path=None):
    items = []
    with open(path or EVALSET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def build_user_message(item, text_1, text_2):
    return (
        f"ORIGINALE (inglese):\n{item['source']}\n\n"
        f"REFERENCE professionale (italiano):\n{item['reference']}\n\n"
        f"SISTEMA 1:\n{text_1}\n\n"
        f"SISTEMA 2:\n{text_2}\n\n"
        f"Valuta entrambi i sistemi."
    )


class TokenRateLimiter:
    """Tiene le richieste sotto il tetto di token al minuto dell'account.

    Serve perché il retry da solo non basta: quando il secchiello è vuoto lo
    resta per decine di secondi, e quattro tentativi con backoff esponenziale
    si esauriscono in sette. È esattamente così che una run è finita a 229
    segmenti su 400 — i segmenti falliti venivano saltati, non riprovati, e il
    confronto restava monco senza che niente lo segnalasse.

    Finestra scorrevole invece di secchiello a gettoni: il limite di OpenAI è
    calcolato sui token consumati negli ultimi sessanta secondi, e replicarlo
    con la stessa forma evita di andare a sbattere sul bordo.
    """

    def __init__(self, tokens_per_minute, safety=0.85):
        self.budget = max(1, int(tokens_per_minute * safety))
        self.lock = threading.Lock()
        self.spent = []          # (istante, token) degli ultimi 60 secondi
        self.waited = 0.0

    def acquire(self, tokens):
        while True:
            with self.lock:
                now = time.monotonic()
                self.spent = [(t, n) for t, n in self.spent if now - t < 60]
                used = sum(n for _, n in self.spent)
                if used + tokens <= self.budget or not self.spent:
                    self.spent.append((now, tokens))
                    return
                # Aspetta che scada la prenotazione più vecchia: è il primo
                # istante in cui il budget può essersi liberato.
                pausa = 60 - (now - self.spent[0][0]) + 0.05
                self.waited += pausa
            time.sleep(max(0.05, pausa))


class CreditoEsaurito(RuntimeError):
    """Il conto è a zero: nessun tentativo successivo può riuscire."""


def _credito_finito(exc):
    testo = str(exc).lower()
    return ("no credits remaining" in testo
            or "insufficient_quota" in testo
            or "credit_balance" in testo
            or "billing" in testo and "hard limit" in testo)


def _retry_after_seconds(exc):
    """Quanto chiede di aspettare il 429, se lo dice.

    Il messaggio di OpenAI porta il tempo esatto ("Please try again in
    1.634s"); rispettarlo è più preciso di qualunque backoff inventato.
    """
    m = re.search(r"try again in ([\d.]+)(ms|s)", str(exc))
    if not m:
        return None
    val = float(m.group(1))
    return val / 1000 if m.group(2) == "ms" else val


def _call_anthropic(client, user_message, model):
    """Ritorna (payload, usage). Il system prompt è messo in cache: è identico
    per tutti i segmenti e vale ~700 token per chiamata."""
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema",
                                  "schema": RESULT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("giudizio rifiutato dal modello")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "cache_read": response.usage.cache_read_input_tokens,
    }


def _call_openai(client, user_message, model):
    """GEMBA-MQM è stato definito e validato su GPT-4: usarlo qui è fedele
    all'implementazione originale della metrica, non un ripiego."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "mqm_evaluation",
                "strict": True,
                "schema": RESULT_SCHEMA,
            },
        },
        max_completion_tokens=MAX_TOKENS,
    )
    choice = response.choices[0]
    if choice.finish_reason == "content_filter":
        raise RuntimeError("giudizio bloccato dal filtro contenuti")
    if choice.message.refusal:
        raise RuntimeError(f"giudizio rifiutato: {choice.message.refusal}")
    return json.loads(choice.message.content), {
        "input": response.usage.prompt_tokens,
        "output": response.usage.completion_tokens,
        "cache_read": getattr(
            getattr(response.usage, "prompt_tokens_details", None),
            "cached_tokens", 0) or 0,
    }


def judge_one(client, item, trans_a, trans_b, rng_seed,
              provider="anthropic", model=None, limiter=None):
    """Una chiamata al giudice. L'ordine di presentazione dipende dall'id, così
    la randomizzazione è deterministica e la run è riproducibile."""
    rng = random.Random(rng_seed + item["id"])
    swap = rng.random() < 0.5

    text_a = trans_a.get(item["id"], "")
    text_b = trans_b.get(item["id"], "")
    text_1, text_2 = (text_b, text_a) if swap else (text_a, text_b)
    user_message = build_user_message(item, text_1, text_2)

    call = _call_anthropic if provider == "anthropic" else _call_openai
    model = model or (MODEL if provider == "anthropic" else OPENAI_MODEL)

    last_exc = None
    for attempt in range(8):
        if limiter is not None:
            limiter.acquire(TOKENS_PER_JUDGMENT)
        try:
            payload, usage = call(client, user_message, model)
            break
        except Exception as exc:
            # I rifiuti non si risolvono riprovando: solo gli errori di rete
            # e i rate limit meritano un altro tentativo.
            if "rifiutato" in str(exc) or "filtro" in str(exc):
                raise
            # Il credito finito arriva con lo stesso codice 429 di un limite
            # di frequenza, ma non è transitorio: riprovarlo significa
            # macinare a vuoto otto tentativi per quattro giri su ogni
            # segmento rimasto. Si ferma tutto subito, il checkpoint tiene il
            # lavoro fatto e basta rilanciare dopo aver ricaricato.
            if _credito_finito(exc):
                raise CreditoEsaurito(str(exc)[:200])
            last_exc = exc
            if attempt == 7:
                raise
            # Otto tentativi e non quattro, e attesa fino a un minuto: un
            # rate limit sui token non si sblocca in sette secondi, ci vuole
            # che scorra la finestra. Se il server dice quanto aspettare, si
            # usa quello.
            suggerito = _retry_after_seconds(exc)
            pausa = suggerito + 0.5 if suggerito is not None else \
                min(60.0, 2 ** attempt) + rng.random()
            time.sleep(pausa)
    else:
        raise last_exc or RuntimeError("retry esauriti")

    # Rimappa dalle etichette anonime ai sistemi reali.
    if swap:
        errors_a = payload["system_2_errors"]
        errors_b = payload["system_1_errors"]
        pref_map = {"system_1": "b", "system_2": "a", "tie": "tie"}
    else:
        errors_a = payload["system_1_errors"]
        errors_b = payload["system_2_errors"]
        pref_map = {"system_1": "a", "system_2": "b", "tie": "tie"}

    return {
        "id": item["id"],
        "category": item["category"],
        "source": item["source"],
        "reference": item["reference"],
        "text_a": text_a,
        "text_b": text_b,
        "errors_a": errors_a,
        "errors_b": errors_b,
        "preferred": pref_map[payload["preferred"]],
        "preference_reason": payload["preference_reason"],
        "usage": usage,
    }


def mqm_score(errors):
    """Punteggio MQM pesato: più basso è meglio. 0 = nessun errore."""
    return sum(SEVERITY_WEIGHT.get(e["severity"], 1) for e in errors)


def print_report(results, name_a, name_b, out_path, model=MODEL):
    n = len(results)
    lines = []
    add = lines.append

    add("=" * 72)
    add(f"  GEMBA-MQM — {name_a}  (A)   vs   {name_b}  (B)")
    add(f"  Segmenti valutati: {n} | giudice: {model}")
    add("=" * 72)

    # --- Error span per categoria, normalizzati per 100 segmenti ------------
    cat_a, cat_b = Counter(), Counter()
    sev_a, sev_b = Counter(), Counter()
    sub_a, sub_b = Counter(), Counter()
    for r in results:
        for e in r["errors_a"]:
            cat_a[e["category"]] += 1
            sev_a[e["severity"]] += 1
            sub_a[f"{e['category']}/{e['subcategory']}"] += 1
        for e in r["errors_b"]:
            cat_b[e["category"]] += 1
            sev_b[e["severity"]] += 1
            sub_b[f"{e['category']}/{e['subcategory']}"] += 1

    k = 100.0 / n
    add("")
    add("  ERROR SPAN PER 100 SEGMENTI (più basso = meglio)")
    add(f"  {'categoria':<18}{'A':>10}{'B':>10}{'delta':>10}")
    add(f"  {'-' * 48}")
    for cat in ["accuracy", "fluency", "style", "terminology",
                "non_translation"]:
        a, b = cat_a[cat] * k, cat_b[cat] * k
        add(f"  {cat:<18}{a:>10.1f}{b:>10.1f}{b - a:>+10.1f}")
    ta, tb = sum(cat_a.values()) * k, sum(cat_b.values()) * k
    add(f"  {'-' * 48}")
    add(f"  {'TOTALE':<18}{ta:>10.1f}{tb:>10.1f}{tb - ta:>+10.1f}")
    add("")
    add("  Il delta è B meno A: negativo = B ha meno errori di A.")

    # --- La metrica che decide --------------------------------------------
    fs_a = (cat_a["fluency"] + cat_a["style"]) * k
    fs_b = (cat_b["fluency"] + cat_b["style"]) * k
    acc_a = (cat_a["accuracy"] + cat_a["non_translation"]) * k
    acc_b = (cat_b["accuracy"] + cat_b["non_translation"]) * k
    add("")
    add("  CRITERIO DI AVANZAMENTO")
    add(f"    fluency+style   A {fs_a:6.1f}   B {fs_b:6.1f}   "
        f"delta {fs_b - fs_a:+6.1f}   <- deve SCENDERE")
    add(f"    accuracy+non-tr A {acc_a:6.1f}   B {acc_b:6.1f}   "
        f"delta {acc_b - acc_a:+6.1f}   <- non deve salire")

    # --- Severità ----------------------------------------------------------
    add("")
    add("  SEVERITÀ (conteggio assoluto)")
    add(f"  {'':<18}{'A':>10}{'B':>10}")
    for sev in ["minor", "major", "critical"]:
        add(f"  {sev:<18}{sev_a[sev]:>10}{sev_b[sev]:>10}")

    # --- Punteggio MQM pesato ---------------------------------------------
    mqm_a = sum(mqm_score(r["errors_a"]) for r in results) / n
    mqm_b = sum(mqm_score(r["errors_b"]) for r in results) / n
    add("")
    add(f"  MQM pesato medio (minor=1 major=5 critical=10, più basso = meglio)")
    add(f"    A {mqm_a:.2f}   B {mqm_b:.2f}   delta {mqm_b - mqm_a:+.2f}")

    # --- Preferenza diretta ------------------------------------------------
    pref = Counter(r["preferred"] for r in results)
    add("")
    add("  QUALE SOTTOTITOLO PUBBLICHERESTI")
    add(f"    A vince : {pref['a']:>4}  ({pref['a'] / n * 100:.0f}%)")
    add(f"    B vince : {pref['b']:>4}  ({pref['b'] / n * 100:.0f}%)")
    add(f"    pari    : {pref['tie']:>4}  ({pref['tie'] / n * 100:.0f}%)")

    # --- Rottura per categoria di segmento ---------------------------------
    add("")
    add("  PER CATEGORIA DI SEGMENTO (error span totali per 100 segmenti)")
    add(f"  {'categoria':<16}{'n':>5}{'A':>10}{'B':>10}{'delta':>10}"
        f"{'  preferenza':>14}")
    add(f"  {'-' * 65}")
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        rs = by_cat[cat]
        m = len(rs)
        ea = sum(len(r["errors_a"]) for r in rs) * 100.0 / m
        eb = sum(len(r["errors_b"]) for r in rs) * 100.0 / m
        p = Counter(r["preferred"] for r in rs)
        add(f"  {cat:<16}{m:>5}{ea:>10.1f}{eb:>10.1f}{eb - ea:>+10.1f}"
            f"{f'A {p[chr(97)]} / B {p[chr(98)]}':>14}")

    # --- Sottocategorie più frequenti --------------------------------------
    add("")
    add("  SOTTOCATEGORIE PIÙ FREQUENTI")
    add(f"  {'sottocategoria':<36}{'A':>8}{'B':>8}")
    allsubs = set(sub_a) | set(sub_b)
    for sub in sorted(allsubs, key=lambda s: -(sub_a[s] + sub_b[s]))[:12]:
        add(f"  {sub:<36}{sub_a[sub]:>8}{sub_b[sub]:>8}")

    # --- Costo -------------------------------------------------------------
    tot_in = sum(r["usage"]["input"] for r in results)
    tot_out = sum(r["usage"]["output"] for r in results)
    tot_cache = sum(r["usage"]["cache_read"] for r in results)
    add("")
    add(f"  Token: input {tot_in:,} | cache read {tot_cache:,} | "
        f"output {tot_out:,}")
    add("=" * 72)

    report = "\n".join(lines)
    print(report)
    report_path = out_path.replace(".jsonl", "_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"\nReport salvato: {report_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="JSONL traduzioni sistema A")
    ap.add_argument("--b", required=True, help="JSONL traduzioni sistema B")
    ap.add_argument("--name-a", default=None)
    ap.add_argument("--name-b", default=None)
    ap.add_argument("--limit", type=int, default=0,
                    help="valuta solo i primi N segmenti (prova a costo basso)")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--tpm", type=int, default=DEFAULT_TPM,
                    help=f"tetto di token al minuto dell'account "
                         f"(default {DEFAULT_TPM}); 0 disattiva il "
                         f"limitatore. È per ORGANIZZAZIONE: se girano due "
                         f"run insieme, va dimezzato in entrambe")
    ap.add_argument("--provider", default="anthropic",
                    choices=["anthropic", "openai"])
    ap.add_argument("--model", default=None,
                    help="sovrascrive il modello di default del provider")
    ap.add_argument("--src", default=None,
                    help="JSONL del set (source/reference/category); "
                         "default: il set sintetico")
    args = ap.parse_args()

    name_a = args.name_a or os.path.splitext(os.path.basename(args.a))[0]
    name_b = args.name_b or os.path.splitext(os.path.basename(args.b))[0]
    out_path = os.path.join(SCRIPT_DIR, f"gemba_{name_a}_vs_{name_b}.jsonl")

    cfg = {}
    cfg_path = os.path.expanduser("~/.transcriberpro/config.json")
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)

    if args.provider == "anthropic":
        import anthropic
        key = cfg.get("claude_api_key") or None
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    else:
        from openai import OpenAI
        key = cfg.get("openai_api_key") or None
        client = OpenAI(api_key=key) if key else OpenAI()

    model = args.model or (MODEL if args.provider == "anthropic"
                           else OPENAI_MODEL)

    items = load_evalset(args.src)
    trans_a = load_translations(args.a)
    trans_b = load_translations(args.b)

    missing = [it["id"] for it in items
               if it["id"] not in trans_a or it["id"] not in trans_b]
    if missing:
        print(f"ATTENZIONE: {len(missing)} segmenti senza traduzione in uno "
              f"dei due file, esclusi: {missing[:10]}")
        items = [it for it in items if it["id"] not in set(missing)]

    if args.limit:
        items = items[:args.limit]

    # Riprende una run interrotta invece di ripagare i segmenti già giudicati.
    done = {}
    if os.path.isfile(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    done[r["id"]] = r
        if done:
            print(f"Checkpoint trovato: {len(done)} segmenti già giudicati.")

    todo = [it for it in items if it["id"] not in done]
    print(f"Da giudicare: {len(todo)} segmenti | {args.provider}/{model} | "
          f"{args.workers} richieste parallele\n")

    results = list(done.values())
    lock = threading.Lock()
    t0 = time.time()

    limiter = TokenRateLimiter(args.tpm) if args.tpm else None
    if limiter:
        print(f"Ritmo massimo: {args.tpm} token/min → "
              f"~{limiter.budget // TOKENS_PER_JUDGMENT} giudizi/min\n")

    if todo:
        # La prima chiamata scrive la cache del system prompt: se partissero
        # tutte insieme, ognuna la riscriverebbe a prezzo pieno.
        first = judge_one(client, todo[0], trans_a, trans_b, SEED,
                          args.provider, model, limiter)
        results.append(first)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(first, ensure_ascii=False) + "\n")

        # Un segmento che fallisce va RIMESSO IN CODA, non saltato: saltandolo
        # il confronto resta monco e il report lo dichiara completo lo stesso.
        # È così che una run è finita a 229 segmenti su 400 senza che nulla lo
        # segnalasse.
        pendenti = list(todo[1:])
        fatti = 1
        a_secco = False
        with open(out_path, "a", encoding="utf-8") as fout:
            for giro in range(1, 5):
                if not pendenti:
                    break
                if giro > 1:
                    print(f"\n  Giro {giro}: riprovo {len(pendenti)} segmenti "
                          f"rimasti indietro")
                    time.sleep(20)
                falliti = []
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = {
                        pool.submit(judge_one, client, it, trans_a, trans_b,
                                    SEED, args.provider, model, limiter): it
                        for it in pendenti
                    }
                    for fut in as_completed(futures):
                        item = futures[fut]
                        try:
                            r = fut.result()
                        except CreditoEsaurito as exc:
                            if not a_secco:
                                print(f"\n  CREDITO ESAURITO: {exc}")
                                a_secco = True
                            falliti.append(item)
                            continue
                        except Exception as exc:
                            print(f"  [{item['id']}] fallito: "
                                  f"{str(exc)[:120]}")
                            falliti.append(item)
                            continue
                        with lock:
                            results.append(r)
                            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                            fout.flush()
                            fatti += 1
                            n = fatti
                        if n % 20 == 0 or n == len(todo):
                            el = time.time() - t0
                            print(f"  [{n:>4}/{len(todo)}] {el:.0f}s | "
                                  f"~{el / n * (len(todo) - n):.0f}s rimanenti")
                pendenti = falliti
                if a_secco:
                    break

        if pendenti:
            motivo = ("credito esaurito" if a_secco
                      else "quattro giri di tentativi")
            print(f"\n  ATTENZIONE: {len(pendenti)} segmenti NON giudicati "
                  f"({motivo}).")
            print(f"  Il report qui sotto vale sui {len(results)} segmenti "
                  f"effettivamente valutati, non su tutto il set.")
            print(f"  Rilanciare lo stesso comando: riprende dal checkpoint.")
        if limiter and limiter.waited > 1:
            print(f"  Attesa per il tetto di token: "
                  f"{limiter.waited / 60:.1f} min")

    print(f"\nGiudizi completati in {(time.time() - t0) / 60:.1f} minuti")
    print(f"Risultati: {out_path}\n")
    results.sort(key=lambda r: r["id"])
    print_report(results, name_a, name_b, out_path, model)


if __name__ == "__main__":
    main()
