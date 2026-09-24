"""
Ricomposizione delle frasi spezzate PRIMA della traduzione (opzione
`translation_recompose_sentences`, SPENTA di default).

Il problema: i segmenti di trascrizione finiscono spesso a meta' frase
("After all, Dad tried to send her | husband to jail."); il traduttore
traduce ogni blocco SRT da solo e le due meta' escono come frammenti tradotti
male. Qui:

  1. `recompose`: le catene di blocchi di continuazione diventano UN'unita'
     di frase (al massimo 3 blocchi, 160 caratteri, 10 s, gap < 1 s);
  2. il traduttore traduce l'SRT delle unita' (un blocco per unita');
  3. `resplit`: il testo TRADOTTO di ogni unita' fusa si ridivide in modo
     deterministico sui blocchi originali, con i TEMPI ORIGINALI invariati.
     Invariante: nessuna parola persa, duplicata o riordinata.

Misurato sul banco split_eval (v2, 24/09/2026, segmenti Qwen3, NLLB-FT, 200
unita' fuse in 61 finestre): giudice GEMBA B 179 contro A 48, COMET +0,04 in
7 film su 7. Le guardie strutturali della ridivisione v1 non passavano; la
ridivisione v2 (questa) le rispetta nella rimisura offline sulle stesse
traduzioni (v. split_eval/recompose.py, di cui questo modulo e' la copia di
produzione: un test verifica che restino allineati).

AUTOSUFFICIENTE: solo libreria standard, nessun modello. La traduzione la fa
`translate_fn(input_srt, output_srt) -> bool` (in pipeline:
translator.translate_file con i suoi argomenti).

GUARDIE DI RICOMPOSIZIONE (l'SRT non porta lo speaker):
  - mai unire blocchi con il trattino di cambio parlante ([-–—] a inizio riga,
    anche dopo tag) ne' blocchi a due voci: sono la sola traccia del cambio di
    parlante che la diarizzazione lascia nell'SRT;
  - si unisce solo se il blocco NON chiude la frase (. ? ! …) E il successivo
    apre come un seguito (minuscola, cifra o congiunzione/preposizione/
    articolo) E il gap e' < 1 s: un cambio di parlante a meta' frase senza
    trattino e' raro e comunque non chiude la frase precedente;
  - mai blocchi musicali (♪ #) ne' blocchi con tag (<i>, {\\an8}): il tag si
    perderebbe o si sposterebbe nella ridivisione;
  - al massimo 3 blocchi, 160 caratteri, 10 s per unita' (parametri misurati).

SICUREZZA: qualunque anomalia (unita' tradotte mancanti o vuote, eccezione,
testo non ridivisibile senza blocchi vuoti che non si recupera) fa ripiegare
sul percorso normale translate_fn(SRT originale). L'uscita ha SEMPRE gli
stessi indici e tempi (stringhe originali) del sorgente, mai blocchi vuoti.
InterruptedError (annullamento) non viene mai assorbito.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

SCHEMA = 'split-eval/mapping/1'

DEFAULT_CONFIG: Dict[str, object] = {
    # ── recompose ──
    'lang': 'en',               # lingua della sorgente (parole di continuazione)
    'max_gap_s': 1.0,           # gap massimo fra blocchi della stessa unita'
    'max_blocks': 3,            # blocchi massimi per unita'
    'max_chars': 160,           # caratteri massimi del testo sorgente dell'unita'
    'max_span_s': 10.0,         # durata massima (inizio primo - fine ultimo)
    'merge_ellipsis': False,    # unire anche "…" + minuscola (variante midcut)
    'merge_softend': False,     # unire anche ", ; :" + maiuscola (variante midcut)
    'respect_speakers': True,   # MAI oltre un cambio di speaker (se presente)
    # ── resplit ──
    'tgt_lang': 'it',
    'measure': 'chars',         # proporzione per 'chars' o 'words' della sorgente
    'cpl': 42,
    'max_lines': 2,
    'cps_max': 20.0,
    'max_dev': 0.25,            # scostamento massimo di proporzione a ogni taglio
    'fallback': 'force',        # 'force' (v2) | 'first' | 'span'
    # pesi del costo di un taglio (in unita' di proporzione, 0..1)
    'w_strong': 0.15,           # bonus: taglio dopo . ? ! …
    'w_soft': 0.10,             # bonus: taglio dopo , ; : o trattino
    'w_conj': 0.05,             # bonus: il pezzo seguente apre con congiunzione/relativo
    'w_bad_end': 0.30,          # malus: pezzo che finisce con articolo/preposizione/congiunzione
    'mirror_bad_end': 1 / 3,    # fattore del malus se ANCHE il blocco sorgente finisce "appeso"
    'w_cpl': 0.50,              # malus per riga oltre CPL (per CPL di eccesso)
    'w_cps': 0.05,              # malus per pezzo oltre cps_max
}

# Solo produzione (non nel banco): guardia sui tag.
PROD_CONFIG: Dict[str, object] = {
    'skip_tagged': True,        # mai unire blocchi con tag <..> o {..}
}

# ══ RICONOSCIMENTO DELLA CONTINUAZIONE (copia di split_eval/midcut.py) ════════

_TAG = re.compile(r'<[^>]*>|\{[^}]*\}')
_SDH_LABEL = re.compile(r"^\s*([-–—]\s*)?[A-Z][A-Z0-9 .'\-]{1,}(?:\s*\[[^\]]*\])?\s*:\s+")
_BRACKETS = re.compile(r'\[[^\]]*\]')
_PARENS = re.compile(r'\(([^)]*)\)')
_MUSIC_LINE = re.compile(r'^\s*#|#\s*$')
_CLOSERS = "\"'»”’)\\]"
STRONG_END = re.compile(r'[.?!…][' + _CLOSERS + r']*$')
SOFT_END = re.compile(r'[,;:][' + _CLOSERS + r']*$')
ELLIPSIS_END = re.compile(r'(?:…|\.{2,})[' + _CLOSERS + r']*$')
_DASH_START = re.compile(r'^\s*[-–—]')
_LEAD = re.compile(r'^[\s"\'«»“”‘’(\[¿¡…\.]+')
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
}


def _lang2(lang: str) -> str:
    l = (lang or 'en').lower()
    return {'eng': 'en', 'ita': 'it', 'english': 'en', 'italian': 'it'}.get(l, l[:2])


def is_music(raw: str) -> bool:
    if '♪' in raw or '♫' in raw:
        return True
    plain = _TAG.sub('', raw)
    return any(_MUSIC_LINE.search(l) for l in plain.splitlines() if l.strip())


def clean_lines(raw: str) -> List[str]:
    out = []
    for line in _TAG.sub('', raw or '').replace('\r', '').split('\n'):
        line = _SDH_LABEL.sub(lambda m: (m.group(1) or ''), line)
        line = _BRACKETS.sub(' ', line)
        line = _PARENS.sub(lambda m: ' ' if not any(c.islower() for c in m.group(1)) else m.group(0), line)
        line = re.sub(r'\s+', ' ', line).strip()
        if line and line not in ('-', '–', '—'):
            out.append(line)
    return out


def ends_sentence(text: str) -> bool:
    return bool(STRONG_END.search(text.rstrip()))


def ends_ellipsis(text: str) -> bool:
    return bool(ELLIPSIS_END.search(text.rstrip()))


def starts_with_dash(raw_or_lines) -> bool:
    lines = clean_lines(raw_or_lines) if isinstance(raw_or_lines, str) else list(raw_or_lines)
    return bool(lines) and bool(_DASH_START.match(lines[0]))


def has_dash_line(raw: str) -> bool:
    """Una QUALUNQUE riga (anche prima della pulizia, anche dopo un tag) apre
    con un trattino: piu' largo di _extract_dash_flags ('- '), di proposito."""
    for line in (raw or '').replace('\r', '').split('\n'):
        if _DASH_START.match(_TAG.sub('', line)):
            return True
    return False


def is_dialogue_block(raw: str) -> bool:
    lines = clean_lines(raw)
    return len(lines) > 1 and any(_DASH_START.match(l) for l in lines)


def first_word(text: str) -> str:
    s = _LEAD.sub('', text or '')
    m = _FIRST_WORD.match(s)
    if not m:
        return ''
    w = m.group(0).replace('’', "'")
    if "'" in w:
        return w[:w.index("'") + 1]
    return w


def continuation_kind(text: str, lang: str) -> Optional[str]:
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


def pair_kind(a_raw: str, b_raw: str, gap: float, lang: str, max_gap_s: float = 1.0) -> Optional[str]:
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


# ══ RECOMPOSE / RESPLIT (copia di split_eval/recompose.py) ══════════════════

_CLOSE = "\"'»”’)\\]"
_STRONG = re.compile(r'[.?!…][' + _CLOSE + r']*$')
_SOFT = re.compile(r'(?:[,;:]|--|[—–])[' + _CLOSE + r']*$')
_EDGE = re.compile(r"^[\"'«»“”‘’(\[¿¡…\.\-–—]+|[\"'«»“”‘’)\],.;:!?…\-–—]+$")

BAD_END: Dict[str, frozenset] = {
    'it': frozenset("""
        il lo la i gli le un uno una di a ad da in con su per tra fra del dello della dei degli delle
        al allo alla ai agli alle dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul
        sullo sulla sui sugli sulle col coi e ed o od ma che cui se non mi ti si ci vi ne mio mia tuo
        tua suo sua nostro nostra vostro vostra loro questo questa quel quella quello molto più
    """.split()),
    'en': frozenset("""
        the a an of to in on at for with from by about into and or but nor so that which who whose
        if as than my your his her our their its this these those very not
    """.split()),
}
CONJ_START: Dict[str, frozenset] = {
    'it': frozenset("e ed o ma però perché poiché che cui quando mentre se come dove quindi finché anche oppure".split()),
    'en': frozenset("and or but because that which who when while where if so than as".split()),
}
DANGLING_SRC: Dict[str, frozenset] = {
    'en': BAD_END['en'] | frozenset("""
        i we you he she they it it's i'm you're we're they're he's she's there's that's
        is are was were be been am have has had will would can could should must do does did
        don't didn't doesn't won't can't gonna wanna just really
    """.split()),
    'it': BAD_END['it'],
}
APOCOPE: Dict[str, frozenset] = {
    'it': frozenset("po' be' mo' di' fa' va' sta' da' to' pie' ca' de'".split()),
    'en': frozenset(),
}


def make_config(config: Optional[Dict] = None) -> Dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (config or {}).items():
        if k not in cfg:
            raise KeyError(f"parametro di configurazione sconosciuto: {k}")
        cfg[k] = v
    if cfg['fallback'] not in ('force', 'first', 'span'):
        raise ValueError("fallback deve essere 'force', 'first' o 'span'")
    if cfg['measure'] not in ('chars', 'words'):
        raise ValueError("measure deve essere 'chars' o 'words'")
    return cfg


def norm_ws(text: str) -> str:
    return ' '.join(str(text or '').split())


def _t(b: Dict, k: str) -> float:
    return float(b[k] if k in b else b['s' if k == 'start' else 'e'])


def can_join(a: Dict, b: Dict, cfg: Dict, skip_tagged: bool = False) -> Tuple[bool, str]:
    """(True, motivo) se il blocco b prosegue la frase del blocco a."""
    ta, tb = str(a.get('text', '')), str(b.get('text', ''))
    if is_dialogue_block(ta) or is_dialogue_block(tb):
        return False, 'dialogo a due voci'
    if starts_with_dash(ta) or starts_with_dash(tb):
        return False, 'trattino (cambio parlante)'
    if skip_tagged:
        if has_dash_line(ta) or has_dash_line(tb):
            return False, 'trattino (cambio parlante)'
        if _TAG.search(ta) or _TAG.search(tb):
            return False, 'tag di formattazione'
        if _SDH_LABEL.match(tb) or re.match(r'\s*[\[(]', tb):
            return False, 'etichetta parlante / didascalia sonora'
    if cfg['respect_speakers'] and (a.get('speaker') or b.get('speaker')) \
            and a.get('speaker') != b.get('speaker'):
        return False, 'speaker diverso'
    gap = _t(b, 'start') - _t(a, 'end')
    kind = pair_kind(ta, tb, gap, cfg['lang'], cfg['max_gap_s'])
    allowed = {'midcut'} | ({'ellipsis'} if cfg['merge_ellipsis'] else set()) \
        | ({'softend'} if cfg['merge_softend'] else set())
    if kind not in allowed:
        return False, f"nessuna continuazione ({kind})"
    return True, kind


def recompose(blocks: Sequence[Dict], config: Optional[Dict] = None,
              skip_tagged: bool = False) -> Tuple[List[Dict], Dict]:
    """Unisce catene di blocchi consecutivi in unita' di frase (v. il modulo
    gemello split_eval/recompose.py). skip_tagged: guardia di produzione."""
    cfg = make_config(config)
    groups: List[List[int]] = []
    reasons: List[List[str]] = []
    for i, b in enumerate(blocks):
        if groups:
            g = groups[-1]
            a = blocks[g[-1]]
            ok, why = can_join(a, b, cfg, skip_tagged)
            if ok:
                src_join = norm_ws(' '.join(str(blocks[j].get('text', '')) for j in g + [i]))
                span = _t(b, 'end') - _t(blocks[g[0]], 'start')
                if len(g) >= cfg['max_blocks']:
                    ok = False
                elif len(src_join) > cfg['max_chars']:
                    ok = False
                elif span > cfg['max_span_s']:
                    ok = False
            if ok:
                g.append(i)
                reasons[-1].append(why)
                continue
        groups.append([i])
        reasons.append([])
    units, mu = [], []
    for uid, (g, rs) in enumerate(zip(groups, reasons), start=1):
        merged = len(g) > 1
        text = norm_ws(' '.join(str(blocks[j].get('text', '')) for j in g)) if merged \
            else str(blocks[g[0]].get('text', ''))
        units.append({'uid': uid, 'start': _t(blocks[g[0]], 'start'), 'end': _t(blocks[g[-1]], 'end'),
                      'text': text, 'blocks': list(g), 'merged': merged})
        mu.append({'uid': uid, 'blocks': list(g), 'merged': merged, 'reasons': rs,
                   'src': [str(blocks[j].get('text', '')) for j in g],
                   'times': [[_t(blocks[j], 'start'), _t(blocks[j], 'end')] for j in g]})
    mapping = {'schema': SCHEMA, 'n_blocks': len(blocks), 'config': cfg, 'units': mu}
    return units, mapping


def wrap_lines(text: str, cpl: int = 42) -> List[str]:
    text = norm_ws(text)
    if len(text) <= cpl:
        return [text] if text else []
    words = text.split()
    if len(words) == 1:
        return [text]
    mid = len(text) // 2
    best_i, best_d, acc = 1, float('inf'), 0
    for i, w in enumerate(words[:-1]):
        acc += len(w) + (1 if i > 0 else 0)
        d = abs(acc - mid)
        if d < best_d:
            best_d, best_i = d, i + 1
    return wrap_lines(' '.join(words[:best_i]), cpl) + wrap_lines(' '.join(words[best_i:]), cpl)


def _core(word: str) -> str:
    return _EDGE.sub('', word).lower().replace('’', "'")


def _elision_blocks_cut(prev: str, lang: str) -> bool:
    if not prev.endswith(("'", '’')):
        return False
    w = prev.lower().replace('’', "'")
    if w in APOCOPE.get(lang, frozenset()):
        return False
    if len(w) > 2 and w[0] in "'‘":
        return False
    return True


def _cut_parts(prev: str, nxt: str, cfg: Dict) -> Optional[Tuple[float, float]]:
    lang = cfg['tgt_lang']
    if _elision_blocks_cut(prev, lang):
        return None
    cost, bad = 0.0, 0.0
    if _STRONG.search(prev):
        cost -= cfg['w_strong']
    elif _SOFT.search(prev):
        cost -= cfg['w_soft']
    else:
        if _core(prev) in BAD_END.get(lang, frozenset()):
            bad += cfg['w_bad_end']
        if re.fullmatch(r'[\d.,:]+', prev) and re.match(r'[^\W\d_]', nxt):
            cost += cfg['w_bad_end'] / 2
    if _core(nxt) in CONJ_START.get(lang, frozenset()):
        cost -= cfg['w_conj']
    return cost, bad


def src_dangles(src: str, lang: str) -> bool:
    words = norm_ws(src).split()
    if not words or _STRONG.search(words[-1]) or _SOFT.search(words[-1]):
        return False
    return _core(words[-1]) in DANGLING_SRC.get(lang, frozenset())


def _piece_penalty(piece: str, dur: float, cfg: Dict) -> float:
    lines = wrap_lines(piece, cfg['cpl'])
    pen = 0.0
    over = sum(max(0, len(l) - cfg['cpl']) for l in lines)
    over += sum(len(l) for l in lines[cfg['max_lines']:])
    if over:
        pen += cfg['w_cpl'] * over / cfg['cpl']
    if dur > 0 and len(piece) / dur > cfg['cps_max']:
        pen += cfg['w_cps']
    return pen


def split_text(text: str, src_texts: Sequence[str], durations: Sequence[float],
               config: Optional[Dict] = None) -> Tuple[List[str], Dict]:
    """Divide `text` (tradotto) in len(src_texts) pezzi (programmazione
    dinamica su tutti i punti di taglio). Ritorna (pezzi, info)."""
    cfg = make_config(config)
    k = len(src_texts)
    t = norm_ws(text)
    words = t.split()
    n = len(words)
    info = {'fallback': False, 'forced': False, 'reason': '', 'cuts': [], 'targets': [], 'fractions': [],
            'dev': []}
    if k <= 1:
        return [t], info
    if cfg['measure'] == 'chars':
        w = [max(1, len(norm_ws(s))) for s in src_texts]
    else:
        w = [max(1, len(norm_ws(s).split())) for s in src_texts]
    tot = float(sum(w))
    targets = [sum(w[:m]) / tot for m in range(1, k)]
    info['targets'] = [round(x, 4) for x in targets]

    def _fallback(reason: str):
        info.update(fallback=True, reason=reason)
        return [t] + [''] * (k - 1), info

    if not t:
        info['reason'] = 'testo tradotto vuoto'
        return [''] * k, info
    if n < k:
        return _fallback('meno parole che blocchi')
    if n > max(60, 6 * sum(len(norm_ws(s).split()) for s in src_texts)):
        return _fallback('traduzione anomala (troppo lunga)')
    total_len = len(t)
    prefix = [0] * (n + 1)
    for j in range(1, n + 1):
        prefix[j] = prefix[j - 1] + len(words[j - 1]) + (1 if j > 1 else 0)

    def frac(j: int) -> float:
        return prefix[j] / total_len if cfg['measure'] == 'chars' else j / n

    parts = [None] * (n + 1)
    for j in range(1, n):
        parts[j] = _cut_parts(words[j - 1], words[j], cfg)
    mirror = [cfg['mirror_bad_end'] if src_dangles(s, cfg['lang']) else 1.0 for s in src_texts[:-1]]
    durs = [max(0.0, float(durations[m])) if durations else 0.0 for m in range(k)]
    pen_cache: Dict[Tuple[int, int, int], float] = {}

    def piece_pen(i: int, j: int, m: int) -> float:
        key = (i, j, m)
        if key not in pen_cache:
            pen_cache[key] = _piece_penalty(' '.join(words[i:j]), durs[m], cfg)
        return pen_cache[key]

    INF = float('inf')

    def solve(mode: str) -> Optional[List[int]]:
        D = [[INF] * (n + 1) for _ in range(k + 1)]
        B = [[-1] * (n + 1) for _ in range(k + 1)]
        D[0][0] = 0.0
        for m in range(1, k + 1):
            j_range = [n] if m == k else range(m, n - (k - m) + 1)
            for j in j_range:
                if m < k:
                    if parts[j] is None:
                        continue
                    d = abs(frac(j) - targets[m - 1])
                    if mode == 'bounded' and d > cfg['max_dev']:
                        continue
                    ling = parts[j][0] + parts[j][1] * mirror[m - 1]
                    cut_cost = d + ling if mode != 'mindev' else d + 0.1 * ling
                else:
                    cut_cost = 0.0
                for i in range(m - 1, j):
                    if D[m - 1][i] == INF:
                        continue
                    pp = piece_pen(i, j, m - 1)
                    c = D[m - 1][i] + (pp if mode != 'mindev' else 0.1 * pp) + cut_cost
                    if c < D[m][j]:
                        D[m][j], B[m][j] = c, i
        if D[k][n] == INF:
            return None
        cuts, j = [], n
        for m in range(k, 0, -1):
            i = B[m][j]
            cuts.append(i)
            j = i
        return list(reversed(cuts))[1:]

    def record(cuts: List[int]) -> List[float]:
        fr = [frac(c) for c in cuts]
        dev = [abs(f - tg) for f, tg in zip(fr, targets)]
        info.update(cuts=cuts, fractions=[round(x, 4) for x in fr], dev=[round(x, 4) for x in dev])
        return dev

    if cfg['fallback'] == 'force':
        cuts = solve('bounded')
        if cuts is None:
            cuts = solve('mindev')
            if cuts is None:
                return _fallback('nessun taglio ammissibile')
            dev = record(cuts)
            info.update(forced=True, reason=f"taglio forzato: scostamento minimo {max(dev):.2f} > {cfg['max_dev']}")
        else:
            record(cuts)
    else:
        cuts = solve('free')
        if cuts is None:
            return _fallback('nessun taglio ammissibile')
        dev = record(cuts)
        if max(dev) > cfg['max_dev']:
            return _fallback(f"scostamento {max(dev):.2f} > {cfg['max_dev']}")
    bounds = [0] + cuts + [n]
    pieces = [' '.join(words[bounds[m]:bounds[m + 1]]) for m in range(k)]
    return pieces, info


def check_invariant(text: str, pieces: Sequence[str]) -> bool:
    return norm_ws(' '.join(p for p in pieces if p)) == norm_ws(text)


def resplit(translated_units: Union[Dict[int, str], Sequence[str]], mapping: Dict,
            config: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
    """Ridistribuisce il testo TRADOTTO di ogni unita' sui blocchi originali
    (tempi originali). Ritorna (blocks, report); v. split_eval/recompose.py."""
    cfg = make_config(config if config is not None else mapping.get('config'))
    if not isinstance(translated_units, dict):
        translated_units = {u['uid']: t for u, t in zip(mapping['units'], translated_units)}
    n_blocks = mapping['n_blocks']
    out: List[Optional[Dict]] = [None] * n_blocks
    rep_units = []
    for u in mapping['units']:
        text = translated_units.get(u['uid'], '')
        text = '' if text is None else str(text)
        if not u['merged']:
            j = u['blocks'][0]
            s, e = u['times'][0]
            out[j] = {'start': s, 'end': e, 'text': text.strip(), 'uid': u['uid'], 'drop': False}
            continue
        durs = [max(0.0, e - s) for s, e in u['times']]
        pieces, info = split_text(text, u['src'], durs, cfg)
        if not check_invariant(text, pieces):
            raise AssertionError(f"invariante violata sull'unita' {u['uid']}")
        span = info['fallback'] and cfg['fallback'] == 'span'
        for m, (j, (s, e)) in enumerate(zip(u['blocks'], u['times'])):
            if span and m == 0:
                e = u['times'][-1][1]
            out[j] = {'start': s, 'end': e, 'text': '\n'.join(wrap_lines(pieces[m], cfg['cpl'])),
                      'uid': u['uid'], 'drop': bool(span and m > 0)}
        rep_units.append({'uid': u['uid'], 'n': len(u['blocks']), **info})
    if any(b is None for b in out):
        raise ValueError("mapping incompleto: blocchi senza unita'")
    devs = [d for r in rep_units for d in r['dev']]
    report = {'n_units': len(mapping['units']), 'n_merged': len(rep_units),
              'n_fallback': sum(1 for r in rep_units if r['fallback']),
              'n_forced': sum(1 for r in rep_units if r.get('forced')),
              'n_empty_text': sum(1 for r in rep_units if r['reason'] == 'testo tradotto vuoto'),
              'dev': devs, 'max_dev': max(devs) if devs else None, 'units': rep_units,
              'fallback_policy': cfg['fallback']}
    return out, report


# ══ SRT (stesso parser di BaseTranslator._parse_srt) ════════════════════════

TRANSLATOR_SRT_PATTERN = r'(\d+)\s*\n([\d:,]+)\s*-->\s*([\d:,]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|$)'
_TS = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')

SrtBlock = Tuple[int, str, str, str]      # (indice, inizio, fine, testo) come _parse_srt


def ts_to_s(value: str) -> float:
    m = _TS.search(value or '')
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, '0')) / 1000


def parse_srt_text(content: str) -> List[SrtBlock]:
    """Esattamente cio' che BaseTranslator._parse_srt restituirebbe (blocchi
    con testo vuoto scartati)."""
    content = content.replace('﻿', '')
    out = []
    for m in re.finditer(TRANSLATOR_SRT_PATTERN, content, re.MULTILINE):
        text = m.group(4).strip()
        if text:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip(), text))
    return out


def read_srt(path: Union[str, Path]) -> List[SrtBlock]:
    with open(path, 'r', encoding='utf-8') as f:
        return parse_srt_text(f.read())


def render_srt(blocks: Sequence[SrtBlock]) -> str:
    """Stesso formato di BaseTranslator._generate_srt."""
    out: List[str] = []
    for idx, start, end, text in blocks:
        out += [str(idx), f"{start} --> {end}", text, '']
    return '\n'.join(out)


def write_srt(path: Union[str, Path], blocks: Sequence[SrtBlock]) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_srt(blocks))


# ══ ALTO LIVELLO ═════════════════════════════════════════════════════════════

RECOMPOSE_ENGINES = ('nllb', 'nllb_finetuned')
RECOMPOSE_LANG_PAIRS = (('en', 'it'),)


def recompose_enabled(model: str, src_lang: str, tgt_lang: str) -> Tuple[bool, str]:
    """Predicato di attivazione usato dalla pipeline quando l'opzione e'
    accesa: (True, '') oppure (False, motivo da loggare).
    Solo NLLB: il ramo LLM (TranslateGemma) ha un budget di 84 caratteri per
    blocco che penalizza le unita' fuse; claude/openai/opensubtitles non sono
    stati misurati. Solo en->it: e' l'unica coppia misurata."""
    if model not in RECOMPOSE_ENGINES:
        return False, f"non prevista per il motore '{model}' (solo NLLB)"
    if (src_lang, tgt_lang) not in RECOMPOSE_LANG_PAIRS:
        return False, f"misurata solo en→it (qui {src_lang}→{tgt_lang})"
    return True, ''

def _side_path(output_srt: Path, tag: str) -> Path:
    return output_srt.with_name(f"{output_srt.stem}.{tag}{output_srt.suffix or '.srt'}")


def translate_srt_with_recompose(input_srt: Union[str, Path], output_srt: Union[str, Path],
                                 translate_fn: Callable[[str, str], bool],
                                 config: Optional[Dict] = None,
                                 log: Optional[Callable[[str], None]] = None,
                                 polish_fn: Optional[Callable[[List[str]], List[str]]] = None) -> Dict:
    """Traduce input_srt in output_srt con la ricomposizione delle frasi.

    translate_fn(in_path: str, out_path: str) -> bool: il traduttore reale.
    polish_fn(texts) -> texts: rifinitura finale sull'intera lista dei blocchi
    (in produzione BaseTranslator._polish; il banco l'ha misurata cosi').
    config: chiavi di DEFAULT_CONFIG e di PROD_CONFIG.

    Ritorna {'ok', 'mode': 'recompose'|'passthrough'|'fallback', 'reason',
    'n_blocks', 'n_units', 'n_merged_units', 'n_merged_blocks', 'n_forced',
    'n_retranslated_units'}. 'ok' e' l'esito della traduzione nel ramo usato.
    Nel ripiego ('fallback'/'passthrough') si chiama translate_fn(input_srt,
    output_srt) UNA volta sola: e' esattamente il percorso di oggi, e le sue
    eccezioni si propagano come oggi.
    """
    log = log or (lambda msg: None)
    input_srt, output_srt = Path(input_srt), Path(output_srt)
    res = {'ok': False, 'mode': 'fallback', 'reason': '', 'n_blocks': 0, 'n_units': 0, 'n_merged_units': 0,
           'n_merged_blocks': 0, 'n_forced': 0, 'n_retranslated_units': 0}
    tmp_files: List[Path] = []
    try:
        mode, reason = _recompose_attempt(input_srt, output_srt, translate_fn, config, log, polish_fn,
                                          res, tmp_files)
    except InterruptedError:
        raise
    except Exception as exc:
        mode, reason = 'fallback', f"errore {type(exc).__name__}: {exc}"
    finally:
        for p in tmp_files:
            try:
                p.unlink()
            except OSError:
                pass
    if mode == 'recompose':
        res.update(ok=True, mode='recompose', reason='')
        extra = f", {res['n_forced']} tagli forzati" if res['n_forced'] else ''
        extra += (f", {res['n_retranslated_units']} unità ritradotte blocco per blocco"
                  if res['n_retranslated_units'] else '')
        log(f"   🔗 Ricomposizione frasi completata: {res['n_merged_units']} unità ridivise su "
            f"{res['n_merged_blocks']} blocchi{extra}")
        return res
    if mode == 'fallback':
        log(f"   ⚠️ Ricomposizione frasi: {reason} — traduco i blocchi uno per uno (percorso normale)")
    res.update(mode=mode, reason=reason)
    res['ok'] = bool(translate_fn(str(input_srt), str(output_srt)))
    return res


def _recompose_attempt(input_srt: Path, output_srt: Path, translate_fn: Callable[[str, str], bool],
                       config: Optional[Dict], log: Callable[[str], None],
                       polish_fn: Optional[Callable[[List[str]], List[str]]], res: Dict,
                       tmp_files: List[Path]) -> Tuple[str, str]:
    """('recompose', '') se output_srt e' scritto e valido, altrimenti
    ('fallback'|'passthrough', motivo): chi chiama usa il percorso normale."""
    cfg_in = dict(config or {})
    prod = {k: cfg_in.pop(k, v) for k, v in PROD_CONFIG.items()}
    cfg = make_config(cfg_in)
    src = read_srt(input_srt)
    res['n_blocks'] = len(src)
    if not src:
        return 'fallback', 'SRT sorgente vuoto o illeggibile'
    if len({b[0] for b in src}) != len(src):
        return 'fallback', 'indici SRT duplicati'
    blocks = [{'start': ts_to_s(s), 'end': ts_to_s(e), 'text': t} for _, s, e, t in src]
    units, mapping = recompose(blocks, cfg, skip_tagged=bool(prod['skip_tagged']))
    merged = [u for u in units if u['merged']]
    res.update(n_units=len(units), n_merged_units=len(merged),
               n_merged_blocks=sum(len(u['blocks']) for u in merged))
    if not merged:
        log("   🔗 Ricomposizione frasi: nessuna frase spezzata da unire")
        return 'passthrough', "nessuna unita' fusa"
    log(f"   🔗 Ricomposizione frasi ATTIVA: {len(merged)} frasi spezzate riunite "
        f"({res['n_merged_blocks']} blocchi → {len(merged)} unità; {len(src)} blocchi, "
        f"{len(units)} unità da tradurre)")

    # 1) SRT delle unita': un blocco per unita', indice = uid, tempi = dal
    #    primo all'ultimo blocco (stringhe originali)
    ublocks = [(u['uid'], src[u['blocks'][0]][1], src[u['blocks'][-1]][2], u['text']) for u in units]
    back = parse_srt_text(render_srt(ublocks))
    if [(b[0], b[3]) for b in back] != [(b[0], b[3].strip()) for b in ublocks]:
        return 'fallback', "SRT delle unità non rileggibile in modo identico (parser del traduttore)"
    units_in, units_out = _side_path(output_srt, 'units'), _side_path(output_srt, 'units_tr')
    tmp_files += [units_in, units_out]
    write_srt(units_in, ublocks)

    # 2) traduzione delle unita'
    if not translate_fn(str(units_in), str(units_out)) or not units_out.exists():
        return 'fallback', 'traduzione delle unità fallita'
    tr = {i: t for i, _, _, t in read_srt(units_out)}
    if set(tr) != {u['uid'] for u in units}:
        return 'fallback', f"unità tradotte {len(tr)} ≠ unità inviate {len(units)}"
    if any(not norm_ws(t) for t in tr.values()):
        return 'fallback', 'unità tradotta vuota'

    # 3) ridivisione sui blocchi originali (tempi invariati)
    rb, rep = resplit(tr, mapping, cfg)
    res['n_forced'] = rep['n_forced']
    texts = [b['text'] for b in rb]
    # unita' fuse non ridivisibili senza blocchi vuoti (meno parole che
    # blocchi, es. "Come | in." -> "Entra."): i loro blocchi si traducono
    # uno per uno, come oggi
    bad = [u for u in mapping['units'] if u['merged'] and any(not norm_ws(texts[j]) for j in u['blocks'])]
    if bad:
        retry = [src[j] for u in bad for j in u['blocks']]
        r_in, r_out = _side_path(output_srt, 'retry'), _side_path(output_srt, 'retry_tr')
        tmp_files += [r_in, r_out]
        write_srt(r_in, retry)
        if not translate_fn(str(r_in), str(r_out)) or not r_out.exists():
            return 'fallback', 'ritraduzione dei blocchi non ridivisibili fallita'
        rt = {i: t for i, _, _, t in read_srt(r_out)}
        pos_of = {src[j][0]: j for u in bad for j in u['blocks']}
        if set(rt) != set(pos_of) or any(not norm_ws(t) for t in rt.values()):
            return 'fallback', 'ritraduzione dei blocchi non ridivisibili incompleta'
        for idx, t in rt.items():
            texts[pos_of[idx]] = t
        res['n_retranslated_units'] = len(bad)

    # 4) rifinitura finale sull'intera lista (come il banco: assemble_b)
    if polish_fn is not None:
        try:
            pol = polish_fn(list(texts))
            if isinstance(pol, list) and len(pol) == len(texts) and all(norm_ws(p) for p in pol):
                texts = pol
            else:
                log("   ⚠️ Ricomposizione frasi: rifinitura finale ignorata (uscita non valida)")
        except InterruptedError:
            raise
        except Exception as exc:
            log(f"   ⚠️ Ricomposizione frasi: rifinitura finale ignorata ({exc})")

    # 5) controlli finali: stessi indici e tempi, nessun blocco vuoto
    if len(texts) != len(src) or any(not norm_ws(t) for t in texts):
        return 'fallback', 'uscita con blocchi mancanti o vuoti'
    write_srt(output_srt, [(i, s, e, t) for (i, s, e, _), t in zip(src, texts)])
    check = read_srt(output_srt)
    if [(b[0], b[1], b[2]) for b in check] != [(b[0], b[1], b[2]) for b in src]:
        return 'fallback', 'SRT finale non rileggibile con gli stessi indici/tempi'
    return 'recompose', ''
