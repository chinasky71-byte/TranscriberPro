# -*- coding: utf-8 -*-
"""WebUI: creazione del glossario a resa fissa (cast incollato o id TMDB)."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from web import glossary as fixed  # noqa: E402
from web.app import create_app  # noqa: E402

CAST = """Main
Ella Beatty as Lizzie Borden[1]
Vicky Krieps as
Bridget "Maggie" Sullivan, the Borden family's housemaid and Lizzie's lover[1]
Charlie Hunnam as Andrew Borden, Emma's and Lizzie's father[3]
Rebecca Hall as Abby Borden, Andrew's second wife[3]
Recurring
Billie Lourd as Emma Borden, Lizzie's older sister[4]
"""


class FakeConfig:
    CONFIG_DIR = Path("/tmp/tp-config")

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, save=True):
        self.values[key] = value


class FakeRunner:
    def run(self, *args, **kwargs):
        return {"ok": True, "output": "x.srt", "error": None, "cancelled": False}


def _make(tmp_path, monkeypatch, values=None):
    monkeypatch.setattr(fixed, "list_fixed_glossaries", lambda: _fixed_list(tmp_path, monkeypatch))
    from core import glossary as core_glossary
    monkeypatch.setattr(core_glossary, "_glossary_dir", lambda: tmp_path / "glossary")
    (tmp_path / "glossary").mkdir(exist_ok=True)
    config = FakeConfig(dict({"allowed_media_roots": [str(tmp_path)],
                              "glossary_id": "monster-2022"}, **(values or {})))
    manager = JobManager(runner=FakeRunner(), keep_alive=True, log_dir=tmp_path / "logs")
    return create_app(manager, token=None, config=config), config


def _fixed_list(tmp_path, monkeypatch):
    from core import glossary as core_glossary
    monkeypatch.setattr(core_glossary, "_glossary_dir", lambda: tmp_path / "glossary", raising=False)
    return fixed.list_fixed_glossaries.__wrapped__(tmp_path) if hasattr(fixed.list_fixed_glossaries, "__wrapped__") else []


def test_parse_cast_text_dalle_schede(tmp_path):
    terms = fixed.parse_cast_text(CAST)
    assert "Lizzie Borden" in terms
    assert "Andrew Borden" in terms          # senza la descrizione dopo la virgola
    assert "Abby Borden" in terms
    assert "Emma Borden" in terms
    assert 'Bridget "Maggie" Sullivan' in terms and "Maggie" in terms   # alias fra virgolette
    assert "Recurring" not in terms and "Main" not in terms
    assert not any(term.endswith(" as") for term in terms)


def test_parse_cast_text_senza_as(tmp_path):
    terms = fixed.parse_cast_text("Lizzie Borden\nAbby Borden\nBorden")
    # il nome completo e anche i singoli nomi: nei dialoghi si dice "Lizzie"
    for name in ("Lizzie Borden", "Abby Borden", "Borden", "Lizzie", "Abby"):
        assert terms.get(name) == name


def test_parse_scarta_ruoli_generici():
    assert fixed.parse_cast_text("Himself\nNarrator\nAl") == {}


def test_pagina_mostra_modulo_e_glossari(tmp_path, monkeypatch):
    app, _ = _make(tmp_path, monkeypatch)
    with TestClient(app) as client:
        page = client.get("/glossary")
        assert page.status_code == 200
        assert "Create one" in page.text and 'name="cast_text"' in page.text
        assert 'name="tmdb_id"' in page.text and 'name="show_key"' in page.text
        assert "No fixed glossary yet" in page.text


def test_crea_glossario_da_cast_incollato(tmp_path, monkeypatch):
    app, _ = _make(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post("/glossary/build", data={
            "source": "manual", "show_key": "monster-2022", "cast_text": CAST})
        assert "Glossary saved" in response.text
        path = tmp_path / "glossary" / "manual_monster-2022.json"
        assert path.exists()
        assert "Lizzie Borden" in path.read_text(encoding="utf-8")
        page = client.get("/glossary")
        assert "monster-2022" in page.text and "manual" in page.text


def test_serve_una_chiave(tmp_path, monkeypatch):
    app, _ = _make(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post("/glossary/build", data={"source": "manual", "cast_text": CAST})
        assert "show key required" in response.text
        assert not list((tmp_path / "glossary").glob("*.json"))


def test_tmdb_senza_chiave_spiega_il_rimedio(tmp_path, monkeypatch):
    app, _ = _make(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post("/glossary/build", data={"source": "tmdb", "tmdb_id": "12345"})
        assert "no TMDB API key" in response.text


def test_tmdb_id_non_numerico(tmp_path, monkeypatch):
    app, _ = _make(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post("/glossary/build", data={"source": "tmdb", "tmdb_id": "monster"})
        assert "must be a number" in response.text
