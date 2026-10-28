# -*- coding: utf-8 -*-
"""Architecture guard tests: the domain must not know the OS or the GPU runtime.

These rules are documented in docs/architecture/layers.md. The allowlist below
contains the violations that already exist; it must only shrink. Adding an
entry requires a review justification.

Run:  python -m pytest linux_tests/test_architecture_boundaries.py -q
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"

FORBIDDEN_IMPORT_PREFIXES = ("platform_services", "runtime", "PyQt6", "PySide6")

# No core -> gui exception left: FileProgress moved to core/jobs/progress.py.
ALLOWED_GUI_IMPORTS = set()

# OS checks in core. Matched as (relative path, substring of the source line).
# The test fails both on a new occurrence and on a stale entry.
ALLOWED_OS_CHECKS = {
    ("core/queue_runner.py", "sys.platform.startswith('linux')"),
    ("core/queue_runner.py", "os.name != 'nt'"),
    ("core/llm_subtitle_translator/gguf_worker.py", "os.name != 'nt'"),
    ("core/pipeline_cli.py", "sys.platform != 'win32'"),
}

OS_ATTR = {("sys", "platform"), ("os", "name"), ("platform", "system")}


def _python_files(base: Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def _os_attr_lines(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if isinstance(value, ast.Name) and (value.id, node.attr) in OS_ATTR:
            yield node.lineno


def test_core_does_not_import_platform_or_gui_frameworks():
    violations = []
    for path in _python_files(CORE):
        rel = _rel(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for lineno, module in _imports(tree):
            if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{rel}:{lineno} imports {module}")
            elif module == "gui" or module.startswith("gui."):
                key = (rel, module)
                if key not in ALLOWED_GUI_IMPORTS:
                    violations.append(f"{rel}:{lineno} imports {module} (move it to core/jobs)")
    assert not violations, "Domain layer must not import platform/runtime/Qt/gui:\n" + "\n".join(violations)


def test_os_checks_in_core_are_allowlisted_and_allowlist_is_not_stale():
    found = set()
    for path in _python_files(CORE):
        rel = _rel(path)
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        tree = ast.parse(lines and "\n".join(lines) or "", filename=str(path))
        for lineno in _os_attr_lines(tree):
            source = lines[lineno - 1].strip()
            matched = [entry for entry in ALLOWED_OS_CHECKS
                       if entry[1] in source]
            if not matched:
                found.add((rel, source))
    assert not found, (
        "New OS check in core/. Move it to platform_services/ or runtime/, or "
        "add an explicit allowlist entry with a justification:\n"
        + "\n".join(f"{p}: {s}" for p, s in sorted(found))
    )

    # Every allowlist entry must still exist, otherwise it hides future changes.
    stale = []
    for rel, needle in sorted(ALLOWED_OS_CHECKS):
        path = ROOT / rel
        if not path.exists():
            stale.append(f"{rel}: file missing")
            continue
        if not any(needle in line for line in path.read_text(encoding="utf-8-sig").splitlines()):
            stale.append(f"{rel}: {needle!r} not found")
    assert not stale, "Stale allowlist entries (remove them):\n" + "\n".join(stale)


def test_no_platform_services_or_runtime_package_yet():
    """Guard the naming: when the packages are added, they must stay out of core."""
    for name in ("platform_services", "runtime"):
        pkg = ROOT / name
        if pkg.exists():
            assert pkg.is_dir(), f"{name} exists but is not a directory"
