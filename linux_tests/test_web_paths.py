# -*- coding: utf-8 -*-
"""Media path validation tests (no server)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.paths import compute_roots, validate_media_path  # noqa: E402


def test_accepts_file_under_root(tmp_path):
    media = tmp_path / "movie.mp4"
    media.write_text("x")
    assert validate_media_path(str(media), [tmp_path]) == media.resolve()


def test_rejects_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    media = tmp_path / "other.mp4"
    media.write_text("x")
    with pytest.raises(PermissionError):
        validate_media_path(str(media), [root])


def test_rejects_missing_and_relative(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_media_path(str(tmp_path / "missing.mp4"), [tmp_path])
    with pytest.raises(ValueError):
        validate_media_path("relative.mp4", [tmp_path])


def test_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        validate_media_path(str(tmp_path), [tmp_path])


def test_compute_roots_from_env_and_config(monkeypatch, tmp_path):
    fake = tmp_path / "configured"
    monkeypatch.setenv("TP_MEDIA_ROOTS", str(tmp_path))
    assert compute_roots(lambda key, default: default) == [tmp_path.resolve()]

    monkeypatch.delenv("TP_MEDIA_ROOTS", raising=False)
    roots = compute_roots(lambda key, default: [str(fake)])
    assert roots == [fake.resolve()]
