# -*- coding: utf-8 -*-
"""
Normalizzazione e clustering delle rese italiane di un termine glossario.
File: mt_eval/glossary_cluster.py

Puro Python, nessuna dipendenza pesante (testabile in isolamento, import
istantaneo). Sostituisce la metrica binaria "verbatim/assente" di
build_glossary_candidates.py: quello che conta davvero non è se il
termine inglese compare letterale nel blocco italiano, ma QUALI rese
diverse il motore ha prodotto per lo stesso termine — un termine SEMPRE
reso allo stesso modo è sano anche se "100% assente" nella metrica
verbatim (vedi memoria piano_glossario_per_show.md).
"""
import re
import unicodedata
from typing import Dict, List, Optional

# Articoli/preposizioni articolate italiane da spogliare in testa alla resa,
# cosi' "L'Arca" e "Arca" finiscono nello stesso cluster (stessa scelta
# lessicale, variante solo per concordanza dell'articolo — non un difetto).
# "l'" elide SENZA spazio ("l'Arca"), gli altri articoli hanno spazio
# ("la Arca" non esiste in italiano corretto ma trattato comunque per
# robustezza su rese imperfette del motore).
_LEADING_ARTICLES = re.compile(
    r"^(?:l['’](?=\w)|(?:gli|le|la|lo|il|i|un|una|uno|dei|degli|delle|"
    r"del|dello|della|nel|nello|nella|nei|negli|nelle|al|allo|alla|ai|"
    r"agli|alle|dal|dallo|dalla|dai|dagli|dalle)\s+)", re.IGNORECASE)

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(span: Optional[str]) -> Optional[str]:
    """Forma canonica di una resa per il clustering. None resta None
    (occorrenza omessa/non estratta, esclusa dal conteggio cluster)."""
    if span is None:
        return None
    text = unicodedata.normalize("NFKC", span).strip()
    if not text:
        return None
    text = _LEADING_ARTICLES.sub("", text)
    text = _PUNCT_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text or None


class Cluster:
    __slots__ = ("text", "n", "examples")

    def __init__(self, text: str):
        self.text = text
        self.n = 0
        self.examples: List[dict] = []

    def add(self, raw_span: str, example: Optional[dict] = None):
        self.n += 1
        if example is not None and len(self.examples) < 4:
            self.examples.append(example)

    def to_dict(self) -> dict:
        return {"text": self.text, "n": self.n, "examples": self.examples}


def cluster(spans: List[Optional[str]],
            examples: Optional[List[Optional[dict]]] = None) -> List[Cluster]:
    """Raggruppa le rese normalizzate. `spans[i]` puo' essere None (occorrenza
    omessa/non estratta): esclusa dai cluster, ma va contata a parte da chi
    chiama per il coverage. Ordina per frequenza decrescente."""
    if examples is None:
        examples = [None] * len(spans)
    buckets: Dict[str, Cluster] = {}
    # La chiave di raggruppamento e' la forma normalizzata, ma il testo
    # mostrato e' la resa piu' frequente in forma originale (non normalizzata)
    # tra quelle che vi confluiscono, per leggibilita' nel report.
    display: Dict[str, Dict[str, int]] = {}
    for raw, ex in zip(spans, examples):
        key = normalize(raw)
        if key is None:
            continue
        c = buckets.setdefault(key, Cluster(key))
        c.add(raw, ex)
        display.setdefault(key, {})
        display[key][raw] = display[key].get(raw, 0) + 1
    for key, c in buckets.items():
        best_raw = max(display[key].items(), key=lambda kv: kv[1])[0]
        # L'articolo/preposizione articolata in testa va tolto anche dal
        # testo mostrato/salvato, non solo dalla chiave di raggruppamento:
        # una resa con l'articolo incollato ("dell'Arca") finirebbe cosi'
        # com'e' nel glossario, e in pipeline sostituirebbe il placeholder
        # producendo doppio articolo ("la dell'Arca") — bug reale misurato
        # in revisione. Preserva la capitalizzazione del resto della resa.
        stripped = _LEADING_ARTICLES.sub("", best_raw)
        c.text = stripped.strip() or best_raw
    return sorted(buckets.values(), key=lambda c: -c.n)


def verdict(clusters: List[Cluster], total_occurrences: int,
            min_occurrences: int = 8, min_minor_cluster: int = 2,
            max_dominant_share: float = 0.85) -> dict:
    """Giudizio sul termine a partire dai suoi cluster di resa.

    Ritorna: {"diverging": bool, "dominant": str|None,
              "dominant_share": float, "reason": str}

    "diverging" e' True SOLO se: occorrenze sufficienti, esiste un cluster
    minoritario con almeno `min_minor_cluster` occorrenze indipendenti (un
    singolo caso isolato e' rumore d'allineamento, non un vero difetto), e
    il cluster dominante non copre gia' quasi tutto (< max_dominant_share).
    """
    if not clusters:
        return {"diverging": False, "dominant": None, "dominant_share": 0.0,
                "reason": "nessuna resa estratta"}
    if total_occurrences < min_occurrences:
        return {"diverging": False, "dominant": clusters[0].text,
                "dominant_share": clusters[0].n / total_occurrences,
                "reason": f"solo {total_occurrences} occorrenze utili "
                          f"(minimo {min_occurrences})"}

    dominant = clusters[0]
    dominant_share = dominant.n / total_occurrences
    minor_clusters = [c for c in clusters[1:] if c.n >= min_minor_cluster]

    if dominant_share >= max_dominant_share:
        return {"diverging": False, "dominant": dominant.text,
                "dominant_share": dominant_share,
                "reason": f"resa dominante '{dominant.text}' copre "
                          f"{dominant_share:.0%}, sotto la soglia di rischio"}
    if not minor_clusters:
        return {"diverging": False, "dominant": dominant.text,
                "dominant_share": dominant_share,
                "reason": "nessun cluster minoritario con >=2 occorrenze "
                          "indipendenti (rumore d'allineamento escluso)"}
    return {"diverging": True, "dominant": dominant.text,
            "dominant_share": dominant_share,
            "reason": f"resa dominante '{dominant.text}' ({dominant_share:.0%}) "
                      f"vs {len(minor_clusters)} resa/e alternativa/e "
                      f"({', '.join(c.text for c in minor_clusters)})"}
