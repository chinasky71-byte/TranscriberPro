# -*- coding: utf-8 -*-
"""Guard test for the structured event protocol (docs/architecture/events.md).

The pipeline and its consumers depend on the event kinds listed there. A new
kind must be documented and added to this test first.

Run:  python -m pytest linux_tests/test_events_schema.py -q
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"

ALLOWED_KINDS = {
    "phase",
    "route",
    "audio_lang",
    "embedded",
    "skip",
    "step",
    "ocr_leave",
    "bar",
}

EMITTER_NAMES = {"emit", "_tp_emit", "_ev"}
PREFIX = "@@TPEV@@ "


def _python_files(base: Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _literal_emit_kinds():
    """Yield (relative path, line, kind) for literal emitter calls in core/."""
    for path in _python_files(CORE):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in EMITTER_NAMES or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield path.relative_to(ROOT).as_posix(), node.lineno, first.value


def test_every_literal_event_kind_is_documented():
    unknown = [(p, n, k) for p, n, k in _literal_emit_kinds() if k not in ALLOWED_KINDS]
    assert not unknown, (
        "Undocumented event kind(s) emitted from core/. Update "
        "docs/architecture/events.md and ALLOWED_KINDS in this test:\n"
        + "\n".join(f"{p}:{n} -> {k!r}" for p, n, k in unknown)
    )


def test_event_prefix_and_roundtrip():
    from utils.events import PREFIX as IMPL_PREFIX, format_line, parse_line

    assert IMPL_PREFIX == PREFIX
    line = format_line("phase", {"name": "asr", "engine": "qwen3"})
    assert line.startswith(PREFIX)
    kind, fields = parse_line(line)
    assert kind == "phase"
    assert fields == {"name": "asr", "engine": "qwen3"}


def test_malformed_event_is_ignored():
    from utils.events import PREFIX as IMPL_PREFIX, parse_line

    assert parse_line("") is None
    assert parse_line("not an event") is None
    assert parse_line(IMPL_PREFIX + "{not json") == ("", {})


def test_events_are_disabled_without_env(monkeypatch):
    from utils import events

    monkeypatch.delenv(events.ENV_VAR, raising=False)
    assert events.enabled() is False
    monkeypatch.setenv(events.ENV_VAR, "1")
    assert events.enabled() is True
