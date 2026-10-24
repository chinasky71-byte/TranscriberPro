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


def _load_util(name):
    """Modulo di utils/ caricato da file (solo libreria standard): `import utils` qui NON deve ancora avvenire (importa PyQt6)."""
    spec = importlib.util.spec_from_file_location('tp_' + name, ROOT / 'utils' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prepare_llama():
    """DLL CUDA di torch/lib sul PATH, poi llama_cpp."""
    _load_util('cuda_dll_path').ensure_torch_lib_on_path()
    import llama_cpp  # noqa: F401  -- PRIMO import nativo del processo (vedi docstring)
    return llama_cpp


def _open_channel():
    out = os.fdopen(os.dup(1), 'w', encoding='ascii', buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    # dup2 sposta solo il descrittore del C runtime: le DLL che scrivono sull'handle standard di Windows (driver CUDA/Vulkan,
    # CRT statici) userebbero ancora il canale di protocollo.
    _load_util('platform_compat').point_stdout_handle_to_stderr()
    return out


PARENT_POLL_S = 2.0


def _watch_parent():
    """Se il processo padre muore (anche con TerminateProcess) il figlio non deve restare con la VRAM occupata, neanche dentro un
    caricamento o una decodifica nativi in cui non legge lo stdin: esce da solo."""
    import threading
    import time
    ppid = os.getppid()
    compat = _load_util('platform_compat')

    def alive():
        # POSIX: se il padre muore il figlio e' adottato (ppid cambia); Windows: handle sul pid del padre
        return os.getppid() == ppid if os.name != 'nt' else compat.process_alive(ppid)

    def loop():
        while True:
            time.sleep(PARENT_POLL_S)
            if not alive():
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()


def main():
    chan = _open_channel()
    _watch_parent()

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
        from utils.translations import get_translations
    except Exception as exc:
        emit({'ev': 'error', 'kind': 'runtime', 'msg': f'{type(exc).__name__}: {exc}', 'phase': 'start'})
        return 1
    emit({'ev': 'ready'})

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
