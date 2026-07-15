# -*- coding: utf-8 -*-
"""
Gender Line Selector — Fase 2 del redesign Gender Corrector.
File: core/gender_line_selector.py

Seleziona le righe italiane che contengono una forma di GENERE in PRIMA
PERSONA (participio/aggettivo che concorda col PARLANTE): sono le uniche
righe che il nuovo corrector deve riscrivere, usando il genere del parlante
fornito dalla Speaker Gender Map (core/speaker_gender.py).

Filtro morfosintattico spaCy (it_core_news_lg), validato su Veronica Mars
S01 (268 candidati, 32/32 unit test, precisione confermata da spot-check
umano e da cross-check con il genere audio):

  ACCETTA un token g se:
    - participio (VerbForm=Part) o aggettivo (ADJ), SINGOLARE, con Gender;
    - desinenza coerente col genere (Fem→-a, Masc→-o): uccide i mis-tag;
    - legato SINTATTICAMENTE a un verbo di 1ª persona singolare
      (aux/copula figlio, head finito, o "sono"+predicato singolare, o
      soggetto esplicito "io").

  SCARTA:
    - participi retti da AVERE in qualsiasi forma (invariabili: "ho detto",
      "potrei aver detto", "ricordo di averlo fatto", "Avrei voluto");
    - modificatori/argomenti nominali (amod, nummod, obj, ...): concordano
      col nome, non col parlante ("una CATTIVA compagnia", "l'orso VINTO");
    - 2ª/3ª persona (verbo reggente P2/P3, soggetto "tu");
    - "stesso/a", locuzioni avverbiali (token dopo ADP), coordinazioni
      (dep conj), mis-tag lessicali ricorrenti (ciao/vero/so/...).

Dipendenze: SOLO spaCy (nessun Qt, nessun torch). Se spaCy o il modello
non sono disponibili, `available()` è False e `select()` ritorna sempre
None: il chiamante salta la correzione (fail-safe: nessuna riscrittura).

NOTA deploy: spaCy NON è installato nel venv principale dell'app (per non
perturbare ctranslate2/setuptools). In produzione questo modulo gira nel
subprocess dello STEP 6.5 con un ambiente che include spaCy, oppure spaCy
andrà aggiunto al venv app previa verifica di compatibilità.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

SPACY_MODEL = 'it_core_news_lg'

_NLP = None
_SPACY_TRIED = False

# Forme flesse di "avere": il lemmatizer spaCy fallisce su forme
# capitalizzate ("Avrei"→"Avrei") e clitiche ("averlo"→"avere lo")
_AVERE_FORMS = {
    'ho', 'hai', 'ha', 'abbiamo', 'avete', 'hanno',
    'avevo', 'avevi', 'aveva', 'avevamo', 'avevate', 'avevano',
    'ebbi', 'avesti', 'ebbe', 'avemmo', 'aveste', 'ebbero',
    'avrò', 'avrai', 'avrà', 'avremo', 'avrete', 'avranno',
    'avrei', 'avresti', 'avrebbe', 'avremmo', 'avreste', 'avrebbero',
    'abbia', 'abbiate', 'abbiano', 'avessi', 'avesse', 'avessimo',
    'avessero', 'avendo', 'aver', 'avere',
}

# Mis-tag lessicali ricorrenti di spaCy (interiezioni/particelle con
# desinenza in -o/-a che vengono taggate ADJ/Part con Gender)
_STOPLIST = ('ciao', 'vero', 'so', 'ecco', 'bene', 'no')

# Dipendenze nominali: il token concorda col nome, non col parlante
_NOMINAL_DEPS = ('amod', 'nummod', 'det', 'appos', 'nmod', 'obl',
                 'obj', 'iobj', 'nsubj', 'fixed', 'flat', 'compound')


@dataclass
class LineCandidate:
    """Riga selezionata: forma marcata trovata e genere che esprime."""
    marker: str          # la parola marcata (es. "stanca")
    gender: str          # 'F' | 'M' — genere ESPRESSO dal testo attuale


def _get_nlp():
    global _NLP, _SPACY_TRIED
    if not _SPACY_TRIED:
        _SPACY_TRIED = True
        try:
            import spacy
            _NLP = spacy.load(SPACY_MODEL)
        except Exception as e:
            logger.warning(f"spaCy/{SPACY_MODEL} non disponibile: {e} — "
                           "selettore genere disattivato (fail-safe)")
            _NLP = None
    return _NLP


def available() -> bool:
    """True se spaCy e il modello italiano sono caricabili."""
    return _get_nlp() is not None


def _is_avere(tok) -> bool:
    """True se il token è una forma di 'avere' (anche clitica/capitalizzata)."""
    lem = tok.lemma_.lower()
    if lem == 'avere' or lem.startswith('avere '):
        return True
    txt = tok.text.lower()
    return txt in _AVERE_FORMS or txt.startswith('aver')


def select(ita_text: str) -> Optional[LineCandidate]:
    """Analizza una riga italiana e ritorna il candidato di 1ª persona
    con genere, o None se la riga non va toccata."""
    marker, gender = firstperson_gender(ita_text)
    if marker and gender:
        return LineCandidate(marker=marker, gender=gender)
    return None


def firstperson_gender(ita: str) -> Tuple[Optional[str], Optional[str]]:
    """Ritorna (marker, 'F'|'M') se la riga contiene una forma di genere
    plausibilmente riferita al parlante (1ª persona), altrimenti (None, None).
    """
    hits = speaker_gendered_tokens(ita)
    if hits:
        return hits[0]
    return None, None


def speaker_gendered_tokens(ita: str) -> list:
    """Forme di genere riferite al PARLANTE (1ª persona). Lista di
    (testo_token, 'F'|'M') in ordine, incluse catene coordinate."""
    return _gendered_tokens(ita, person='1')


def addressee_gendered_tokens(ita: str) -> list:
    """Forme di genere riferite all'INTERLOCUTORE (2ª persona singolare:
    "sei stanca", "eri andata"). Stesse esclusioni della 1ª persona."""
    return _gendered_tokens(ita, person='2')


# copule/ausiliari di 2ª persona che spaCy a volte mis-tagga
# ("Sei" a inizio frase → NUM "sei")
_P2_COPULA = {'sei', 'eri', 'sarai', 'saresti', 'fosti', 'stai', 'stavi', 'starai'}


def _gendered_tokens(ita: str, person: str) -> list:
    nlp = _get_nlp()
    if nlp is None:
        return []
    doc = nlp(ita)

    selected = []          # token spaCy accettati
    for g in doc:
        # candidato: participio o aggettivo SINGOLARE marcato al genere
        if g.morph.get('Number') != ['Sing']:
            continue
        if g.morph.get('Gender') not in (['Fem'], ['Masc']):
            continue
        if not (g.pos_ == 'ADJ' or g.morph.get('VerbForm') == ['Part']):
            continue
        # la desinenza deve combaciare col genere (esclude mis-tag
        # tipo "potresti" e forme invariabili non misurabili)
        low = g.text.lower()
        if g.morph.get('Gender') == ['Fem'] and not low.endswith('a'):
            continue
        if g.morph.get('Gender') == ['Masc'] and not low.endswith('o'):
            continue
        # "stesso/stessa" concorda col nome, mai col parlante
        if g.lemma_.lower() == 'stesso':
            continue
        # mis-tag lessicali ricorrenti (interiezioni/particelle)
        if low in _STOPLIST:
            continue
        # modificatore/argomento NOMINALE ("una CATTIVA compagnia",
        # "il mio orso VINTO"): concorda col nome, non col parlante
        if g.dep_ in _NOMINAL_DEPS:
            continue
        # participio retto da AVERE in QUALSIASI forma — finita
        # ("Avrò dimenticato"), infinita ("potrei aver detto"), con clitico
        # ("ricordo di averlo fatto", lemma spaCy "avere lo"), o come
        # fratello aux del participio modale ("Avrei voluto"). Il participio
        # con avere è invariabile (o concorda col clitico oggetto), mai
        # col parlante.
        if g.morph.get('VerbForm') == ['Part']:
            linked = [c for c in g.children if c.dep_.startswith('aux')
                      or c.dep_ == 'cop']
            if g.pos_ == 'AUX' or g.dep_.startswith('aux'):
                linked += [c for c in g.head.children
                           if c is not g and c.dep_.startswith('aux')]
            if any(_is_avere(c) for c in linked):
                continue
        # locuzioni avverbiali ("di nascosto", "all'improvviso"):
        # token retto/preceduto direttamente da preposizione
        if g.i > 0 and doc[g.i - 1].pos_ == 'ADP':
            continue

        # verbi FINITI legati SINTATTICAMENTE a g (l'ausiliare/copula che
        # regge g, non un verbo di un'altra proposizione nella stessa cue).
        # dep 'conj' escluso: un verbo COORDINATO ("...fantastica e lo
        # apprezzo") appartiene a un'altra proposizione.
        fins = [c for c in g.children
                if c.pos_ in ('AUX', 'VERB') and c.morph.get('VerbForm') == ['Fin']
                and c.dep_ != 'conj']
        h = g.head
        if h is not g and g.dep_ != 'conj':
            if h.pos_ in ('AUX', 'VERB') and h.morph.get('VerbForm') == ['Fin']:
                fins.append(h)
            for c in h.children:
                if c.pos_ == 'AUX' and c.morph.get('VerbForm') == ['Fin']:
                    fins.append(c)
        # anti-FP: locuzioni congiuntive ("dato che", "visto che")
        if (g.text.lower() in ('dato', 'visto', 'detto')
                and g.i + 1 < len(doc)
                and doc[g.i + 1].text.lower() == 'che'):
            continue
        # copule P2 mis-taggate (es. "Sei" → NUM): recuperale come anchor
        # SOLO nella stessa proposizione di g (figli diretti, o head se g
        # è complemento predicativo) — mai da proposizioni sorelle
        # ("la polizia è brava, perché non SEI lì" non deve legare).
        _local = list(g.children)
        if g.dep_ in ('xcomp', 'ccomp', 'advcl', 'acl', 'ROOT', 'root'):
            _local.append(g.head)
        p2_near = [t for t in _local
                   if t is not g and t.text.lower() in _P2_COPULA]
        if not fins and not p2_near:
            continue

        # participio con ausiliare AVERE finito (ridondante ma innocuo)
        if g.morph.get('VerbForm') == ['Part']:
            if any(_is_avere(f) for f in fins if f.pos_ == 'AUX'):
                continue

        persons = set()
        has_sono = False
        has_p2cop = bool(p2_near)
        for f in fins:
            persons.update(f.morph.get('Person'))
            low_f = f.text.lower()
            if low_f == 'sono':
                has_sono = True
            if low_f in _P2_COPULA:
                has_p2cop = True
        # soggetto esplicito "io"/"tu" tra i figli del verbo reggente
        # (e del predicato stesso: "fossi stato tu" aggancia "tu" a g)
        subj_toks = [c for f in fins for c in f.children] + list(g.children)
        has_io = any(c.text.lower() == 'io' for c in subj_toks)
        has_tu = any(c.text.lower() == 'tu' for c in subj_toks)

        if person == '1':
            if has_tu and not has_io:
                continue
            # 1ª persona: verbo reggente P1, o "io ...", o "sono" +
            # predicato singolare. Escludi 2ª/3ª persona chiara.
            if has_p2cop or '2' in persons:
                continue
            if '3' in persons and not has_sono and not has_io:
                continue
            if not ('1' in persons or has_io or has_sono):
                continue
        else:  # person == '2': interlocutore
            if has_io:
                continue
            # evidenza P2 solo dalla stessa proposizione: ricalcola persons
            # sui soli anchor locali (figli di g + head predicativo)
            def _same_clause(a):
                lo, hi = sorted((a.i, g.i))
                # barriere: punteggiatura, subordinanti, pronomi
                # interrogativi/relativi ("sai COS'È successo")
                return not any(
                    tok.text in (',', ';', ':') or tok.pos_ == 'SCONJ'
                    or (tok.pos_ == 'PRON'
                        and (tok.morph.get('PronType') in (['Int'], ['Rel'])))
                    for tok in doc[lo + 1:hi])
            _local_fins = [f for f in fins
                           if (f in _local or f is g.head) and _same_clause(f)]
            p2_near = [t2 for t2 in p2_near if _same_clause(t2)]
            has_p2cop = bool(p2_near) or any(
                f.text.lower() in _P2_COPULA for f in _local_fins)
            persons = set()
            for f in _local_fins:
                persons.update(f.morph.get('Person'))
            if not _local_fins and not p2_near and not has_tu:
                continue
            if '1' in persons and not (has_p2cop or has_tu):
                continue
            if '3' in persons and not (has_p2cop or has_tu or '2' in persons):
                continue
            if not ('2' in persons or has_p2cop or has_tu):
                continue
            # predicato con aux/copula di 3ª persona nella PROPRIA
            # proposizione ("se n'È andato", "cos'È successo"):
            # il soggetto è un terzo, non l'interlocutore
            if any(c.dep_ in ('aux', 'aux:pass', 'cop')
                   and c.morph.get('Person') == ['3']
                   and c.text.lower() not in _P2_COPULA
                   for c in g.children):
                continue

        selected.append(g)

    # catena di accordo coordinata: "sono stancO e confusO" — il secondo
    # aggettivo/participio è `conj` del primo e concorda con lo stesso
    # soggetto (il parlante)
    sel_set = set(t.i for t in selected)
    for t in doc:
        if t.i in sel_set or t.dep_ != 'conj' or t.head.i not in sel_set:
            continue
        if t.morph.get('Number') != ['Sing']:
            continue
        if t.morph.get('Gender') not in (['Fem'], ['Masc']):
            continue
        if not (t.pos_ == 'ADJ' or t.morph.get('VerbForm') == ['Part']):
            continue
        lw = t.text.lower()
        if t.morph.get('Gender') == ['Fem'] and not lw.endswith('a'):
            continue
        if t.morph.get('Gender') == ['Masc'] and not lw.endswith('o'):
            continue
        selected.append(t)
        sel_set.add(t.i)

    selected.sort(key=lambda t: t.i)
    return [(t.text, 'F' if t.morph.get('Gender') == ['Fem'] else 'M')
            for t in selected]
