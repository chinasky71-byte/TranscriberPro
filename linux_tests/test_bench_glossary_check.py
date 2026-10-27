# -*- coding: utf-8 -*-
"""bench/glossary_check.py: selezione delle righe e punteggio dei termini (nessun modello)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bench'))

import glossary_check as gc  # noqa: E402


def _srt(tmp_path, entries):
    blocks = [f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{text}\n"
              for i, text in enumerate(entries, start=1)]
    path = tmp_path / 'ref.srt'
    path.write_text("\n".join(blocks), encoding='utf-8')
    return path


def test_seleziona_solo_le_righe_con_termini(tmp_path):
    ref = _srt(tmp_path, ["Any dust, Ms. Borden?", "<i>la la la</i>", "Good morning.",
                          "Lizzie is here."])
    lines = gc.lines_with_terms(ref, ["Borden", "Lizzie"])
    assert len(lines) == 2
    assert "Borden" in lines[0] and "Lizzie" in lines[1]


def test_limite(tmp_path):
    ref = _srt(tmp_path, ["Borden uno", "Borden due", "Borden tre"])
    assert len(gc.lines_with_terms(ref, ["Borden"], limit=2)) == 2


def test_punteggio_termini():
    score = gc.score_line("Any dust, Ms. Borden?", "Un po' di polvere, signora Borden?", ["Borden", "Lizzie"])
    assert score["terms"] == ["Borden"] and score["kept"] == ["Borden"] and score["missing"] == []
    lost = gc.score_line("Ms. Borden", "Signora Bond", ["Borden"])
    assert lost["missing"] == ["Borden"]


def test_scrittura_e_rilettura_srt(tmp_path):
    path = gc._write_srt(["riga uno", "riga due"], tmp_path / "x.srt")
    assert gc._read_srt_lines(path) == ["riga uno", "riga due"]


def test_nessun_percorso_personale():
    text = (ROOT / 'bench' / 'glossary_check.py').read_text(encoding='utf-8')
    assert '/home/' not in text and 'C:\\' not in text
