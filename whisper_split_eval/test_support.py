"""
Estrae il metodo REALE FasterWhisperEngine._split_segment_by_words dal
sorgente del motore (ast, nessun import di torch/config/modelli) e lo lega a
un finto `self` con una finta config: cosi' test e controllo negativo
eseguono esattamente il codice di produzione, aggancio compreso.
"""
from __future__ import annotations

import ast
import logging
import sys
import textwrap
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / 'core' / 'engines' / 'faster_whisper_engine.py'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeConfig:
    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.calls = []

    def get(self, key, default=None):
        self.calls.append(key)
        return self.settings.get(key, default)


def _method_source() -> str:
    src = ENGINE_PATH.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'FasterWhisperEngine':
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == '_split_segment_by_words':
                    return textwrap.dedent(ast.get_source_segment(src, f))
    raise RuntimeError('metodo _split_segment_by_words non trovato')


def engine_method(option_on, config: FakeConfig = None, new_module=None, lang='en'):
    """Ritorna una funzione split(segment) = metodo reale del motore legato a
    un finto self. option_on: True/False/None (None = chiave assente).
    new_module: modulo sostitutivo per core.whisper_sentence_split (test di
    eccezione/risultato non valido)."""
    cfg = config or FakeConfig({} if option_on is None else {'whisper_split_sentence_aware': option_on})
    ns = {'logger': logging.getLogger('whisper_split_eval_fake')}
    exec(compile(_method_source(), str(ENGINE_PATH), 'exec'), ns)
    fn = ns['_split_segment_by_words']
    fake_self = types.SimpleNamespace(config=cfg, _split_lang=lang)
    if new_module is None:
        new_module = real_new_module()

    def split(seg, *a, **k):
        # `from core.whisper_sentence_split import ...` senza eseguire
        # core/__init__ (cache_bootstrap): pacchetto 'core' finto se assente
        saved = {m: sys.modules.get(m) for m in ('core', 'core.whisper_sentence_split')}
        if saved['core'] is None:
            stub = types.ModuleType('core')
            stub.__path__ = []
            sys.modules['core'] = stub
        sys.modules['core.whisper_sentence_split'] = new_module
        try:
            return fn(fake_self, seg, *a, **k)
        finally:
            for m, v in saved.items():
                if v is None:
                    sys.modules.pop(m, None)
                else:
                    sys.modules[m] = v
    return split


def real_new_module():
    import importlib.util
    name = '_wse_real_new_split'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(ROOT / 'core' / 'whisper_sentence_split.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
