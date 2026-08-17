"""
Post-processing deterministico dei sottotitoli italiani
=======================================================
Tutto ciò che si può garantire in codice non va chiesto al modello: costa
zero, non sbaglia e non consuma budget di prompt. Qui stanno le regole della
guida di stile italiana Netflix che sono meccaniche, più il re-wrap delle
righe.

Il re-wrap colma un buco reale della pipeline: `SubtitleFormatter` viene
invocato in `core/pipeline.py` allo STEP 4.5, cioè PRIMA della traduzione.
Dopo la traduzione nessuno ricontrolla le righe, e l'italiano è mediamente
il 15-20% più lungo dell'inglese — sulla baseline NLLB fine-tuned misurata su
300 blocchi, il 59% delle righe superava i 42 caratteri.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

CPL_MAX = 42
MAX_LINES = 2
ELLIPSIS = "…"

# Frazione della lunghezza totale a cui puntare per il taglio della prima riga.
# La guida Netflix chiede la "piramide": riga bassa più lunga della riga alta.
_SPLIT_TARGET = 0.45

_NUMBER_WORDS = {
    1: "uno", 2: "due", 3: "tre", 4: "quattro", 5: "cinque",
    6: "sei", 7: "sette", 8: "otto", 9: "nove", 10: "dieci",
}

_DASH_PREFIX = re.compile(r"^\s*[-–—]\s*")

# Alias pubblico: serve anche al translator, per spezzare e ricomporre i
# blocchi di dialogo usando lo stesso identico criterio del wrapping.
DASH_PREFIX = _DASH_PREFIX


# --------------------------------------------------------------------------
# Punteggiatura
# --------------------------------------------------------------------------
def normalize_punctuation(text: str) -> str:
    """Ellissi a carattere singolo, niente punteggiatura doppia, spaziatura."""
    # Tre punti (o più) -> carattere ellissi U+2026
    text = re.sub(r"\.{3,}", ELLIPSIS, text)
    text = re.sub(rf"{ELLIPSIS}\s*\.+", ELLIPSIS, text)

    # Punteggiatura doppia: l'ellissi non si combina con altri segni.
    text = re.sub(rf"{ELLIPSIS}\s*([!?,.;:])", ELLIPSIS, text)
    text = re.sub(rf"([!?,.;:])\s*{ELLIPSIS}", ELLIPSIS, text)
    text = re.sub(r"([!?])[!?]+", r"\1", text)
    text = re.sub(r"\.\s*([,;:])", r"\1", text)

    # Spazi prima della punteggiatura e spazi multipli.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)

    # Virgolette tipografiche senza spazi interni.
    text = re.sub(r"«\s+", "«", text)
    text = re.sub(r"\s+»", "»", text)

    return text.strip()


def strip_continuation_marks(blocks: List[str]) -> List[str]:
    """Toglie i puntini di continuazione tra blocchi consecutivi.

    Regola Netflix esplicita: quando una frase prosegue nel sottotitolo
    successivo NON si usano né ellissi né trattini. È l'errore che quasi tutti
    i tool automatici commettono, perché i puntini arrivano dall'originale o
    li aggiunge il modello.

    La continuazione si riconosce dal fatto che il blocco seguente attacca in
    minuscola: se iniziasse per maiuscola sarebbe una frase nuova, e allora
    l'ellissi è legittima (pausa o interruzione).
    """
    out = list(blocks)
    for i in range(len(out) - 1):
        cur, nxt = out[i], out[i + 1]
        if not cur or not nxt:
            continue
        if not cur.rstrip().endswith(ELLIPSIS):
            continue
        # Il blocco seguente può aprire a sua volta con trattino ed ellissi:
        # vanno tolti entrambi prima di guardare l'iniziale.
        head = _DASH_PREFIX.sub("", nxt.lstrip().split("\n")[0])
        head = head.lstrip(ELLIPSIS).lstrip()
        if head[:1].islower():
            out[i] = cur.rstrip()[:-1].rstrip()
            # Anche il blocco successivo può aprire con l'ellissi.
            out[i + 1] = re.sub(rf"^(\s*[-–—]?\s*){ELLIPSIS}\s*",
                                r"\1", nxt)
    return out


def spell_small_numbers(text: str) -> str:
    """Numeri da 1 a 10 in lettere.

    Applicata con prudenza: si salta tutto ciò che sembra un'ora, una data,
    una percentuale, un decimale o un numero con unità di misura, dove la
    cifra è la forma corretta e sostituirla cambierebbe il senso.
    """
    def repl(m: re.Match) -> str:
        value = int(m.group(0))
        before = text[max(0, m.start() - 2):m.start()]
        after = text[m.end():m.end() + 2]
        if any(c in before for c in ":/.,-%") or any(
                c in after for c in ":/.,-%°"):
            return m.group(0)
        if re.match(r"\s*(?:ore|anni|km|kg|m|cm|mm|%|euro|\$)", after):
            return m.group(0)
        return _NUMBER_WORDS[value]

    return re.sub(r"(?<!\d)([1-9]|10)(?!\d)", repl, text)


# --------------------------------------------------------------------------
# Divisione delle righe
# --------------------------------------------------------------------------
def wrap_line(text: str, cpl: int = CPL_MAX) -> List[str]:
    """Divide una riga in al massimo due, con la riga bassa più lunga.

    Preferisce sempre una riga sola quando ci sta: la guida di stile lo chiede
    esplicitamente, ed è anche più leggibile.
    """
    text = text.strip()
    if len(text) <= cpl:
        return [text]

    words = text.split()
    if len(words) < 2:
        return [text]

    target = len(text) * _SPLIT_TARGET
    best: Optional[Tuple[float, int]] = None

    acc = 0
    for i, word in enumerate(words[:-1]):
        acc += len(word) + (1 if i > 0 else 0)
        first, second = acc, len(text) - acc - 1
        if first > cpl or second > cpl:
            continue
        # Penalizza le righe con una sola parola isolata in alto.
        penalty = 12.0 if i == 0 else 0.0
        # Penalizza la piramide rovesciata (riga alta più lunga della bassa).
        if first > second:
            penalty += (first - second) * 0.6
        score = abs(acc - target) + penalty
        if best is None or score < best[0]:
            best = (score, i + 1)

    if best is None:
        # Nessun taglio rispetta il limite su entrambe le righe: taglia
        # comunque a metà, il blocco è troppo denso e il vincolo è già perso.
        mid = len(words) // 2
        return [" ".join(words[:mid]), " ".join(words[mid:])]

    cut = best[1]
    return [" ".join(words[:cut]), " ".join(words[cut:])]


# Un secondo trattino DENTRO una riga che ne ha già uno in testa: è una
# battuta di un altro parlante finita sulla riga sbagliata. Il seguito deve
# aprire in maiuscola o con una virgoletta — così un inciso ("- Sì - disse
# lui") o un trattino di lista non vengono scambiati per un cambio di voce.
_INNER_DASH = re.compile(r"\s+[-–—]\s+(?=[«\"'A-ZÀ-ÖØ-Þ])")


def _split_flattened_dialogue(line: str) -> List[str]:
    """Rimette una battuta per riga quando due parlanti sono finiti su una.

    MISURATO (mt_eval/validate_pipeline_path.py): il ramo NLLB consegna certi
    blocchi di dialogo già appiattiti — "- Un posto in questo mondo. - Voglio
    diventare un killer a pagamento." su una riga sola. Non è colpa della
    rifinitura, che li riceve così, ma è qui che si possono rimettere a posto:
    dividere sul trattino interno costa nulla e recupera l'unica regola di
    forma che conta davvero in un dialogo, cioè un parlante per riga.
    """
    if not _DASH_PREFIX.match(line):
        return [line]
    pezzi = _INNER_DASH.split(line)
    if len(pezzi) < 2:
        return [line]
    fuori = [pezzi[0].strip()]
    fuori += [f"- {p.strip()}" for p in pezzi[1:] if p.strip()]
    return fuori


def wrap_block(text: str) -> str:
    """Applica il wrapping a un blocco, preservando i dialoghi.

    Un blocco di dialogo ha una battuta per riga con il trattino: quelle righe
    non si possono unire né ridividere fra loro, al massimo si accorcia il
    testo di ciascuna.
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return ""

    # Prima di decidere se è un dialogo, si recuperano le battute appiattite:
    # altrimenti una riga con due parlanti passa per monologo e viene
    # rimpaginata a metà di una frase, col trattino del secondo che resta in
    # fondo alla prima riga.
    recuperate: List[str] = []
    for l in lines:
        recuperate.extend(_split_flattened_dialogue(l))
    lines = recuperate

    is_dialogue = len(lines) > 1 and any(_DASH_PREFIX.match(l) for l in lines)

    if is_dialogue:
        # Una riga per parlante: si tiene la struttura anche se sfora, perché
        # spezzarla assegnerebbe la battuta al parlante sbagliato.
        return "\n".join(l.strip() for l in lines)

    joined = " ".join(l.strip() for l in lines)
    wrapped = wrap_line(joined)
    return "\n".join(wrapped[:MAX_LINES])


# --------------------------------------------------------------------------
# Ingresso unico
# --------------------------------------------------------------------------
def is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and not any(c.islower() for c in letters)


def preserve_screen_text(text: str, source: str) -> str:
    """Se l'originale è testo a schermo (tutto maiuscolo), lo è anche la resa.

    Regola Netflix per i forced narrative: cartelli, insegne e messaggi vanno
    in maiuscolo.

    ATTENZIONE — la regola vale solo se il maiuscolo è ECCEZIONALE nel file.
    Molti sottotitoli, in particolare quelli per non udenti, sono scritti
    interamente in maiuscolo per convenzione: lì il maiuscolo non segnala
    nulla, e propagarlo produce un sottotitolo italiano tutto maiuscolo che è
    semplicemente sbagliato. Il chiamante decide passando `apply`, che sa
    quanto maiuscolo c'è nell'intero file.
    """
    if not is_all_caps(source):
        return text
    return text.upper()


def process(
    blocks: Dict[int, str],
    order: Optional[Sequence[int]] = None,
    spell_numbers: bool = False,
    sources: Optional[Dict[int, str]] = None,
) -> Dict[int, str]:
    """Applica tutte le regole a un file intero.

    `order` serve alla regola di continuazione, che guarda il blocco seguente:
    va passato l'ordine temporale reale dei sottotitoli.

    `spell_numbers` è disattivato di default: la regola dei numeri in lettere
    è quella con più eccezioni e il guadagno di stile non vale il rischio di
    trasformare un orario o un numero civico.
    """
    ids = list(order) if order is not None else sorted(blocks)

    texts = [normalize_punctuation(blocks.get(i, "")) for i in ids]
    texts = strip_continuation_marks(texts)

    # Il maiuscolo va propagato solo se nel file è un'eccezione. Sopra un
    # quarto dei blocchi è la convenzione tipografica del sottotitolo di
    # partenza, non un cartello da rendere in maiuscolo.
    caps_rule = False
    if sources:
        caps = sum(1 for i in ids if is_all_caps(sources.get(i, "")))
        caps_rule = 0 < caps <= max(1, len(ids) // 4)

    out: Dict[int, str] = {}
    for idx, text in zip(ids, texts):
        if spell_numbers:
            text = spell_small_numbers(text)
        if caps_rule and sources and idx in sources:
            text = preserve_screen_text(text, sources[idx])
        out[idx] = wrap_block(text)
    return out


def stats(blocks: Dict[int, str],
          durations: Optional[Dict[int, float]] = None) -> Dict[str, float]:
    """Conformità misurabile: la diagnostica oggettiva della pipeline."""
    n = len(blocks) or 1
    over_cpl = sum(
        1 for t in blocks.values()
        if any(len(l) > CPL_MAX for l in t.split("\n"))
    )
    over_lines = sum(1 for t in blocks.values()
                     if len(t.split("\n")) > MAX_LINES)
    over_cps = 0
    if durations:
        for idx, text in blocks.items():
            dur = durations.get(idx, 0)
            if dur > 0 and len(text.replace("\n", " ")) / dur > 17.0:
                over_cps += 1
    return {
        "blocchi": len(blocks),
        "over_cpl_pct": over_cpl * 100.0 / n,
        "over_lines_pct": over_lines * 100.0 / n,
        "over_cps_pct": over_cps * 100.0 / n,
    }
