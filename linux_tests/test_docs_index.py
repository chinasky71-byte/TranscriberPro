# -*- coding: utf-8 -*-
"""Documentation entry-point guards.

AGENTS.md is the single entry point. A new session must be able to reach the
current state and the active work from there, and the index must list every
required document.

Run:  python -m pytest linux_tests/test_docs_index.py -q
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
docs = ROOT / "docs"

REQUIRED = [
    "docs/README.md",
    "docs/STATUS.md",
    "docs/PROGRESS.md",
    "docs/CONTRIBUTING.md",
    "docs/SUPPORT_MATRIX.md",
    "docs/architecture/README.md",
    "docs/webui/SPEC.md",
    "docs/webui/PLAN.md",
    "docs/benchmarks/README.md",
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _relative_links(path: Path):
    for raw in LINK_RE.findall(path.read_text(encoding="utf-8")):
        target = raw.strip().split()[0] if raw.strip() else ""
        if not target or target.startswith("#") or "://" in target:
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        if target.lower().endswith(".md"):
            yield target


def test_required_documents_exist():
    missing = [name for name in REQUIRED if not (ROOT / name).exists()]
    assert not missing, "Missing required documents:\n" + "\n".join(missing)


def test_agents_links_every_state_document():
    text = AGENTS.read_text(encoding="utf-8")
    missing = []
    for name in REQUIRED:
        relative = Path(name).relative_to(".").as_posix()
        # tolerate both "docs/x.md" and "x.md" depending on the section
        if relative not in text and Path(relative).name not in text:
            missing.append(name)
    assert not missing, "AGENTS.md does not link:\n" + "\n".join(missing)
    assert "docs/adr/" in text
    assert "docs/README.md" in text


def test_index_lists_every_required_document():
    index = (docs / "README.md").read_text(encoding="utf-8")
    missing = []
    for name in REQUIRED:
        relative = Path(name).relative_to("docs").as_posix()
        if relative not in index and Path(relative).name not in index:
            missing.append(name)
    assert not missing, "docs/README.md does not list:\n" + "\n".join(missing)


def test_links_in_entry_and_state_docs_resolve():
    broken = []
    for path in [AGENTS, docs / "README.md", docs / "STATUS.md",
                 docs / "PROGRESS.md", docs / "webui" / "SPEC.md",
                 docs / "webui" / "PLAN.md"]:
        for target in _relative_links(path):
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, "Broken links:\n" + "\n".join(broken)


def test_progress_has_template_and_entries():
    text = (docs / "PROGRESS.md").read_text(encoding="utf-8")
    assert "## Template" in text
    assert re.search(r"^## \d{4}-\d{2}-\d{2} — ", text, re.M), "no session entries"


def test_status_declares_line_and_date():
    text = (docs / "STATUS.md").read_text(encoding="utf-8")
    assert "Updated:" in text
    assert "development" in text
    assert "master" in text
