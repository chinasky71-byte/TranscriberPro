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
    # Allineamento fr/es/de: NON preservato (scelta utente 09/10/2026, scaricato a ogni coda)
    'jonatasgrosman/wav2vec2-large-xlsr-53-english',
    'sentence-transformers/labse',    # canale di allineamento del Glossario per show
    'systran/faster-whisper-large-v3',
    'guillaumekln/faster-whisper-large-v3',
    'openai/whisper-large-v3',
    # Motori di trascrizione e modelli di supporto (decisione 08/10/2026): prima venivano cancellati a
    # fine coda e il primo file della coda successiva li riscaricava (Canary 4,8 GB: da 2 minuti fino a
    # 54 con una rete lenta). Oltre a questi, _configured_engine_slugs() preserva quelli in config.
    'nvidia/canary-qwen-2.5b',
    'qwen/qwen3-1.7b',                # tokenizer/config del SALM Canary
    'qwen/qwen3-asr-1.7b',
    'qwen/qwen3-forcedaligner-0.6b',
    'oliverguhr/fullstop-punctuation-multilang-large',
    'pyannote/',
    'jaesunghuh/voice-gender-classifier',
)

# Checkpoint della cache torch hub da NON svuotare (prefisso del nome file): Demucs htdemucs
# (955717e8-8726e21a.th, 80 MB, scaricato da dl.fbaipublicfiles.com a ogni coda).
TORCH_PRESERVE_PREFIXES = ('955717e8',)


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


def _org_name(spec) -> str:
    """'org/nome[/sottocartella]' -> 'org/nome'. Vuoto per percorsi locali o nomi senza org ('large-v3')."""
    text = str(spec or '').strip().replace(chr(92), '/')
    if not text or text.startswith('/') or (len(text) > 1 and text[1] == ':'):
        return ''
    parts = [x for x in text.split('/') if x]
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ''


def _configured_engine_slugs() -> tuple:
    """Slug dei modelli HF configurati per i motori di trascrizione, per la diarizzazione, per la
    punteggiatura e i Whisper specializzati per lingua (whisper_model_by_language): se si cambia modello
    in config, la sua cache viene preservata senza toccare questa lista."""
    slugs = []
    try:
        from utils.config import get_config
        cfg = get_config()
        for key in ('canary_model_id', 'qwen3_asr_model_id', 'qwen3_aligner_model_id',
                    'punctuation_model_id', 'diarization_model'):
            slugs.append(_org_name(cfg.get(key, '')))
        table = cfg.get('whisper_model_by_language', {}) or {}
        if isinstance(table, dict):
            slugs.extend(_org_name(v) for v in table.values())
    except Exception as e:
        logger.warning(f"Slug motori configurati non risolti: {e}")
    return tuple(x for x in slugs if x)


def _cleanup_enabled() -> bool:
    """Interruttore `model_cache_cleanup_enabled` (default True: la pulizia resta attiva per i modelli
    NON preservati)."""
    try:
        from utils.config import get_config
        v = get_config().get('model_cache_cleanup_enabled', True)
        if v is None:
            return True
        return v if isinstance(v, bool) else str(v).strip().lower() not in ('0', 'false', 'no', 'off')
    except Exception:
        return True


def _is_preserved(slug: str, extra_patterns: tuple = ()) -> bool:
    """Confronto ESATTO sullo slug (minuscolo); un pattern che finisce con '/' vale come prefisso
    ('pyannote/'). Prima era per sottostringa e preservava anche modelli "fratelli" (-Base, -turbo...)."""
    s = slug.lower()
    for p in PRESERVE_PATTERNS + tuple(x for x in extra_patterns if x):
        p = p.lower()
        if (s.startswith(p) if p.endswith('/') else s == p):
            return True
    return False


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

    if not _cleanup_enabled():
        logger.info("Pulizia cache modelli disattivata (model_cache_cleanup_enabled=false)")
        return result

    llm_slug = _production_llm_slug()
    engine_slugs = _configured_engine_slugs()

    hf_root = Path(HF_HUB_CACHE_DIR)
    if hf_root.exists():
        for entry in hf_root.iterdir():
            if not entry.is_dir() or not entry.name.startswith('models--'):
                continue
            slug = _slug_from_dir(entry.name)
            if _is_preserved(slug, extra_patterns=(llm_slug, *engine_slugs)):
                result['preserved'].append(slug)
                continue
            if _try_rmtree(entry):
                result['removed'].append(slug)
                log(f"   Cache rimossa: {slug}")
            else:
                result['failed'].append(slug)

    # Archivio di blob CONDIVISO (huggingface_hub 1.x, usato da venv_cohere/venv_glossary): i file veri stanno in
    # hub/blobs/<xx>/<hash> e le cartelle models--*/blobs hanno solo collegamenti. Cancellata la cartella del
    # modello il blob restava su disco (3,85 GB di Cohere): si tolgono quelli senza piu' nessun riferimento vivo.
    store = hf_root / 'blobs'
    if store.is_dir() and (store / '.huggingface-shared-blobs').exists():
        for refs in store.glob('*/*.refs'):
            try:
                lines = [ln.strip() for ln in refs.read_text(encoding='utf-8', errors='replace').splitlines() if ln.strip()]
                if any((hf_root / ln).exists() or (hf_root / ln).is_symlink() for ln in lines):
                    continue
                blob = refs.with_suffix('')
                for f in (blob, refs, blob.with_suffix('.lock')):
                    if f.exists():
                        f.unlink()
                result['removed'].append(f"shared-blob/{blob.name[:12]}")
            except Exception as e:
                logger.warning(f"Sweep blob condiviso {refs.name}: {e}")

    torch_ckpt = Path(TORCH_HUB_CACHE_DIR)
    if torch_ckpt.exists():
        for entry in torch_ckpt.iterdir():
            if entry.name.startswith(TORCH_PRESERVE_PREFIXES):
                result['preserved'].append(f"torch/{entry.name}")
                continue
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
