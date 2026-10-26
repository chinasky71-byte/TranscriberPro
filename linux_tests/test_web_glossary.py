# -*- coding: utf-8 -*-
"""Glossary review: report listing, decision persistence, pages.

Reports are fixtures written into a temporary directory: the web layer only
reads them, it never builds one (that needs the show folder and the Qwen
extractor).
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from web.app import create_app  # noqa: E402
from web.glossary import GlossaryStore  # noqa: E402


class FakeConfig:
    CONFIG_DIR = Path("/tmp/tp-config-glossary")

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, save=True):
        self.values[key] = value


class FakeRunner:
    def run(self, video, target_language, files_processed, log_path,
            on_line=None, on_event=None, cancel_event=None):
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


REPORT = {
    "show": "Test Show",
    "gate": {"passed": True, "reason": ""},
    "blocks": 1234,
    "episodes_used": ["s01e01", "s01e02"],
    "candidates": [
        {"term": "Alice", "occurrences": 42, "status": "review",
         "reason": "i canali non concordano sulla divergenza",
         "align_verdict": "diverging", "qwen_verdict": "stable"},
        {"term": "Bob", "occurrences": 17, "status": "auto",
         "reason": "i due canali concordano", "align_verdict": "diverging",
         "qwen_verdict": "diverging"},
        {"term": "Carol", "occurrences": 3, "status": "reject",
         "reason": "nessun canale disponibile", "align_verdict": "",
         "qwen_verdict": ""},
    ],
}


def _write_report(root: Path, name: str = "testshow") -> None:
    (root / f"{name}.json").write_text(json.dumps(REPORT), encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "glossary"
    root.mkdir()
    _write_report(root)
    return GlossaryStore(root)


def _app(tmp_path, store):
    config = FakeConfig({"allowed_media_roots": [str(tmp_path)]})
    manager = JobManager(runner=FakeRunner(), keep_alive=True, log_dir=tmp_path / "logs")
    return create_app(manager, config=config, glossary_store=store)


def test_list_and_view(tmp_path, store):
    app = _app(tmp_path, store)
    with TestClient(app) as client:
        reports = client.get("/api/glossary/reports").json()
        assert reports[0]["name"] == "testshow"
        assert reports[0]["show"] == "Test Show"
        assert reports[0]["candidates"] == 3
        assert reports[0]["to_review"] == 1
        assert reports[0]["decided"] == 0

        detail = client.get("/api/glossary/reports/testshow").json()
        assert [row["term"] for row in detail["rows"]] == ["Alice", "Bob", "Carol"]
        assert detail["rows"][0]["decision"] == "pending"
        assert client.get("/api/glossary/reports/nope").status_code == 404


def test_decision_round_trip(tmp_path, store):
    app = _app(tmp_path, store)
    with TestClient(app) as client:
        saved = client.put("/api/glossary/reports/testshow/terms/0",
                           json={"decision": "approved", "translation": "Alise",
                                 "note": "scelta del revisore"})
        assert saved.status_code == 200
        assert saved.json()["decision"] == "approved"

        detail = client.get("/api/glossary/reports/testshow").json()
        assert detail["rows"][0]["translation"] == "Alise"
        assert detail["rows"][0]["decision"] == "approved"

        decided = client.get("/api/glossary/reports").json()[0]["decided"]
        assert decided == 1

        assert client.put("/api/glossary/reports/testshow/terms/9",
                          json={"decision": "approved"}).status_code == 404
        assert client.put("/api/glossary/reports/testshow/terms/0",
                          json={"decision": "maybe"}).status_code == 400
        assert client.put("/api/glossary/reports/testshow/terms/0",
                          json={"decision": "approved",
                                "translation": "x" * 400}).status_code == 400


def test_decisions_file_lives_next_to_the_report(tmp_path, store):
    app = _app(tmp_path, store)
    with TestClient(app) as client:
        client.put("/api/glossary/reports/testshow/terms/1", json={"decision": "rejected"})
    decisions = json.loads((store.root / "testshow.decisions.json").read_text(encoding="utf-8"))
    assert decisions["Bob"]["decision"] == "rejected"
    # the report itself is never modified
    assert json.loads((store.root / "testshow.json").read_text(encoding="utf-8"))["candidates"][1]["status"] == "auto"


def test_report_name_cannot_escape_the_directory(tmp_path, store):
    app = _app(tmp_path, store)
    with TestClient(app) as client:
        for name in ("..%2F..%2Fetc%2Fpasswd", "nope", "testshow.json"):
            assert client.get(f"/api/glossary/reports/{name}").status_code == 404


def test_pages(tmp_path, store):
    app = _app(tmp_path, store)
    with TestClient(app) as client:
        page = client.get("/glossary")
        assert page.status_code == 200
        assert "Test Show" in page.text

        report = client.get("/glossary/testshow")
        assert report.status_code == 200
        assert "Alice" in report.text
        assert "nessun canale disponibile" in report.text

        saved = client.post("/glossary/testshow/terms/0",
                            data={"decision": "approved", "translation": "Alise", "note": ""},
                            follow_redirects=False)
        assert saved.status_code == 303
        assert "Alise" in client.get("/glossary/testshow").text

        missing = client.get("/glossary/nope")
        assert missing.status_code == 200
        assert "Unknown glossary report" in missing.text


def test_glossary_pages_require_login(tmp_path, store):
    app = _app(tmp_path, store)
    app.state.token = "s3cret"
    with TestClient(app) as client:
        for path in ("/glossary", "/glossary/testshow"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"].startswith("/login")
        assert client.get("/api/glossary/reports").status_code == 401


def test_empty_directory_is_not_an_error(tmp_path):
    empty = GlossaryStore(tmp_path / "glossary-empty")
    app = _app(tmp_path, empty)
    with TestClient(app) as client:
        assert client.get("/api/glossary/reports").json() == []
        page = client.get("/glossary")
        assert "No glossary reports found" in page.text
