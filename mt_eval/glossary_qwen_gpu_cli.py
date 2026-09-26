# -*- coding: utf-8 -*-
"""
Estrattore Qwen del glossario per-show - Entrypoint subprocess GPU
File: mt_eval/glossary_qwen_gpu_cli.py

Esegue SOLO il canale Qwen (mt_eval/glossary_qwen_extract.py) nel venv
PRINCIPALE del progetto invece che in venv_glossary/: quel modulo importa
solo `llama_cpp` (nessun torch/transformers), quindi gira identico in
qualunque venv abbia llama-cpp-python. Il venv principale ha gia' una
build CUDA di llama-cpp-python provata in produzione dal gender corrector
sullo stesso modello (core/gender_corrector.py, n_gpu_layers=-1) — questo
la riusa invece di installarne una seconda in venv_glossary/, che
romperebbe l'isolamento voluto tra i due venv (vedi
mt_eval/glossary_align.py) invece di rispettarlo.

Lanciato come SCRIPT diretto (mai `-m core...`, stesso motivo di
core/glossary_builder_cli.py): non importa nulla dal package `core`.

Uso (chiamato da mt_eval/glossary_qwen_bridge.py mentre gira in
venv_glossary/, mai manualmente):
    venv\\Scripts\\python mt_eval\\glossary_qwen_gpu_cli.py <request.json>

Formato request.json:
    {
      "qwen_model_path": "C:\\...\\qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf",
      "n_gpu_layers": -1,
      "result_out": "C:\\...\\glossary_qwen_gpu_result.json",
      "terms": [
        {"term": "Ark", "pairs": [{"source": "...", "reference": "..."}, ...]},
        ...
      ]
    }

Stdout: una riga JSON per evento:
    {"ev":"vram_warning","free_mb":N,"msg":"..."}   (non fatale, solo log)
    {"ev":"cpu_fallback","msg":"..."}               (non fatale, solo log)
    {"ev":"progress","term_idx":N,"term_total":N,"term":"...","done":N,"total":N}
    {"ev":"done","result_path":"<path assoluto>"}
    {"ev":"error","msg":"..."}

Exit code: 0 = completato, 1 = errore fatale, 2 = argomenti invalidi.
"""
import json
import subprocess
import sys
from pathlib import Path

# Il 14B Q4_K_M pesa ~9GB di soli pesi (misurato, vedi consultazione di
# progetto): sotto questa soglia di VRAM libera l'offload GPU rischia lo
# sconfinamento silenzioso di WDDM (nessun OOM, solo rallentamento) — qui
# e' solo un avviso in log, non un blocco: non e' un segnale affidabile
# abbastanza per decidere da solo.
_MIN_FREE_VRAM_MB = 10000


def _emit(event: dict) -> None:
    try:
        print(json.dumps(event, ensure_ascii=False), flush=True)
    except OSError:
        pass  # padre morto (pipe rotta): nessuno legge piu', niente da fare


def _free_vram_mb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def main(argv: list) -> int:
    if len(argv) < 2:
        _emit({"ev": "error", "msg": "argomento request.json mancante"})
        return 2

    req_path = Path(argv[1])
    if not req_path.exists():
        _emit({"ev": "error", "msg": f"request.json non trovato: {req_path}"})
        return 2

    try:
        req = json.loads(req_path.read_text(encoding='utf-8'))
    except Exception as e:
        _emit({"ev": "error", "msg": f"parsing request.json fallito: {e}"})
        return 2

    qwen_model_path = req.get('qwen_model_path')
    terms = req.get('terms', [])
    n_gpu_layers = req.get('n_gpu_layers')
    if n_gpu_layers is None:
        n_gpu_layers = -1
    if not qwen_model_path:
        _emit({"ev": "error", "msg": "qwen_model_path obbligatorio"})
        return 2
    if not Path(qwen_model_path).exists():
        _emit({"ev": "error", "msg": f"modello Qwen non trovato: {qwen_model_path}"})
        return 2

    free_mb = _free_vram_mb()
    if free_mb is not None and free_mb < _MIN_FREE_VRAM_MB:
        _emit({"ev": "vram_warning", "free_mb": free_mb,
               "msg": f"VRAM libera {free_mb}MB, sotto la soglia consigliata "
                      f"{_MIN_FREE_VRAM_MB}MB: possibile spillover silenzioso "
                      f"(WDDM) — l'estrazione potrebbe risultare piu' lenta "
                      f"della CPU invece che piu' veloce"})

    mt_eval_dir = str(Path(__file__).resolve().parent)
    if mt_eval_dir not in sys.path:
        sys.path.insert(0, mt_eval_dir)

    try:
        import glossary_qwen_extract as gq
    except Exception as e:
        _emit({"ev": "error", "msg": f"import motore estrazione fallito: {e}"})
        return 1

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
        from llama_cpp.llama_cpp import llama_supports_gpu_offload
        if n_gpu_layers != 0 and not llama_supports_gpu_offload():
            _emit({"ev": "cpu_fallback", "msg":
                   "llama-cpp-python in questo venv non ha supporto GPU: "
                   "l'estrazione girera' su CPU, molto piu' lenta"})
    except Exception:
        pass

    try:
        gq.load(qwen_model_path, n_gpu_layers=n_gpu_layers)
    except Exception as e:
        _emit({"ev": "error", "msg": f"caricamento modello Qwen fallito: {e}"})
        return 1

    results_out = {}
    try:
        for idx, item in enumerate(terms):
            term = item["term"]
            pairs = item["pairs"]

            def _prog(done, total, _term=term, _idx=idx):
                _emit({"ev": "progress", "term_idx": _idx, "term_total": len(terms),
                       "term": _term, "done": done, "total": total})

            extracted = gq.extract_spans(term, pairs, _prog)
            results_out[term] = [{"kind": r.kind, "text": r.text} for r in extracted]
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        _emit({"ev": "error", "msg": f"eccezione fatale durante l'estrazione: {e}"})
        return 1
    finally:
        gq.unload()

    result_path = req.get('result_out') or str(req_path.with_suffix('.result.json'))
    try:
        Path(result_path).write_text(
            json.dumps(results_out, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        _emit({"ev": "error", "msg": f"scrittura result.json fallita: {e}"})
        return 1

    _emit({"ev": "done", "result_path": result_path})
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv))
