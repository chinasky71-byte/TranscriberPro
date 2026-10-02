# -*- coding: utf-8 -*-
"""
Secondo canale di estrazione: Qwen locale come estrattore di span, non
come giudice. File: glossary_engine/glossary_qwen_extract.py

Per ogni occorrenza chiede al modello "quale espressione italiana
corrisponde al termine inglese in questa coppia?" — un compito di
estrazione, non un verdetto di qualita': lo span restituito e' validato
MECCANICAMENTE (deve essere sottostringa letterale, case-insensitive, del
blocco italiano) prima di essere accettato. Se non lo e', l'occorrenza e'
scartata dal coverage — mai "corretta" o inventata. Questo evita la
trappola gia' misurata coi giudizi GEMBA (punteggi instabili tra run,
vedi memoria feedback_gemba_judge_gotchas.md): l'estrazione di uno span
verificabile e' molto piu' stabile di un giudizio.

Modulo puro (solo `llama_cpp`, nessun torch/transformers): puo' girare
identico in qualunque venv abbia llama-cpp-python. In produzione gira nel
venv PRINCIPALE del progetto via subprocess (vedi
glossary_engine/glossary_qwen_gpu_cli.py + glossary_engine/glossary_qwen_bridge.py), che
ha gia' una build CUDA di llama-cpp-python provata dal gender corrector
sullo stesso modello — non in venv_glossary/ (dove installarne una
seconda romperebbe l'isolamento voluto dei due venv, vedi
glossary_engine/glossary_align.py). Import lazy.
"""
import re
from typing import List, Optional

_model = None
_model_path = None

_OMESSO = "OMESSO"

_SYSTEM_PROMPT = (
    "Sei un estrattore preciso. Dato un termine inglese e una coppia di "
    "frasi inglese/italiano, individua la frase italiana con quale "
    "espressione italiana e' resa quel termine. Copia SOLO parole gia' "
    "presenti nella frase italiana, senza modificarle o tradurle di nuovo. "
    f"Se il concetto non compare per niente, rispondi solo con {_OMESSO}. "
    "Rispondi con la sola espressione (o {omesso}), niente altro, nessuna "
    "spiegazione.".format(omesso=_OMESSO)
)

_USER_TMPL = (
    "Frase inglese: {src}\n"
    "Frase italiana (traduzione): {trg}\n"
    "Termine da cercare: \"{term}\"\n"
    "Risposta:"
)


def load(model_path: str, n_ctx: int = 2048, n_gpu_layers: int = 0):
    global _model, _model_path
    if _model is not None and _model_path == model_path:
        return _model
    try:  # torch\lib nel PATH: cudart/cublas 12 per ggml-cuda.dll (vedi utils/cuda_dll_path.py)
        import importlib.util as _iu, os as _os
        _sp = _iu.find_spec('torch')
        if _os.name == 'nt' and _sp is not None and _sp.submodule_search_locations:
            _lib = _os.path.join(list(_sp.submodule_search_locations)[0], 'lib')
            if _os.path.isdir(_lib):
                _os.environ['PATH'] = _lib + _os.pathsep + _os.environ.get('PATH', '')
    except Exception:
        pass
    try:
        from llama_cpp import Llama
    except Exception as e:   # anche RuntimeError (DLL CUDA non trovata)
        raise ImportError(
            f"llama-cpp-python non utilizzabile in questo venv: {e}") from e
    _model = Llama(model_path=model_path, n_gpu_layers=n_gpu_layers, n_ctx=n_ctx,
                    verbose=False)
    _model_path = model_path
    return _model


def unload():
    global _model, _model_path
    _model = None
    _model_path = None
    import gc
    gc.collect()


def _strip_response(text: str) -> str:
    text = text.strip()
    # Il modello a volte incornicia la risposta in virgolette o markdown.
    text = text.strip('"\'` \n\t')
    # Solo la prima riga: alcuni modelli aggiungono spiegazioni dopo.
    return text.split("\n")[0].strip()


class ExtractResult:
    """kind: 'span' (resa estratta e verificata), 'omitted' (il modello ha
    dichiarato esplicitamente che il concetto non compare), 'invalid'
    (risposta non sottostringa del testo italiano, o errore — scartata,
    NON equivale a 'omitted': un'invalid non prova che l'occorrenza sia
    davvero assente, solo che la risposta del modello non e' verificabile)."""
    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: Optional[str] = None):
        self.kind = kind
        self.text = text


def extract_one(term: str, src: str, trg: str) -> ExtractResult:
    model = _model
    if model is None:
        raise RuntimeError("glossary_qwen_extract.load() non chiamato")
    user_prompt = _USER_TMPL.format(src=src, trg=trg, term=term)
    try:
        out = model.create_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0, top_p=0.1, max_tokens=48)
        raw = out["choices"][0]["message"]["content"]
    except Exception:
        return ExtractResult("invalid")
    answer = _strip_response(raw)
    if not answer:
        return ExtractResult("invalid")
    if answer.upper().startswith(_OMESSO):
        return ExtractResult("omitted")
    # Validazione meccanica: sottostringa letterale case-insensitive del
    # testo italiano — un modello debole degrada in "estrae meno", mai in
    # "glossario sbagliato".
    if answer.lower() not in trg.lower():
        return ExtractResult("invalid")
    return ExtractResult("span", answer)


def extract_spans(term: str, pairs: List[dict],
                   progress_cb=None) -> List[ExtractResult]:
    """Un ExtractResult per coppia (dict con 'source'/'reference').
    progress_cb, se dato, viene chiamato con (fatti, totale)."""
    out = []
    total = len(pairs)
    for i, p in enumerate(pairs):
        out.append(extract_one(term, p["source"], p["reference"]))
        if progress_cb is not None:
            progress_cb(i + 1, total)
    return out


def coverage(results: List[ExtractResult]) -> float:
    """Quota di risposte verificabili (span o 'omesso' esplicito) sul
    totale tentato. Basso => il canale Qwen non e' affidabile per questo
    termine (mai interpretato come "termine assente")."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.kind in ("span", "omitted")) / len(results)


def to_spans(results: List[ExtractResult]) -> List[Optional[str]]:
    """Riduce a lista di span-o-None per il clustering: 'omitted' e
    'invalid' diventano entrambi None (esclusi dai cluster), solo 'span'
    porta un testo."""
    return [r.text if r.kind == "span" else None for r in results]
