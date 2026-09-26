# -*- coding: utf-8 -*-
"""
Gender Rewriter — Fase 3 del redesign Gender Corrector.
File: core/gender_rewriter.py

Riscrive una riga italiana adeguando al genere del PARLANTE (noto dalla
Speaker Gender Map) le forme di 1ª persona individuate dal selettore
(core/gender_line_selector.py).

Due motori:
  - RuleRewriter: flip morfologico deterministico dei token indicati
    (-o↔-a sulla desinenza + tabella articoli/pronomi). Zero modelli,
    zero VRAM, zero allucinazioni possibili.
  - LlamaRewriter: LLM locale (GGUF via llama-cpp-python, es. Qwen2.5-14B)
    con prompt few-shot vincolato: riscrive l'INTERA riga cambiando solo
    le forme riferite al parlante.

VALIDATORE DETERMINISTICO (per qualsiasi motore): la riga riscritta è
accettata SOLO se ogni parola cambiata è una coppia di flessione di genere
plausibile e il numero di parole è invariato. Qualsiasi altra differenza →
si tiene l'originale. Le allucinazioni sono impossibili per costruzione.

Nessuna dipendenza Qt. spaCy NON è richiesto qui (i token da flippare
arrivano già dal selettore).
"""
from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flip morfologico e validatore
# ---------------------------------------------------------------------------

# Coppie chiuse (articoli, pronomi, possessivi) — entrambe le direzioni
_PAIRS_M2F = {
    'un': 'una', 'uno': 'una', 'il': 'la', 'lo': 'la',
    'lui': 'lei', 'egli': 'ella', 'esso': 'essa',
    'questo': 'questa', 'quello': 'quella', 'quest': 'questa',
    'mio': 'mia', 'tuo': 'tua', 'suo': 'sua',
    'nostro': 'nostra', 'vostro': 'vostra',
    'stesso': 'stessa', 'medesimo': 'medesima',
    'nessuno': 'nessuna', 'qualcuno': 'qualcuna', 'ognuno': 'ognuna',
    'tutto': 'tutta', 'altro': 'altra', 'poco': 'poca',
    'molto': 'molta', 'troppo': 'troppa', 'tanto': 'tanta',
    'primo': 'prima', 'ultimo': 'ultima', 'unico': 'unica',
    'solo': 'sola', 'certo': 'certa', 'vivo': 'viva', 'morto': 'morta',
}
_PAIRS_F2M = {v: k for k, v in _PAIRS_M2F.items() if v != 'una'}
_PAIRS_F2M['una'] = 'un'    # una→un (non "uno": ambiguità risolta a favore del comune)


def flip_word(word: str, target_gender: str) -> Optional[str]:
    """Flippa una parola verso il genere target. None se non flippabile.

    Regole: tabella coppie chiuse, poi desinenza -o↔-a (con gestione
    -co/-ca, -go/-ga per conservare il suono: stanco→stanca è diretto,
    il flip NON tocca la radice). Preserva la capitalizzazione.
    """
    if not word:
        return None
    low = word.lower()
    table = _PAIRS_M2F if target_gender == 'F' else _PAIRS_F2M
    flipped = table.get(low)
    if flipped is None:
        if target_gender == 'F' and low.endswith('o'):
            flipped = low[:-1] + 'a'
        elif target_gender == 'M' and low.endswith('a'):
            flipped = low[:-1] + 'o'
        else:
            return None
    # preserva capitalizzazione
    if word.isupper():
        return flipped.upper()
    if word[0].isupper():
        return flipped[0].upper() + flipped[1:]
    return flipped


def _is_gender_pair(a: str, b: str) -> bool:
    """True se (a, b) è una coppia di flessione di genere plausibile."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    if _PAIRS_M2F.get(a) == b or _PAIRS_F2M.get(a) == b:
        return True
    # desinenza -o/-a (stessa radice)
    if len(a) == len(b) and a[:-1] == b[:-1]:
        return {a[-1], b[-1]} in ({'o', 'a'}, {'i', 'e'})
    return False


_WORD_RE = re.compile(r"[\wàèéìòù']+", re.UNICODE)


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text)


def validate_rewrite(original: str, rewritten: str) -> bool:
    """Validatore deterministico: accetta la riscrittura SOLO se
    - il numero di parole è identico, e
    - ogni parola cambiata è una coppia di flessione di genere plausibile.
    """
    w_orig, w_new = _words(original), _words(rewritten)
    if len(w_orig) != len(w_new):
        return False
    return all(_is_gender_pair(a, b) for a, b in zip(w_orig, w_new))


# ---------------------------------------------------------------------------
# Motore rule-based (deterministico)
# ---------------------------------------------------------------------------

class RuleRewriter:
    """Flip morfologico dei token indicati dal selettore. Deterministico."""

    name = 'rule'

    def rewrite(self, ita_line: str, eng_line: Optional[str],
                target_gender: str,
                tokens: List[Tuple[str, str]]) -> Optional[str]:
        """tokens: lista (testo_token, genere_espresso) dal selettore.
        Ritorna la riga riscritta o None se non c'è nulla da cambiare."""
        out = ita_line
        changed = False
        for tok_text, expressed in tokens:
            if expressed == target_gender:
                continue
            flipped = flip_word(tok_text, target_gender)
            if flipped is None:
                continue
            # sostituzione word-boundary della prima occorrenza non ancora toccata
            pattern = re.compile(r'\b' + re.escape(tok_text) + r'\b')
            new_out, n = pattern.subn(flipped, out, count=1)
            if n:
                out = new_out
                changed = True
        return out if changed else None


# ---------------------------------------------------------------------------
# Motore LLM locale (llama-cpp, es. Qwen2.5-14B GGUF)
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "Sei un correttore di sottotitoli italiani. Ti viene data una riga "
    "italiana, il testo originale inglese e il GENERE reale del parlante "
    "(rilevato dalla voce). Riscrivi la riga adeguando al genere del "
    "parlante SOLO le parole che si riferiscono al parlante stesso "
    "(participi, aggettivi, articoli in prima persona).\n"
    "REGOLE:\n"
    "- NON cambiare parole riferite ad altre persone o a oggetti.\n"
    "- NON cambiare significato, ordine delle parole, punteggiatura.\n"
    "- Se la riga è già corretta per quel genere, ricopiala IDENTICA.\n"
    "- Rispondi SOLO con la riga riscritta, nient'altro."
)

_LLM_FEWSHOT = [
    ("EN: I went to a party.\nIT: Sono andato a una festa.\nGENERE PARLANTE: FEMMINA",
     "Sono andata a una festa."),
    ("EN: I'm sure I don't.\nIT: Ora sono sicuro di non saperlo.\nGENERE PARLANTE: FEMMINA",
     "Ora sono sicura di non saperlo."),
    ("EN: I'm tired and confused.\nIT: Sono stanco e confuso.\nGENERE PARLANTE: FEMMINA",
     "Sono stanca e confusa."),
    ("EN: I was never cool.\nIT: Non sono mai stato un figo.\nGENERE PARLANTE: MASCHIO",
     "Non sono mai stato un figo."),
    ("EN: He said I was wrong.\nIT: Ha detto che mi sbagliavo.\nGENERE PARLANTE: FEMMINA",
     "Ha detto che mi sbagliavo."),
    ("EN: I was born ready. She wasn't.\nIT: Io sono nato pronto. Lei no.\nGENERE PARLANTE: FEMMINA",
     "Io sono nata pronta. Lei no."),
]

_GENDER_LABEL = {'F': 'FEMMINA', 'M': 'MASCHIO'}


class LlamaRewriter:
    """Riscrittura con LLM locale GGUF (llama-cpp-python)."""

    name = 'llm'

    def __init__(self, model_path: str, log_callback: Optional[Callable] = None):
        self.model_path = model_path
        self.log = log_callback or (lambda m: None)
        self._model = None

    def load(self) -> bool:
        try:
            from utils.cuda_dll_path import ensure_torch_lib_on_path
            ensure_torch_lib_on_path()
        except Exception:
            pass
        try:
            from llama_cpp import Llama
        except Exception as _e:   # anche RuntimeError (DLL CUDA non trovata)
            self.log(f"llama-cpp-python non disponibile: {_e}")
            return False
        self.log("  📦 Caricamento LLM per riscrittura genere...")
        self._model = Llama(model_path=self.model_path, n_gpu_layers=-1,
                            n_ctx=2048, n_batch=512, verbose=False)
        return True

    def unload(self):
        if self._model is not None:
            del self._model
            self._model = None
        import gc
        gc.collect()

    def rewrite(self, ita_line: str, eng_line: Optional[str],
                target_gender: str,
                tokens: List[Tuple[str, str]] = None) -> Optional[str]:
        if self._model is None:
            return None
        messages = [{"role": "system", "content": _LLM_SYSTEM}]
        for q, a in _LLM_FEWSHOT:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})
        user = (f"EN: {eng_line or '-'}\nIT: {ita_line}\n"
                f"GENERE PARLANTE: {_GENDER_LABEL[target_gender]}")
        messages.append({"role": "user", "content": user})
        try:
            resp = self._model.create_chat_completion(
                messages=messages, temperature=0.0, top_p=0.1,
                max_tokens=160)
            out = resp['choices'][0]['message']['content'].strip()
            # una sola riga, senza prefissi
            out = out.splitlines()[0].strip() if out else ''
            out = re.sub(r'^(IT:|RIGA:)\s*', '', out)
            return out or None
        except Exception as e:
            logger.warning(f"LlamaRewriter errore: {e}")
            return None


# ---------------------------------------------------------------------------
# Applicazione con validatore
# ---------------------------------------------------------------------------

def apply_rewrite(engine, ita_line: str, eng_line: Optional[str],
                  target_gender: str,
                  tokens: List[Tuple[str, str]]) -> Tuple[str, str]:
    """Riscrive con `engine` e applica il validatore.

    Ritorna (riga_finale, esito) con esito in:
      'rewritten'  — riscritta e validata
      'unchanged'  — il testo esprimeva già il genere giusto
      'rejected'   — output del motore respinto dal validatore → originale
      'no_output'  — il motore non ha prodotto nulla → originale
    """
    needs = [t for t in tokens if t[1] != target_gender]
    if not needs:
        return ita_line, 'unchanged'
    out = engine.rewrite(ita_line, eng_line, target_gender, tokens)
    if not out:
        return ita_line, 'no_output'
    if out.strip() == ita_line.strip():
        return ita_line, 'no_output'
    if validate_rewrite(ita_line, out):
        return out, 'rewritten'
    logger.debug(f"Rewrite respinto dal validatore: '{ita_line}' -> '{out}'")
    return ita_line, 'rejected'
