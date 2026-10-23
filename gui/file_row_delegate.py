"""
File Row Delegate
File: gui/file_row_delegate.py

QStyledItemDelegate per la file_list nel pannello sinistro.
Disegna: dot status colorato, nome file (bold), riga meta mono
(dimensione · stato), progress bar inline 4px se status='processing'.

Row height: 44px.
Introdotto in Fase 3 del GUI revamp.
"""

from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QColor, QBrush, QFont, QPainter

from gui.design_tokens import T
from utils.translations import tr


STATUS_COLORS = dict(T.STATUS_COLORS)

# chiavi di traduzione (tr() al momento del disegno: segue la lingua dell'interfaccia)
STATUS_LABELS = {
    'queued':     'dl_queued',
    'processing': 'dl_processing',
    'completed':  'dl_completed',
    'failed':     'dl_failed',
}

ROW_HEIGHT = 44


class FileRowDelegate(QStyledItemDelegate):
    """Delegate che disegna ogni file nella coda con status, meta e progress."""

    def sizeHint(self, option, index):
        return QSize(0, ROW_HEIGHT)  # larghezza 0 = nessuna preferenza, layout decide

    def paint(self, painter: QPainter, option, index):
        painter.save()

        r = option.rect

        # Background
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected:
            painter.fillRect(r, QColor(T.bg_3))
        elif bool(option.state & QStyle.StateFlag.State_MouseOver):
            painter.fillRect(r, QColor(T.bg_2))
        else:
            painter.fillRect(r, QColor(T.bg_1))

        data = index.data(Qt.ItemDataRole.UserRole) or {}
        status   = data.get('status', 'queued')
        progress = int(data.get('progress', 0))
        filename = data.get('filename') or index.data(Qt.ItemDataRole.DisplayRole) or ''
        size     = data.get('size', '')

        x, y, w, h = r.x(), r.y(), r.width(), r.height()

        # --- Status dot (8×8, margine sinistro 12) -----------------------
        dot_x = x + 12
        dot_y = y + (h - 8) // 2
        dot_color = QColor(STATUS_COLORS.get(status, T.fg_4))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(dot_x, dot_y, 8, 8)

        # --- Area testo --------------------------------------------------
        text_x = dot_x + 16
        text_w = w - (text_x - x) - 10

        # Riga 1: nome file (bold, 9pt)
        name_font = QFont(option.font)
        name_font.setPointSize(9)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor(T.fg_row if not is_selected else T.white))
        name_rect = QRect(text_x, y + 5, text_w, 16)
        filename_elided = painter.fontMetrics().elidedText(
            filename, Qt.TextElideMode.ElideMiddle, text_w
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         filename_elided)

        # Riga 2: meta (mono, 7pt, grigio)
        meta_parts = []
        if size:
            meta_parts.append(size)
        meta_parts.append(tr(STATUS_LABELS[status]) if status in STATUS_LABELS else status)
        if status == 'processing' and progress > 0:
            meta_parts.append(f'{progress}%')
        meta = ' · '.join(meta_parts)

        meta_font = QFont()
        meta_font.setFamilies(['JetBrains Mono', 'Consolas', 'Courier New'])
        meta_font.setPointSize(7)
        painter.setFont(meta_font)
        painter.setPen(QColor(T.fg_4))
        meta_rect = QRect(text_x, y + 23, text_w, 14)
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         meta)

        # Eccezioni di QUESTO file alle opzioni predefinite (etichetta breve, utils/job_overrides.py), a destra sulla riga meta
        ov = data.get('ov')
        if ov:
            painter.setPen(QColor(T.accent))
            ov_text = painter.fontMetrics().elidedText(ov, Qt.TextElideMode.ElideRight, max(40, text_w // 2))
            painter.drawText(meta_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, ov_text)

        # --- Progress bar inline (4px, fondo riga) se status='processing' -
        if status == 'processing' and progress > 0:
            bar_y = y + h - 4
            bar_w = max(1, int(w * progress / 100))
            # traccia vuota
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(T.line)))
            painter.drawRect(x, bar_y, w, 4)
            # barra riempita
            painter.setBrush(QBrush(QColor(T.accent)))
            painter.drawRect(x, bar_y, bar_w, 4)

        painter.restore()
