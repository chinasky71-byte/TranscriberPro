"""
Costruzione dei prompt per l'adattamento di sottotitoli EN->IT
==============================================================
Il system prompt chiede di ADATTARE, non di tradurre: è la differenza che
separa un sottotitolo italiano da un calco dell'inglese, ed è la dimensione su
cui NLLB fine-tuned perde pur essendo fedele.

Tre scelte di progetto non ovvie:

1. Gli esempi few-shot mostrano condensazione ESTREMA, non "equilibrata". La
   letteratura sull'isometric MT è netta: con esempi di compressione moderata
   il modello ignora del tutto il vincolo di lunghezza, e lo rispetta solo se
   gli esempi sono estremi. L'italiano è già ~1,2-1,3x più lungo dell'inglese
   e un LLM ci aggiunge un +10-35% di verbosità gratuita da length bias: senza
   questa spinta il risultato sfora sistematicamente i 42 caratteri.

2. Il budget caratteri è dato PER BLOCCO, calcolato dalla durata reale del cue
   (17 CPS, guida di stile italiana Netflix). Un limite globale nel prompt non
   funziona: il modello non sa quanto dura la battuta che sta traducendo.

3. I vincoli di riga NON sono affidati al modello. Il prompt chiede una resa
   breve; il rispetto esatto di 42 caratteri e 2 righe è compito del
   post-processing deterministico, che è affidabile e costa zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

CPL_MAX = 42
CPS_MAX = 17.0

SYSTEM_PROMPT = """\
Sei un adattatore professionista di sottotitoli italiani. Ricevi le battute \
originali in inglese di un film o di una serie TV e produci i sottotitoli \
italiani da mandare in onda.

Adatti, non traduci. Un sottotitolo non è la trascrizione tradotta di ciò che \
viene detto: è la resa più breve e più naturale che conserva senso, tono e \
intenzione. Lo spettatore ha pochi secondi e sta guardando le immagini.

COME SI CONDENSA
- Elimina i riempitivi: well, you know, I mean, like, actually, so, right, \
oh, look, listen, sort of, kind of.
- Elimina i vocativi ridondanti e le false partenze.
- Le parole o frasi ripetute più di una volta dallo stesso parlante si \
traducono una volta sola.
- Preferisci sempre la forma breve: "Ti chiamo domani" invece di "Ti darò un \
colpo di telefono domani mattina".
- Taglia ciò che l'immagine o il contesto già dicono. Non tagliare mai \
informazione che lo spettatore non ricaverebbe altrimenti.

ITALIANO NATURALE, NON TRADUTTORESE
- Niente pronomi soggetto ridondanti: "Non lo so", non "Io non lo so".
- Niente possessivi ridondanti: "Alza la mano", non "Alza la sua mano".
- "cosa", non "che cosa".
- Dove l'inglese usa il passivo, usa l'attivo o il "si" impersonale: \
"Pare che il trattato sia stato firmato in segreto", non "È creduto che...".
- Rendi gli idiomi con l'idioma italiano corrispondente, non alla lettera.
- Scrivi come parla un italiano, non come scrive un traduttore.

TURPILOQUIO
Questo è materiale per adulti e la fedeltà al registro è parte del lavoro. \
Le volgarità NON si attenuano e NON si omettono mai: si rendono con una \
volgarità italiana di pari forza. Attenuare il turpiloquio è un errore di \
traduzione grave quanto sbagliare il significato, perché cambia chi è il \
personaggio.
Sono VIETATI come rese di parolacce inglesi: "diavolo", "maledetto", \
"accidenti", "cavolo", "mazza", "caspita", "dannazione", "santo cielo". \
Sono eufemismi e non appartengono al registro dell'originale.
Corrispondenze corrette:
  fuck / fucking -> cazzo, del cazzo, di merda, fottuto
  what the fuck -> che cazzo
  shit -> merda, cazzo
  bullshit -> stronzate, cazzate
  asshole / prick -> stronzo, coglione
  bitch -> stronza, puttana (secondo il contesto)
  goddamn -> del cazzo, maledetto solo se il tono è blando
  fuck you -> vaffanculo
  motherfucker -> figlio di puttana, stronzo
Se l'originale è volgare, la resa italiana deve contenere una parolaccia.

REGOLE DI STILE (guida italiana Netflix)
- I nomi propri di persona e di luogo NON si traducono.
- I numeri da uno a dieci in lettere, sopra il dieci in cifre; a inizio frase \
sempre in lettere. Ore in formato 24 ore.
- Puntini di sospensione solo per pause lunghe o interruzioni brusche, mai \
quando una frase prosegue nel blocco successivo. Mai punteggiatura doppia.
- Il testo a schermo (cartelli, insegne, messaggi) va TUTTO MAIUSCOLO.
- Se una battuta è già in italiano nell'originale, lasciala invariata.

FORMATO DELLE RIGHE
- Se il blocco originale ha due righe con il trattino di cambio parlante, \
mantieni due righe e il trattino: un parlante per riga.
- Negli altri casi scrivi una riga sola: alla divisione ci pensa il sistema.
- Non aggiungere trattini che non ci sono nell'originale.

OUTPUT
Rispondi SOLO con un array JSON, un oggetto per ogni blocco ricevuto, nello \
stesso ordine e con lo stesso id:
[{"id": 1, "it": "..."}, {"id": 2, "it": "..."}]
Nessun testo prima o dopo l'array. Usa \\n per separare le due righe di un \
blocco di dialogo."""


# Esempi di condensazione volutamente aggressivi: servono a spostare il
# modello, non a rappresentare il caso medio.
FEW_SHOT_SOURCE = [
    {"id": 1, "en": "Well, I mean, you know, I just think that maybe we "
                    "should probably talk about this later.", "budget": 46},
    {"id": 2, "en": "I'm gonna go ahead and give you a call tomorrow "
                    "morning, okay?", "budget": 38},
    {"id": 3, "en": "- What the hell are you doing in here?\n"
                    "- I could ask you the very same thing.", "budget": 60},
    {"id": 4, "en": "No, no, no, no! Don't you dare touch that thing!",
     "budget": 32},
    {"id": 5, "en": "It is believed that the treaty was signed in secret by "
                    "both of the parties.", "budget": 54},
    {"id": 6, "en": "Are you fucking kidding me right now?", "budget": 36},
    {"id": 7, "en": "The thing is, I don't really know what I'm supposed to "
                    "be doing with my life.", "budget": 48},
    {"id": 8, "en": "He told me that he had already seen her at the station "
                    "at eight o'clock.", "budget": 52},
    # Da qui in poi: turpiloquio. Il modello, allineato per evitarlo, tende
    # a produrre eufemismi ("diavolo", "maledetto") anche quando la regola
    # scritta lo vieta. Gli esempi sono la leva che funziona davvero.
    {"id": 9, "en": "What the fuck is that?", "budget": 30},
    {"id": 10, "en": "Shit, I got a whole fucking briefing on this.",
     "budget": 44},
    {"id": 11, "en": "You're such an asshole, you know that?", "budget": 38},
    {"id": 12, "en": "That's complete bullshit and you know it.",
     "budget": 40},
]

FEW_SHOT_TARGET = [
    {"id": 1, "it": "Forse è meglio parlarne dopo."},
    {"id": 2, "it": "Ti chiamo domattina."},
    {"id": 3, "it": "- Che diavolo ci fai qui?\n- Potrei chiederti lo stesso."},
    {"id": 4, "it": "No! Non toccarlo!"},
    {"id": 5, "it": "Pare che il trattato sia stato firmato in segreto."},
    {"id": 6, "it": "Mi stai prendendo per il culo?"},
    {"id": 7, "it": "Il fatto è che non so cosa fare della mia vita."},
    {"id": 8, "it": "Mi ha detto di averla vista alle otto alla stazione."},
    {"id": 9, "it": "Che cazzo è?"},
    {"id": 10, "it": "Cazzo, mi hanno fatto un briefing su questo."},
    {"id": 11, "it": "Sei proprio uno stronzo, lo sai?"},
    {"id": 12, "it": "Sono stronzate e lo sai."},
]


@dataclass
class SubtitleUnit:
    """Un blocco da tradurre, con quello che serve per adattarlo bene."""

    id: int
    text: str
    duration: float = 0.0          # secondi; 0 = budget non calcolabile
    is_dialogue: bool = False      # blocco a due parlanti (trattini)
    speaker: Optional[str] = None  # etichetta dalla diarization

    @property
    def budget(self) -> int:
        """Caratteri disponibili a 17 CPS. Due righe da 42 sono il tetto
        fisico, qualunque sia la durata."""
        if self.duration <= 0:
            return CPL_MAX * 2
        return max(12, min(int(self.duration * CPS_MAX), CPL_MAX * 2))


@dataclass
class DocumentContext:
    """Ciò che si sa del film e che vale per tutti i blocchi."""

    title: Optional[str] = None
    overview: Optional[str] = None
    characters: Sequence[str] = field(default_factory=tuple)
    glossary: Dict[str, str] = field(default_factory=dict)
    # Registro per coppia di parlanti, deciso una volta e congelato:
    # {"SPEAKER_00|SPEAKER_01": "informale"}
    register: Dict[str, str] = field(default_factory=dict)

    def header(self, units: Sequence[SubtitleUnit]) -> str:
        """Blocco di contesto, con il glossario filtrato sui soli termini che
        compaiono davvero in questo batch: iniettarlo tutto è rumore e può
        peggiorare la traduzione."""
        parts: List[str] = []
        if self.title:
            parts.append(f"Opera: {self.title}")
        if self.overview:
            parts.append(f"Trama: {self.overview.strip()[:400]}")
        if self.characters:
            parts.append("Personaggi: " + ", ".join(self.characters[:15]))

        if self.glossary:
            haystack = " ".join(u.text for u in units).lower()
            hits = {k: v for k, v in self.glossary.items()
                    if k.lower() in haystack}
            if hits:
                parts.append(
                    "Rese obbligatorie: "
                    + "; ".join(f"{k} -> {v}" for k, v in hits.items())
                )

        speakers = {u.speaker for u in units if u.speaker}
        if speakers and self.register:
            rel = [f"{pair}: {reg}" for pair, reg in self.register.items()
                   if any(s in pair for s in speakers)]
            if rel:
                parts.append("Registro tra i parlanti: " + "; ".join(rel))

        return "\n".join(parts)


def _render_units(units: Sequence[SubtitleUnit]) -> str:
    payload = []
    for u in units:
        entry = {"id": u.id, "en": u.text, "budget": u.budget}
        if u.speaker:
            entry["speaker"] = u.speaker
        payload.append(entry)
    return json.dumps(payload, ensure_ascii=False, indent=1)


def build_messages(
    units: Sequence[SubtitleUnit],
    context: Optional[DocumentContext] = None,
    history: Optional[Sequence[tuple]] = None,
    retry_note: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Costruisce la conversazione per un batch di blocchi.

    `history`: ultime coppie (originale, traduzione già prodotta), passate come
    contesto non da tradurre. Servono per la coerenza di pronomi, genere e
    registro tra battute vicine — la cosa che una traduzione blocco per blocco
    non può ottenere.

    `retry_note`: messaggio d'errore del validatore, per il secondo tentativo.
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "Adatta questi blocchi.\n\n" + _render_units(
                [SubtitleUnit(id=e["id"], text=e["en"],
                              duration=e["budget"] / CPS_MAX)
                 for e in FEW_SHOT_SOURCE]
            )},
        {"role": "assistant", "content":
            json.dumps(FEW_SHOT_TARGET, ensure_ascii=False)},
    ]

    blocks: List[str] = []
    if context:
        header = context.header(units)
        if header:
            blocks.append(header)

    if history:
        recent = "\n".join(
            f"EN: {src}\nIT: {tgt}" for src, tgt in list(history)[-4:]
        )
        blocks.append(
            "Battute immediatamente precedenti, già adattate. Servono solo da "
            "contesto per la coerenza: NON vanno ritradotte.\n" + recent
        )

    blocks.append("Adatta questi blocchi.\n\n" + _render_units(units))

    if retry_note:
        blocks.append(
            f"Il tentativo precedente non è stato accettato: {retry_note}\n"
            f"Riprova rispettando esattamente il formato richiesto."
        )

    messages.append({"role": "user", "content": "\n\n".join(blocks)})
    return messages


def build_mt_messages(unit: SubtitleUnit,
                      target_language: str = "Italian") -> List[Dict[str, str]]:
    """Prompt nativo di traduzione, una battuta per chiamata.

    Formato della model card di Hunyuan-MT. Un modello MT specializzato non è
    addestrato a seguire un regolamento di stile né a rispondere in JSON:
    interrogarlo così è ciò che gli riesce meglio, e le convenzioni del
    sottotitolo le applica il post-processing, che non sbaglia.
    """
    return [{
        "role": "user",
        "content": (
            f"Translate the following segment into {target_language}, "
            f"without additional explanation.\n\n{unit.text}"
        ),
    }]


def build_refine_messages(
    units: Sequence[SubtitleUnit],
    drafts: Dict[int, str],
    context: Optional[DocumentContext] = None,
) -> List[Dict[str, str]]:
    """Variante post-editing: l'LLM riscrive una bozza esistente invece di
    tradurre da zero.

    Parte da una traduzione già fedele (NLLB fine-tuned) e ne corregge solo la
    resa. Riduce per costruzione allucinazioni e omissioni, perché il modello
    vede sempre sia l'originale sia una traduzione ancorata.
    """
    payload = [
        {"id": u.id, "en": u.text, "bozza": drafts.get(u.id, ""),
         "budget": u.budget}
        for u in units
    ]

    blocks: List[str] = []
    if context:
        header = context.header(units)
        if header:
            blocks.append(header)

    blocks.append(
        "Per ogni blocco hai l'originale inglese e una bozza italiana "
        "prodotta da un traduttore automatico: fedele, ma spesso rigida e "
        "calcata sull'inglese.\n"
        "Riscrivi la bozza in italiano naturale da sottotitolo, applicando le "
        "regole che conosci. Conserva il senso della bozza dove è corretta: "
        "correggila solo se travisa l'originale. Se una bozza è già buona, "
        "riportala invariata.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]
