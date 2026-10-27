# -*- coding: utf-8 -*-
"""Apostrofi al posto degli accenti nell'italiano prodotto dai traduttori.

NLLB (e in parte gli LLM) scrive `e'`, `perche'`, `cosi'`, `si'` dove l'italiano
vuole `è`, `perché`, `così`, `sì`. Misurato su una clip da 10 minuti contro un
sottotitolo umano: 49 forme con apostrofo nell'output contro 12 nella reference,
e piegando gli accenti il WER italiano scende di ~4 punti
(`docs/benchmarks/2026-10-26-asr-reference-clip-a.md`, round 5).

La correzione è volutamente **a lista chiusa**: si converte solo una parola che
sta nell'elenco e che finisce con apostrofo. Tutto il resto resta intatto, perché
in italiano l'apostrofo è spesso legittimo:

    un po'      d'accordo     va' / sta' / fa' / da' / di' (imperativi)
    be' / to'   vent'anni     quest'anno

Per questo non esiste una regola generale "togli l'apostrofo": sostituirebbe
anche queste forme corrette.

Uso: `fix_text(testo)` sulle righe di un SRT italiano.
"""
from __future__ import annotations

import re
from typing import Dict

# Parole che in italiano vogliono l'accento quando il traduttore le scrive con
# l'apostrofo finale (chiave = forma senza accento, minuscola).
ACCENTED: Dict[str, str] = {
    "e": "è",
    "si": "sì",
    "ne": "né",
    "perche": "perché",
    "cosi": "così",
    "piu": "più",
    "puo": "può",
    "gia": "già",
    "cio": "ciò",
    "percio": "perciò",
    "citta": "città",
    "qualita": "qualità",
    "verita": "verità",
    "liberta": "libertà",
    "volonta": "volontà",
    "societa": "società",
    "universita": "università",
    "possibilita": "possibilità",
    "difficolta": "difficoltà",
    "attivita": "attività",
    "felicita": "felicità",
    "realta": "realtà",
    "meta": "metà",
    "pieta": "pietà",
    "bonta": "bontà",
    "gioventu": "gioventù",
    "virtu": "virtù",
    "servitu": "servitù",
    "caffe": "caffè",
    "tre": "tre",          # non accentata: presente per documentare le esclusioni
}

# Forme che finiscono con apostrofo e sono corrette così: mai toccate.
KEEP = {
    "po", "va", "sta", "fa", "da", "di", "be", "to", "mo", "ancor", "vent",
    "quant", "tutt", "grand", "sant", "bell", "quest", "quell", "d", "l", "un",
    "nell", "dell", "sull", "all", "coll", "dall",
}

# una parola (lettere, anche accentate) seguita da uno o più apostrofi finali
_PATTERN = re.compile(r"(?<![A-Za-zÀ-ÿ])([A-Za-zÀ-ÿ]+)'(?=[\s.,!?;:»\"”)]|$)")


def _replace(match: "re.Match[str]") -> str:
    word = match.group(1)
    key = word.lower()
    if key in KEEP:
        return match.group(0)
    accented = ACCENTED.get(key)
    if not accented:
        return match.group(0)
    if word.isupper() and len(word) > 1:
        return accented.upper()               # PERCHE' -> PERCHÉ
    if word[:1].isupper():
        return accented[:1].upper() + accented[1:]
    return accented


def fix_text(text: str) -> str:
    """Converte le forme accentate note; tutto il resto resta com'è."""
    if not text or "'" not in text:
        return text
    return _PATTERN.sub(_replace, text)


def fix_srt_text(content: str) -> str:
    """Come `fix_text`, ma preserva i timestamp (che contengono virgole, non apostrofi)."""
    return "\n".join(fix_text(line) for line in content.splitlines())


def count_fixes(text: str) -> int:
    """Quante sostituzioni farebbe `fix_text` — utile per i report."""
    return len(_PATTERN.findall(text)) - sum(
        1 for match in _PATTERN.finditer(text)
        if match.group(1).lower() in KEEP or match.group(1).lower() not in ACCENTED)
