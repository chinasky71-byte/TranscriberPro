"""
Cache cleaner - cancella modelli HF/torch dalla cache locale dopo uso,
preservando i modelli marcati come italiani / sempre-necessari.

Chiamato dalla pipeline a fine processing per ogni file (vedi
ProcessingPipeline._cleanup()).
"""
import logging
import shutil
import time
from pathlib import Path

from utils.cache_bootstrap import HF_HUB_CACHE_DIR, TORCH_HUB_CACHE_DIR

logger = logging.getLogger(__name__)

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


def _is_preserved(slug: str) -> bool:
    s = slug.lower()
    return any(p.lower() in s for p in PRESERVE_PATTERNS)


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

    hf_root = Path(HF_HUB_CACHE_DIR)
    if hf_root.exists():
        for entry in hf_root.iterdir():
            if not entry.is_dir() or not entry.name.startswith('models--'):
                continue
            slug = _slug_from_dir(entry.name)
            if _is_preserved(slug):
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
