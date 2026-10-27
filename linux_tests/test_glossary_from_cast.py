# -*- coding: utf-8 -*-
"""Glossario costruito dal cast TMDB (core/glossary.py::ensure_glossary)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import glossary as gl  # noqa: E402


class FakeClient:
    def __init__(self, cast=None, error=None):
        self.cast = cast or {}
        self.error = error
        self.calls = []

    def get_cast_info(self, tmdb_id, media_type, season=None, episode=None, max_cast=15):
        self.calls.append((tmdb_id, media_type, season, episode))
        if self.error:
            raise RuntimeError(self.error)
        return dict(self.cast)


@pytest.fixture(autouse=True)
def temp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "_glossary_dir", lambda: tmp_path)
    return tmp_path


def test_costruisce_dal_cast(tmp_path):
    client = FakeClient({"Lizzie Borden": "F", "Andrew Borden": "M", "Abby Borden": "F"})
    terms = gl.ensure_glossary(1234, client, "tv", season=4, episode=1)
    assert terms == {"Lizzie Borden": "Lizzie Borden", "Andrew Borden": "Andrew Borden",
                     "Abby Borden": "Abby Borden"}
    assert client.calls == [(1234, "tv", 4, 1)]
    saved = (tmp_path / "tmdb_1234.json").read_text(encoding="utf-8")
    assert "Lizzie Borden" in saved
    assert gl.load_glossary(1234) == terms


def test_non_sovrascrive_un_glossario_esistente(tmp_path):
    (tmp_path / "tmdb_99.json").write_text('{"Borden": "Bordén"}', encoding="utf-8")
    client = FakeClient({"Lizzie Borden": "F"})
    terms = gl.ensure_glossary(99, client)
    assert terms == {"Borden": "Bordén"}          # quello dell'utente vince
    assert client.calls == []                      # e non si chiama nemmeno TMDB


def test_cast_vuoto_non_scrive_nulla(tmp_path):
    assert gl.ensure_glossary(7, FakeClient({})) == {}
    assert not (tmp_path / "tmdb_7.json").exists()


def test_errore_di_rete_non_solleva(tmp_path):
    logs = []
    terms = gl.ensure_glossary(8, FakeClient(error="timeout"), log=logs.append)
    assert terms == {} and "timeout" in logs[0]
    assert not (tmp_path / "tmdb_8.json").exists()


def test_scarta_segnaposto_e_nomi_corti():
    terms = gl.cast_to_terms({"Himself": "M", "Narrator": "M", "Al": "M", "Lizzie Borden": "F"})
    assert terms == {"Lizzie Borden": "Lizzie Borden"}


def test_il_pipeline_usa_ensure_glossary():
    text = (ROOT / "core/pipeline.py").read_text(encoding="utf-8")
    assert "ensure_glossary(_meta['id']" in text
    assert "load_glossary(_key) if _key else {}" in text
