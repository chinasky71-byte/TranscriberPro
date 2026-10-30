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
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

from utils import path_map
from utils.config import Config

MEDIA_ROOTS_KEY = "allowed_media_roots"
START_DIR_KEY = "picker_start_dir"
GGUF_DIR_KEY = "llm_translator_gguf_dir"
PERCENT_KEY = "translation_max_untranslated_pct"
TARGET_LANGUAGE_KEY = "target_language"
# Library search (web/arr.py): the two servers' base URL and the path rules.
ARR_URL_KEYS = ("sonarr_url", "radarr_url")
ARR_MAP_KEY = "arr_path_map"
# Lingua di destinazione: una sola (ADR-009). Il motore traduce verso l'italiano
# e rifiuta il resto, quindi un campo libero sarebbe solo un modo di sbagliare.
TARGET_LANGUAGES = ("ita",)

# chiavi numeriche con i loro limiti (min, max, passo per l'input)
NUMBER_CONFIG_KEYS = {
    PERCENT_KEY: (0.0, 100.0, "0.1"),
}

SAFE_CONFIG_KEYS = {
    "language",
    MEDIA_ROOTS_KEY,
    START_DIR_KEY,
    "transcription_engine_mode",
    "use_gpu",
    TARGET_LANGUAGE_KEY,
    "llm_translator_gguf_quant",
    GGUF_DIR_KEY,
    *ARR_URL_KEYS,
    ARR_MAP_KEY,
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
    "sonarr_api_key",
    "radarr_api_key",
    "huggingface_token",
    "opensubtitles_password",
    "opensubtitles_api_key",
    "opensubtitles_xmlrpc_password",
    "library_scanner_api_key",
}

BOOL_CONFIG_KEYS = {
    "use_gpu",
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
    "llm_translator_gguf_quant": ("Q4_K_M", "Q3_K_M", "IQ3_M"),
    TARGET_LANGUAGE_KEY: TARGET_LANGUAGES,
    "punctuation_restore_mode": ("auto", "off", "missing", "all"),
}

# Nessuna chiave libera: ogni valore scrivibile ha una forma dichiarata qui sopra
# (enum, numero, booleano, cartella, segreto). Resta il set perche' il ramo di
# validazione esiste e un campo libero futuro deve passare di li'.
FREE_TEXT_KEYS: set = set()

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


def as_dir(key: str, value: Any) -> str:
    """Un percorso di cartella, oppure la stringa vuota.

    Vuoto vuol dire "usa il default" per entrambe le chiavi che lo usano: la
    cartella iniziale del picker (prima root ammessa) e la cartella dei GGUF
    (`models/translategemma-12b-gguf`). Un valore non vuoto deve essere una
    cartella assoluta che esiste: un percorso che non risolve non puo' funzionare
    e tenerlo nasconderebbe solo l'errore.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{key}: expected a path or an empty value")
    text = value.strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ConfigError(f"{key}: the path must be absolute")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise ConfigError(f"{key}: not a directory: {text}")
    return str(resolved)


def as_start_dir(value: Any) -> str:
    """La cartella su cui si apre il picker (vedi `as_dir`)."""
    return as_dir(START_DIR_KEY, value)


def as_url(key: str, value: Any) -> str:
    """A base URL for Sonarr/Radarr, or the empty string.

    Empty means "this server is not configured", which is how the feature stays
    off. Anything else must be `http`/`https` with a host: `web/arr.py` hands the
    value to `urllib`, and a `file://` URL there would read a local file instead
    of asking a server.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{key}: expected a URL or an empty value")
    text = value.strip().rstrip("/")
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(f"{key}: expected an http(s) URL, e.g. http://sonarr:8989")
    return text


def as_path_map(value: Any) -> str:
    """The server-path to local-path rules, one per line, or empty.

    Both one rule per line and a `;`-separated string are accepted, because the
    settings field is small and people paste either form. Invalid lines are
    rejected here instead of being silently dropped: a rule the user wrote and
    this module ignored would look like working configuration while every
    result stayed unreachable.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{ARR_MAP_KEY}: expected <server prefix>=<local prefix> per line")
    lines = [line.strip() for line in value.replace(";", "\n").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    for line in lines:
        server, separator, local = line.partition("=")
        if not separator or not server.strip() or not local.strip():
            raise ConfigError(f"{ARR_MAP_KEY}: expected <server prefix>=<local prefix> "
                              f"per line, got: {line}")
    if lines and not path_map.parse_map("\n".join(lines)):
        raise ConfigError(f"{ARR_MAP_KEY}: no usable rule in {lines[0]!r}")
    return "\n".join(lines)


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
        elif key in ARR_URL_KEYS:
            cleaned[key] = as_url(key, value)
        elif key == ARR_MAP_KEY:
            cleaned[key] = as_path_map(value)
        elif key in (START_DIR_KEY, GGUF_DIR_KEY):
            cleaned[key] = as_dir(key, value)
        elif key in NUMBER_CONFIG_KEYS:
            if value is None or (isinstance(value, str) and not value.strip()):
                continue                      # campo vuoto = lascia il valore attuale
            low, high, _step = NUMBER_CONFIG_KEYS[key]
            cleaned[key] = as_number(key, value, low, high)
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
