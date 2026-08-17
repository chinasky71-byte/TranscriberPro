"""
Validazione deterministica dell'output dell'LLM
================================================
Un modello da 8B che traduce a blocchi disallinea: fonde due battute in una,
salta un id, risponde con testo attorno al JSON, entra in loop. Sono i modi di
fallire documentati da tutti i tool di sottotitolazione basati su LLM, e senza
una rete che li intercetti la pipeline non è utilizzabile in produzione.

I controlli sono divisi in due classi, e la distinzione è la parte che conta:

- BLOCCANTI: l'output è inservibile (cardinalità sbagliata, blocco vuoto,
  testo non tradotto, output degenerato). Innescano il retry a scalare.
- SEGNALAZIONI: l'output è usabile ma imperfetto (sfora il budget caratteri,
  registro incoerente). NON innescano retry — le sistema il post-processing,
  oppure restano come diagnostica. Fare retry su queste porterebbe a cicli
  infiniti, perché l'italiano è strutturalmente più lungo dell'inglese.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .prompt_builder import CPL_MAX, SubtitleUnit

# Ratio oltre i quali la traduzione ha quasi certamente perso o inventato
# contenuto. Molto ampi di proposito: condensare è l'obiettivo, non un difetto.
#
# La prima versione usava 0.35 come soglia BLOCCANTE ed era sbagliata: faceva
# scattare il retry proprio sui blocchi condensati meglio, triplicando il tempo
# di elaborazione per punire il comportamento desiderato. Ora un testo corto è
# bloccante solo quando è così corto da essere quasi certamente un'omissione, e
# solo su sorgenti lunghi, dove perdere metà del contenuto conta davvero.
LEN_RATIO_MIN = 0.20          # sotto questa soglia: probabile omissione
LEN_RATIO_SUSPECT = 0.35      # sotto questa: solo segnalazione
LEN_RATIO_MAX = 2.4
OMISSION_MIN_SRC_LEN = 40     # sorgenti più corti condensano molto per natura

# Stopword ad alta frequenza, usate solo per distinguere "è italiano" da
# "è rimasto inglese". Non è un language detector: è un test a due classi.
_IT_MARKERS = {
    "che", "non", "di", "il", "la", "le", "lo", "gli", "un", "una", "per",
    "con", "sono", "è", "ho", "hai", "ha", "mi", "ti", "si", "ci", "vi",
    "come", "quando", "perché", "cosa", "questo", "questa", "quello", "del",
    "della", "nel", "nella", "ma", "se", "più", "anche", "solo", "tutto",
    "essere", "fare", "voglio", "devo", "posso", "sei", "siamo", "no", "sì",
}
_EN_MARKERS = {
    "the", "and", "you", "that", "this", "with", "have", "what", "for",
    "not", "your", "was", "are", "they", "there", "would", "should", "could",
    "know", "just", "don't", "i'm", "it's", "we're", "he's", "she's", "about",
}

_WORD_RE = re.compile(r"[a-zàèéìòóùA-ZÀÈÉÌÒÓÙ']+")

# Turpiloquio. La guida di stile italiana Netflix vieta di censurare: le
# volgarità vanno rese con severità equivalente.
#
# Serve un controllo esplicito perché i modelli chat allineati (misurato su
# i modelli allineati) attenuano sistematicamente le parolacce anche con la regola
# scritta nel system prompt: 6 rese corrette su 30, contro 26 di NLLB
# fine-tuned e 17 della traduzione umana. Rafforzare il prompt con esempi
# few-shot porta a 13/30 — meglio, ma non basta. Questo controllo intercetta
# ciò che il prompt non ottiene.
_EN_PROFANITY = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|arsehole|bitch\w*|bastard|cunt|"
    r"dick|prick|twat|wanker|bollocks|motherfuck\w*|goddamn|piss(?:ed)?)\b",
    re.I)
_IT_PROFANITY = re.compile(
    r"cazz|merd|stronz|fanculo|porc[oa]|troi|figa|coglion|puttan|inculat|"
    r"bastard|vaffa|fott|incazz|schifez|minchi", re.I)
# Eufemismi che i modelli allineati producono al posto delle parolacce.
_IT_EUPHEMISM = re.compile(
    r"diavol|maledett|accident|caspit|cavolo|dannazion|perbacco|"
    r"santo ciel|accipicchia|mannagg|mazza\b", re.I)


@dataclass
class Issue:
    """Un problema rilevato su un blocco (o sull'intero batch se id è None)."""

    code: str
    detail: str
    id: Optional[int] = None
    blocking: bool = True

    def __str__(self) -> str:
        where = f"blocco {self.id}" if self.id is not None else "batch"
        return f"[{self.code}] {where}: {self.detail}"


def parse_response(raw: str, expected_ids: Sequence[int]) -> Tuple[Dict[int, str], List[Issue]]:
    """Estrae {id: testo} dalla risposta grezza del modello.

    Tollera il caso comune in cui il modello incornicia il JSON con del testo
    o con un blocco markdown: recuperare qui evita un retry inutile.
    """
    issues: List[Issue] = []
    text = raw.strip()

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return {}, [Issue("no_json", "nessun array JSON nella risposta")]

    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        return {}, [Issue("bad_json", f"JSON non valido: {exc}")]

    if not isinstance(data, list):
        return {}, [Issue("bad_json", "la risposta non è un array")]

    out: Dict[int, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            idx = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        value = entry.get("it", entry.get("text", ""))
        if isinstance(value, str):
            out[idx] = value.strip()

    expected = set(expected_ids)
    missing = sorted(expected - set(out))
    extra = sorted(set(out) - expected)
    if missing:
        issues.append(Issue(
            "missing_ids",
            f"{len(missing)} blocchi assenti nella risposta: {missing[:8]}",
        ))
    if extra:
        issues.append(Issue(
            "extra_ids", f"id non richiesti nella risposta: {extra[:8]}",
        ))
        for idx in extra:
            out.pop(idx, None)

    return out, issues


def _is_degenerate(text: str) -> bool:
    """Loop ripetitivo: stesso n-gramma che ricorre oltre ogni plausibilità."""
    words = text.split()
    if len(words) < 8:
        return False
    for n in (1, 2, 3):
        grams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
        if not grams:
            continue
        most = max(set(grams), key=grams.count)
        if grams.count(most) >= max(4, len(grams) // 3):
            return True
    return False


def _looks_english(text: str) -> bool:
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if len(words) < 4:
        return False
    it_hits = len(words & _IT_MARKERS)
    en_hits = len(words & _EN_MARKERS)
    return en_hits >= 2 and en_hits > it_hits


def _register_of(text: str) -> Optional[str]:
    """Rileva il registro dalla forma allocutiva, se presente."""
    lower = f" {text.lower()} "
    formal = re.search(r"\b(lei|la ringrazio|le dispiace|si accomodi|"
                       r"voglia|desidera|scusi|senta|guardi|dica)\b", lower)
    informal = re.search(r"\b(tu|ti|tuo|tua|tuoi|tue|sei|hai|puoi|vuoi|"
                         r"scusa|senti|guarda|dimmi|vieni)\b", lower)
    if formal and not informal:
        return "formale"
    if informal and not formal:
        return "informale"
    return None


def validate(
    units: Sequence[SubtitleUnit],
    translations: Dict[int, str],
    glossary: Optional[Dict[str, str]] = None,
    speaker_register: Optional[Dict[str, str]] = None,
) -> List[Issue]:
    """Gli otto controlli. Restituisce la lista dei problemi trovati."""
    issues: List[Issue] = []
    by_id = {u.id: u for u in units}

    # 1 — cardinalità 1:1
    missing = [u.id for u in units if u.id not in translations]
    if missing:
        issues.append(Issue(
            "cardinality",
            f"{len(missing)}/{len(units)} blocchi senza traduzione: "
            f"{missing[:8]}",
        ))

    for idx, text in translations.items():
        unit = by_id.get(idx)
        if unit is None:
            continue
        src = unit.text
        stripped = text.strip()

        # 2 — non vuoto
        if not stripped or not re.search(r"\w", stripped):
            issues.append(Issue("empty", "traduzione vuota", idx))
            continue

        # 3 — rapporto di lunghezza
        if len(src) >= 15:
            ratio = len(stripped) / len(src)
            if ratio < LEN_RATIO_MIN and len(src) >= OMISSION_MIN_SRC_LEN:
                issues.append(Issue(
                    "too_short",
                    f"rapporto {ratio:.2f}: probabile omissione", idx))
            elif ratio < LEN_RATIO_SUSPECT:
                issues.append(Issue(
                    "short",
                    f"rapporto {ratio:.2f}: condensazione forte",
                    idx, blocking=False))
            elif ratio > LEN_RATIO_MAX:
                issues.append(Issue(
                    "too_long",
                    f"rapporto {ratio:.2f}: probabile aggiunta", idx))

        # 4 — budget caratteri (segnalazione: la sistema il post-process)
        visible = len(stripped.replace("\n", " "))
        if visible > unit.budget:
            issues.append(Issue(
                "over_budget",
                f"{visible} caratteri contro un budget di {unit.budget}",
                idx, blocking=False))
        long_lines = [l for l in stripped.split("\n") if len(l) > CPL_MAX]
        if long_lines:
            issues.append(Issue(
                "over_cpl",
                f"{len(long_lines)} righe oltre {CPL_MAX} caratteri",
                idx, blocking=False))

        # 5 — output degenerato
        if _is_degenerate(stripped):
            issues.append(Issue("degenerate", "testo ripetitivo", idx))

        # 6 — lingua
        if _looks_english(stripped):
            issues.append(Issue("wrong_language",
                                "l'output sembra inglese", idx))

        # 7 — copy-through
        if stripped == src.strip() and len(src) > 12:
            issues.append(Issue("copy_through",
                                "identico all'originale inglese", idx))

        # 7b — turpiloquio attenuato
        if _EN_PROFANITY.search(src) and not _IT_PROFANITY.search(stripped):
            softened = bool(_IT_EUPHEMISM.search(stripped))
            issues.append(Issue(
                "softened_profanity",
                "l'originale è volgare ma la resa "
                + ("usa un eufemismo" if softened else "non lo è")
                + ": va resa con una volgarità italiana di pari forza",
                idx))

        # 8a — glossario
        if glossary:
            low_src, low_tgt = src.lower(), stripped.lower()
            for term, rendering in glossary.items():
                if term.lower() in low_src and rendering.lower() not in low_tgt:
                    issues.append(Issue(
                        "glossary",
                        f"'{term}' doveva essere reso con '{rendering}'",
                        idx, blocking=False))

    # 8b — oscillazione del registro nella stessa coppia di parlanti
    if speaker_register:
        for idx, text in translations.items():
            unit = by_id.get(idx)
            if unit is None or not unit.speaker:
                continue
            expected = speaker_register.get(unit.speaker)
            found = _register_of(text)
            if expected and found and found != expected:
                issues.append(Issue(
                    "register",
                    f"registro {found} dove ci si aspetta {expected}",
                    idx, blocking=False))

    return issues


def blocking(issues: Sequence[Issue]) -> List[Issue]:
    return [i for i in issues if i.blocking]


def summarize(issues: Sequence[Issue], limit: int = 3) -> str:
    """Riassunto compatto da rimandare al modello nel prompt di retry."""
    hard = blocking(issues)
    if not hard:
        return ""
    parts = [str(i) for i in hard[:limit]]
    if len(hard) > limit:
        parts.append(f"e altri {len(hard) - limit} problemi")
    return "; ".join(parts)
