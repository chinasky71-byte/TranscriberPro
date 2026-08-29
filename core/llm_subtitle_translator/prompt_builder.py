"""
Unità di sottotitolo e prompt di traduzione
===========================================
Resta il minimo che serve al percorso "mt": una battuta per chiamata, con il
prompt nativo del produttore.

Qui viveva anche il percorso "adapt" — un prompt di sistema con le regole del
sottotitolo, esempi few-shot di condensazione, glossario, registro dei parlanti
e una finestra scorrevole delle battute già tradotte, il tutto con un batch di
blocchi in JSON. È stato rimosso il 2026-08-18: chiedeva al modello di
restituire gli id corretti, e i modelli sotto una certa taglia sbagliavano —
fondevano due blocchi e scrivevano le traduzioni successive sotto gli id
sbagliati, con i tempi che restavano giusti e il file che sembrava sano.

Non era una regolazione da correggere ma un difetto di impianto: il percorso
"mt" è immune per costruzione, perché l'output È la traduzione e non c'è nessun
id da sbagliare. Con Aya rimossa e Tower+ scartato non restava nessun modello
che lo usasse, e il valore predefinito di `prompt_style` lo rendeva contagioso
— chi avesse aggiunto un modello senza dichiararlo avrebbe ereditato il
percorso rotto per omissione.

Se dovesse tornare utile il contesto fra blocchi (glossario, registro tu/Lei,
coerenza dei pronomi) sta nella storia del repo, non in questo file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

CPL_MAX = 42
CPS_MAX = 17.0

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


def rewrite_messages(source_en: str, draft_it: str, budget: int = 0,
                     loader: str = "gemma3", src_lang: str = "en",
                     tgt_lang: str = "it") -> List[Dict]:
    """PROTOTIPO (Fase 3, piano Gender V2.5) — non richiamato dalla pipeline
    di produzione, solo da mt_eval/probe_rewrite_guard.py.

    Riscrive una bozza IT già tradotta, vincolata al source EN, senza
    licenza di aggiungere contenuto: non è `translate()` (source→MT in un
    solo passaggio), è un secondo passaggio "correggi senza inventare".

    Nessun ruolo di sistema (TranslateGemma/gemma3 non ne ha uno praticabile
    per un'istruzione fuori dal suo chat template di traduzione) — tutto nel
    canale testo unico, stesso punto d'innesto già usato da
    mt_prefix/mt_budget_rule in engine.py.mt_messages(): istruzione PRIMA,
    cortissima; bozza IT SUBITO DOPO (deve dominare l'attenzione del
    modello); source EN in coda, come riferimento secondario — mai misurato
    se questo ordine regge su un compito diverso dalla traduzione pura,
    è esattamente ciò che il probe verifica.
    """
    instruction = (
        "Riscrivi il sottotitolo italiano SOLO se contiene un errore, "
        "mantenendo ogni informazione dell'originale inglese: non "
        "aggiungere NULLA che non sia nell'inglese. Se è già corretto, "
        "restituiscilo identico."
    )
    if budget > 0:
        instruction += f" Non più di {budget} caratteri."
    text = (f"{instruction}\n\nITALIANO:\n{draft_it}\n\n"
            f"INGLESE (riferimento):\n{source_en}")

    if loader == "gemma3":
        return [{
            "role": "user",
            "content": [{
                "type": "text",
                "source_lang_code": src_lang,
                "target_lang_code": tgt_lang,
                "text": text,
            }],
        }]
    return [{"role": "user", "content": text}]
