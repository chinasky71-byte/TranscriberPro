# -*- coding: utf-8 -*-
"""
Guardia anti-allucinazione per-segmento — PROTOTIPO, Fase 3 di Gender V2.5.
File: core/llm_subtitle_translator/hallucination_guard.py

Non esiste oggi un controllo capace di rilevare un'AGGIUNTA breve di
contenuto: `too_long` in validator.py scatta solo sopra 2.4x la lunghezza
(LEN_RATIO_MAX), troppo grezzo per un'aggiunta come quella osservata su
Knight's & Magic ("for generations" → "fin dalla fondazione di questo
regno", TranslateGemma) — non allunga abbastanza il blocco da superare
quella soglia.

Giudizio LLM per-segmento, non batch: un fatto aggiunto è un evento raro e
puntuale, un giudizio aggregato lo diluirebbe nella media del blocco. Stesso
pattern di chiamata di mt_eval/run_gemba.py (client Anthropic, output
strutturato via json_schema), ma senza il MQM completo — qui serve solo un
sì/no più il testo aggiunto, non un punteggio di qualità.

**Non integrato in pipeline**: prototipo per la sperimentazione isolata di
mt_eval/probe_rewrite_guard.py. Nessun chiamante di produzione lo usa.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "added_content": {"type": "boolean"},
        "added_text": {"type": ["string", "null"]},
    },
    "required": ["added_content", "added_text"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Confronti un sottotitolo inglese con la sua resa italiana. Il tuo "
    "unico compito è dire se la resa italiana contiene un'informazione, un "
    "fatto o un dettaglio ASSENTE dall'inglese — non giudichi fluenza, "
    "stile o correttezza grammaticale, solo se c'è qualcosa di INVENTATO "
    "che un ascoltatore prenderebbe per vero. Condensare o omettere non è "
    "un'aggiunta: se la resa è fedele, più corta, o omette, "
    "added_content=false. Se added_content=true, added_text riporta la "
    "porzione di testo italiano che non ha corrispondenza nell'inglese."
)


def check_added_content(client, source_en: str, translation_it: str,
                        model: str = "claude-opus-5",
                        provider: str = "anthropic") -> Dict[str, Any]:
    """Un giudizio per segmento.

    Ritorna {"added_content": bool, "added_text": str|None}. Nessun
    retry/gestione errori qui — è un prototipo isolato per lo script di
    probe, non un percorso di produzione: un'eccezione del client si
    propaga al chiamante.

    `provider="openai"`: stesso schema di risposta, formato di chiamata di
    `mt_eval/run_gemba.py._call_openai` — fallback quando il credito
    Anthropic è esaurito (gotcha noto del progetto, vedi
    memory/feedback_gemba_judge_gotchas.md).
    """
    user_message = f"INGLESE:\n{source_en}\n\nITALIANO:\n{translation_it}"

    if provider == "openai":
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "hallucination_check", "strict": True,
                                "schema": RESULT_SCHEMA},
            },
            max_completion_tokens=500,
        )
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise RuntimeError("giudizio bloccato dal filtro contenuti")
        if choice.message.refusal:
            raise RuntimeError(f"giudizio rifiutato: {choice.message.refusal}")
        return json.loads(choice.message.content)

    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema",
                                  "schema": RESULT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("giudizio rifiutato dal modello")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def guard_rewrite(client, source_en: str, draft_it: str, rewritten_it: str,
                  model: str = "claude-opus-5", provider: str = "anthropic") -> str:
    """Applica il criterio della Fase 3: qualunque `added_content: true`
    sulla RISCRITTURA → scarta, tieni la bozza originale. Nessuna soglia di
    severità, nessun retry automatico.

    Ritorna il testo finale da usare (rewritten_it o draft_it).
    """
    verdict = check_added_content(client, source_en, rewritten_it,
                                  model=model, provider=provider)
    if verdict.get("added_content"):
        return draft_it
    return rewritten_it
