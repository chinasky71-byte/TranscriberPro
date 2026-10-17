# -*- coding: utf-8 -*-
"""
Aggiunta di righe a un log testuale con barre di avanzamento riscritte sul posto.

Stesso comportamento del log principale (`MainWindow._write_progress_line`): una riga di avanzamento
(Demucs, Traduzione, Trascrizione...) sostituisce la propria barra precedente invece di accodarsi,
a meno che quella sia completa ('✅') o di una fase precedente. Usato dal log del dialogo
Sincronizzazione sottotitoli (`gui/sync_dialog.py`).
"""
import re

from PyQt6.QtGui import QTextCursor

# Stesse chiavi di LogFilter.UPDATABLE_PATTERNS (gui/services/log_filter.py), la logica del log principale.
PROGRESS_PATTERNS = ["Progresso:", "Demucs: [", "Traduzione: [", "Trascrizione: [", "Warm-up: [",
                     "Correzione genere: [", "⚙️ OCR"]
_SCAN_BLOCKS = 40


def _pct(text: str):
    m = re.search(r'(\d+)%', text)
    return int(m.group(1)) if m else None


def append_log_line(edit, msg: str, patterns=PROGRESS_PATTERNS) -> None:
    """Accoda `msg` a `edit` (QTextEdit/QPlainTextEdit); se contiene una barra di avanzamento la
    riscrive sul posto (sempre come ultima riga)."""
    line = msg.rstrip('\n')
    doc = edit.document()
    cursor = QTextCursor(doc)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    last = cursor.block()

    key = next((p for p in patterns if p in line), None) if '\n' not in line else None
    target = None
    if key is not None:
        new_pct = _pct(line)
        blk, n = last, 0
        while blk.isValid() and n < _SCAN_BLOCKS:
            text = blk.text()
            if key in text:
                old_pct = _pct(text)
                if '✅' not in text and (new_pct is None or old_pct is None or old_pct <= new_pct):
                    target = blk
                break
            blk = blk.previous()
            n += 1
        # righe di stato senza % si aggiornano solo se sono l'ultima
        if target is not None and new_pct is None and target.blockNumber() != last.blockNumber():
            target = None

    if target is not None and target.blockNumber() == last.blockNumber():
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(line)
    else:
        if target is not None:
            rm = QTextCursor(target)
            rm.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            rm.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            rm.removeSelectedText()
            cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.position() > 0:
            cursor.insertBlock()
        cursor.insertText(line)
    edit.moveCursor(QTextCursor.MoveOperation.End)
    edit.verticalScrollBar().setValue(edit.verticalScrollBar().maximum())
