"""
TranslateGemma-12B: lo spec del modello e il suo prompt
======================================================
Quello che RESTA del vecchio motore transformers dopo ADR-009: i pesi sono un
GGUF eseguito da llama.cpp (`gguf_engine.py`), quindi caricamento e generazione
non stanno piu' qui — ma lo `ModelSpec` (etichetta, contesto, tetto al batch) e
il prompt sì, perché sono caratteristiche del MODELLO, non del runtime.

Il resto della pipeline lavora su messaggi in formato chat e non sa quale
runtime ci sia dietro: `build_mt_messages()` produce i messaggi, `gguf_engine`
li rende con il chat template di TranslateGemma.

Le regole del sottotitolo (`mt_prefix`, `mt_budget_rule`) vivono qui perché
TranslateGemma non prevede un ruolo di sistema: il campo `text` è l'unico
canale aperto per dargli un'istruzione, ed è una proprietà dei pesi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class ModelSpec:
    """Tutto ciò che distingue un occupante dello slot dagli altri."""

    model_id: str
    label: str
    # Parametri di decoding. Fonte: model card del vendor.
    generation: Dict[str, Any] = field(default_factory=dict)
    # Finestra di contesto utile (token).
    context_window: int = 8192
    # Quante conversazioni al massimo nella stessa generazione. È il vero
    # regolatore del picco di VRAM: i pesi sono una costante, mentre la KV
    # cache e le attivazioni crescono in proporzione al batch. Su WDDM
    # superare la memoria dedicata non produce un OOM ma uno sconfinamento
    # silenzioso nella RAM di sistema — nessun errore, solo un rallentamento
    # di 4-5 volte — quindi il tetto va messo per modello, misurato con
    # `mt_eval/vram_probe.py`, non lasciato a un valore unico per tutti.
    max_batch: int = 12
    # Istruzioni da anteporre al testo dentro il prompt nativo. Serve ai
    # modelli il cui chat template non prevede un ruolo di sistema: l'unico
    # canale per dargli una regola è il campo del testo da tradurre.
    # Vuoto = prompt del produttore intatto.
    mt_prefix: str = ""
    # Quando applicare `mt_prefix`. Se resta None il prefisso va su ogni
    # battuta; con un pattern, solo su quelle che lo contengono. Serve perché
    # un'istruzione può essere un guadagno su una classe di battute e un danno
    # su tutte le altre — vedi la tabella su MT_PREFIX_TRIGGER.
    mt_prefix_when: Optional[Any] = None
    # Istruzione sul budget di caratteri, con un segnaposto `{budget}`. Va
    # tenuta separata da `mt_prefix` perché ha una condizione diversa: il
    # registro serve solo dove c'è del turpiloquio, il budget vale sempre —
    # è autolimitante, su una battuta corta non chiede di tagliare niente.
    mt_budget_rule: str = ""
    gated: bool = False
    notes: str = ""


# Le regole che TranslateGemma può ricevere, e l'unico posto da cui può
# riceverle. Il suo chat template costruisce da sé l'istruzione di traduzione
# a partire dai codici lingua e non prevede un ruolo di sistema: il campo
# `text` è l'unico canale aperto.
#
# MISURATO su 40 blocchi di Deadpool 2 (mt_eval/probe_tg_prompt.py), metà con
# turpiloquio. Senza queste righe il modello conservava 3 volgarità su 20 e
# rendeva "pumpkin fucker" con "idiota"; con queste, 14 su 20 — quanto il
# sottotitolo professionale della pellicola, che ne conserva 15. Il rapporto di
# lunghezza scende da 1,15 a 1,10 volte l'inglese. Costo: due secondi ogni
# quaranta blocchi.
#
# Restano corte di proposito: il testo finisce dentro un'istruzione di
# traduzione, e più righe si aggiungono più cresce il rischio che il modello le
# traduca invece di applicarle. Una terza variante che scavalcava del tutto il
# template per dettare regole più lunghe conservava ancora più volgarità (18 su
# 20) ma, uscendo dalla forma su cui il modello è addestrato, produceva parole
# inesistenti ("indemaniato") e concordanze sbagliate: guadagno sul registro,
# perdita sulla lingua. Scartata.
#
# NOTA: la stringa misurata comprendeva anche "più breve dell'originale, senza
# riempitivi", che il giudizio ha poi mostrato dannosa sui blocchi normali. Quel
# pezzo è stato sostituito da MT_BUDGET_RULE, che dice un numero invece di un
# aggettivo. Qui resta la sola clausola sul registro.
TRANSLATEGEMMA_SUBTITLE_RULES = (
    "Conserva le parolacce con parolacce italiane "
    "(fuck→cazzo, shit→merda, asshole→stronzo)."
)

# Su QUALI battute mettere la clausola sul registro.
#
# MISURATO col giudizio testa a testa fra le due varianti dello STESSO motore
# (mt_eval/gemba_ftg_vs_ftgr.jsonl, 400 blocchi di Deadpool 2), che è l'unico
# confronto valido: le due rese finiscono nella stessa chiamata al giudice.
#
#                          nativo   con regole   preferenza
#   blocchi volgari (36)     5,97      3,89       25% / 69%
#   blocchi normali (364)    2,23      2,12       27% / 31%
#   totale (400)             2,57      2,28       27% / 35%
#
# ATTENZIONE ALLA TRAPPOLA: confrontando invece DUE RUN SEPARATE contro NLLB il
# risultato sembrava opposto (le regole apparivano dannose sui blocchi normali).
# Era un artefatto: fra una run e l'altra la calibrazione del giudice slitta —
# NLLB stesso, sugli stessi identici segmenti, è passato da 2,15 a 1,84. I
# punteggi assoluti di run diverse NON si confrontano; solo i confronti interni
# a una run valgono.
#
# La clausola sul registro resta comunque condizionata, ma per un'altra ragione:
# su una battuta senza parolacce non ha niente da fare, e toglierla accorcia il
# preambolo — meno testo che il modello possa tradurre invece di applicare.
MT_PREFIX_TRIGGER = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|cunt|dick|prick|"
    r"motherfuck\w*|goddamn|bastard|cock|pussy|balls|piss\w*|whore|slut|"
    r"douche\w*|jackass|dumbass|screw you|son of a bitch)\b", re.I)

# Il budget di caratteri della battuta, detto al modello come NUMERO.
#
# Il giudizio su un film senza turpiloquio (A Man Called Otto) isola quello che
# resta a TranslateGemma dopo il turpiloquio: capisce quanto NLLB e sbaglia
# meno gravemente (7 errori critici contro 11), ma perde su `style` di 13 punti
# su 100 segmenti. Scrive battute troppo lunghe, e basta.
#
# MISURATO (mt_eval/probe_tg_budget.py) su 60 blocchi stretti, cioè quelli in
# cui l'inglese già affolla lo spazio disponibile:
#
#                          caratteri   x EN   >42 car   oltre budget
#   professionista             43,9    0,83       0%         27%
#   nessuna regola             59,0    1,11      65%         67%
#   regola generica            54,5    1,03      55%         57%
#   budget esplicito           51,6    0,97      52%         53%
#
# Un aggettivo ("più breve") sposta poco; un numero sposta il triplo, e porta
# il rapporto sotto 1,0 per la prima volta. La regola è anche AUTOLIMITANTE: su
# una battuta che nel budget ci sta già, un tetto non chiede di tagliare
# niente, mentre "più breve dell'originale" lo chiede sempre.
MT_BUDGET_RULE = ("Rendi come sottotitolo italiano in non più di {budget} "
                  "caratteri, tagliando i riempitivi.")

TRANSLATEGEMMA_SPEC = ModelSpec(
    # Pesi locali (GGUF): il traduttore non li carica da qui, ma l'etichetta e
    # il contesto sì — e questo percorso è l'unico che il prodotto usa.
    model_id=str(PROJECT_ROOT / "models" / "translategemma-12b-it-finale"),
    label="TranslateGemma 12B",
    generation=dict(do_sample=False, num_beams=1),
    mt_prefix=TRANSLATEGEMMA_SUBTITLE_RULES,
    mt_prefix_when=MT_PREFIX_TRIGGER,
    mt_budget_rule=MT_BUDGET_RULE,
    gated=True,
    context_window=131072,
    # MISURATO (mt_eval/vram_probe.py, scheda da 12.288 MiB, percorso NF4 non
    # più esistente; il numero resta perché `max_batch` è il tetto al numero di
    # conversazioni che il traduttore manda al motore in un colpo). Il tetto
    # vero del percorso GGUF è `n_parallel` (KV cache), e `gguf_engine` lo
    # sostituisce nello spec dell'istanza.
    max_batch=16,
    notes="Addestrato con RL contro la letteralità (MetricX-QE, AutoMQM). "
          "La variante 4B era stata bocciata a luglio; il 12B è la taglia "
          "che nei benchmark supera il baseline Gemma 3 27B.",
)

DEFAULT_MODEL_KEY = "translategemma-12b"

# Un solo occupante dello slot (ADR-009). Il dizionario resta perché il WebUI
# (`/api/system`) e il cache cleaner chiedono "quale modello" senza sapere se
# ce n'e' uno o dieci.
MODEL_SPECS: Dict[str, ModelSpec] = {DEFAULT_MODEL_KEY: TRANSLATEGEMMA_SPEC}


def build_mt_messages(text: str, src_lang: str = "en", tgt_lang: str = "it",
                      budget: int = 0,
                      spec: ModelSpec = TRANSLATEGEMMA_SPEC) -> List[Dict[str, Any]]:
    """Il prompt di traduzione nativo di `spec` (una conversazione per battuta).

    Vive qui e non in `prompt_builder` perché è una caratteristica dei pesi,
    non dello stile che vogliamo ottenere: TranslateGemma vuole un `content`
    strutturato con i codici lingua. Il resto della pipeline non deve saperlo.

    Se il modello dichiara un `mt_prefix`, le regole del sottotitolo entrano
    qui — dentro il testo — perché è l'unico varco che il suo chat template
    lascia aperto.
    """
    # Una riga sola, composta: due istruzioni su due righe allungano il
    # preambolo e aumentano la probabilità che il modello le traduca invece di
    # applicarle.
    regole: List[str] = []
    if spec.mt_budget_rule and budget > 0:
        regole.append(spec.mt_budget_rule.format(budget=budget))
    if spec.mt_prefix and (spec.mt_prefix_when is None
                           or spec.mt_prefix_when.search(text)):
        regole.append(spec.mt_prefix)
    if regole:
        regole.append("Traduci solo la battuta:")
        text = " ".join(regole) + "\n" + text

    return [{
        "role": "user",
        "content": [{
            "type": "text",
            "source_lang_code": src_lang,
            "target_lang_code": tgt_lang,
            "text": text,
        }],
    }]
