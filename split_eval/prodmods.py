"""
Caricamento IN SOLA LETTURA dei moduli di produzione puri (nessun torch):

- core/subtitle_formatter.py        -> SubtitleFormatter
- core/subtitle_cleaner.py          -> SubtitleCleaner
- core/llm_subtitle_translator/postprocess.py -> process, wrap_block, ...

Si caricano PER PERCORSO con un nome di modulo privato, senza passare dal
pacchetto `core`: (1) core/__init__ importa utils.cache_bootstrap (crea
cartelle, imposta variabili d'ambiente); (2) i test di asr_eval sostituiscono
sys.modules['core'] con un modulo finto, e `import core.x` fallirebbe; (3)
core/llm_subtitle_translator/__init__ e' vuoto ma il pacchetto e' pensato
per import lazy. Il codice eseguito e' esattamente quello dei file reali.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMATTER_PATH = ROOT / 'core' / 'subtitle_formatter.py'
CLEANER_PATH = ROOT / 'core' / 'subtitle_cleaner.py'
POSTPROCESS_PATH = ROOT / 'core' / 'llm_subtitle_translator' / 'postprocess.py'

_cache = {}


def _load(name: str, path: Path):
    if name in _cache:
        return _cache[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclass/annotations lo richiedono
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    _cache[name] = mod
    return mod


def formatter_module():
    return _load('_split_eval_prod_subtitle_formatter', FORMATTER_PATH)


def cleaner_module():
    return _load('_split_eval_prod_subtitle_cleaner', CLEANER_PATH)


def postprocess_module():
    return _load('_split_eval_prod_postprocess', POSTPROCESS_PATH)


def SubtitleFormatter(**kw):
    """Istanza del formatter di produzione (stessi argomenti del costruttore)."""
    return formatter_module().SubtitleFormatter(**kw)


def SubtitleCleaner():
    return cleaner_module().SubtitleCleaner
