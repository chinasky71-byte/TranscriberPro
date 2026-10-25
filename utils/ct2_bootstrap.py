# -*- coding: utf-8 -*-
"""
Bootstrap ctranslate2 — inizializza il contesto GPU PRIMA di PyTorch.

Problema (verificato il 24/10/2026 su Ubuntu 26.04, GPU AMD Radeon RX 9060 XT
(RDNA4, gfx1200), ROCm 7.0, torch 2.10.0+rocm7.0, ctranslate2 4.8.3):

  se PyTorch inizializza per primo il contesto HIP (Demucs e i controlli VRAM
  via torch.cuda.mem_get_info lo fanno prima di Whisper), la prima inferenza
  faster-whisper/ctranslate2 termina con SIGSEGV (exit -11) dentro encode().
  Lo stesso crash colpisce detect_language(). Invertendo l'ordine — ctranslate2
  prima di qualsiasi chiamata torch.cuda — tutto funziona.

  `ctranslate2.get_cuda_device_count()` crea il contesto del dispositivo senza
  caricare alcun modello: e' l'inizializzazione minima e costa pochi ms.

Nota: `import torch` e' necessario prima di `import ctranslate2` perche' la
ruota ROCm di ctranslate2 carica le librerie HIP fornite dal wheel torch
(libhiprand.so.1 ecc.); importare torch non inizializza pero' il contesto.

Chiamare `ensure_ct2_initialized()` il prima possibile nel processo che esegue
la trascrizione (core/pipeline_cli.py), prima di importare/usare torch.cuda.
Su macchine senza ctranslate2 o senza GPU la funzione non fa nulla e ritorna
False, senza sollevare eccezioni.

Variabile d'ambiente: TP_SKIP_CT2_INIT=1 disattiva il bootstrap.
"""
import os
import sys

_done = False


def ensure_ct2_initialized() -> bool:
    """Inizializza ctranslate2 (contesto GPU) se possibile. Idempotente.

    Returns:
        True se ctranslate2 e' stato inizializzato (o lo era gia'), False se
        non disponibile / disattivato / errore.
    """
    global _done
    if _done:
        return True
    if os.environ.get('TP_SKIP_CT2_INIT') == '1':
        return False
    # Il SIGSEGV riguarda solo ROCm (Linux): su Windows non si tocca l'ordine
    # di import di torch/onnxruntime/llama_cpp nel processo.
    if not sys.platform.startswith('linux'):
        return False
    try:
        import torch  # noqa: F401  (carica le librerie HIP/CUDA del wheel)
        import ctranslate2
        ctranslate2.get_cuda_device_count()
        _done = True
        return True
    except Exception:
        # ctranslate2 assente, ruota CPU, driver non disponibile: non e' un
        # errore di questa funzione. Chi usa ctranslate2 gestira' il proprio.
        return False
