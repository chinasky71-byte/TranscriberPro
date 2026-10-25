"""Quality metrics used by the benchmark harness.

Pure functions, no dependencies outside the standard library. They operate on
normalized token/character sequences from :mod:`bench.text`.
"""
from __future__ import annotations

import difflib
from collections import Counter


def edit_distance(reference: list[str], hypothesis: list[str]) -> tuple[int, int, int]:
    """Levenshtein distance plus substitution, deletion and insertion counts."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    # Each cell stores (cost, substitutions, deletions, insertions).
    table = [[(0, 0, 0, 0)] * cols for _ in range(rows)]
    for i in range(1, rows):
        table[i][0] = (i, 0, i, 0)
    for j in range(1, cols):
        table[0][j] = (j, 0, 0, j)
    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                table[i][j] = table[i - 1][j - 1]
                continue
            sub = table[i - 1][j - 1]
            delete = table[i - 1][j]
            insert = table[i][j - 1]
            candidates = [
                (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                (delete[0] + 1, delete[1], delete[2] + 1, delete[3]),
                (insert[0] + 1, insert[1], insert[2], insert[3] + 1),
            ]
            table[i][j] = min(candidates, key=lambda item: item[0])
    return table[-1][-1]


def wer(reference: list[str], hypothesis: list[str]) -> dict:
    if not reference:
        return {"rate": 0.0 if not hypothesis else 1.0, "sub": 0, "del": 0, "ins": len(hypothesis)}
    cost, sub, delete, insert = edit_distance(reference, hypothesis)
    return {"rate": cost / len(reference), "sub": sub, "del": delete, "ins": insert}


def cer(reference: str, hypothesis: str) -> dict:
    if not reference:
        return {"rate": 0.0 if not hypothesis else 1.0}
    cost, _, _, _ = edit_distance(list(reference), list(hypothesis))
    return {"rate": cost / len(reference)}


def chrf(reference: str, hypothesis: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score (chrF), computed for n = 1..max_n."""
    if not reference and not hypothesis:
        return 1.0
    if not reference or not hypothesis:
        return 0.0
    scores = []
    for n in range(1, max_n + 1):
        ref_grams = Counter(reference[i:i + n] for i in range(len(reference) - n + 1))
        hyp_grams = Counter(hypothesis[i:i + n] for i in range(len(hypothesis) - n + 1))
        overlap = sum((ref_grams & hyp_grams).values())
        total_hyp = sum(hyp_grams.values())
        total_ref = sum(ref_grams.values())
        precision = overlap / total_hyp if total_hyp else 0.0
        recall = overlap / total_ref if total_ref else 0.0
        if precision + recall == 0:
            scores.append(0.0)
        else:
            beta2 = beta * beta
            scores.append((1 + beta2) * precision * recall / (beta2 * precision + recall))
    return sum(scores) / len(scores)


def similarity(reference: list[str], hypothesis: list[str]) -> float:
    """Word-level sequence similarity in [0, 1]."""
    if not reference and not hypothesis:
        return 1.0
    return difflib.SequenceMatcher(None, reference, hypothesis, autojunk=False).ratio()


def untranslated_blocks(sources: list[str], translations: list[str]) -> list[int]:
    """Indices of blocks whose translation is identical to the source."""
    flagged = []
    for index, (source, translation) in enumerate(zip(sources, translations)):
        if normalize_pair(source) == normalize_pair(translation):
            flagged.append(index)
    return flagged


def normalize_pair(text: str) -> str:
    from bench.text import normalize
    return normalize(text)
