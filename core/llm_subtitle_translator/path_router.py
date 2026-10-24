"""
Instradamento del traduttore LLM: transformers (bf16 / NF4), GGUF o NLLB-FT
============================================================================
Si arriva qui con `llm_translator_gguf_enabled` acceso (default dal 24/10, vedi `LLMSubtitleTranslator._acquire_engine`): con il flag
spento il traduttore chiama `get_engine` come ha sempre fatto e questo modulo non viene nemmeno importato.

Qui si leggono i fatti (backend, VRAM libera, GGUF presenti, ruota di llama-cpp-python) e si passano alla funzione
pura `utils.translator_path_select.choose_translator_path`, che decide. Ogni esito e' scritto nel log: il percorso
scelto, e per il ripiego su NLLB il MOTIVO. Mai un cambio di motore in silenzio, mai un'eccezione verso il chiamante:
`acquire_engine` restituisce un motore oppure None, e None vuol dire "traduci con NLLB fine-tuned".
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from utils import translator_path_select as sel
from utils.logger import setup_logger
from utils.translations import tr

from .engine import DEFAULT_MODEL_KEY, PROJECT_ROOT, _free_vram_gb

logger = setup_logger(__name__)

DEFAULT_GGUF_DIR = PROJECT_ROOT / "models" / "translategemma-12b-gguf"

# Nome del file: qualunque prefisso, poi la quantizzazione subito prima di ".gguf" (es.
# translategemma-12b-it-finale-Q3_K_M.gguf). I file a pezzi ('-00001-of-0000N') non sono supportati: i 12B quantizzati
# a 3-4 bit stanno in un file solo, e un pezzo mancante darebbe un modello rotto.
_QUANT_FILE = re.compile(r"[-_.](" + "|".join(sel.QUANT_PREFERENCE) + r")\.gguf$", re.I)


def scan_gguf_dir(directory) -> Dict[str, str]:
    """{quantizzazione: percorso del file} per i GGUF presenti in `directory` (vuoto se la cartella non esiste)."""
    found: Dict[str, str] = {}
    try:
        for f in sorted(Path(directory).glob("*.gguf")):
            m = _QUANT_FILE.search(f.name)
            if m and f.is_file():
                found.setdefault(m.group(1).upper(), str(f))
    except Exception as exc:
        logger.debug(f"scan_gguf_dir: {exc}")
    return found


def _torch_state() -> Tuple[bool, bool]:
    """(torch vede una GPU, e' ROCm). Senza torch: (False, False)."""
    try:
        import torch
        return bool(torch.cuda.is_available()), bool(getattr(torch.version, "hip", None))
    except Exception:
        return False, False


def runtime_inputs(torch_cuda: Optional[bool] = None, torch_hip: Optional[bool] = None,
                   report=None, marker: Optional[str] = None,
                   free_fn: Optional[Callable[[], float]] = None) -> Tuple[str, Optional[float], bool]:
    """(backend, VRAM libera in GiB, llama-cpp-python puo' usare la GPU). Gli argomenti servono ai test.

    - torch vede la GPU: 'cuda' (NVIDIA) o 'rocm' (AMD con torch ROCm); VRAM libera come la legge il motore storico
      (torch.cuda.mem_get_info).
    - altrimenti, ruota Vulkan di llama-cpp-python e una GPU con driver Vulkan reale: 'vulkan'. La VRAM libera la da'
      utils.gpu_detect; se il sistema non la espone si usa la VRAM TOTALE (il caricamento che non entra fallisce e il
      ripiego e' dichiarato).
    - altrimenti 'cpu'.
    La ruota di llama-cpp-python e' quella dichiarata dal marcatore dell'installer (utils.llm_model_select).
    """
    from utils.llm_model_select import llama_backend_marker
    if torch_cuda is None:
        torch_cuda, torch_hip = _torch_state()
    marker = marker or llama_backend_marker()
    if torch_cuda:
        backend = "rocm" if torch_hip else "cuda"
        free = (free_fn or _free_vram_gib_safe)()
    else:
        backend, free = "cpu", None
        if marker == "vulkan":
            if report is None:
                from utils.gpu_detect import detect_gpus
                report = detect_gpus()
            vk = [g for g in report.gpus if "vulkan" in g.backends and g.vram_mib]
            if vk:
                g = max(vk, key=lambda x: x.vram_mib)
                mib = g.vram_free_mib if g.vram_free_mib is not None else g.vram_mib
                backend, free = "vulkan", mib / 1024.0
    llama_gpu = marker == "vulkan" or (backend == "cuda" and marker == "cuda")
    return backend, free, llama_gpu


def _free_vram_gib_safe() -> float:
    try:
        return float(_free_vram_gb())
    except Exception:
        return 0.0


def _config_values(cfg_get: Callable) -> dict:
    def num(key, default, cast):
        try:
            v = cast(cfg_get(key, default))
        except Exception:
            return default
        return v if v == v and v not in (float('inf'), float('-inf')) and v > 0 else default     # niente NaN, infiniti, <= 0

    def flag(key, default):
        v = cfg_get(key, default)
        if isinstance(v, str):
            return v.strip().lower() in ('1', 'true', 'yes', 'si', 'on')
        return bool(v)
    return dict(
        directory=(str(cfg_get("llm_translator_gguf_dir", "") or "").strip() or str(DEFAULT_GGUF_DIR)),
        quant=sel.normalize_quant(cfg_get("llm_translator_gguf_quant", "auto")),
        n_parallel=max(1, num("llm_translator_gguf_parallel", sel.DEFAULT_N_PARALLEL, int)),
        nf4_min=num("llm_translator_nf4_min_free_gb", sel.DEFAULT_NF4_MIN_FREE_GIB, float),
        gguf_before_nf4=flag("llm_translator_gguf_before_nf4", sel.DEFAULT_GGUF_BEFORE_NF4),
        gguf_min_free={q: num(key, default, float) for q, (key, default) in (
            ("Q4_K_M", ("llm_translator_gguf_q4_min_free_gb", sel.DEFAULT_GGUF_MIN_FREE_GIB["Q4_K_M"])),
            ("IQ3_M", ("llm_translator_gguf_iq3_min_free_gb", sel.DEFAULT_GGUF_MIN_FREE_GIB["IQ3_M"])))},
    )


def acquire_engine(model_key: str, log_callback: Optional[Callable], adapter: Optional[str],
                   model_path: Optional[str], *, get_engine_fn: Callable, cfg_get: Callable,
                   log: Callable[[str], None],
                   inputs: Optional[Tuple[str, Optional[float], bool]] = None):
    """Il motore da usare per questo file, oppure None = "traduci con NLLB fine-tuned".

    `get_engine_fn`: `engine.get_engine` (iniettabile per i test). `inputs`: (backend, free_gib, llama_gpu) gia'
    letti (test); None = si leggono ora.
    """
    def legacy():
        return get_engine_fn(model_key, log_callback, adapter=adapter, model_path=model_path)

    # Solo TranslateGemma-12B ha un percorso GGUF.
    if model_key != DEFAULT_MODEL_KEY:
        return legacy()
    try:
        return _acquire(model_key, log_callback, adapter, legacy, cfg_get, log, inputs)
    except Exception as exc:
        # Un difetto del router non deve fermare la coda: si torna al percorso storico, che e' quello provato.
        logger.error(f"path_router: {exc}", exc_info=True)
        log(tr('gg_router_error').format(exc=exc))
        return legacy()


def _acquire(model_key, log_callback, adapter, legacy, cfg_get, log, inputs):
    from . import engine as _engine_mod
    from . import gguf_engine as ge

    # Un motore gia' in memoria (file precedente della coda) si riusa senza ridecidere: la VRAM libera di adesso
    # NON comprende i pesi che il motore stesso occupa, e porterebbe a scartare il percorso con cui ha caricato.
    if _engine_mod._engine is not None:
        return legacy()
    loaded = ge.current_gguf_engine()
    if loaded is not None:
        return loaded

    cfg = _config_values(cfg_get)
    backend, free, llama_gpu = inputs if inputs is not None else runtime_inputs()
    if backend in ('cuda', 'rocm') and not free:
        # torch vede la GPU ma la VRAM libera non si legge: non si sceglie al buio, vale il percorso storico.
        return legacy()

    available: Dict[str, str] = {}
    gguf_note = None
    if adapter:
        # Il GGUF e' gia' fuso: un adattatore LoRA configurato non verrebbe applicato, e il modello sarebbe un altro.
        gguf_note = 'gg_adapter_blocks_gguf'
    elif not importlib.util.find_spec("llama_cpp"):
        gguf_note = 'gg_llama_missing'
    elif not llama_gpu:
        gguf_note = 'gg_llama_no_gpu'
    else:
        available = scan_gguf_dir(cfg["directory"])

    choice = sel.choose_translator_path(
        free, backend, gguf_available=available.keys(), quant=cfg["quant"],
        nf4_min_free_gib=cfg["nf4_min"], n_parallel=cfg["n_parallel"], gguf_before_nf4=cfg["gguf_before_nf4"],
        gguf_min_free_gib=cfg["gguf_min_free"])
    if gguf_note and choice.kind in (sel.GGUF, sel.NLLB):
        log(tr(gguf_note))        # solo se il GGUF serviva davvero a questa scheda
    log(tr('gg_path_chosen').format(path=choice.label, free_gb=free or 0.0, backend=backend))

    if choice.kind in (sel.BF16, sel.NF4):
        ge.unload_gguf_engine()
        return legacy()

    load_failed = False
    if choice.kind == sel.GGUF:
        _engine_mod.unload_engine()
        try:
            return ge.get_gguf_engine(
                available[choice.quant], choice.quant, model_key, log_callback,
                n_parallel=cfg["n_parallel"])
        except ge.GGUFCancelled:
            return None                 # Stop dell'utente: nessun ripiego (ne' NF4 ne' NLLB) e nessun messaggio di errore
        except Exception as exc:
            logger.warning(f"Caricamento GGUF fallito: {exc}", exc_info=True)
            log(tr('gg_load_failed').format(exc=exc))
            load_failed = True
            if backend == 'cuda' and free and free >= cfg["nf4_min"]:
                # NF4 e' il ripiego automatico se il GGUF non si carica e la scheda lo regge: con gguf_before_nf4 spento il
                # GGUF si sceglie solo sotto nf4_min, quindi qui ci si arriva solo con l'opzione accesa.
                log(tr('gg_load_failed_nf4'))
                try:
                    return legacy()
                except Exception as exc2:       # niente secondo giro di legacy() dal gestore del router
                    logger.warning(f"Ripiego NF4 fallito: {exc2}", exc_info=True)
                    log(tr('gg_load_failed').format(exc=exc2))
            # Altrimenti la VRAM non regge bf16/NF4 (non si sarebbe scelto il GGUF): NLLB-FT.

    if choice.reason == 'gguf_missing' and not load_failed:
        # Nessun GGUF utilizzabile: chi non li ha ancora (installer non aggiornato) non deve peggiorare. Vale il percorso
        # storico, che e' quello che questa scheda usava prima dell'accensione di default.
        log(tr(gguf_note) if gguf_note else tr('gg_missing_legacy').format(dir=cfg["directory"]))
        return legacy()

    reason = tr('gg_reason_load_failed') if load_failed else _reason_text(choice, free, cfg)
    log(tr('gg_using_nllb').format(reason=reason))
    return None


def _reason_text(choice: sel.PathChoice, free: Optional[float], cfg: dict) -> str:
    r = choice.reason
    if r == 'no_gpu':
        return tr('gg_reason_no_gpu')
    if r == 'gguf_missing':
        return tr('gg_reason_gguf_missing').format(dir=cfg["directory"])
    if r == 'quant_unknown':
        return tr('gg_reason_quant_unknown').format(quant=cfg["quant"])
    if r == 'vram_too_low':
        return tr('gg_reason_vram_too_low').format(free_gb=free or 0.0, need_gb=choice.need_gib or 0.0)
    return r
