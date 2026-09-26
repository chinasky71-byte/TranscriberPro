"""
Split dei segmenti faster-whisper che preferisce i CONFINI DI FRASE.
File: core/whisper_sentence_split.py

Perche': in modalita' BatchedInferencePipeline (without_timestamps=True) ogni
chunk VAD da <=30 s diventa UN solo segmento Whisper; tutti i confini interni
li crea FasterWhisperEngine._split_segment_by_words, che taglia appena si
superano 80 caratteri / 6 s senza guardare la punteggiatura -> ~41% dei
blocchi finiva a meta' frase (misura: whisper_split_eval/). Il traduttore
traduce ogni blocco da solo, quindi i frammenti escono tradotti male.

Cosa fa: sceglie i punti di taglio con una programmazione dinamica sul costo
totale, con questa gerarchia:
  (i)   fine frase (. ? ! … e varianti con virgolette/parentesi finali; non
        dopo abbreviazioni tipo Mr./Dr./U.S., ne' "No." davanti a un numero);
  (ii)  clausola (; : poi , e trattini), o davanti a una congiunzione;
  (iii) solo se serve, una parola qualunque (mai subito dopo articolo,
        preposizione, pronome soggetto o ausiliare, se evitabile).
Le pause fra le parole rendono un taglio piu' conveniente. Vincoli:
  - max_chars / max_duration (80 / 6 s, come oggi) sono MORBIDI;
  - hard_max_chars / hard_max_duration (84 / 9 s) sono DURI: 84 = due righe
    da 42 del SubtitleFormatter (il suo _wrap_cpl e' ricorsivo: un pezzo
    oltre 84 caratteri diventerebbe un blocco da 3-4 righe). Unica eccezione:
    una singola parola intera (anche di piu' token attaccati, es.
    "Boop-a-doop-a.") che da sola li supera (oltre 2 x 84 caratteri e' un
    loop di allucinazione: None -> split originale);
  - MAI tagli dentro una parola: si taglia solo prima di un token con spazio
    iniziale (i token senza spazio, "post" + "-traumatic", restano uniti).
  - pezzi molto corti a meta' frase sono penalizzati (niente "lungo | due").

Invarianti (verificati da whisper_split_eval/tests): la sequenza delle parole
e' identica e completa (nessuna persa/duplicata/riordinata), il testo di ogni
pezzo e' la concatenazione delle sue parole (come nello split originale),
start/end = prima/ultima parola del pezzo. I segmenti gia' corti (<= 80
caratteri e <= 6 s) o senza parole vengono restituiti ESATTAMENTE come fa lo
split originale.

Modulo PURO: solo libreria standard, nessun import del progetto o di torch.
Lingue: `lang='en'` (default, liste inglesi, comportamento misurato) e
`lang='it'` (liste italiane in _boundary_type_it; stessi parametri numerici);
altre lingue -> None (split originale).
Lo usa FasterWhisperEngine._split_segment_by_words solo se la config ha
'whisper_split_sentence_aware' = True e la lingua del file e' in
'whisper_split_sentence_langs' (default ['en']); in caso di eccezione o risultato non
valido il motore prosegue con lo split originale. Per rimuoverlo: cancellare
questo file e il blocco marcato nel motore.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

DEFAULT_PARAMS: Dict[str, float] = {
    'max_chars': 80,            # morbido (come lo split originale)
    'max_duration': 6.0,        # morbido (come lo split originale)
    'hard_max_chars': 84,       # duro: 2 righe x 42 del formatter
    'hard_max_duration': 9.0,   # duro
    'cpl': 42,                  # caratteri per riga del formatter (controllo 2 righe)
    'piece_cost': 1.0,          # costo di ogni pezzo (favorisce pezzi pieni)
    'cost_sentence': 0.0,       # taglio a fine frase
    'cost_sentence_weak': 1.5,  # fine frase incerta (puntini/sigla + minuscola)
    'cost_clause': 3.0,         # ; :
    'cost_comma': 4.0,          # , e trattini
    'cost_before_conj': 6.0,    # nessuna punteggiatura, davanti a congiunzione
    'cost_word': 8.0,           # parola qualunque
    'cost_after_function': 12.0,  # dopo articolo/preposizione/pronome/ausiliare
    'cost_abbrev': 14.0,        # dopo Mr./Dr./... (mai, se evitabile)
    'cost_inside_word': 100.0,  # dentro una parola ("post|-traumatic"): solo se inevitabile
    'pause_s': 1.0,             # pausa fra parole che rende il taglio naturale (0,5 frammentava: +41% blocchi)
    'pause_bonus': 2.0,
    'glitch_gap_s': 9.0,        # salto temporale dentro una parola (= hard_max_duration): glitch di Whisper, si taglia
    'over_chars_w': 0.3,        # penalita' per carattere oltre max_chars
    'over_dur_w': 1.0,          # penalita' per secondo oltre max_duration
    'wrap3_penalty': 6.0,       # il formatter lo metterebbe su 3+ righe
    'short_frag_chars': 20,     # pezzo corto a meta' frase...
    'short_frag_w': 4.0,        # ...penalita' massima (proporzionale)
    'tail_max_words': 3,        # coda <= 3 parole (come oggi: < 4)...
    'tail_max_gap': 0.8,        # ...con pausa <= 0,8 s si riunisce se possibile
}

_CLOSERS = '"\'”’»)]}'
_ABBREV = frozenset("""
    mr mrs ms dr prof st jr sr sgt lt capt col gen gov rev mt ft vs
    messrs mme mlle
    sig sigg dott avv ing geom mons egr
""".split())   # riga 3: titoli italiani (nessuno e' una parola inglese di fine frase)
_CONJ = frozenset("""
    and but or nor so yet because cause 'cause that which who whom whose where when while
    whereas whether if unless until till though although since than then
""".split())
_FUNCTION = frozenset("""
    the a an of to in on at for with from by into onto about as over under after before
    through between against without like
    my your his her its our their this these those
    i you he she we they it
    is are was were am be been being have has had do does did will would can could
    should shall may might must
    and but or nor so because that which who if than
    very just not no really
""".split())
_ACRONYM = re.compile(r"^(?:[A-Za-z]\.){2,}$")
_INITIAL = re.compile(r"^[A-Z]\.$")
_LETTERS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
# scritture senza spazi fra le parole (Han, Kana, punteggiatura CJK, Thai,
# Lao, Tibetano, Myanmar, Khmer, forme fullwidth)
_NOSPACE_SCRIPT = re.compile(
    '[฀-໿ༀ-࿿က-႟ក-៿'
    '　-ヿ㐀-䶿一-鿿豈-﫿＀-￯]')

# tipi di confine
SENT, SENT_WEAK, CLAUSE, COMMA, CONJ, WORD, FUNC, ABBREV, INSIDE = (
    'sent', 'sent_weak', 'clause', 'comma', 'conj', 'word', 'func', 'abbrev', 'inside')
STRONG_TYPES = (SENT, SENT_WEAK)


def _core(word: str) -> str:
    """Parola senza spazi e senza chiusure finali (virgolette, parentesi)."""
    return word.strip().rstrip(_CLOSERS)


def _bare(word: str) -> str:
    m = _LETTERS.search(word.strip().replace('’', "'"))
    return m.group(0).lower() if m else ''


def _starts_lower(word: str) -> bool:
    s = word.strip().lstrip('"\'“‘«([¿¡-–—')
    return bool(s) and s[0].isalpha() and s[0].islower()


def _starts_digit(word: str) -> bool:
    s = word.strip().lstrip('"\'“‘«([')
    return bool(s) and s[0].isdigit()


# ── regole ITALIANE (lang='it') ──────────────────────────────────────────────
# Tarate SOLO su 3 file (whisper_split_eval/work_it_runs/raw: Casper, Il
# diavolo veste Prada, The Bad Guy). Con le liste inglesi l'italiano veniva
# tagliato dopo articoli/preposizioni/"non" ("del | centro", "Non | mi era mai
# capitato", "di suo | figlio") e "so" era preso per la congiunzione inglese
# ("lo | so"). Quello che NON serve codice nuovo, perche' coperto dalle unita'
# (token senza spazio iniziale -> mai tagli dentro): elisioni ("l" + "'avevo",
# "dell" + "'umorismo?", "c" + "'è"), migliaia e orari ("1" + ".200" + ".000",
# "12" + ".30."). Numeri col punto davanti a maiuscola restano FINE FRASE: nei
# dati sono sempre fini frase ("42. Che", "38. Io", "2001. Una"), nessuna
# regola per gli ordinali. Abbreviazioni, «», "?!", trattino di battuta,
# puntini iniziali ("...che": 1 caso): zero o quasi occorrenze nei dati di
# taratura -> regole a priori (abbreviazioni) o gestione generica gia'
# esistente (_CLOSERS, _starts_lower), come per l'inglese.
_ABBREV_IT = frozenset("""
    sig sigg dott prof avv ing geom arch on mons gen col tel cfr es pag n egr
    mr mrs ms dr
""".split())   # a priori: nessuna occorrenza "X." nei dati di taratura. TOLTI "cap" e
# "art": nei film doppiati sono anche nomi a fine frase (dati: "Sono Cap." in Casper)
_ABBREV_IT_AMBIG = frozenset(['ecc', 'etc'])   # + minuscola: abbreviazione; + maiuscola: fine frase incerta
_CONJ_IT = frozenset("""
    e ed o od oppure ma però perché poiché siccome che cui quando mentre se come dove
    quindi dunque finché affinché sebbene benché anziché cioè né
""".split())
_FUNCTION_IT = frozenset("""
    il lo la i gli le l un uno una
    di a ad da in con su per tra fra
    del dello della dei degli delle al allo alla ai agli alle dal dallo dalla dai dagli dalle
    nel nello nella nei negli nelle sul sullo sulla sui sugli sulle col coi
    e ed o ma però perché che cui se come quando mentre dove quindi né
    mi ti ci vi si ne
    io tu non
    è sono sei siamo siete era ero erano sarà ho hai ha abbiamo avete hanno avevo aveva
    essere avere stato stata
    posso puoi può devo devi deve dobbiamo
    mio mia miei mie tuo tua tuoi tue suo sua suoi sue nostro nostra nostri nostre
    vostro vostra vostri vostre
    questo questa questi queste quel quei quegli quella quelle
    molto molta molti molte
""".split())
# parole che formano una locuzione con la congiunzione seguente (conteggi sui
# dati di taratura, parola + congiunzione senza punteggiatura): quello che 37,
# solo che 8 (+ solo perché 2), cosa che 7, certo che 5, prima che 4, ciò che 3,
# quelli che 3, anche se 3, più che/più o 4, visto che 2, già che 2, proprio come 2
_CONJ_GLUE_IT = frozenset("""
    quello quelli ciò cosa solo prima certo anche più visto già proprio
""".split())


def _boundary_type_it(word: str, next_word: Optional[str]) -> str:
    c = _core(word)
    nxt = next_word or ''
    if next_word is not None and nxt and not nxt[:1].isspace():
        return INSIDE
    if not c:
        return WORD
    if c.endswith('…') or c.endswith('...'):
        return SENT_WEAK if _starts_lower(nxt) else SENT
    last = c[-1]
    if last in '?!':
        return SENT_WEAK if _starts_lower(nxt) else SENT
    if last == '.':
        body = c[:-1]
        low = body.lower().lstrip('"\'“‘«(')
        if low in _ABBREV_IT_AMBIG:
            return ABBREV if _starts_lower(nxt) or _starts_digit(nxt) else SENT_WEAK
        if _INITIAL.match(c.lstrip('"\'“‘«(')):
            # lettera maiuscola + punto: nei dati 3 casi su 3 sono FINE FRASE
            # ("un piano B. Sai che", "un piano A. È tornata!", "con la O. A me"),
            # nessuna iniziale di nome staccata (J.K. e' un token attaccato)
            # -> fine frase incerta, non abbreviazione come in inglese.
            # Controllata PRIMA di _ABBREV_IT: "N." maiuscolo e' una lettera, non "n." (numero)
            return SENT_WEAK
        if low in _ABBREV_IT:
            return ABBREV
        # niente regola "No." + cifra (inglese): in italiano "No. 3 volte" e' fine frase
        if _ACRONYM.match(c.lstrip('"\'“‘«(')):
            return SENT_WEAK if (nxt.strip()[:1].isupper() and not _starts_lower(nxt)) else ABBREV
        return SENT_WEAK if _starts_lower(nxt) else SENT
    if last in ';:':
        return CLAUSE
    if last in ',-–—':
        return COMMA
    b = _bare(c)
    # diversamente dall'inglese la parola funzionale PRIMA prevale sulla
    # congiunzione DOPO ("il motivo per | cui", "il genere di | cui"), e le
    # locuzioni congiuntive restano unite ("tutto quello | che" x37 nei dati,
    # "solo | che", "prima | che loro le presentino", "Solo | quando")
    if b in _FUNCTION_IT:
        return FUNC
    if _bare(nxt) in _CONJ_IT:
        return FUNC if b in _CONJ_GLUE_IT else CONJ
    return WORD


def _norm_lang(lang) -> str:
    return str(lang or 'en').strip().lower()[:2]


SUPPORTED_LANGS = ('en', 'it')


def boundary_type(word: str, next_word: Optional[str], lang: str = 'en') -> str:
    """Tipo del confine DOPO `word` (seguita da `next_word`)."""
    if lang != 'en' and _norm_lang(lang) == 'it':
        return _boundary_type_it(word, next_word)
    c = _core(word)
    nxt = next_word or ''
    if next_word is not None and nxt and not nxt[:1].isspace():
        # token attaccato alla parola precedente ("post" + "-traumatic"):
        # tagliare qui spezzerebbe la parola (e il formatter aggiungerebbe
        # uno spazio). Lo split originale lo fa; qui solo se inevitabile.
        return INSIDE
    if not c:
        return WORD
    if c.endswith('…') or c.endswith('...'):
        return SENT_WEAK if _starts_lower(nxt) else SENT
    last = c[-1]
    if last in '?!':
        return SENT_WEAK if _starts_lower(nxt) else SENT
    if last == '.':
        body = c[:-1]
        low = body.lower().lstrip('"\'“‘«(')
        if low in _ABBREV or _INITIAL.match(c.lstrip('"\'“‘«(')):
            return ABBREV
        if low == 'no' and _starts_digit(nxt):
            return ABBREV
        if _ACRONYM.match(c.lstrip('"\'“‘«(')):
            # "U.S." a fine frase o dentro la frase: decide la maiuscola dopo
            return SENT_WEAK if (nxt.strip()[:1].isupper() and not _starts_lower(nxt)) else ABBREV
        return SENT_WEAK if _starts_lower(nxt) else SENT
    if last in ';:':
        return CLAUSE
    if last in ',-–—':
        return COMMA
    if _bare(nxt) in _CONJ:
        return CONJ
    b = _bare(c)
    if b in _FUNCTION or re.search(r"'(m|re|ll|ve|d|s)$", b or ''):
        return FUNC
    return WORD


def wrap_lines(text: str, cpl: int = 42) -> int:
    """Numero di righe prodotte da SubtitleFormatter._wrap_cpl (stessa logica)."""
    if len(text) <= cpl:
        return 1
    words = text.split()
    if len(words) == 1:
        return 1
    mid = len(text) // 2
    best_i, best_dist = 1, float('inf')
    acc = 0
    for i, w in enumerate(words[:-1]):
        acc += len(w) + (1 if i > 0 else 0)
        dist = abs(acc - mid)
        if dist < best_dist:
            best_dist, best_i = dist, i + 1
    return (wrap_lines(' '.join(words[:best_i]), cpl)
            + wrap_lines(' '.join(words[best_i:]), cpl))


def _piece(words: List[dict]) -> dict:
    return {
        'start': words[0]['start'],
        'end': words[-1]['end'],
        'text': ''.join(w['word'] for w in words).strip(),
        'words': list(words),
    }


def sentence_aware_split(segment: dict, max_chars: int = 80, max_duration: float = 6.0,
                         params: Optional[Dict[str, float]] = None,
                         lang: str = 'en') -> Optional[List[dict]]:
    """Stessa interfaccia e formato di FasterWhisperEngine._split_segment_by_words:
    lista di dict {start, end, text, words}. Ritorna None se non sa decidere
    (il chiamante usa allora lo split originale). `lang`: 'en' (default,
    regole inglesi) o 'it' (regole italiane; anche codici a 3 lettere, si
    guardano le prime 2); per ogni altra lingua None (nessuna regola misurata)."""
    lang = _norm_lang(lang)
    if lang not in SUPPORTED_LANGS:
        return None
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    P['max_chars'] = max_chars
    P['max_duration'] = max_duration

    words = segment.get('words', [])
    text = segment['text']
    duration = segment['end'] - segment['start']

    # Segmento gia' corto o senza parole: identico allo split originale
    if not words or (len(text) <= max_chars and duration <= max_duration):
        return [{'start': segment['start'], 'end': segment['end'],
                 'text': text, 'words': words}]

    n = len(words)
    if not ''.join(w['word'] for w in words).strip():
        return None
    # lingue senza spazi (zh/ja/th/lo/my/yue: faster-whisper divide per
    # carattere, parole senza spazio iniziale): '。！？' non sono riconosciuti
    # e l'intero segmento sarebbe una sola "parola" -> resta lo split
    # originale. La guardia richiede anche la SCRITTURA: un segmento latino con
    # molti token attaccati ("Boop-a-doop-a" x5) va gestito qui, non rimandato
    # allo split originale (che taglierebbe dentro le parole).
    if (sum(1 for w in words[1:] if not w['word'][:1].isspace()) * 2 > max(1, n - 1)
            and _NOSPACE_SCRIPT.search(''.join(w['word'] for w in words))):
        return None

    # Unita' = parole intere: un token con spazio iniziale (o il primo) piu' i
    # token seguenti senza spazio ("post" + "-traumatic", "Boop" + "-a" +
    # "-doop" + "-a."). Si taglia SOLO fra unita': mai dentro una parola,
    # nemmeno se un'unita' da sola supera i limiti duri (eccezione "pezzo di
    # una sola unita'").
    # Eccezione: un token attaccato preceduto da un salto >= glitch_gap_s NON appartiene alla stessa
    # parola (nessuna parola contiene 9 s di silenzio: e' un timestamp errato di Whisper, es. "Cos" a
    # 1423 s e "'e'" a 1529 s). Senza questa eccezione l'unita' da 106 s trascinava l'intero resto del
    # segmento in un blocco mostrato 100 s in anticipo.
    _gg = P['glitch_gap_s']
    ustart = [0] + [k for k in range(1, n)
                    if words[k]['word'][:1].isspace()
                    or float(words[k]['start']) - float(words[k - 1]['end']) >= _gg]
    m = len(ustart)

    def tok(u: int) -> int:
        """Indice del primo token dell'unita' u (u == m -> n)."""
        return ustart[u] if u < m else n

    # Valvola: una "parola" oltre 2 x hard_max_chars non e' una parola ma un
    # loop di allucinazione ("-ha-ha-ha..." x1000): terrebbe un blocco da
    # migliaia di caratteri -> resta lo split originale (comportamento di prima)
    for u in range(m):
        if len(''.join(w['word'] for w in words[tok(u):tok(u + 1)]).strip()) > 2 * P['hard_max_chars']:
            return None

    # confini: btype[u] / bcost[u] = confine DOPO l'unita' u (u < m-1)
    btype: List[str] = []
    bcost: List[float] = []
    cost_of = {SENT: P['cost_sentence'], SENT_WEAK: P['cost_sentence_weak'],
               CLAUSE: P['cost_clause'], COMMA: P['cost_comma'], CONJ: P['cost_before_conj'],
               WORD: P['cost_word'], FUNC: P['cost_after_function'], ABBREV: P['cost_abbrev'],
               INSIDE: P['cost_inside_word']}
    for u in range(m - 1):
        k = tok(u + 1) - 1              # ultimo token dell'unita' u
        t = boundary_type(words[k]['word'], words[k + 1]['word'], lang)
        c = cost_of[t]
        gap = float(words[k + 1]['start']) - float(words[k]['end'])
        if gap >= P['pause_s'] and t not in (ABBREV, INSIDE):
            c -= P['pause_bonus']
            if t not in STRONG_TYPES:
                c = max(c, 0.5)
        btype.append(t)
        bcost.append(c)

    # DP sulle unita': pezzo = unita' i..j-1 = token tok(i)..tok(j)-1
    INF = float('inf')
    best = [INF] * (m + 1)
    back = [-1] * (m + 1)
    best[0] = 0.0
    for j in range(1, m + 1):
        acc = ''
        t_end = tok(j) - 1
        for i in range(j - 1, -1, -1):
            acc = ''.join(w['word'] for w in words[tok(i):tok(i + 1)]) + acc
            ptxt = acc.strip()
            L = len(ptxt)
            D = float(words[t_end]['end']) - float(words[tok(i)]['start'])
            single = (i == j - 1)
            if not single and (L > P['hard_max_chars'] or D > P['hard_max_duration']
                               or j - i > 200):
                break           # vincoli monotoni: allargando a sinistra peggiora
            if best[i] == INF:
                continue
            c = P['piece_cost']
            c += P['over_chars_w'] * max(0, L - P['max_chars'])
            c += P['over_dur_w'] * max(0.0, D - P['max_duration'])
            if L > P['cpl'] and wrap_lines(ptxt, int(P['cpl'])) > 2:
                c += P['wrap3_penalty']
            left_mid = i > 0 and btype[i - 1] not in STRONG_TYPES
            right_mid = j < m and btype[j - 1] not in STRONG_TYPES
            if (left_mid or right_mid) and L < P['short_frag_chars']:
                c += P['short_frag_w'] * (P['short_frag_chars'] - L) / P['short_frag_chars']
            if j < m:
                c += bcost[j - 1]
            tot = best[i] + c
            if tot < best[j]:
                best[j] = tot
                back[j] = i
    if best[m] == INF:
        return None

    cuts = []
    j = m
    while j > 0:
        i = back[j]
        if i < 0:
            return None
        cuts.append((i, j))
        j = i
    cuts.reverse()
    pieces = [_piece(words[tok(i):tok(j)]) for i, j in cuts]

    # Coda corta: come oggi (<4 parole, pausa <= 0,8 s, frase precedente non
    # conclusa) ma solo se l'unione rispetta i vincoli duri. Parole = unita'.
    if len(pieces) >= 2 and cuts[-1][1] - cuts[-1][0] <= P['tail_max_words']:
        tail, prev = pieces[-1], pieces[-2]
        k_prev = cuts[-2][1] - 1
        gap = float(tail['words'][0]['start']) - float(prev['words'][-1]['end'])
        if gap <= P['tail_max_gap'] and btype[k_prev] not in STRONG_TYPES:
            merged = _piece(prev['words'] + tail['words'])
            if (len(merged['text']) <= P['hard_max_chars']
                    and merged['end'] - merged['start'] <= P['hard_max_duration']):
                pieces[-2:] = [merged]

    pieces = [p for p in pieces if p['text']]
    return pieces or None


def validate_split(segment: dict, pieces) -> bool:
    """True se `pieces` e' un risultato accettabile per `segment`: lista non
    vuota di dict {start,end,text,words}, parole identiche (stessi oggetti,
    stesso ordine, nessuna persa/duplicata), testo = concatenazione delle
    parole, tempi coerenti e non decrescenti."""
    try:
        if not isinstance(pieces, list) or not pieces:
            return False
        flat = []
        prev_start = None
        for p in pieces:
            if not isinstance(p, dict) or not {'start', 'end', 'text', 'words'} <= set(p):
                return False
            ws = p['words']
            if not ws or not p['text']:
                return False
            if p['text'] != ''.join(w['word'] for w in ws).strip():
                return False
            if p['start'] != ws[0]['start'] or p['end'] != ws[-1]['end']:
                return False
            if p['end'] < p['start']:
                return False
            if prev_start is not None and p['start'] < prev_start:
                return False
            prev_start = p['start']
            flat.extend(ws)
        src = segment.get('words') or []
        return len(flat) == len(src) and all(a is b for a, b in zip(flat, src))
    except Exception:
        return False
