"""
Normalizzazione IDENTICA per riferimento e ipotesi (versione NORM_VERSION).

Passi: NFKC; rimozione <..>, {..} (tag ASS), [..], (..) con profondita'
azzerata a ogni battuta/segmento; nomi parlante 'NOME:'; minuscolo;
contrazioni inglesi da dizionario fisso; numeri in cifre -> parole
(0-9999, anni, decimali, ordinali inglesi); apostrofo e trattini ->
spazio; accenti tolti su TUTTE le lettere (estensione dichiarata della
regola "e/e' unificate": simmetrica, toglie anche perche'/perché, piu'/più).
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple

NORM_VERSION = "asr-norm/1"

FILLERS = {
    'en': {'uh', 'um', 'uhm', 'umm', 'er', 'erm', 'hmm', 'hm', 'mm', 'mmm', 'mhm',
           'ah', 'eh', 'oh', 'huh'},
    'it': {'ehm', 'eh', 'uh', 'um', 'uhm', 'mh', 'mhm', 'mm', 'mmm', 'hmm', 'hm',
           'ah', 'oh'},
}

PHANTOM_PHRASES = {
    'en': ['thanks for watching', 'thank you for watching', 'please subscribe',
           'subtitles by', 'amara org', 'like and subscribe'],
    'it': ['grazie per la visione', 'sottotitoli a cura di', 'sottotitoli creati dalla comunita',
           'amara org', 'iscriviti al canale', 'qtss', 'sottotitoli e revisione a cura di'],
}

_EN_CONTRACTIONS = {
    "don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "can not",
    "cannot": "can not", "won't": "will not", "wouldn't": "would not", "shouldn't": "should not",
    "couldn't": "could not", "isn't": "is not", "aren't": "are not", "wasn't": "was not",
    "weren't": "were not", "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "mustn't": "must not", "needn't": "need not", "ain't": "is not", "shan't": "shall not",
    "i'm": "i am", "you're": "you are", "we're": "we are", "they're": "they are",
    "i've": "i have", "you've": "you have", "we've": "we have", "they've": "they have",
    "i'll": "i will", "you'll": "you will", "he'll": "he will", "she'll": "she will",
    "we'll": "we will", "they'll": "they will", "it'll": "it will", "that'll": "that will",
    "i'd": "i would", "you'd": "you would", "he'd": "he would", "she'd": "she would",
    "we'd": "we would", "they'd": "they would", "it'd": "it would",
    "it's": "it is", "he's": "he is", "she's": "she is", "that's": "that is",
    "what's": "what is", "there's": "there is", "here's": "here is", "where's": "where is",
    "who's": "who is", "how's": "how is", "let's": "let us", "y'all": "you all",
    "'cause": "because", "cause": "because", "'em": "them", "ma'am": "madam",
    "gonna": "going to", "wanna": "want to", "gotta": "got to", "gimme": "give me",
    "lemme": "let me", "kinda": "kind of", "sorta": "sort of", "outta": "out of",
    "ok": "okay", "o.k.": "okay", "o.k": "okay", "okey": "okay",
}
_IT_SUBST = {"ok": "okay", "o.k.": "okay", "o.k": "okay", "okey": "okay"}

_EN_ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
            'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
            'seventeen', 'eighteen', 'nineteen']
_EN_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
_EN_ORD = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth',
           'nine': 'ninth', 'twelve': 'twelfth'}

_IT_ONES = ['zero', 'uno', 'due', 'tre', 'quattro', 'cinque', 'sei', 'sette', 'otto', 'nove',
            'dieci', 'undici', 'dodici', 'tredici', 'quattordici', 'quindici', 'sedici',
            'diciassette', 'diciotto', 'diciannove']
_IT_TENS = ['', '', 'venti', 'trenta', 'quaranta', 'cinquanta', 'sessanta', 'settanta',
            'ottanta', 'novanta']


def _en_under_100(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    t, o = divmod(n, 10)
    return _EN_TENS[t] + ('' if o == 0 else ' ' + _EN_ONES[o])


def en_cardinal(n: int) -> str:
    if n < 100:
        return _en_under_100(n)
    if n < 1000:
        h, r = divmod(n, 100)
        return _EN_ONES[h] + ' hundred' + ('' if r == 0 else ' ' + _en_under_100(r))
    th, r = divmod(n, 1000)
    return en_cardinal(th) + ' thousand' + ('' if r == 0 else ' ' + en_cardinal(r))


def en_year(n: int) -> str:
    if 2000 <= n <= 2009:
        return en_cardinal(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return _en_under_100(hi) + ' hundred'
    if lo < 10:
        return _en_under_100(hi) + ' oh ' + _EN_ONES[lo]
    return _en_under_100(hi) + ' ' + _en_under_100(lo)


def en_ordinal(n: int) -> str:
    words = en_cardinal(n).split()
    last = words[-1]
    if last in _EN_ORD:
        last = _EN_ORD[last]
    elif last.endswith('y'):
        last = last[:-1] + 'ieth'
    else:
        last = last + 'th'
    return ' '.join(words[:-1] + [last])


def _it_under_100(n: int) -> str:
    if n < 20:
        return _IT_ONES[n]
    t, o = divmod(n, 10)
    tens = _IT_TENS[t]
    if o == 0:
        return tens
    if o in (1, 8):
        tens = tens[:-1]
    return tens + ('tre' if o == 3 else _IT_ONES[o])


def it_cardinal(n: int) -> str:
    if n < 100:
        return _it_under_100(n)
    if n < 1000:
        h, r = divmod(n, 100)
        head = 'cento' if h == 1 else _IT_ONES[h] + 'cento'
        if r == 0:
            return head
        tail = _it_under_100(r)
        if tail.startswith('otta'):
            head = head[:-1]
        return head + tail
    th, r = divmod(n, 1000)
    head = 'mille' if th == 1 else it_cardinal(th) + 'mila'
    return head + ('' if r == 0 else it_cardinal(r))


def number_words(n: int, lang: str, *, as_year: bool = False) -> str:
    if lang == 'en':
        return en_year(n) if as_year else en_cardinal(n)
    return it_cardinal(n)


_RE_ORD = re.compile(r'^(\d{1,4})(st|nd|rd|th)$')
_RE_DEC = re.compile(r'^(\d{1,4})[.,](\d{1,3})$')
_RE_TIME = re.compile(r'^(\d{1,2}):(\d{2})$')
_RE_THOUS = re.compile(r'^(\d{1,3})([.,])(\d{3})$')
_RE_INT = re.compile(r'^\d+$')
_RE_NUM_IN_WORD = re.compile(r'\d+')


def _digits_to_words(core: str, lang: str) -> Tuple[str, bool]:
    """Converte un token numerico; ritorna (testo, convertito?)."""
    m = _RE_ORD.match(core)
    if m and lang == 'en':
        return en_ordinal(int(m.group(1))), True
    m = _RE_TIME.match(core)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        tail = '' if mi == 0 else ' ' + (('oh ' + _EN_ONES[mi]) if (lang == 'en' and mi < 10)
                                         else number_words(mi, lang))
        return number_words(h, lang) + tail, True
    m = _RE_THOUS.match(core)
    if m and ((lang == 'en' and m.group(2) == ',') or (lang == 'it' and m.group(2) == '.')):
        return number_words(int(m.group(1)) * 1000 + int(m.group(3)), lang), True
    m = _RE_DEC.match(core)
    if m:
        sep = 'point' if lang == 'en' else 'virgola'
        frac = ' '.join(number_words(int(d), lang) for d in m.group(2)) if lang == 'en' \
            else number_words(int(m.group(2)), lang)
        return f"{number_words(int(m.group(1)), lang)} {sep} {frac}", True
    if _RE_INT.match(core):
        n = int(core)
        if n > 9999:
            return ' '.join(number_words(int(d), lang) for d in core), True
        as_year = lang == 'en' and len(core) == 4 and (1100 <= n <= 1999 or 2000 <= n <= 2099)
        return number_words(n, lang, as_year=as_year), True
    return core, False


def strip_accents(s: str) -> str:
    return unicodedata.normalize('NFC', ''.join(
        c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c)))


_OPEN = {'<': '>', '{': '}', '[': ']', '(': ')'}
_CLOSE = {v: k for k, v in _OPEN.items()}


def strip_markup(text: str) -> str:
    """Toglie <..> {..} [..] (..); profondita' azzerata a ogni chiamata."""
    depth = {k: 0 for k in _OPEN}
    out = []
    for ch in text:
        if ch in _OPEN:
            depth[ch] += 1
            continue
        if ch in _CLOSE:
            o = _CLOSE[ch]
            if depth[o] > 0:
                depth[o] -= 1
            out.append(' ')
            continue
        if any(depth.values()):
            continue
        out.append(ch)
    return ''.join(out)


_RE_SPK_CAP1 = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ'\-]{0,20}:$")
_APOS = str.maketrans({'’': "'", '‘': "'", '`': "'", '´': "'", 'ʼ': "'"})
_RE_STRIP_PUNCT = re.compile(r"^[^\w']+|[^\w'.,:]+$|[.,:]+$")
_CURRENCY = {'$': ('dollars', 'dollari'), '€': ('euros', 'euro'), '£': ('pounds', 'sterline')}


def _is_speaker(w: str, first: bool) -> bool:
    """'JOHN:' ovunque nella riga, 'John:' solo come prima parola."""
    if not w.endswith(':'):
        return False
    letters = [c for c in w if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return True
    return first and bool(_RE_SPK_CAP1.match(w))


def _norm_word(w: str, lang: str) -> List[str]:
    w = w.lower()
    suffix = []
    for sym, names in _CURRENCY.items():
        if sym in w and any(c.isdigit() for c in w):
            w = w.replace(sym, '')
            suffix.append(names[0] if lang == 'en' else names[1])
    if '%' in w and any(c.isdigit() for c in w):
        w = w.replace('%', '')
        suffix.append('percent' if lang == 'en' else 'per cento')
    core = _RE_STRIP_PUNCT.sub('', w)
    core = _RE_STRIP_PUNCT.sub('', core)
    if not core:
        return []
    table = _EN_CONTRACTIONS if lang == 'en' else _IT_SUBST
    if core in table:
        core = table[core]
    elif lang == 'en' and core.endswith("n't"):
        core = core[:-3] + ' not'
    if suffix:
        core = core + ' ' + ' '.join(suffix)
    parts = []
    for p in core.split():
        conv, ok = _digits_to_words(p.strip('.,:'), lang)
        if ok:
            parts.append(conv)
            continue
        if _RE_NUM_IN_WORD.search(p):
            p = _RE_NUM_IN_WORD.sub(lambda m: ' ' + _digits_to_words(m.group(0), lang)[0] + ' ', p)
        parts.append(p)
    s = ' '.join(parts)
    s = s.replace("'", ' ')
    s = re.sub(r'[\-‐‑‒–—―_/]', ' ', s)
    s = strip_accents(s)
    s = re.sub(r'[^\w\s]', ' ', s)
    return [t for t in s.split() if t]


def normalize_line_words(words: Sequence[str], lang: str) -> List[Tuple[str, int]]:
    """Parole grezze di UNA riga/segmento -> [(token, indice parola sorgente)]."""
    words = [unicodedata.normalize('NFKC', w).translate(_APOS) for w in words]
    cleaned = _strip_markup_words(words)
    items = [(sub, i) for i, w in enumerate(cleaned) for sub in w.split()]
    out = []
    for k, (w, i) in enumerate(items):
        if _is_speaker(w, first=(k == 0)):
            continue
        for tok in _norm_word(w, lang):
            out.append((tok, i))
    return out


def _strip_markup_words(words: List[str]) -> List[str]:
    """strip_markup applicato a una sequenza di parole mantenendo la
    corrispondenza parola per parola (profondita' condivisa nella riga)."""
    depth = {k: 0 for k in _OPEN}
    out = []
    for w in words:
        buf = []
        for ch in w:
            if ch in _OPEN:
                depth[ch] += 1
                buf.append(' ')
                continue
            if ch in _CLOSE:
                o = _CLOSE[ch]
                if depth[o] > 0:
                    depth[o] -= 1
                buf.append(' ')
                continue
            if any(depth.values()):
                continue
            buf.append(ch)
        out.append(''.join(buf))
    return out


def normalize_text(text: str, lang: str) -> List[str]:
    """Testo multi-riga (battuta) -> token normalizzati."""
    toks = []
    for line in text.splitlines():
        line = re.sub(r'^\s*[-–—]+\s*', '', line)
        toks.extend(t for t, _ in normalize_line_words(line.split(), lang))
    return toks


def is_filler(tok: str, lang: str) -> bool:
    return tok in FILLERS.get(lang, set())


def filter_fillers_collapse(tokens: Sequence[str], lang: str) -> List[int]:
    """Indici dei token tenuti per il WERc: niente intercalari, ripetizioni
    consecutive collassate."""
    kept: List[int] = []
    prev = None
    for i, t in enumerate(tokens):
        if is_filler(t, lang):
            continue
        if t == prev:
            continue
        kept.append(i)
        prev = t
    return kept


def find_phantoms(tokens: Sequence[str], lang: str) -> List[Tuple[int, int, str]]:
    """Occorrenze di frasi fantasma note: (inizio, fine esclusa, frase)."""
    hits = []
    for ph in PHANTOM_PHRASES.get(lang, []):
        p = ph.split()
        n = len(p)
        for i in range(len(tokens) - n + 1):
            if list(tokens[i:i + n]) == p:
                hits.append((i, i + n, ph))
    return hits


def number_vocab(lang: str) -> set:
    words = set()
    for n in range(0, 100):
        words.update(number_words(n, lang).split())
    if lang == 'en':
        words.update({'hundred', 'thousand', 'point'})
        words.discard('one')
    else:
        words.update({'cento', 'mille', 'mila', 'virgola'})
        words.difference_update({'uno'})
    return words


def is_number_token(tok: str, lang: str, _cache={}) -> bool:
    if lang not in _cache:
        _cache[lang] = number_vocab(lang)
    return tok in _cache[lang] or (lang == 'it' and _looks_it_compound_number(tok))


_IT_NUM_PARTS = sorted(set(_IT_ONES + [t for t in _IT_TENS if t] + [t[:-1] for t in _IT_TENS if t]
                           + ['cento', 'cent', 'mille', 'mila']), key=len, reverse=True)


def _looks_it_compound_number(tok: str) -> bool:
    if len(tok) < 6:
        return False
    s = tok
    while s:
        for p in _IT_NUM_PARTS:
            if s.startswith(p):
                s = s[len(p):]
                break
        else:
            return False
    return True
