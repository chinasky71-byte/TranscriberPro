# -*- coding: utf-8 -*-
"""TP_DATA_DIR / TP_MODELS_DIR overrides (container-friendly paths)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(code: str, env_extra: dict) -> str:
    env = os.environ.copy()
    env.update(env_extra)
    result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_tp_data_dir_changes_config_location(tmp_path):
    data = tmp_path / "data"
    out = _run("from utils.config import Config; print(Config.CONFIG_DIR)", {"TP_DATA_DIR": str(data)})
    assert out == str(data)
    assert (data / "config.json") == data / "config.json"


def test_tp_models_dir_changes_cache_location(tmp_path):
    models = tmp_path / "models"
    out = _run("from utils.cache_bootstrap import MODELS_ROOT; print(MODELS_ROOT)",
               {"TP_MODELS_DIR": str(models)})
    assert out == str(models)
    assert (models / ".cache" / "huggingface" / "hub").is_dir()


def test_allowed_media_roots_default_is_empty():
    out = _run("from utils.config import Config; print(Config.DEFAULTS['allowed_media_roots'])", {})
    assert out == "[]"
