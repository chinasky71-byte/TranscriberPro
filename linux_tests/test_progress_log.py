# -*- coding: utf-8 -*-
"""Fase 4c: ProgressLog (core) = gui.progress_log.append_log_line su sequenze di righe, confrontato con un vero QTextEdit."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.progress_log import ProgressLog  # noqa: E402
from core.services.log_filter import UPDATABLE_PATTERNS  # noqa: E402

KEY = next(iter(UPDATABLE_PATTERNS))
KEY2 = list(UPDATABLE_PATTERNS)[1] if len(UPDATABLE_PATTERNS) > 1 else KEY

SEQS = {
    'bar_in_place': [f'{KEY} 10%', f'{KEY} 20%', f'{KEY} 55%'],
    'bar_then_text_then_bar': [f'{KEY} 10%', 'testo', f'{KEY} 30%', 'altro', f'{KEY} 60%'],
    'complete_bar_is_kept': [f'{KEY} 100% ✅', f'{KEY} 5%'],
    'lower_pct_is_a_new_phase': [f'{KEY} 80%', f'{KEY} 10%'],
    'status_without_pct_only_if_last': [f'{KEY} 10%', f'{KEY}', 'x', f'{KEY}'],
    'multiline_never_updates': [f'{KEY} 10%', f'{KEY} 20%\naltro'],
    'two_kinds': [f'{KEY} 10%', f'{KEY2} 10%', f'{KEY} 40%', f'{KEY2} 50%'],
    'plain': ['a', 'b\n', 'c'],
    'empty': ['', f'{KEY} 1%', ''],
    'far_bar_not_found': ['x'] * 45 + [f'{KEY} 10%'] + ['y'] * 45 + [f'{KEY} 20%'],
}


@pytest.mark.parametrize('name', sorted(SEQS))
def test_come_append_log_line_della_gui(name, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication, QTextEdit
    app = QApplication.instance() or QApplication([])      # noqa: F841
    from gui.progress_log import append_log_line
    edit, log = QTextEdit(), ProgressLog(keep=10 ** 6)
    for msg in SEQS[name]:
        append_log_line(edit, msg)
        log.append(msg)
        assert edit.toPlainText() == '\n'.join(log.lines), (name, msg)


def test_le_operazioni_descrivono_la_modifica():
    log = ProgressLog()
    assert log.append(f'{KEY} 10%') == {'op': 'append', 'line': f'{KEY} 10%'}
    assert log.append(f'{KEY} 20%') == {'op': 'update_last', 'line': f'{KEY} 20%'}
    log.append('testo')
    assert log.append(f'{KEY} 30%') == {'op': 'replace', 'line': f'{KEY} 30%', 'remove_index': 0}
    assert log.lines == ['testo', f'{KEY} 30%']


def test_tiene_solo_le_ultime_righe():
    log = ProgressLog(keep=3)
    for i in range(6):
        log.append(f'r{i}')
    assert log.lines == ['r3', 'r4', 'r5']
