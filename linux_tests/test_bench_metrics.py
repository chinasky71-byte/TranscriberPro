# -*- coding: utf-8 -*-
"""Unit tests for the benchmark harness (no GPU, no network)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import metrics  # noqa: E402
from bench.text import (  # noqa: E402
    Line, compact, normalize, parse_reference, parse_srt_entries, split_sentences,
    srt_blocks, srt_from_entries, srt_from_lines, tokens,
)


def test_normalize_numbers_and_percent():
    assert normalize("Thirty percent?") == "30%"
    assert normalize("twenty nineteen") == "2019"
    assert normalize("Trenta percento") == "30%"
    assert normalize("30 percent") == "30%"


def test_normalize_punctuation_and_apostrophes():
    assert tokens("Buon giorno, a tutti.") == ["buon", "giorno", "a", "tutti"]
    assert tokens("l\u2019alluvione") == ["l'alluvione"]


def test_parse_reference_skips_header(tmp_path):
    path = tmp_path / "ref.txt"
    path.write_text("Header line\n\nA: Hello there.\nB: Fine.\n", encoding="utf-8")
    lines = parse_reference(path)
    assert lines == [Line("A", "Hello there."), Line("B", "Fine.")]


def test_wer_and_cer():
    result = metrics.wer(["a", "b", "c"], ["a", "x", "c"])
    assert result["rate"] == pytest.approx(1 / 3)
    assert result["sub"] == 1 and result["del"] == 0 and result["ins"] == 0
    assert metrics.cer("abc", "axc")["rate"] == pytest.approx(1 / 3)
    assert metrics.wer([], [])["rate"] == 0.0
    assert metrics.wer([], ["x"])["rate"] == 1.0


def test_chrf_and_similarity():
    assert metrics.chrf("hello world", "hello world") == pytest.approx(1.0)
    assert metrics.chrf("abc", "xyz") < 0.2
    assert metrics.similarity(["a", "b"], ["a", "b"]) == 1.0
    assert metrics.similarity(["a", "b"], ["a", "c"]) < 1.0


def test_untranslated_blocks():
    assert metrics.untranslated_blocks(["Hello", "Bye"], ["Hello", "Ciao"]) == [0]
    assert metrics.untranslated_blocks(["Hello"], ["Ciao"]) == []


def test_split_sentences():
    assert split_sentences("No problem. What's going on? You sounded worried.") == [
        "No problem.", "What's going on?", "You sounded worried."]
    assert split_sentences("Single sentence") == ["Single sentence"]


def test_srt_roundtrip():
    lines = [Line("A", "First line."), Line("B", "Second line.")]
    text = srt_from_lines(lines)
    path = Path("/tmp") / "tp_bench_roundtrip.srt"
    path.write_text(text, encoding="utf-8")
    try:
        assert srt_blocks(path) == ["First line.", "Second line."]
    finally:
        path.unlink(missing_ok=True)


def test_srt_timings_are_realistic():
    """1 s per block would make the LLM condense (duration * 17 CPS budget)."""
    import re
    lines = [Line("A", "x" * 150), Line("B", "short")]
    text = srt_from_lines(lines)
    stamps = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", text)
    assert len(stamps) == 2
    def seconds(parts):
        h, m, s, ms = map(int, parts)
        return h * 3600 + m * 60 + s + ms / 1000
    first = seconds(stamps[0][4:]) - seconds(stamps[0][:4])
    second = seconds(stamps[1][4:]) - seconds(stamps[1][:4])
    assert first >= 9.0        # 150 chars / 15 cps
    assert second >= 1.5       # minimum duration


def test_compact_removes_spaces():
    assert compact("a b c") == "abc"


def test_srt_entries_roundtrip():
    lines = [Line("A", "First line."), Line("B", "Second line.")]
    source = srt_from_lines(lines)
    path = Path("/tmp") / "tp_bench_entries.srt"
    path.write_text(source, encoding="utf-8")
    try:
        entries = parse_srt_entries(path)
        assert [entry["text"] for entry in entries] == ["First line.", "Second line."]
        assert entries[0]["start"] == "00:00:00,000"
        rebuilt = srt_from_entries(entries)
        path.write_text(rebuilt, encoding="utf-8")
        assert srt_blocks(path) == ["First line.", "Second line."]
    finally:
        path.unlink(missing_ok=True)


def test_http_cleanup():
    from bench._translate_http import _clean
    assert _clean('"Buongiorno a tutti."') == "Buongiorno a tutti."
    assert _clean("Italian: Ciao") == "Ciao"
    assert _clean("  due\n righe  ") == "due righe"
