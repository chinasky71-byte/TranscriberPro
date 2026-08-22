"""
Cache cleaner - cancella modelli HF/torch dalla cache locale dopo uso,
preservando i modelli marcati come italiani / sempre-necessari.

Chiamato da ProcessingWorker.run() UNA volta sola a coda conclusa (fine
naturale o "Ferma") — NON per-file: i modelli (pyannote, ECAPA, Demucs...)
vengono riusati dagli elementi successivi della coda.
"""
import shutil
import time
from pathlib import Path

from utils.cache_bootstrap import HF_HUB_CACHE_DIR, TORCH_HUB_CACHE_DIR
# setup_logger, NON logging.getLogger: il file handler condiviso viene
# agganciato solo ai logger creati esplicitamente (altrimenti i warning
# di cleanup fallito si perderebbero nel vuoto).
from utils.logger import setup_logger

logger = setup_logger('utils.cache_cleaner')

# Slug HF (org/name) da PRESERVARE. Match substring case-insensitive sullo slug
# ricostruito dal nome dir HF (`models--ORG--NAME`).
PRESERVE_PATTERNS = (
    'jonatasgrosman/wav2vec2-large-xlsr-53-italian',
    'systran/faster-whisper-large-v3',
    'guillaumekln/faster-whisper-large-v3',
    'openai/whisper-large-v3',
)


def _slug_from_dir(dir_name: str) -> str:
    """models--facebook--nllb-200-3.3B -> facebook/nllb-200-3.3B"""
    if not dir_name.startswith('models--'):
        return dir_name
    return dir_name[len('models--'):].replace('--', '/')


def _production_llm_slug() -> str:
    """Slug HF del modello LLM che occupa lo slot di produzione (chiave
    `llm_translator_model` in config, o il default se assente/sconosciuta —
    stessa logica di ripiego di `LLMSubtitleTranslator._configured_model`).

    Va preservato come i motori ASR: è un download da svariati GB (12B in
    NF4), non un modello sperimentale usato una volta per un confronto. Import
    lazy: `engine.py` non porta torch a livello di modulo, ma non c'è motivo
    di caricarlo se questa funzione non viene chiamata.
    """
    try:
        from utils.config import get_config
        from core.llm_subtitle_translator.engine import (DEFAULT_MODEL_KEY,
                                                          MODEL_SPECS)
        key = (get_config().get('llm_translator_model', '') or '').strip()
        spec = MODEL_SPECS.get(key) or MODEL_SPECS.get(DEFAULT_MODEL_KEY)
        return spec.model_id if spec else ''
    except Exception as e:
        logger.warning(f"Slug modello LLM produzione non risolto: {e}")
        return ''


def _is_preserved(slug: str, extra_patterns: tuple = ()) -> bool:
    s = slug.lower()
    patterns = PRESERVE_PATTERNS + tuple(p for p in extra_patterns if p)
    return any(p.lower() in s for p in patterns)


def _try_rmtree(path: Path, retries: int = 2) -> bool:
    """rmtree con retry per gestire mmap lock di Windows dopo unload modelli."""
    for attempt in range(retries):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return True
        except (OSError, PermissionError) as e:
            if attempt < retries - 1:
                time.sleep(0.5)
                continue
            logger.warning(f"Cleanup fallito {path.name}: {e}")
            return False
    return False


def cleanup_non_italian_caches(log_callback=None) -> dict:
    """
    Cancella le sottocartelle della cache HF non incluse in PRESERVE_PATTERNS,
    e svuota la cache torch hub (Demucs).

    Returns: dict con liste 'removed', 'preserved', 'failed' (slug stringhe).
    """
    result = {'removed': [], 'preserved': [], 'failed': []}
    log = log_callback or (lambda m: None)

    llm_slug = _production_llm_slug()

    hf_root = Path(HF_HUB_CACHE_DIR)
    if hf_root.exists():
        for entry in hf_root.iterdir():
            if not entry.is_dir() or not entry.name.startswith('models--'):
                continue
            slug = _slug_from_dir(entry.name)
            if _is_preserved(slug, extra_patterns=(llm_slug,)):
                result['preserved'].append(slug)
                continue
            if _try_rmtree(entry):
                result['removed'].append(slug)
                log(f"   Cache rimossa: {slug}")
            else:
                result['failed'].append(slug)

    torch_ckpt = Path(TORCH_HUB_CACHE_DIR)
    if torch_ckpt.exists():
        for entry in torch_ckpt.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                    result['removed'].append(f"torch/{entry.name}")
                elif entry.is_dir():
                    if _try_rmtree(entry):
                        result['removed'].append(f"torch/{entry.name}")
                    else:
                        result['failed'].append(f"torch/{entry.name}")
            except Exception as e:
                logger.warning(f"Cleanup torch hub {entry.name}: {e}")
                result['failed'].append(f"torch/{entry.name}")

    return result
