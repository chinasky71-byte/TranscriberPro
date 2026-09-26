# -*- coding: utf-8 -*-
"""
Windows: rende visibili a llama-cpp-python le DLL CUDA 12 che arrivano con torch.

La wheel CUDA di llama-cpp-python (ggml-cuda.dll) dipende da cudart64_12.dll e cublas64_12.dll, che NON sono
incluse nella wheel: su un PC senza il CUDA Toolkit 12.x nel PATH `import llama_cpp` fallisce con
"Failed to load shared library ... llama.dll (or one of its dependencies)" se torch non e' gia' stato importato
nel processo. Le stesse DLL sono in <site-packages>/torch/lib: basta anteporre quella cartella al PATH PRIMA di
importare llama_cpp. Non importa torch (si localizza il pacchetto con find_spec), quindi e' economico e sicuro
nei processi che non devono caricare torch.

Uso:
    from utils.cuda_dll_path import ensure_torch_lib_on_path
    ensure_torch_lib_on_path()
    from llama_cpp import Llama
"""
import importlib.util
import os


def ensure_torch_lib_on_path() -> bool:
    """Antepone torch/lib al PATH del processo (solo Windows). True se la cartella esiste ed e' nel PATH."""
    if os.name != 'nt':
        return False
    try:
        spec = importlib.util.find_spec('torch')
        if spec is None or not spec.submodule_search_locations:
            return False
        lib = os.path.join(list(spec.submodule_search_locations)[0], 'lib')
        if not os.path.isdir(lib):
            return False
        path = os.environ.get('PATH', '')
        if lib.lower() not in [p.lower() for p in path.split(os.pathsep)]:
            os.environ['PATH'] = lib + os.pathsep + path
        return True
    except Exception:
        return False
