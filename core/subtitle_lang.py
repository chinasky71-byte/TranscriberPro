# -*- coding: utf-8 -*-
"""
Lingua delle tracce sottotitoli: normalizzazione dei codici, lettura del titolo e
riconoscimento sul TESTO (senza dipendenze esterne).
File: core/subtitle_lang.py

Principio (decisione 09/10/2026, caso RahXephon: traccia "English Forced SRT" con tag `it`):
la lingua di una traccia si decide dal CONTENUTO. Il titolo da solo corregge solo un tag
assente/sconosciuto; se il testo non da' un verdetto affidabile non si cambia nulla.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ISO 639-2/B/T e varianti (3 lettere) -> ISO 639-1
LANG_3_TO_2 = {
    'ita': 'it', 'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
    'deu': 'de', 'ger': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
    'kor': 'ko', 'chi': 'zh', 'zho': 'zh', 'ara': 'ar', 'hin': 'hi',
    'pol': 'pl', 'tur': 'tr', 'nld': 'nl', 'dut': 'nl', 'swe': 'sv',
    'dan': 'da', 'nor': 'no', 'nob': 'no', 'fin': 'fi', 'ces': 'cs', 'cze': 'cs',
    'hun': 'hu', 'ron': 'ro', 'rum': 'ro', 'ukr': 'uk', 'ell': 'el',
    'gre': 'el', 'heb': 'he', 'vie': 'vi', 'tha': 'th', 'srp': 'sr',
    'hrv': 'hr', 'bos': 'bs', 'slk': 'sk', 'slo': 'sk', 'slv': 'sl',
    'bul': 'bg', 'cat': 'ca', 'lit': 'lt', 'lav': 'lv', 'est': 'et',
    'ind': 'id', 'msa': 'ms', 'may': 'ms', 'fas': 'fa', 'per': 'fa',
    'ben': 'bn', 'tam': 'ta', 'tel': 'te', 'urd': 'ur', 'isl': 'is',
    'ice': 'is', 'afr': 'af', 'eus': 'eu', 'baq': 'eu', 'glg': 'gl',
    'mkd': 'mk', 'mac': 'mk', 'sqi': 'sq', 'alb': 'sq', 'bel': 'be',
    'cmn': 'zh', 'yue': 'zh', 'nb': 'no', 'nn': 'no', 'iw': 'he', 'in': 'id',
    'und': 'und',
}
_KNOWN_2 = set(LANG_3_TO_2.values()) - {'und'}
# alias comuni (2 lettere non ISO usate da alcuni muxer)
_ALIASES_2 = {'jp': 'ja', 'cz': 'cs', 'gr': 'el', 'kr': 'ko', 'cn': 'zh', 'dk': 'da', 'nb': 'no', 'nn': 'no',
              'iw': 'he', 'in': 'id'}
_UNDETERMINED = {'und', 'unk', 'zxx', 'mul', 'mis', 'qaa', 'qad', 'xx', ''}

# preferenza per il codice a 3 lettere (Tesseract usa fra/deu/...)
_LANG_2_TO_3 = {
    'it': 'ita', 'en': 'eng', 'es': 'spa', 'fr': 'fra', 'de': 'deu', 'pt': 'por',
    'ru': 'rus', 'ja': 'jpn', 'ko': 'kor', 'zh': 'zho', 'ar': 'ara', 'hi': 'hin',
    'pl': 'pol', 'tr': 'tur', 'nl': 'nld', 'sv': 'swe', 'da': 'dan', 'no': 'nor',
    'fi': 'fin', 'cs': 'ces', 'hu': 'hun', 'ro': 'ron', 'uk': 'ukr', 'el': 'ell',
    'he': 'heb', 'vi': 'vie', 'th': 'tha', 'sr': 'srp', 'hr': 'hrv', 'bs': 'bos',
    'sk': 'slk', 'sl': 'slv', 'bg': 'bul', 'ca': 'cat', 'lt': 'lit', 'lv': 'lav',
    'et': 'est', 'id': 'ind', 'ms': 'msa', 'fa': 'fas', 'bn': 'ben', 'ta': 'tam',
    'te': 'tel', 'ur': 'urd', 'is': 'isl', 'af': 'afr', 'eu': 'eus', 'gl': 'glg',
    'mk': 'mkd', 'sq': 'sqi', 'be': 'bel',
}

# nomi di lingua nei titoli delle tracce (it/en/nativo) -> ISO 639-1
_TITLE_NAMES = {
    'it': ['italian', 'italiano', 'italiana', 'italien', 'italienisch', 'ita'],
    'en': ['english', 'inglese', 'anglais', 'englisch', 'eng'],
    'es': ['spanish', 'spagnolo', 'espanol', 'español', 'castellano', 'castilian', 'espagnol'],
    'fr': ['french', 'francese', 'francais', 'français', 'francaise', 'französisch', 'fra'],
    'de': ['german', 'tedesco', 'deutsch', 'allemand', 'deu'],
    'pt': ['portuguese', 'portoghese', 'portugues', 'português', 'brazilian'],
    'ru': ['russian', 'russo', 'russkiy', 'русский'],
    'ja': ['japanese', 'giapponese', 'nihongo', '日本語', 'jpn'],
    'ko': ['korean', 'coreano', '한국어'],
    'zh': ['chinese', 'cinese', 'mandarin', 'cantonese', '中文'],
    'nl': ['dutch', 'olandese', 'nederlands'],
    'ar': ['arabic', 'arabo'],
    'pl': ['polish', 'polacco', 'polski'],
    'tr': ['turkish', 'turco'],
    'sv': ['swedish', 'svedese'],
    'da': ['danish', 'danese'],
    'no': ['norwegian', 'norvegese'],
    'fi': ['finnish', 'finlandese'],
    'cs': ['czech', 'ceco'],
    'hu': ['hungarian', 'ungherese'],
    'ro': ['romanian', 'rumeno'],
    'uk': ['ukrainian', 'ucraino'],
    'el': ['greek', 'greco'],
    'he': ['hebrew', 'ebraico'],
    'vi': ['vietnamese', 'vietnamita'],
    'th': ['thai', 'tailandese'],
    'hi': ['hindi'],
}
_NAME_TO_LANG = {n: lg for lg, names in _TITLE_NAMES.items() for n in names}
_TITLE_RE = re.compile(
    r'(?<!\w)(' + '|'.join(sorted((re.escape(n) for n in _NAME_TO_LANG), key=len, reverse=True)) + r')(?!\w)',
    re.IGNORECASE)

_FORCED_RE = re.compile(r'(?<!\w)(?<!non-)(?<!non )(?<!not )(?<!non_)(forced|forzat[oaie]|forzati|foreign|signs?\s*(?:&|and|e)?\s*songs?|signs)(?!\w)',
                        re.IGNORECASE)
_HI_RE = re.compile(r'(?<!\w)(sdh|hi|cc|hearing[\s_-]*impaired|closed[\s_-]*captions?|non[\s_-]*udenti|per[\s_-]*sordi)(?!\w)',
                    re.IGNORECASE)
_COMMENTARY_RE = re.compile(r'(?<!\w)(commentary|commento|commentaire)(?!\w)', re.IGNORECASE)


def normalize_lang(code) -> str:
    """Qualsiasi codice/nome lingua -> ISO 639-1 (2 lettere) oppure 'und'.
    Mai le "prime 2 lettere": un codice che non si riconosce diventa 'und'."""
    if not code:
        return 'und'
    c = str(code).strip().lower()
    if c in _UNDETERMINED:
        return 'und'
    first = re.split(r'[-_/.;,\s]', c, maxsplit=1)[0]
    if first in _UNDETERMINED:
        return 'und'
    if first in _ALIASES_2:
        return _ALIASES_2[first]
    if len(first) == 2:
        return first if first in _KNOWN_2 else 'und'
    if len(first) == 3:
        return LANG_3_TO_2.get(first, 'und')
    return _NAME_TO_LANG.get(c) or lang_from_title(c) or 'und'


def lang2_to_3(lang2: str) -> str:
    """ISO 639-1 -> codice a 3 lettere (Tesseract/ffmpeg); 'und' se ignoto."""
    return _LANG_2_TO_3.get((lang2 or '').lower(), 'und')


# nomi dei modelli Tesseract che non coincidono col codice ISO a 3 lettere
_TESSERACT_NAMES = {'zh': 'chi_sim'}


def tesseract_name(lang2: str) -> str:
    """Nome del traineddata Tesseract per una lingua ISO 639-1 ('und' se ignota)."""
    return _TESSERACT_NAMES.get((lang2 or '').lower()) or lang2_to_3(lang2)


def lang_from_title(title: str) -> Optional[str]:
    """Lingua nominata nel titolo della traccia, solo se ne nomina UNA sola; altrimenti None."""
    found = {_NAME_TO_LANG[m.group(1).lower()] for m in _TITLE_RE.finditer(title or '')}
    return next(iter(found)) if len(found) == 1 else None


def title_is_forced(title: str) -> bool:
    return bool(_FORCED_RE.search(title or ''))


def title_is_hi(title: str) -> bool:
    return bool(_HI_RE.search(title or ''))


def title_is_commentary(title: str) -> bool:
    return bool(_COMMENTARY_RE.search(title or ''))


# ============================================================================
# Riconoscimento della lingua sul testo
# ============================================================================
# Parole frequenti, scelte evitando (per quanto possibile) quelle in comune tra lingue.
_WORDS = {
    'en': """the and you that was for are with his they this have from not but what all were when your can said
        there which she how their will about out then them these would like him into has been who its now just
        didn isn wasn couldn wouldn doesn it we my be if yes here know think going want right well really
        very because oh okay hey gonna got let ll ve""",
    'it': """il gli che non per sono siamo ho hai hanno ma ci vi della dei delle nel nella
        questo questa quello cosa anche più perché dove chi io lui lei noi voi loro essere avere
        fare grazie ciao già ancora molto tutto tutti niente mai allora quindi però adesso signore
        sì dai dire vedere cosa ecco è gli sono questo non che perché""",
    'es': """el los las una por para pero como más esto esta eso usted soy eres estoy está están muy también aquí
        allí ahora cuando donde quién qué cómo gracias hola bueno tengo tiene tienes hay todo siempre mucho sus mis señor""",
    'fr': """les des une est pour avec dans pas vous nous je elle ils elles suis êtes avez oui merci bonjour mais
        comme très aussi ici maintenant parce quand où qui quoi ça cette ces mon mes être avoir faire tout
        rien toujours jamais beaucoup bien déjà encore alors donc fait monsieur""",
    'de': """der das und ist nicht ich du sie wir ihr er ein eine einen mit von zu den dem auf für aber auch
        wer wo wenn dann nein danke bitte jetzt noch nur schon sehr mehr immer nie gut kann muss bin
        bist sind haben werden wird herr""",
    'pt': """não você vocês eles estou são uma com mas isso isto muito também aqui agora onde quem obrigado obrigada olá tenho tem tudo sempre bem já ainda então fazer meu
        minha seu sua dos ela ele eu nós só senhor""",
    'nl': """een het niet geen maar ook met voor naar dat dit wat wie waar wanneer hoe ja nee dank hier nog heel
        erg altijd nooit goed kan wil moet ben bent zijn heeft hebben wordt mijn jouw jij hij zij wij jullie ik
        meneer""",
}
_WORD_SETS = {lg: frozenset(w.split()) for lg, w in _WORDS.items()}

# alfabeti non latini: (nome, regex dei caratteri, famiglia di lingue compatibili)
_SCRIPTS = [
    ('kana', re.compile(r'[぀-ヿ]'), ('ja',)),
    ('hangul', re.compile(r'[가-힯ᄀ-ᇿ]'), ('ko',)),
    ('han', re.compile(r'[一-鿿]'), ('zh', 'ja')),
    ('cyrillic', re.compile(r'[Ѐ-ӿ]'), ('ru', 'uk', 'bg', 'sr', 'be', 'mk')),
    ('arabic', re.compile(r'[؀-ۿ]'), ('ar', 'fa', 'ur')),
    ('hebrew', re.compile(r'[֐-׿]'), ('he',)),
    ('greek', re.compile(r'[Ͱ-Ͽ]'), ('el',)),
    ('thai', re.compile(r'[฀-๿]'), ('th',)),
]

MIN_WORDS = 40          # parole riconosciute minime per un verdetto
MIN_SHARE = 0.65        # quota minima della prima lingua sulle parole riconosciute
MIN_RATIO = 2.5         # la prima deve avere almeno 2,5 volte la seconda
PART_MIN_WORDS = 8      # parole minime perche' un terzo del campione conti
PART_SHARE = 0.50
PART_RATIO = 1.5
SAMPLE_BLOCKS = 400     # battute campionate, distribuite su tutto il file

_TS_RE = re.compile(r'^\s*\d{1,2}:\d{2}:\d{2}[,.]\d+\s*-->')
_TAG_RE = re.compile(r'<[^>]*>|\{[^}]*\}')
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def srt_dialogue_lines(srt_text: str) -> List[str]:
    """Una stringa per battuta (testo senza indici, tempi, tag HTML/ASS)."""
    blocks = re.split(r'\r?\n\s*\r?\n', srt_text or '')
    out: List[str] = []
    for b in blocks:
        lines = [ln for ln in b.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not _TS_RE.match(ln) and not ln.strip().isdigit()]
        raw = ' '.join(lines)
        # canzoni (testo spesso in un'altra lingua): non contano per la lingua dei dialoghi
        if '♪' in raw or '♫' in raw or raw.lstrip().startswith('#'):
            continue
        text = _TAG_RE.sub(' ', raw).strip()
        if text:
            out.append(text)
    return out


def _sample(lines: List[str], n: int = SAMPLE_BLOCKS) -> List[str]:
    if len(lines) <= n:
        return lines
    step = len(lines) / n
    return [lines[int(i * step)] for i in range(n)]


def _word_counts(text: str) -> dict:
    counts = {lg: 0 for lg in _WORD_SETS}
    for w in _WORD_RE.findall(text.lower()):
        for lg, ws in _WORD_SETS.items():
            if w in ws:
                counts[lg] += 1
    return counts


def detect_text_language(srt_text: str) -> Tuple[Optional[str], dict]:
    """Verdetto sul testo di un SRT: (lingua ISO 639-1 | None, prove).
    None = nessun verdetto affidabile (testo troppo corto, lingue miste, lingua non coperta)."""
    lines = _sample(srt_dialogue_lines(srt_text))
    joined = ' '.join(lines)
    evidence = {'lines': len(lines)}
    if not joined.strip():
        return None, evidence

    letters = sum(1 for ch in joined if ch.isalpha())
    # 1) alfabeto
    if letters:
        for name, rx, family in _SCRIPTS:
            if len(rx.findall(joined)) / letters >= 0.30:
                evidence.update(script=name)
                return family[0], evidence

    # 2) lingue latine: parole frequenti
    counts = _word_counts(joined)
    evidence['scores'] = {k: v for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v}
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    (top_lg, top), (_, second) = ranked[0], ranked[1]
    if total < MIN_WORDS or top / total < MIN_SHARE or top < MIN_RATIO * max(second, 1):
        return None, evidence
    # Coerenza: il verdetto deve valere in (almeno 2) parti del file e non essere smentito da nessuna
    # (una canzone o una scena in un'altra lingua non cambia la lingua della traccia).
    third = max(1, len(lines) // 3)
    parts = [lines[i:i + third] for i in range(0, len(lines), third)][:3] if len(lines) >= 3 else [lines]
    supporting = 0
    for part in parts:
        pc = _word_counts(' '.join(part))
        ptotal = sum(pc.values())
        if ptotal < PART_MIN_WORDS:
            continue
        pr = sorted(pc.items(), key=lambda kv: -kv[1])
        if pr[0][1] / ptotal >= PART_SHARE and pr[0][1] >= PART_RATIO * max(pr[1][1], 1):
            if pr[0][0] != top_lg:
                evidence['part_disagrees'] = pr[0][0]
                return None, evidence
            supporting += 1
    if supporting < 2:
        evidence['supporting_parts'] = supporting
        return None, evidence
    return top_lg, evidence


def script_family(lang2: str) -> Tuple[str, ...]:
    """Lingue compatibili con l'alfabeto del verdetto (per non contraddire ru/uk, ja/zh...)."""
    for _, _, family in _SCRIPTS:
        if lang2 in family:
            return family
    return (lang2,)


def contradicts(presumed: str, verdict: Optional[str]) -> bool:
    """True se il verdetto sul testo e' affidabile e NON compatibile con la lingua presunta."""
    if not verdict:
        return False
    return (presumed or 'und') not in script_family(verdict) and presumed != verdict
