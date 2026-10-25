"""Media path validation for the WebUI.

Only files that exist and live under an allowed root can enter the queue.
Roots come from `TP_MEDIA_ROOTS` (os.pathsep-separated), the
`allowed_media_roots` config key, or the user's home directory as a fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, List

ROOTS_ENV = "TP_MEDIA_ROOTS"


def compute_roots(config_get: Callable[[str, object], object],
                  env: str | None = None) -> List[Path]:
    raw_env = (env if env is not None else os.environ.get(ROOTS_ENV, "")).strip()
    values: Iterable[str]
    if raw_env:
        values = [item for item in raw_env.split(os.pathsep) if item.strip()]
    else:
        configured = config_get("allowed_media_roots", []) or []
        values = configured if configured else [str(Path.home())]
    return [Path(value).expanduser().resolve() for value in values]


def validate_media_path(path: str, roots: Iterable[Path]) -> Path:
    """Resolve and validate a media path.

    Raises ValueError (not absolute / not a file), FileNotFoundError, or
    PermissionError (outside the allowed roots). Returns the resolved path.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ValueError("path must be absolute")
    resolved = candidate.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not resolved.is_file():
        raise ValueError(f"not a file: {path}")
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise PermissionError(f"path outside the allowed roots: {path}")


def is_allowed(path: Path, roots: Iterable[Path]) -> bool:
    resolved = Path(path).resolve()
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)
