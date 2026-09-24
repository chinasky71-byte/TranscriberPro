"""
Lettura/scrittura SRT per il banco, compatibile con il parser del
traduttore di produzione (BaseTranslator._parse_srt in core/translator.py).

TRANSLATOR_SRT_PATTERN e' una COPIA LETTERALE del pattern di produzione:
un test (tests/test_static.py) verifica per ast che coincida ancora. Serve
per il controllo di andata e ritorno: un blocco il cui testo contiene una
riga fatta di sole cifre verrebbe troncato dal parser di produzione, e il
banco deve accorgersene invece di mappare per posizione.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

TRANSLATOR_SRT_PATTERN = r'(\d+)\s*\n([\d:,]+)\s*-->\s*([\d:,]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|$)'

_TS = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')


def ts(seconds: float) -> str:
    """Secondi -> 'HH:MM:SS,mmm' (stesso arrotondamento di SubtitleFormatter._ts)."""
    ms = int(round(max(0.0, float(seconds)) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_to_s(value: str) -> float:
    m = _TS.search(value or '')
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, '0')) / 1000


def parse_like_translator(content: str) -> List[Tuple[int, str, str, str]]:
    """Esattamente cio' che BaseTranslator._parse_srt restituirebbe."""
    out = []
    for m in re.finditer(TRANSLATOR_SRT_PATTERN, content, re.MULTILINE):
        text = m.group(4).strip()
        if text:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip(), text))
    return out


def parse_blocks(content: str) -> List[Dict]:
    """SRT -> [{index, start, end, text}] con il parser del traduttore."""
    return [{'index': i, 'start': ts_to_s(a), 'end': ts_to_s(b), 'text': t}
            for i, a, b, t in parse_like_translator(content.replace('\r\n', '\n').replace('﻿', ''))]


def render(blocks: Sequence[Dict], skip_empty: bool = True, renumber: bool = False) -> str:
    """[{start, end, text, [index]}] -> SRT. Con renumber=False usa 'index'
    se presente (serve a conservare gli id delle unita')."""
    out: List[str] = []
    n = 0
    for b in blocks:
        text = str(b.get('text', '')).strip('\n')
        if skip_empty and not text.strip():
            continue
        if b.get('drop'):
            continue
        n += 1
        idx = n if renumber or 'index' not in b else int(b['index'])
        out += [str(idx), f"{ts(b['start'])} --> {ts(b['end'])}", text, '']
    return '\n'.join(out)


def roundtrip_problems(blocks: Sequence[Dict]) -> List[str]:
    """Problemi di andata e ritorno col parser di produzione: indici persi o
    testo alterato. Lista vuota = sicuro."""
    srt = render(blocks, skip_empty=False)
    back = {i: t for i, _, _, t in parse_like_translator(srt)}
    probs = []
    for b in blocks:
        idx = int(b['index'])
        want = str(b.get('text', '')).strip()
        if not want:
            continue
        if idx not in back:
            probs.append(f"blocco {idx} perso dal parser")
        elif back[idx] != want:
            probs.append(f"blocco {idx} alterato dal parser: {back[idx]!r} != {want!r}")
    return probs
