"""
Metrica 'midcut': quota di blocchi che finiscono A META' FRASE.

Un blocco e' 'midcut' quando:
  1. NON termina con punteggiatura di fine frase (. ? ! … o '...', anche
     seguiti da virgolette/parentesi di chiusura);
  2. il blocco successivo e' nella stessa scena: gap (inizio del successivo
     meno fine di questo) < max_gap_s (1,0 s);
  3. il successivo apre in MINUSCOLA, con una cifra, oppure con una parola
     di continuazione (congiunzione, relativo, preposizione, articolo) della
     lingua, maiuscola o no;
  4. nessuno dei due e' un blocco musicale (♪/#), e il successivo NON apre
     con il trattino di cambio parlante.

Due varianti separate, NON incluse nel numero principale (che resta quello
della definizione di progetto):
  - 'ellipsis': il blocco termina con i puntini (… o ...) e il successivo
    apre in minuscola -> convenzione "vecchia" di continuazione con puntini.
    Il formatter e il postprocess di produzione trattano i puntini come
    chiusura forte.
  - 'softend': il blocco termina con , ; : e il successivo apre in
    maiuscola senza parola di continuazione ("If you're late, | I will...").
    Sui sub professionali e' quasi sempre una frase che prosegue, ma la
    maiuscola rende il criterio meno certo (nomi, "I" inglese, citazioni).

Niente rimozione degli accenti prima della ricerca delle parole: "È" non deve
diventare la congiunzione "e".

Modulo PURO (solo re): lo importano sia split_eval sia asr_eval.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

MAX_GAP_S = 1.0

_TAG = re.compile(r'<[^>]*>|\{[^}]*\}')
# Etichetta di parlante SDH in testa alla riga: "JOHN:", "MAN [ON PHONE]:"
_SDH_LABEL = re.compile(r"^\s*([-–—]\s*)?[A-Z][A-Z0-9 .'\-]{1,}(?:\s*\[[^\]]*\])?\s*:\s+")
_BRACKETS = re.compile(r'\[[^\]]*\]')
_PARENS = re.compile(r'\(([^)]*)\)')
_MUSIC_LINE = re.compile(r'^\s*#|#\s*$')
_CLOSERS = "\"'»”’)\\]"
STRONG_END = re.compile(r'[.?!…][' + _CLOSERS + r']*$')
SOFT_END = re.compile(r'[,;:][' + _CLOSERS + r']*$')
ELLIPSIS_END = re.compile(r'(?:…|\.{2,})[' + _CLOSERS + r']*$')
_DASH_START = re.compile(r'^\s*[-–—]')
_LEAD = re.compile(r'^[\s"\'«»“”‘’„‚(\[¿¡…\.]+')
_FIRST_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]*)?", re.UNICODE)

CONT_WORDS: Dict[str, frozenset] = {
    'en': frozenset("""
        and but or nor so yet because cause 'cause that which who whom whose where when while
        whereas whether if unless until till than as though although since to of in on at for
        with without from by about into onto over under after before through between against
        like the a an
    """.split()),
    'it': frozenset("""
        e ed o od ma però perché poiché che cui quando mentre se come dove anche né oppure quindi
        dunque finché affinché sebbene benché anziché cioè
        di a ad da in con su per tra fra del dello della dei degli delle al allo alla ai agli alle
        dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul sullo sulla sui sugli
        sulle col coi
        il lo la i gli le un uno una
        l' un' dell' all' dall' nell' sull' d' quell' quest'
    """.split()),
    # francese (28/09/2026, a priori, prima di guardare i dati di taratura): congiunzioni,
    # relativi, preposizioni, articoli ed elisioni che aprono il seguito di una frase
    'fr': frozenset("""
        et ou mais donc car ni or puis ensuite alors que qu' qui dont où quand lorsque lorsqu' puisque
        puisqu' comme si s' parce quoique bien afin pendant tandis sinon sauf
        de d' du des à au aux en dans par pour sur sous avec sans chez vers entre contre avant après
        depuis selon malgré jusqu' jusque
        le la les l' un une
    """.split()),
    # tedesco (28/09/2026, da whisper_split_eval/de_prelim/cont_words_de.py): esclusi der/die/das (aperture di frase
    # comuni). LIMITE: una continuazione che apre con un SOSTANTIVO (maiuscolo) non e' vista -> per il tedesco
    # la metrica principale e' quella dei tagli senza punteggiatura (whisper_split_eval/naked_cuts.py).
    'de': frozenset("""
        aber als am an ans anstatt auf aufs aus ausser außer bei beim bevor bis damit dass daß denn
        durch ehe ein eine einem einen einer eines entlang falls für fürs gegen gegenüber hinter im
        in indem ins mit nach nachdem neben noch ob obgleich obwohl oder ohne seit seitdem sobald
        sodass sofern solange sondern sowie sowohl statt trotz um ums und unter vom von vor weder
        wegen weil wenn wie wo wobei womit woran worauf wovon während zu zum zur zwischen über übers
    """.split()),
}


def _lang2(lang: str) -> str:
    l = (lang or 'en').lower()
    return {'eng': 'en', 'ita': 'it', 'english': 'en', 'italian': 'it',
            'fre': 'fr', 'fra': 'fr', 'french': 'fr',
            'ger': 'de', 'deu': 'de', 'german': 'de'}.get(l, l[:2])


def is_music(raw: str) -> bool:
    if '♪' in raw or '♫' in raw:
        return True
    plain = _TAG.sub('', raw)
    return any(_MUSIC_LINE.search(l) for l in plain.splitlines() if l.strip())


def clean_lines(raw: str) -> List[str]:
    """Righe del blocco senza markup, etichette SDH e descrizioni sonore."""
    out = []
    for line in _TAG.sub('', raw or '').replace('\r', '').split('\n'):
        line = _SDH_LABEL.sub(lambda m: (m.group(1) or ''), line)
        line = _BRACKETS.sub(' ', line)
        # (SOSPIRA) si', (tra parentesi con minuscole) no: puo' essere testo
        line = _PARENS.sub(lambda m: ' ' if not any(c.islower() for c in m.group(1)) else m.group(0), line)
        line = re.sub(r'\s+', ' ', line).strip()
        if line and line not in ('-', '–', '—'):
            out.append(line)
    return out


def clean_text(raw: str) -> str:
    return ' '.join(clean_lines(raw))


def ends_sentence(text: str) -> bool:
    return bool(STRONG_END.search(text.rstrip()))


def ends_ellipsis(text: str) -> bool:
    return bool(ELLIPSIS_END.search(text.rstrip()))


def starts_with_dash(raw_or_lines) -> bool:
    lines = clean_lines(raw_or_lines) if isinstance(raw_or_lines, str) else list(raw_or_lines)
    return bool(lines) and bool(_DASH_START.match(lines[0]))


def is_dialogue_block(raw: str) -> bool:
    """Blocco a due voci: piu' righe e almeno una col trattino in testa."""
    lines = clean_lines(raw)
    return len(lines) > 1 and any(_DASH_START.match(l) for l in lines)


def first_word(text: str) -> str:
    s = _LEAD.sub('', text or '')
    m = _FIRST_WORD.match(s)
    if not m:
        return ''
    w = m.group(0).replace('’', "'")
    if "'" in w:
        return w[:w.index("'") + 1]      # elisione: l'uomo -> l'
    return w


def continuation_kind(text: str, lang: str) -> Optional[str]:
    """'lower' | 'digit' | 'word' se il testo apre come seguito di una frase,
    None altrimenti. Il trattino iniziale (cambio parlante) esclude."""
    if not text or _DASH_START.match(text):
        return None
    s = _LEAD.sub('', text)
    if not s:
        return None
    c = s[0]
    if c.isdigit():
        return 'digit'
    if c.isalpha() and c.islower():
        return 'lower'
    w = first_word(s).lower()
    if w and w in CONT_WORDS.get(_lang2(lang), frozenset()):
        return 'word'
    return None


def pair_kind(a_raw: str, b_raw: str, gap: float, lang: str, max_gap_s: float = MAX_GAP_S) -> Optional[str]:
    """None | 'midcut' | 'ellipsis' | 'softend' per la coppia di blocchi
    consecutivi (a, b); v. docstring del modulo."""
    if gap >= max_gap_s:
        return None
    if is_music(a_raw) or is_music(b_raw):
        return None
    a_lines, b_lines = clean_lines(a_raw), clean_lines(b_raw)
    if not a_lines or not b_lines:
        return None
    if _DASH_START.match(b_lines[0]):
        return None
    a = ' '.join(a_lines)
    b = ' '.join(b_lines)
    if ends_sentence(a):
        if ends_ellipsis(a):
            s = _LEAD.sub('', b)
            if s and s[0].isalpha() and s[0].islower():
                return 'ellipsis'
        return None
    if continuation_kind(b, lang):
        return 'midcut'
    if SOFT_END.search(a.rstrip()):
        s = _LEAD.sub('', b)
        if s and s[0].isalpha():
            return 'softend'
    return None


def _t(b: Dict, k: str) -> float:
    if k == 's':
        return float(b['start'] if 'start' in b else b['s'])
    return float(b['end'] if 'end' in b else b['e'])


def midcut_flags(blocks: Sequence[Dict], lang: str, max_gap_s: float = MAX_GAP_S) -> List[Optional[str]]:
    """Per ogni blocco (nell'ordine dato, gia' cronologico) il tipo di taglio
    verso il SUCCESSIVO: None | 'midcut' | 'ellipsis'."""
    out: List[Optional[str]] = []
    for i, a in enumerate(blocks):
        if i + 1 >= len(blocks):
            out.append(None)
            continue
        b = blocks[i + 1]
        out.append(pair_kind(str(a.get('text', '')), str(b.get('text', '')), _t(b, 's') - _t(a, 'e'),
                             lang, max_gap_s))
    return out


def midcut_stats(blocks: Iterable[Dict], lang: str, max_gap_s: float = MAX_GAP_S) -> Dict:
    """Conteggi su una sequenza di blocchi {start|s, end|e, text}.

    n_blocks  = blocchi con testo, esclusi quelli musicali (denominatore)
    n_midcut  = blocchi che finiscono a meta' frase (definizione principale)
    n_ellipsis_cont = variante puntini + minuscola (NON inclusa in n_midcut)
    n_softend_cont  = variante , ; : + maiuscola (NON inclusa in n_midcut)
    n_noend   = blocchi senza punteggiatura finale (qualunque successivo)
    """
    bl = [b for b in blocks if clean_text(str(b.get('text', '')))]
    bl.sort(key=lambda b: (_t(b, 's'), _t(b, 'e')))
    flags = midcut_flags(bl, lang, max_gap_s)
    speech = [(b, f) for b, f in zip(bl, flags) if not is_music(str(b.get('text', '')))]
    n = len(speech)
    n_mid = sum(1 for _, f in speech if f == 'midcut')
    n_ell = sum(1 for _, f in speech if f == 'ellipsis')
    n_soft = sum(1 for _, f in speech if f == 'softend')
    n_noend = sum(1 for b, _ in speech if not ends_sentence(clean_text(str(b.get('text', '')))))
    return {'n_blocks': n, 'n_midcut': n_mid, 'n_ellipsis_cont': n_ell, 'n_softend_cont': n_soft,
            'n_noend': n_noend,
            'rate': (n_mid / n) if n else None,
            'rate_incl_ellipsis': ((n_mid + n_ell) / n) if n else None,
            'rate_broad': ((n_mid + n_ell + n_soft) / n) if n else None,
            'noend_rate': (n_noend / n) if n else None}


# ── blocchi del formatter di produzione (senza diarizzazione) ─────────────

_SRT_TS = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, '0')) / 1000


def srt_blocks(content: str) -> List[Dict]:
    """SRT -> [{start, end, text}] (testo con le righe originali)."""
    content = content.replace('﻿', '').replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for block in re.split(r'\n\s*\n', content):
        lines = block.strip('\n').split('\n')
        for k, line in enumerate(lines):
            m = _SRT_TS.search(line)
            if m:
                g = m.groups()
                text = '\n'.join(l for l in lines[k + 1:] if l.strip())
                if text.strip():
                    out.append({'start': _ts(*g[:4]), 'end': _ts(*g[4:]), 'text': text})
                break
    out.sort(key=lambda b: (b['start'], b['end']))
    return out


def formatter_blocks(segments: Sequence[Dict], readability: bool = True) -> List[Dict]:
    """I blocchi che SubtitleFormatter di produzione produrrebbe dai segmenti
    (nessuno speaker: percorso _format_srt_fallback della pipeline)."""
    from split_eval import prodmods
    segs = [{'start': float(s['start']), 'end': float(s['end']), 'text': str(s.get('text', '')),
             **({'words': s['words']} if s.get('words') else {})} for s in segments]
    srt = prodmods.SubtitleFormatter(readability=readability).format_srt(segs)
    return srt_blocks(srt)
