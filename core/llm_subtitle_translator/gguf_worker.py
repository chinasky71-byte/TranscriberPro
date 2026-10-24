# -*- coding: utf-8 -*-
"""Processo di lavoro del motore GGUF (llama.cpp): gira in un processo PULITO, fuori dal processo della pipeline.

Perche': su Windows (llama-cpp-python 0.3.34, ruote a backend dinamici) `llama_supports_gpu_offload()` va in access
violation se `llama_cpp` viene importato DOPO `utils` (che importa PyQt6) o dopo altri pacchetti nativi: stessa famiglia di
"onnxruntime prima di PyQt6". Nel processo figlio della pipeline `utils`/PyQt6 sono gia' caricati, quindi qui `llama_cpp` e'
il PRIMO import nativo del processo, e solo dopo si importa il motore (che importa `utils`).

Lanciato come SCRIPT diretto da `gguf_subprocess.GGUFSubprocessEngine` (mai `-m`, mai a mano). Protocollo: una riga JSON
(solo ASCII) per messaggio. Sull'stdin arrivano le richieste, sul canale di protocollo escono gli eventi:
    {"op":"load","gguf_path":..,"quant":..,"model_key":..,"n_parallel":N,"ctx_per_seq":N,"n_gpu_layers":N}
    {"op":"generate","conversations":[[{role,content}..]..],"max_new_tokens":N}
    {"op":"unload"}                                        (il processo esce)
    -> {"ev":"ready"} | {"ev":"log","msg":..} | {"ev":"loaded"} | {"ev":"result","outputs":[..]}
       | {"ev":"error","msg":..,"kind":"unknown_language"|"runtime"}
Il canale di protocollo e' un duplicato privato dell'stdout originale: l'stdout reale (fd 1) viene deviato sull'stderr, cosi'
le stampe native di ggml/llama.cpp non possono corrompere il protocollo.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _prepare_llama():
    """DLL CUDA di torch/lib sul PATH (stdlib-only, caricato da file: `import utils` qui NON deve ancora avvenire), poi llama_cpp."""
    spec = importlib.util.spec_from_file_location('tp_cuda_dll_path', ROOT / 'utils' / 'cuda_dll_path.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ensure_torch_lib_on_path()
    import llama_cpp  # noqa: F401  -- PRIMO import nativo del processo (vedi docstring)
    return llama_cpp


def _open_channel():
    out = os.fdopen(os.dup(1), 'w', encoding='ascii', buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def main():
    chan = _open_channel()

    def emit(ev):
        try:
            chan.write(json.dumps(ev) + '\n')   # ensure_ascii: nessun problema di codifica su Windows
            chan.flush()
        except OSError:
            pass                                # il processo padre e' morto: nessuno legge piu'

    try:
        _prepare_llama()
        sys.path[0] = str(ROOT)     # sys.path[0] e' la cartella dello script: i suoi moduli (engine, translator...) oscurerebbero altri pacchetti
        from core.llm_subtitle_translator import gguf_engine as ge
    except Exception as exc:
        emit({'ev': 'error', 'kind': 'runtime', 'msg': f'{type(exc).__name__}: {exc}', 'phase': 'start'})
        return 1
    emit({'ev': 'ready'})
    from utils.translations import get_translations

    engine = None
    for line in sys.stdin:
        if not line.strip():
            continue
        op = rid = None
        try:
            req = json.loads(line)
            op, rid = req.get('op'), req.get('id')
            if op == 'load':
                get_translations().set_language(req.get('lang') or 'en')     # messaggi nella lingua dell'app, non del locale di sistema
                if engine is not None:
                    engine.unload(quiet=True)
                    engine = None
                engine = ge.GGUFEngine(
                    req['gguf_path'], req['quant'], req['model_key'], lambda m: emit({'ev': 'log', 'msg': str(m)}),
                    n_parallel=req['n_parallel'], ctx_per_seq=req['ctx_per_seq'], n_gpu_layers=req['n_gpu_layers'])
                engine.load()
                emit({'ev': 'loaded', 'id': rid})
            elif op == 'generate':
                outs = engine.generate(req['conversations'], max_new_tokens=req['max_new_tokens'])
                emit({'ev': 'result', 'id': rid, 'outputs': outs})
            elif op == 'unload':
                break
            else:
                emit({'ev': 'error', 'id': rid, 'kind': 'runtime', 'msg': f'unknown request: {op!r}'})
        except Exception as exc:
            kind = 'unknown_language' if isinstance(exc, ge.UnknownLanguageError) else 'runtime'
            if op == 'load':
                engine = None           # caricamento fallito: nessuno stato a meta'
            emit({'ev': 'error', 'id': rid, 'kind': kind, 'msg': str(exc)})
    if engine is not None:
        try:
            engine.unload(quiet=True)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
