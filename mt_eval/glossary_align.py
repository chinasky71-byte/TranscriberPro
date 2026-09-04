# -*- coding: utf-8 -*-
"""
Allineamento parola-parola EN->IT via SimAlign+LaBSE.
File: mt_eval/glossary_align.py

Estrae, per ogni occorrenza di un termine candidato nel testo inglese, lo
span italiano corrispondente nel blocco allineato — sostituisce la
metrica binaria verbatim/assente con la resa REALE prodotta dal motore,
cosi' il clustering (glossary_cluster.py) puo' distinguere un termine
sempre tradotto allo stesso modo (sano) da uno reso in modi diversi
(vero difetto).

Richiede simalign+sentence-transformers+torch: NON installati nel venv
principale del progetto (conflitto di versione con transformers==4.57.6,
richiesto da qwen-asr/whisperx — vedi CLAUDE.md). Gira SOLO nel venv
dedicato `venv_glossary/` (creato una tantum, stesso pattern di
venv_canary/venv_comet). Import lazy: questo modulo non fallisce al
caricamento se le dipendenze mancano, solo quando si prova a usarlo.
"""
import re
from typing import List, Optional, Tuple

_WORD_RE = re.compile(r"\w+(?:['’]\w+)?|[^\w\s]", re.UNICODE)

_aligner = None
_aligner_model_name = None


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(text)


def load(model_name: str = "sentence-transformers/LaBSE", device: str = "cpu"):
    """Carica il modello di allineamento una volta (singleton di modulo).
    Solleva ImportError con messaggio chiaro se le dipendenze mancano."""
    global _aligner, _aligner_model_name
    if _aligner is not None and _aligner_model_name == model_name:
        return _aligner
    try:
        from simalign import SentenceAligner
    except ImportError as e:
        raise ImportError(
            "simalign/sentence-transformers non installati: usa "
            "venv_glossary\\Scripts\\python.exe, non il venv principale"
        ) from e
    _aligner = SentenceAligner(
        model=model_name, token_type="bpe", matching_methods="i",
        device=device)
    _aligner_model_name = model_name
    return _aligner


def unload():
    """Libera il modello (RAM/eventuale VRAM) prima di caricare Qwen —
    mai i due modelli insieme in memoria (vedi piano di sviluppo).

    gc.collect() + torch.cuda.empty_cache() liberano solo i riferimenti
    Python: il working set del processo (visibile in Task Manager) non
    torna all'OS finche' non lo si forza esplicitamente — stesso
    problema e stessa soluzione di utils/resource_monitor.py
    (release_ram_to_os), reimplementata qui invece che importata perche'
    questo processo gira in venv_glossary/, che non ha psutil e non puo'
    importare il package utils (vedi core/glossary_builder_cli.py)."""
    global _aligner, _aligner_model_name
    _aligner = None
    _aligner_model_name = None
    try:
        import gc
        for _ in range(3):
            gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        import sys
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetProcessWorkingSetSize(
                ctypes.c_void_p(-1), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
            kernel32.EmptyWorkingSet(ctypes.c_void_p(-1))
        else:
            import ctypes.util
            libc_name = ctypes.util.find_library('c') or 'libc.so.6'
            libc = ctypes.CDLL(libc_name)
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            libc.malloc_trim.restype = ctypes.c_int
            libc.malloc_trim(ctypes.c_size_t(0))
    except Exception:
        pass  # silenzioso — non critico


def _find_term_span(src_tokens: List[str], term: str) -> Optional[Tuple[int, int]]:
    """Prima occorrenza (inizio, fine_esclusa) del termine (1-3 parole) come
    sequenza contigua case-insensitive in src_tokens. LIMITE NOTO: se il
    termine compare piu' volte nello stesso blocco (raro nei sottotitoli,
    un blocco e' quasi sempre una battuta breve) solo la prima viene
    allineata — non un bug bloccante, segnalato in revisione come
    accettabile per ora."""
    term_tokens = _tokenize(term)
    n = len(term_tokens)
    if n == 0:
        return None
    term_low = [t.lower() for t in term_tokens]
    for i in range(len(src_tokens) - n + 1):
        if [t.lower() for t in src_tokens[i:i + n]] == term_low:
            return (i, i + n)
    return None


def extract_span(src_text: str, trg_text: str, term: str) -> Optional[str]:
    """Span italiano allineato all'occorrenza di `term` in `src_text`, o
    None se il termine non compare nella frase sorgente, o nessun token
    italiano vi si allinea (occorrenza trattata come "omessa" a valle)."""
    aligner = load()
    src_tokens = _tokenize(src_text)
    trg_tokens = _tokenize(trg_text)
    span = _find_term_span(src_tokens, term)
    if span is None or not trg_tokens:
        return None
    start, end = span
    try:
        aligns = aligner.get_word_aligns(src_tokens, trg_tokens)["itermax"]
    except Exception:
        return None
    trg_idx = sorted({j for (i, j) in aligns if start <= i < end})
    if not trg_idx:
        return None
    # Span contiguo min..max: cattura anche token italiani intermedi non
    # direttamente allineati (es. articoli), piu' leggibile per il cluster.
    lo, hi = trg_idx[0], trg_idx[-1]
    return " ".join(trg_tokens[lo:hi + 1])


def align_spans(pairs: List[dict], term: str) -> List[Optional[str]]:
    """Span italiano allineato per ogni coppia in `pairs` (dict con chiavi
    'source'/'reference', formato di build_film_bench.align()). Una entry
    None per occorrenza non allineabile — mai un'eccezione che interrompe
    il batch."""
    out = []
    for p in pairs:
        try:
            out.append(extract_span(p["source"], p["reference"], term))
        except Exception:
            out.append(None)
    return out
