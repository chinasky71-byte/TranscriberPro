"""Config contract for the WebUI.

One place for the keys the browser may read or write and for the validation
rules applied before a value is saved. `web/app.py` (JSON API) and
`web/ui.py` (server-rendered settings page) both use this module, so the two
paths cannot drift apart.

Rules:

- only whitelisted keys are writable; unknown keys are an error;
- secrets are readable as `{"is_set": bool}` and writable as strings; an empty
  value clears the secret and is stored as `""` (the config default);
- a value that fails validation never reaches `Config.set`, therefore never
  reaches the pipeline;
- error messages name the key, never echo a secret.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

from utils.config import Config

MEDIA_ROOTS_KEY = "allowed_media_roots"
START_DIR_KEY = "picker_start_dir"
PERCENT_KEY = "translation_max_untranslated_pct"
TARGET_LANGUAGE_KEY = "target_language"

SAFE_CONFIG_KEYS = {
    "language",
    MEDIA_ROOTS_KEY,
    START_DIR_KEY,
    "transcription_engine_mode",
    "whisper_model",
    "use_gpu",
    TARGET_LANGUAGE_KEY,
    "translation_model",
    "llm_translator_model",
    "llm_translator_gguf_enabled",
    PERCENT_KEY,
    "enable_diarization",
    "dialogue_style_enabled",
    "gender_correction_enabled",
    "punctuation_restore_mode",
    "model_cache_cleanup_enabled",
    "opensubtitles_upload_enabled",
    "mux_subtitle_into_video",
    "replace_mislabeled_italian_track",
}

SECRET_CONFIG_KEYS = {
    "huggingface_token",
    "claude_api_key",
    "openai_api_key",
    "opensubtitles_password",
    "opensubtitles_api_key",
    "opensubtitles_xmlrpc_password",
    "library_scanner_api_key",
}

BOOL_CONFIG_KEYS = {
    "use_gpu",
    "llm_translator_gguf_enabled",
    "enable_diarization",
    "dialogue_style_enabled",
    "gender_correction_enabled",
    "model_cache_cleanup_enabled",
    "opensubtitles_upload_enabled",
    "mux_subtitle_into_video",
    "replace_mislabeled_italian_track",
}

ENUM_CONFIG_KEYS: Dict[str, Tuple[str, ...]] = {
    "language": ("auto", "it", "en"),
    "transcription_engine_mode": tuple(Config.VALID_TRANSCRIPTION_ENGINE_MODES),
    "translation_model": tuple(Config.VALID_TRANSLATION_MODELS),
    "punctuation_restore_mode": ("auto", "off", "missing", "all"),
}

# Every other whitelisted key is a free string; these must not be empty.
FREE_TEXT_KEYS = {"whisper_model", "llm_translator_model"}

_TARGET_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
_TRUE_STRINGS = {"1", "true", "on", "yes"}
_FALSE_STRINGS = {"", "0", "false", "off", "no"}


class ConfigError(ValueError):
    """A config value is not acceptable. The message never contains a secret."""


def as_bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    raise ConfigError(f"{key}: expected a boolean (true/false)")


def as_number(key: str, value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{key}: expected a number between {low:g} and {high:g}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{key}: expected a number between {low:g} and {high:g}") from None
    if not low <= number <= high:
        raise ConfigError(f"{key}: expected a number between {low:g} and {high:g}")
    return number


def as_media_roots(value: Any) -> list:
    """Normalise the allowed media roots.

    Accepts a list, or a string separated by `os.pathsep` (the form sends one
    path per line, the environment one per `:`). Every entry must be an
    existing absolute directory: a root that does not resolve cannot authorise
    any media path, and keeping it would only hide the mistake.
    """
    if isinstance(value, str):
        items: Iterable[str] = [item for item in value.split(os.pathsep) if item.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value if str(item).strip()]
    else:
        raise ConfigError(f"{MEDIA_ROOTS_KEY}: expected a list of directories")

    roots = []
    for item in items:
        candidate = Path(item).expanduser()
        if not candidate.is_absolute():
            raise ConfigError(f"{MEDIA_ROOTS_KEY}: paths must be absolute")
        resolved = candidate.resolve()
        if not resolved.is_dir():
            raise ConfigError(f"{MEDIA_ROOTS_KEY}: not a directory: {item.strip()}")
        roots.append(str(resolved))
    return roots


def as_start_dir(value: Any) -> str:
    """Normalise the folder the WebUI file picker opens on.

    Empty means "use the first allowed root". A non-empty value must be an
    absolute existing directory; whether it is also reachable by the picker is
    decided at listing time, because the allowed roots can change later.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{START_DIR_KEY}: expected a path or an empty value")
    text = value.strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ConfigError(f"{START_DIR_KEY}: the path must be absolute")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise ConfigError(f"{START_DIR_KEY}: not a directory: {text}")
    return str(resolved)


def as_secret(key: str, value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{key}: expected a string or null")
    return value.strip()


def normalise_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalise a batch of writable config values.

    Raises ConfigError on the first unacceptable value; nothing is applied
    until the whole batch is valid.
    """
    cleaned: Dict[str, Any] = {}
    for key, value in values.items():
        if key not in SAFE_CONFIG_KEYS and key not in SECRET_CONFIG_KEYS:
            raise ConfigError(f"keys not writable: {key}")
        if key in SECRET_CONFIG_KEYS:
            cleaned[key] = as_secret(key, value)
        elif key in BOOL_CONFIG_KEYS:
            cleaned[key] = as_bool(key, value)
        elif key in ENUM_CONFIG_KEYS:
            text = value.strip() if isinstance(value, str) else None
            if text not in ENUM_CONFIG_KEYS[key]:
                raise ConfigError(
                    f"{key}: allowed values are {', '.join(ENUM_CONFIG_KEYS[key])}")
            cleaned[key] = text
        elif key == MEDIA_ROOTS_KEY:
            cleaned[key] = as_media_roots(value)
        elif key == START_DIR_KEY:
            cleaned[key] = as_start_dir(value)
        elif key == PERCENT_KEY:
            cleaned[key] = as_number(key, value, 0.0, 100.0)
        elif key == TARGET_LANGUAGE_KEY:
            text = value.strip() if isinstance(value, str) else ""
            if not _TARGET_LANGUAGE_RE.match(text):
                raise ConfigError(f"{key}: expected an ISO 639-2 code such as 'ita'")
            cleaned[key] = text
        elif key in FREE_TEXT_KEYS:
            text = value.strip() if isinstance(value, str) else ""
            if not text:
                raise ConfigError(f"{key}: expected a non-empty string")
            cleaned[key] = text
        else:  # pragma: no cover - the whitelist above covers every key
            raise ConfigError(f"keys not writable: {key}")
    return cleaned


def read_values(config: Any) -> Dict[str, Any]:
    """Readable view of the whitelisted keys: secrets are masked."""
    values: Dict[str, Any] = {}
    for key in sorted(SAFE_CONFIG_KEYS):
        values[key] = config.get(key)
    for key in sorted(SECRET_CONFIG_KEYS):
        values[key] = {"is_set": bool(config.get(key))}
    return values


def apply_values(config: Any, values: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate then save. Raises ConfigError before writing anything."""
    cleaned = normalise_values(values)
    for key, value in cleaned.items():
        config.set(key, value, save=True)
    return read_values(config)
