"""
Sandbox della configurazione: va importato PER PRIMO da ogni processo del
banco, prima di qualsiasi modulo core/*.

- Config.CONFIG_DIR / CONFIG_FILE puntano a work/_cfg/ (sono attributi di
  classe calcolati alla definizione: vanno sovrascritti a mano);
- copia li' la config reale (sola lettura dell'originale);
- Config.save diventa no-op (load() salva da solo quando mancano chiavi);
- Config.set scrive solo in memoria e avvisa (REGOLA FERREA: il banco non
  scrive mai la config di produzione);
- i valori del banco vanno in cfg.settings, mai con Config.set();
- sha256 della config reale prima/dopo: se cambia, errore.

Il sottoprocesso Canary (canary_cli.py, venv_canary) NON legge la config:
riceve model_id/batch_size in canary_args.json, scritto dal processo padre
(gia' in sandbox).
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

REAL_CONFIG = Path.home() / '.transcriberpro' / 'config.json'

BENCH_SETTINGS: Dict[str, object] = {
    'transcription_profile': 'maximum',
    'whisper_model': 'large-v3',
    'whisper_device': 'auto',
    'canary_batch_size': 8,
    'qwen3_max_new_tokens': 0,
    'asr_chunk_target_duration': 20,
    'asr_chunk_min_duration': 10,
    'asr_chunk_max_duration': 25,
    'punctuation_restore_mode': 'auto',
    'punctuation_device': 'cpu',
    'qwen3_asr_model_id': 'Qwen/Qwen3-ASR-1.7B',
    'qwen3_aligner_model_id': 'Qwen/Qwen3-ForcedAligner-0.6B',
    'canary_model_id': 'nvidia/canary-qwen-2.5b',
    'transcription_engine_mode': 'auto',
}

_state: Dict[str, object] = {'active': False, 'real_sha': None, 'set_calls': []}


class SandboxError(RuntimeError):
    pass


def _sha(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def activate(work: Path, real_config: Path = REAL_CONFIG,
             overrides: Optional[Dict[str, object]] = None):
    """Attiva il sandbox e ritorna l'istanza Config del processo."""
    import utils.config as uc
    if _state['active']:
        return uc.get_config()
    if uc._config_instance is not None:
        raise SandboxError("get_config() gia' chiamato prima del sandbox: importare sandbox per primo")
    cfg_dir = Path(work) / '_cfg'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    real_config = Path(real_config)
    _state['real_path'] = real_config
    _state['real_sha'] = _sha(real_config)
    if real_config.exists():
        shutil.copyfile(real_config, cfg_dir / 'config.json')

    uc.Config.CONFIG_DIR = cfg_dir
    uc.Config.CONFIG_FILE = cfg_dir / 'config.json'
    uc.Config.save = lambda self: None

    def _set(self, key, value, save=True):
        _state['set_calls'].append((key, value))
        print(f"  ⚠️ [sandbox] Config.set({key!r}) chiamato dal codice: applicato solo in memoria",
              flush=True)
        self.settings[key] = value
    uc.Config.set = _set

    cfg = uc.get_config()
    if Path(cfg.CONFIG_FILE).resolve() != (cfg_dir / 'config.json').resolve():
        raise SandboxError("Config non rediretta")
    for k, v in {**BENCH_SETTINGS, **(overrides or {})}.items():
        cfg.settings[k] = v
    _state['active'] = True
    check_real_config()
    return cfg


def check_real_config() -> None:
    """Errore se la config reale e' cambiata da quando il sandbox e' attivo."""
    if _state.get('real_path') is None:
        return
    now = _sha(_state['real_path'])
    if now != _state['real_sha']:
        raise SandboxError(
            f"La config reale {_state['real_path']} e' CAMBIATA durante il banco "
            f"(sha {str(_state['real_sha'])[:12]} -> {str(now)[:12]}). Se l'app Transcriber Pro "
            f"era aperta puo' essere stata lei; altrimenti e' un difetto del sandbox: fermarsi.")


def fingerprint(cfg) -> Dict[str, object]:
    return {k: cfg.get(k) for k in sorted(BENCH_SETTINGS)}


def set_calls():
    return list(_state['set_calls'])
