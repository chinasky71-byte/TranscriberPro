"""
Misura dei TAGLI NUDI (28/09/2026, richiesta dell'utente per il tedesco: "tagli senza punteggiatura ne' congiunzione").

Diversamente dalla metrica midcut (split_eval/midcut.py) NON dipende dalla minuscola del blocco successivo, che in
tedesco non funziona (i sostantivi sono maiuscoli: "um zwoelf | Uhr im Seehaus" sfuggirebbe). Una coppia di blocchi
consecutivi (a, b) e' un taglio nudo se:
  - la pausa fra a e b e' < MAX_GAP_S (stessa soglia della metrica midcut);
  - nessuno dei due e' musica/descrizione sonora;
  - a (ripulito come in midcut: markup, etichette SDH) NON finisce con punteggiatura: , ; : . ? ! … - – —
    (le virgolette/parentesi di chiusura finali si ignorano);
  - b NON apre con un trattino (cambio parlante);
  - la prima parola di b NON e' una congiunzione della lista CONJ[lang] qui sotto.
Le liste sono FISSE e indipendenti dalle regole di core/whisper_sentence_split.py (congelate il 28/09/2026 PRIMA di
guardare i dati di taratura tedeschi): se si tarano le regole, la misura non si sposta con loro.
Quota = tagli nudi / blocchi.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List

import common as C

CONJ = {
    'de': frozenset("""
        und oder aber denn sondern sowie sowohl weder noch doch
        weil dass daß ob wenn als obwohl obgleich damit sodass sofern falls während bevor ehe nachdem seit seitdem
        bis sobald solange indem wobei wie wo
    """.split()),
    'fr': frozenset("""
        et ou mais donc car ni or puis alors que qu' qui dont où quand lorsque lorsqu' puisque puisqu' comme si s'
        parce quoique tandis afin sinon
    """.split()),
}
_END_PUNCT = tuple(',;:.?!…-–—')
_CLOSE = '"\'”’“‘»«)]}'
_LEAD = re.compile(r'^[\s"\'«»“”‘’„‚(\[¿¡…\.]+')
_DASH = re.compile(r'^\s*[-–—]')
_WORD = re.compile(r"[^\W\d_]+(?:['’])?", re.UNICODE)


def _first_word(text: str) -> str:
    s = _LEAD.sub('', text or '')
    m = _WORD.match(s)
    return m.group(0).replace('’', "'").lower() if m else ''


def naked_flags(blocks: List[Dict], lang: str) -> List[bool]:
    MC = C.midcut_mod()
    conj = CONJ[lang]
    out = []
    for i, a in enumerate(blocks):
        if i + 1 >= len(blocks):
            out.append(False)
            continue
        b = blocks[i + 1]
        gap = float(b.get('start', b.get('s'))) - float(a.get('end', a.get('e')))
        ta, tb = str(a.get('text', '')), str(b.get('text', ''))
        if gap >= MC.MAX_GAP_S or MC.is_music(ta) or MC.is_music(tb):
            out.append(False)
            continue
        la, lb = MC.clean_lines(ta), MC.clean_lines(tb)
        if not la or not lb:
            out.append(False)
            continue
        end = ' '.join(la).rstrip().rstrip(_CLOSE).rstrip()
        if not end or end.endswith(_END_PUNCT) or _DASH.match(lb[0]):
            out.append(False)
            continue
        fw = _first_word(' '.join(lb))
        out.append(bool(fw) and fw not in conj and fw.rstrip("'") not in conj)
    return out


def naked_stats(blocks: Iterable[Dict], lang: str) -> Dict:
    bl = list(blocks)
    f = naked_flags(bl, lang)
    n = sum(f)
    return {'n_blocks': len(bl), 'n_naked': n, 'rate': n / max(1, len(bl))}
