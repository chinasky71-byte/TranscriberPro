"""
Costruzione del set di valutazione stratificato — Fase 0
========================================================
Campiona N segmenti da slang_dataset_stage2.jsonl bilanciando le CATEGORIE
difficili invece di prendere un campione casuale (che le sotto-rappresenta).

Motivo: il giudizio GEMBA-MQM deve dire dove un motore vince o perde, non solo
di quanto. Serve quindi che ogni categoria abbia abbastanza segmenti da rendere
il conteggio di error span leggibile.

Eseguire con:
    venv\\Scripts\\python mt_eval\\build_evalset.py

Output: mt_eval/evalset.jsonl  (source, reference, category)
"""

import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATASET = os.path.join(ROOT_DIR, "slang_dataset_stage2.jsonl")
OUT_PATH = os.path.join(SCRIPT_DIR, "evalset.jsonl")

SEED = 20260816
TOTAL = 300

# Quote per categoria. Il dialogo pesa di più perché è il caso dominante nei
# sottotitoli e quello dove NLLB-FT produce il "traduttorese" più evidente.
QUOTAS = {
    "dialogo": 70,
    "slang_idioma": 70,
    "monologo": 50,
    "parolacce": 30,
    "nomi_propri": 30,
    "numeri_date": 25,
    "testo_schermo": 25,
}

SLANG_KEYWORDS = [
    "ratio", "simp", "goated", "cringe", "bussin", "sus", "clout", "flex",
    "glow up", "main character", "understood the assignment", "no cap", "bet",
    "deadass", "stan", "ship", "ghost", "situationship", "manifesting",
    "gaslighting", "red flag", "green flag", "rizz", "glazing", " mid",
    "based", "delulu", "NPC", "POV", "love bombing", "benching",
    "breadcrumb", "soft launch", "hard launch", "slay", "lowkey", "highkey",
    "vibe", " fire", "shade", "era ", "canon event", "sending me",
    "ate that", "ick", "romanticize", "rent free", "trauma dump",
    "parasocial", "feral", "unhinged", "serve", "served", "villain era",
    "chronically online", "brain rot", "brainrot", "touch grass",
    "ratio'd", "soft life", "bestie",
]

PROFANITY = [
    "fuck", "shit", "bitch", "asshole", "bastard", "damn", "goddamn",
    "cunt", "dick", "piss", "bullshit", "motherfucker", "prick", "twat",
    "wanker", "bollocks", "crap", "screw you", "son of a bitch",
]

# Parole comuni che iniziano per maiuscola senza essere nomi propri.
_STOP_CAPS = {
    "I", "I'm", "I've", "I'll", "I'd", "The", "A", "An", "And", "But", "Or",
    "So", "If", "When", "What", "Why", "How", "Who", "Where", "You", "He",
    "She", "It", "We", "They", "This", "That", "There", "Here", "No", "Yes",
    "Not", "Do", "Don't", "Did", "Is", "Are", "Was", "Were", "Be", "Been",
    "Have", "Has", "Had", "Will", "Would", "Can", "Could", "Should", "My",
    "Your", "His", "Her", "Their", "Our", "Its", "Oh", "Well", "Just", "Now",
    "Okay", "OK", "Please", "Thanks", "Thank", "Hey", "Hi", "Hello", "Let",
    "Get", "Go", "Come", "Look", "Listen", "Stop", "Wait", "Sorry", "Maybe",
    "All", "Some", "Any", "Every", "One", "Two", "Three", "For", "To", "In",
    "On", "At", "Of", "With", "From", "By", "As", "Like", "Then", "Because",
}

_NUM_RE = re.compile(r"\b\d")
_TIME_RE = re.compile(r"\b(?:\d{1,2}:\d{2}|\d+\s*(?:am|pm|o'clock)|"
                      r"january|february|march|april|may|june|july|august|"
                      r"september|october|november|december|monday|tuesday|"
                      r"wednesday|thursday|friday|saturday|sunday)\b", re.I)


def _has_proper_noun(text: str) -> bool:
    """Maiuscola interna alla frase non spiegabile come inizio periodo."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        words = sentence.split()
        for w in words[1:]:                       # salta la prima parola
            bare = w.strip(".,!?;:\"'()[]-—…")
            if not bare or bare in _STOP_CAPS:
                continue
            if bare[0].isupper() and not bare.isupper() and len(bare) > 2:
                return True
    return False


def classify(source: str) -> str:
    """Assegna UNA categoria. L'ordine è una priorità: le categorie più rare
    e più diagnostiche vincono su quelle generiche."""
    lower = source.lower()

    if any(p in lower for p in PROFANITY):
        return "parolacce"

    # Testo a schermo / forced narrative: tutto maiuscolo, nessuna minuscola.
    letters = [c for c in source if c.isalpha()]
    if letters and not any(c.islower() for c in letters) and len(letters) > 3:
        return "testo_schermo"

    if any(k in lower for k in SLANG_KEYWORDS):
        return "slang_idioma"

    if _TIME_RE.search(source) or _NUM_RE.search(source):
        return "numeri_date"

    if _has_proper_noun(source):
        return "nomi_propri"

    # Dialogo: blocco a più righe con marcatore di cambio parlante.
    if "\n" in source and "- " in source:
        return "dialogo"

    # Monologo: frase singola lunga, il caso in cui la fluidità si vede meglio.
    if "\n" not in source and len(source) >= 60:
        return "monologo"

    return "altro"


def main():
    if not os.path.isfile(DATASET):
        sys.exit(f"Dataset non trovato: {DATASET}")

    buckets = defaultdict(list)
    seen = set()
    total_rows = 0

    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            total_rows += 1
            src = item.get("source", "").strip()
            ref = (item.get("target") or item.get("reference") or "").strip()
            if not src or not ref:
                continue
            # Dedup su testo normalizzato: il corpus ha battute ripetute.
            key = src.lower()
            if key in seen:
                continue
            seen.add(key)
            buckets[classify(src)].append({"source": src, "reference": ref})

    print(f"Righe lette: {total_rows} | uniche: {len(seen)}")
    print("\nDisponibilità per categoria:")
    for cat in sorted(buckets, key=lambda c: -len(buckets[c])):
        print(f"  {cat:<16} {len(buckets[cat]):>6}")

    rng = random.Random(SEED)
    selected = []
    shortfall = 0

    for cat, quota in QUOTAS.items():
        pool = buckets.get(cat, [])
        take = min(quota, len(pool))
        if take < quota:
            shortfall += quota - take
            print(f"\n  ATTENZIONE: '{cat}' ha solo {len(pool)} segmenti "
                  f"(quota {quota})")
        for item in rng.sample(pool, take):
            selected.append({**item, "category": cat})

    # Se una categoria è povera, il resto si riempie dalle più ricche così il
    # totale resta N — altrimenti i confronti tra run avrebbero base diversa.
    if shortfall:
        used = {s["source"] for s in selected}
        filler_pool = [it for cat in ("dialogo", "slang_idioma", "monologo")
                       for it in buckets.get(cat, []) if it["source"] not in used]
        rng.shuffle(filler_pool)
        for item in filler_pool[:shortfall]:
            selected.append({**item, "category": classify(item["source"])})

    rng.shuffle(selected)
    for i, item in enumerate(selected, 1):
        item["id"] = i

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for item in selected:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nSet scritto: {OUT_PATH}  ({len(selected)} segmenti)")
    print("\nComposizione finale:")
    for cat, n in Counter(s["category"] for s in selected).most_common():
        print(f"  {cat:<16} {n:>4}")


if __name__ == "__main__":
    main()
