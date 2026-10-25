"""Text helpers for the benchmark harness.

Reference files use a simple ``A: text`` / ``B: text`` format. Normalization is
deliberately conservative: it must be identical for references and hypotheses,
and it must not hide real errors.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

SPEAKER_RE = re.compile(r"^([A-Za-z]):\s*(.*)$")

# Number words that appear in the reference material (English and Italian).
PHRASES = {
    "twenty nineteen": "2019",
    "twenty twenty": "2020",
}
WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50",
    "trenta": "30", "venti": "20", "diciannove": "19",
}

PERCENT_WORDS = ("percent", "percento", "per cento")


@dataclass(frozen=True)
class Line:
    speaker: str
    text: str


def parse_reference(path: Path) -> list[Line]:
    """Return the ``A:``/``B:`` lines of a reference file, in order.

    Header lines before the first speaker line are ignored, so both the
    English and the Italian reference files use the same parser.
    """
    lines: list[Line] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        match = SPEAKER_RE.match(raw.strip())
        if match:
            lines.append(Line(match.group(1).upper(), match.group(2).strip()))
    return lines


def normalize(text: str) -> str:
    """Lowercase, NFKC, numbers to digits, punctuation removed, spaces collapsed."""
    value = unicodedata.normalize("NFKC", text).lower()
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("caffé", "caffe")  # reference typo, normalized on both sides

    for phrase, digits in PHRASES.items():
        value = value.replace(phrase, digits)
    for word, digits in WORDS.items():
        value = re.sub(rf"\b{re.escape(word)}\b", digits, value)
    for word in PERCENT_WORDS:
        value = re.sub(rf"\b{re.escape(word)}\b", "%", value)
    value = re.sub(r"(\d+)\s*%", r"\1%", value)

    value = re.sub(r"[^a-z0-9%' ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def compact(text: str) -> str:
    """Normalized text without spaces, for character-level metrics."""
    return normalize(text).replace(" ", "")


def srt_from_lines(lines: list[Line]) -> str:
    """Build an SRT with one block per reference line.

    Timings are synthetic: translation engines ignore them, and this keeps the
    comparison aligned one-to-one with the reference.
    """
    blocks = []
    for index, line in enumerate(lines, start=1):
        start = f"00:00:{index:02d},000"
        end = f"00:00:{index + 1:02d},000"
        blocks.append(f"{index}\n{start} --> {end}\n{line.text}\n")
    return "\n".join(blocks)


def srt_blocks(path: Path) -> list[str]:
    """Return the text of every block of an SRT file, in order."""
    blocks: list[str] = []
    current: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        if line.isdigit() or "-->" in line:
            continue
        current.append(line)
    if current:
        blocks.append(" ".join(current))
    return blocks
