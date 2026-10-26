# -*- coding: utf-8 -*-
"""Guard: implementation progress is recorded in docs/PROGRESS.md.

Rule (AGENTS.md, Workflow): one PROGRESS entry per pull request, written before
the merge. The log is the evidence trail a cold start reads after
`docs/STATUS.md`; a merged step without an entry is invisible.

The checks are structural on purpose: they cannot judge whether an entry is
honest, but they stop the log from drifting into a stale or unordered list.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "PROGRESS.md"

ENTRY_RE = re.compile(r"(?m)^## (\d{4}-\d{2}-\d{2}) — (.+)$")

# Fields every entry must carry (the template at the top of the file).
REQUIRED_FIELDS = ("Branch / commits:", "Goal:", "Done", "Tests",
                   "Decisions", "Known issues", "Next step:")

# Entries are append-only: the full template is required from the day the rule
# was introduced, older entries keep the fields they were written with.
FULL_TEMPLATE_SINCE = "2026-10-26"
CORE_FIELDS = ("Branch / commits:", "Goal:", "Done", "Next step:")


def _entries():
    text = PROGRESS.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(text))
    entries = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        entries.append({
            "date": match.group(1),
            "title": match.group(2).strip(),
            "body": text[match.start():end],
        })
    return entries


def test_the_log_has_entries():
    assert len(_entries()) >= 10, "the progress log lost its history"


def test_every_entry_has_the_template_fields():
    missing = {}
    for entry in _entries():
        required = (REQUIRED_FIELDS if entry["date"] >= FULL_TEMPLATE_SINCE
                    else CORE_FIELDS)
        absent = [field for field in required if field not in entry["body"]]
        if absent:
            missing[entry["title"]] = absent
    assert missing == {}, f"PROGRESS entries without the template fields: {missing}"


def test_entries_are_newest_first():
    dates = [entry["date"] for entry in _entries()]
    assert dates == sorted(dates, reverse=True), (
        f"PROGRESS.md must list the newest entry first; got {dates}")


def test_entries_use_the_documented_heading_format():
    for entry in _entries():
        assert len(entry["title"]) > 3, f"empty title in entry dated {entry['date']}"


def test_the_rule_is_stated_in_agents_md():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/PROGRESS.md" in agents
    workflow = agents.split("## Workflow", 1)[-1].split("## Hard rules", 1)[0]
    assert "PROGRESS.md" in workflow, "the Workflow section must state the PROGRESS rule"
    assert "before" in workflow.lower() and "merge" in workflow.lower()


def test_the_header_states_the_rule():
    header = PROGRESS.read_text(encoding="utf-8").split("\n## ", 1)[0]
    assert "PROGRESS" in header or "progress" in header.lower()
    assert "merge" in header.lower(), "PROGRESS header must say the entry comes before the merge"


def test_contributing_points_at_the_guard():
    contributing = (ROOT / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "PROGRESS.md" in contributing
    assert "test_docs_progress" in contributing
