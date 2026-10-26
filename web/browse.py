"""Read-only directory browser for the WebUI file picker.

The picker lists folders and video files that live under the allowed media
roots, so a user can queue a file without typing its path. It is a lister, not
a library scanner: no database, no persistent index, no recursion and no write
of any kind.

Rules:

- a requested path must be an existing absolute directory that resolves under
  one of the allowed roots (`web/paths.py::is_allowed`, same check the queue
  uses for media files);
- hidden entries (`.name`) are never listed;
- symlinks are resolved and dropped when they point outside the roots;
- only the extensions in `VIDEO_EXTENSIONS` are shown as media;
- at most `MAX_ENTRIES` entries are returned per directory.

`picker_start_dir` (`web/config_schema.py::START_DIR_KEY`) is used only when it
is itself under an allowed root; otherwise the first root wins, so a stale
setting cannot lock the picker on an unreadable folder.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from web.paths import is_allowed

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mpg", ".mpeg")
MAX_ENTRIES = 500
START_DIR_KEY = "picker_start_dir"

_DIGITS = re.compile(r"(\d+)")


class BrowseError(ValueError):
    """The requested folder cannot be listed. The message is user-facing."""


def natural_key(name: str) -> List[Any]:
    """Sort key that keeps `Episode 2` before `Episode 10`."""
    return [int(part) if part.isdigit() else part.casefold()
            for part in _DIGITS.split(name)]


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"  # pragma: no cover - the loop always returns


def has_subtitle(video: Path) -> bool:
    """True when a sidecar subtitle already sits next to `video`.

    The pipeline writes `<name>.<language>.srt` (ISO 639-1), so the check is
    suffix-agnostic on purpose: any `<stem>.*.srt` or `<stem>.srt` sibling
    counts, whichever language code produced it.
    """
    prefix = video.stem.casefold() + "."
    try:
        entries = list(video.parent.iterdir())
    except OSError:
        return False
    for entry in entries:
        name = entry.name.casefold()
        if name.endswith(".srt") and name.startswith(prefix):
            return True
    return False


def start_dir(config_get: Callable[[str, Any], Any],
              roots: Iterable[Path]) -> Path:
    """Folder the picker opens on: the configured one, else the first root."""
    roots = [Path(root) for root in roots]
    configured = str(config_get(START_DIR_KEY, "") or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_absolute() and candidate.is_dir() \
                and is_allowed(candidate, roots):
            return candidate.resolve()
    return roots[0]


def resolve_dir(path: str, roots: Iterable[Path]) -> Path:
    """Validate a requested folder and return its resolved path."""
    roots = [Path(root) for root in roots]
    candidate = Path(str(path)).expanduser()
    if not candidate.is_absolute():
        raise BrowseError("the folder must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise BrowseError(f"folder not found: {path}") from None
    if not resolved.is_dir():
        raise BrowseError(f"not a folder: {path}")
    if not is_allowed(resolved, roots):
        raise BrowseError("the folder is outside the allowed media roots")
    return resolved


def list_directory(path: str, roots: Iterable[Path],
                   start: Optional[Path] = None,
                   limit: int = MAX_ENTRIES) -> Dict[str, Any]:
    """Describe one folder: sub-folders, video files and the way back up.

    An empty `path` means "open the start folder".
    """
    roots = [Path(root) for root in roots]
    current = resolve_dir(path, roots) if str(path or "").strip() else Path(
        start or roots[0])

    folders: List[Dict[str, str]] = []
    files: List[Dict[str, Any]] = []
    truncated = False
    try:
        entries = sorted(current.iterdir(), key=lambda entry: natural_key(entry.name))
    except OSError as exc:
        raise BrowseError(f"cannot read the folder: {exc.strerror or exc}") from None

    # Sibling subtitles are computed once: one listing, no per-file stat.
    subtitles = [entry.name.casefold() for entry in entries
                 if entry.name.casefold().endswith(".srt")]

    for entry in entries:
        if len(folders) + len(files) >= limit:
            truncated = True
            break
        if entry.name.startswith("."):
            continue
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            continue
        if not is_allowed(resolved, roots):
            continue
        if resolved.is_dir():
            folders.append({"name": entry.name, "path": str(resolved)})
            continue
        if entry.suffix.casefold() not in VIDEO_EXTENSIONS or not resolved.is_file():
            continue
        prefix = entry.stem.casefold() + "."
        files.append({
            "name": entry.name,
            "path": str(resolved),
            "size": entry.stat().st_size,
            "size_h": human_size(entry.stat().st_size),
            "has_subtitle": any(name.startswith(prefix) for name in subtitles),
        })

    parent = ""
    if current not in roots and is_allowed(current.parent, roots):
        parent = str(current.parent)

    return {
        "path": str(current),
        "parent": parent,
        "roots": [{"name": str(root), "path": str(root)} for root in roots],
        "dirs": folders,
        "files": files,
        "truncated": truncated,
        "limit": limit,
    }
