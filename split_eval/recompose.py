"""
Ricomposizione delle frasi spezzate PRIMA della traduzione e ridivisione
DETERMINISTICA del testo tradotto sui blocchi originali.

Algoritmo PURO (nessun modello, nessun torch). Non e' il vecchio percorso
"adapt": al modello non si danno id da restituire. Il modello riceve una
frase intera come UN blocco e restituisce UNA traduzione; la ridivisione la
fa questo codice.

    units, mapping = recompose(blocks, config)
    ... traduzione di units[*]['text'] ...
    new_blocks, report = resplit({uid: testo_tradotto}, mapping, config)

Politica di ripiego ('fallback'), esplicita e testata:
  'first' (default): se non esiste un taglio sensato, l'intera unita'
          tradotta va sul PRIMO blocco e gli altri blocchi ricevono ''
          (stringa vuota: chi scrive l'SRT decide se saltarli, e le metriche
          strutturali li contano come "blocchi vuoti");
  'span': come 'first', ma la fine del primo blocco si estende alla fine
          dell'ultimo e gli altri blocchi sono marcati drop=True (tempi
          CAMBIATI: le metriche li contano come "blocchi fusi/ritemporizzati").
Il ripiego scatta se: le parole tradotte sono meno dei blocchi, oppure lo
scostamento fra la proporzione italiana e quella inglese a un taglio supera
max_dev (proxy di "parole spostate oltre il confine audio del blocco"),
oppure nessun taglio e' ammissibile.

Invariante (testata): ' '.join(pezzi non vuoti) == ' '.join(testo.split())
cioe' nessuna parola persa, duplicata o riordinata.
"""
from __future__ import annotations

import copy
import re
from typing import Dict, List, Optional, Sequence, Tuple, Union

from split_eval import midcut as MC

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
    'fallback': 'first',        # 'first' | 'span'
    # pesi del costo di un taglio (in unita' di proporzione, 0..1)
    'w_strong': 0.15,           # bonus: taglio dopo . ? ! …
    'w_soft': 0.10,             # bonus: taglio dopo , ; : o trattino
    'w_conj': 0.05,             # bonus: il pezzo seguente apre con congiunzione/relativo
    'w_bad_end': 0.30,          # malus: pezzo che finisce con articolo/preposizione/congiunzione
    'w_cpl': 0.50,              # malus per riga oltre CPL (per CPL di eccesso)
    'w_cps': 0.05,              # malus per pezzo oltre cps_max
}

_CLOSE = "\"'»”’)\\]"
_STRONG = re.compile(r'[.?!…][' + _CLOSE + r']*$')
_SOFT = re.compile(r'(?:[,;:]|--|[—–])[' + _CLOSE + r']*$')
_EDGE = re.compile(r"^[\"'«»“”‘’(\[¿¡…\.\-–—]+|[\"'«»“”‘’)\],.;:!?…\-–—]+$")

# Parole con cui un pezzo NON deve finire (resterebbe appeso) e con cui un
# pezzo e' contento di cominciare (congiunzioni/relativi).
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


def make_config(config: Optional[Dict] = None) -> Dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (config or {}).items():
        if k not in cfg:
            raise KeyError(f"parametro di configurazione sconosciuto: {k}")
        cfg[k] = v
    if cfg['fallback'] not in ('first', 'span'):
        raise ValueError("fallback deve essere 'first' o 'span'")
    if cfg['measure'] not in ('chars', 'words'):
        raise ValueError("measure deve essere 'chars' o 'words'")
    return cfg


def norm_ws(text: str) -> str:
    return ' '.join(str(text or '').split())


# ══ RECOMPOSE ═══════════════════════════════════════════════════════════════

def _t(b: Dict, k: str) -> float:
    return float(b[k] if k in b else b['s' if k == 'start' else 'e'])


def can_join(a: Dict, b: Dict, cfg: Dict) -> Tuple[bool, str]:
    """(True, motivo) se il blocco b prosegue la frase del blocco a."""
    ta, tb = str(a.get('text', '')), str(b.get('text', ''))
    if MC.is_dialogue_block(ta) or MC.is_dialogue_block(tb):
        return False, 'dialogo a due voci'
    if MC.starts_with_dash(ta) or MC.starts_with_dash(tb):
        return False, 'trattino (cambio parlante)'
    if cfg['respect_speakers'] and (a.get('speaker') or b.get('speaker')) \
            and a.get('speaker') != b.get('speaker'):
        return False, 'speaker diverso'
    gap = _t(b, 'start') - _t(a, 'end')
    kind = MC.pair_kind(ta, tb, gap, cfg['lang'], cfg['max_gap_s'])
    allowed = {'midcut'} | ({'ellipsis'} if cfg['merge_ellipsis'] else set()) \
        | ({'softend'} if cfg['merge_softend'] else set())
    if kind not in allowed:
        return False, f"nessuna continuazione ({kind})"
    return True, kind


def recompose(blocks: Sequence[Dict], config: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
    """Unisce catene di blocchi consecutivi in unita' di frase.

    blocks: [{start, end, text, [speaker]}] in ordine cronologico (i blocchi
    dell'SRT che il traduttore riceverebbe). Ritorna (units, mapping):
      units   = [{uid, start, end, text, blocks: [posizioni], merged}]
      mapping = {schema, n_blocks, config, units: [{uid, blocks, src, times, merged, reasons}]}
    Le unita' di un solo blocco hanno il testo IDENTICO al blocco (righe e
    trattini compresi): il traduttore le vede come le vedrebbe senza
    ricomposizione.
    """
    cfg = make_config(config)
    groups: List[List[int]] = []
    reasons: List[List[str]] = []
    for i, b in enumerate(blocks):
        if groups:
            g = groups[-1]
            a = blocks[g[-1]]
            ok, why = can_join(a, b, cfg)
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


# ══ RESPLIT ═════════════════════════════════════════════════════════════════

def wrap_lines(text: str, cpl: int = 42) -> List[str]:
    """Divisione in righe a confine di parola vicino alla meta' (stesso
    criterio di SubtitleFormatter._wrap_cpl, ricorsivo)."""
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


def _cut_bonus(prev: str, nxt: str, cfg: Dict) -> float:
    """Costo del taglio fra la parola prev e la parola nxt (negativo = buono).
    None = taglio vietato (elisione: l'|uomo)."""
    if prev.endswith(("'", '’')):
        return None
    lang = cfg['tgt_lang']
    cost = 0.0
    if _STRONG.search(prev):
        cost -= cfg['w_strong']
    elif _SOFT.search(prev):
        cost -= cfg['w_soft']
    else:
        if _core(prev) in BAD_END.get(lang, frozenset()):
            cost += cfg['w_bad_end']
        if re.fullmatch(r'[\d.,:]+', prev) and re.match(r'[^\W\d_]', nxt):
            cost += cfg['w_bad_end'] / 2          # numero | unita' di misura
    if _core(nxt) in CONJ_START.get(lang, frozenset()):
        cost -= cfg['w_conj']
    return cost


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
    """Divide `text` (tradotto) in len(src_texts) pezzi. Ritorna (pezzi, info)
    con info = {fallback, reason, cuts, targets, fractions, dev}."""
    cfg = make_config(config)
    k = len(src_texts)
    t = norm_ws(text)
    words = t.split()
    n = len(words)
    info = {'fallback': False, 'reason': '', 'cuts': [], 'targets': [], 'fractions': [], 'dev': []}
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
    total_len = len(t)
    prefix = [0] * (n + 1)          # caratteri di ' '.join(words[:j])
    for j in range(1, n + 1):
        prefix[j] = prefix[j - 1] + len(words[j - 1]) + (1 if j > 1 else 0)

    def frac(j: int) -> float:
        return prefix[j] / total_len if cfg['measure'] == 'chars' else j / n

    bonus = [None] * (n + 1)
    for j in range(1, n):
        bonus[j] = _cut_bonus(words[j - 1], words[j], cfg)
    INF = float('inf')
    D = [[INF] * (n + 1) for _ in range(k + 1)]
    B = [[-1] * (n + 1) for _ in range(k + 1)]
    D[0][0] = 0.0
    for m in range(1, k + 1):
        dur = max(0.0, float(durations[m - 1])) if durations else 0.0
        j_range = [n] if m == k else range(m, n - (k - m) + 1)
        for j in j_range:
            if m < k:
                if bonus[j] is None:
                    continue
                cut_cost = abs(frac(j) - targets[m - 1]) + bonus[j]
            else:
                cut_cost = 0.0
            for i in range(m - 1, j):
                if D[m - 1][i] == INF:
                    continue
                c = D[m - 1][i] + _piece_penalty(' '.join(words[i:j]), dur, cfg) + cut_cost
                if c < D[m][j]:
                    D[m][j], B[m][j] = c, i
    if D[k][n] == INF:
        return _fallback('nessun taglio ammissibile')
    cuts, j = [], n
    for m in range(k, 0, -1):
        i = B[m][j]
        cuts.append(i)
        j = i
    cuts = list(reversed(cuts))[1:]           # tagli interni c_1..c_{k-1}
    fr = [frac(c) for c in cuts]
    dev = [abs(f - tg) for f, tg in zip(fr, targets)]
    info.update(cuts=cuts, fractions=[round(x, 4) for x in fr], dev=[round(x, 4) for x in dev])
    if max(dev) > cfg['max_dev']:
        return _fallback(f"scostamento {max(dev):.2f} > {cfg['max_dev']}")
    bounds = [0] + cuts + [n]
    pieces = [' '.join(words[bounds[m]:bounds[m + 1]]) for m in range(k)]
    return pieces, info


def check_invariant(text: str, pieces: Sequence[str]) -> bool:
    return norm_ws(' '.join(p for p in pieces if p)) == norm_ws(text)


def resplit(translated_units: Union[Dict[int, str], Sequence[str]], mapping: Dict,
            config: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
    """Ridistribuisce il testo TRADOTTO di ogni unita' sui blocchi originali.

    translated_units: {uid: testo} oppure lista parallela a mapping['units'].
    Ritorna (blocks, report): blocks ha lunghezza mapping['n_blocks'], nello
    stesso ordine dei blocchi di partenza, con i TEMPI ORIGINALI
    ({start, end, text, uid, drop}); 'drop' e' True solo con fallback='span'.
    Il testo dei pezzi di un'unita' fusa e' diviso in righe (CPL, v.
    wrap_lines); le unita' di un solo blocco restano come le ha date il
    traduttore.
    """
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
        if not check_invariant(text, pieces):          # difesa: non deve mai accadere
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
              'n_empty_text': sum(1 for r in rep_units if r['reason'] == 'testo tradotto vuoto'),
              'dev': devs, 'max_dev': max(devs) if devs else None, 'units': rep_units,
              'fallback_policy': cfg['fallback']}
    return out, report
