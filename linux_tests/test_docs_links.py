# -*- coding: utf-8 -*-
"""Documentation guard tests: relative links and ADR numbering.

Run:  python -m pytest linux_tests/test_docs_links.py -q
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "docs" / "architecture"
ADR = ROOT / "docs" / "adr"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
ADR_RE = re.compile(r"ADR-(\d{3})-")


def _docs():
    # legacy/ is archived: its links are historical and may be stale on purpose.
    yield from sorted(p for p in ARCH.glob("*.md"))
    yield from sorted(ADR.glob("*.md"))


def _targets(text):
    for raw in LINK_RE.findall(text):
        target = raw.strip().split()[0] if raw.strip() else ""
        if not target or target.startswith("#"):
            continue
        if "://" in target or target.startswith("mailto:"):
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        if not target.lower().endswith(".md"):
            continue
        yield target


def test_relative_markdown_links_resolve():
    broken = []
    for doc in _docs():
        for target in _targets(doc.read_text(encoding="utf-8")):
            resolved = (doc.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "Broken relative links:\n" + "\n".join(broken)


def test_adr_numbers_are_unique():
    numbers = {}
    for path in sorted(ADR.glob("*.md")):
        match = ADR_RE.search(path.name)
        if not match:
            continue
        numbers.setdefault(match.group(1), []).append(path.name)
    duplicates = {n: files for n, files in numbers.items() if len(files) > 1}
    assert not duplicates, f"Duplicate ADR numbers: {duplicates}"
    assert numbers, "No ADR files found"


def test_adr_have_required_sections():
    required = ["## Context", "## Decision", "## Consequences"]
    missing = []
    for path in sorted(ADR.glob("ADR-*.md")):
        text = path.read_text(encoding="utf-8")
        for section in required:
            if section not in text:
                missing.append(f"{path.name}: missing {section}")
    assert not missing, "ADR sections missing:\n" + "\n".join(missing)


def test_architecture_index_links_every_document():
    index = (ARCH / "README.md").read_text(encoding="utf-8")
    missing = []
    for doc in sorted(ARCH.glob("*.md")):
        if doc.name == "README.md":
            continue
        if doc.name not in index:
            missing.append(doc.name)
    assert not missing, "Documents not linked from docs/architecture/README.md:\n" + "\n".join(missing)
