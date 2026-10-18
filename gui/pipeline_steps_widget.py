# -*- coding: utf-8 -*-
"""
"Pipeline in corso": elenco dei passi del file in lavorazione (visibile con "Log Sintetico").

Vista disegnata a mano (QPainter, come FileRowDelegate): nessuna logica di piano qui, riceve
`PipelineSnapshot` da gui/services/step_plan.py. Colori solo dai token (gui.design_tokens.T).

Stati di una riga: fatto (cerchio verde con spunta), attivo (anello ciano, etichetta in grassetto, percentuale,
ETA e barra), in attesa (numero d'ordine), disattivato / non necessario (cerchio tratteggiato con x, etichetta
barrata), errore, interrotto. La barra e': reale (`pct`), STIMATA (salvataggio/upload: `est_tau`, animata) oppure
indeterminata (passo senza misura).
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from gui.design_tokens import T
from gui.services.step_plan import (ACTIVE, DISABLED, DONE, FAILED, NOT_NEEDED, PENDING, STOPPED,
                                    PipelineSnapshot, est_pct)
from utils.translations import tr

HEADER_H = 32
ROW_H = 30
ACTIVE_ROW_H = 44
PAD_L = 10
PAD_R = 12
CIRCLE = 22
LABEL_X = 44
BOTTOM_PAD = 8

_STATE_TEXT_KEY = {DONE: 'step_state_done', DISABLED: 'step_state_disabled', NOT_NEEDED: 'step_state_not_needed',
                   FAILED: 'step_state_failed', STOPPED: 'step_state_stopped'}


def _c(token: str, alpha: Optional[float] = None) -> QColor:
    col = QColor(token)
    if alpha is not None:
        col.setAlphaF(alpha)
    return col


def _mono(size_pt: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(['JetBrains Mono', 'Consolas', 'Courier New'])
    f.setPointSizeF(size_pt)
    f.setBold(bold)
    return f


class PipelineStepsWidget(QWidget):
    """Elenco dei passi con linea del tempo. Segnale `toggled(bool)`: True = espanso."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipelineCard")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self._snap: Optional[PipelineSnapshot] = None
        self._expanded = True
        self._animated = True
        self._clock = time.time
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.update)
        self._relayout()

    # ------------------------------------------------------------------ API
    def set_snapshot(self, snap: Optional[PipelineSnapshot]) -> None:
        self._snap = snap
        self._relayout()
        self._sync_timer()
        self.update()

    def snapshot(self) -> Optional[PipelineSnapshot]:
        return self._snap

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self._expanded:
            self._expanded = expanded
            self._relayout()
            self._sync_timer()
            self.update()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_animated(self, animated: bool, clock=None) -> None:
        """Banco/test: ferma le animazioni e (facoltativo) fissa l'orologio della barra stimata."""
        self._animated = animated
        if clock is not None:
            self._clock = clock
        self._sync_timer()

    # ------------------------------------------------------------------ layout
    def _row_heights(self):
        if self._snap is None:
            return []
        return [ACTIVE_ROW_H if s.status == ACTIVE else ROW_H for s in self._snap.steps]

    def _relayout(self) -> None:
        h = HEADER_H
        if self._expanded and self._snap is not None:
            h += sum(self._row_heights()) + BOTTOM_PAD
        self.setFixedHeight(h)

    def _needs_animation(self) -> bool:
        if not (self._animated and self._expanded and self._snap is not None and self.isVisible()):
            return False
        # solo le barre stimate o indeterminate si animano: con una percentuale reale basta ridisegnare agli aggiornamenti
        return any(s.status == ACTIVE and s.pct is None for s in self._snap.steps)

    def _sync_timer(self) -> None:
        if self._needs_animation():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() <= HEADER_H:
            self.set_expanded(not self._expanded)
            self.toggled.emit(self._expanded)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.CursorShape.PointingHandCursor if e.position().y() <= HEADER_H
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    # ------------------------------------------------------------------ disegno
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w = self.width()
        p.setPen(QPen(_c(T.line), 1))
        p.drawLine(0, 0, w, 0)
        self._paint_header(p, w)
        if self._expanded and self._snap is not None:
            self._paint_rows(p, w)
        p.end()

    def _paint_header(self, p: QPainter, w: int) -> None:
        snap = self._snap
        x = PAD_L
        cap = QFont(self.font())
        cap.setPointSizeF(8.0)
        cap.setBold(True)
        cap.setCapitalization(QFont.Capitalization.AllUppercase)
        cap.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        p.setFont(cap)
        p.setPen(_c(T.fg_3))
        text = tr('pipeline_in_progress')
        cw = QFontMetrics(cap).horizontalAdvance(text.upper())
        p.drawText(QRectF(x, 0, cw + 2, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   text.upper())
        x += cw + 10
        if snap is not None:
            pill = f"{snap.done}/{snap.total}"
            pf = _mono(8.0, True)
            pw = QFontMetrics(pf).horizontalAdvance(pill) + 14
            r = QRectF(x, (HEADER_H - 18) / 2, pw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(T.bg_3))
            p.drawRoundedRect(r, 9, 9)
            p.setFont(pf)
            p.setPen(_c(T.fg_0))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, pill)
            x += pw + 10
            nf = _mono(8.0)
            p.setFont(nf)
            p.setPen(_c(T.fg_4))
            avail = max(0, w - x - PAD_R - 22)
            p.drawText(QRectF(x, 0, avail, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(nf).elidedText(snap.file_name, Qt.TextElideMode.ElideMiddle, int(avail)))
        # chevron (giu' = espanso, destra = compresso)
        cx, cy = w - PAD_R - 6, HEADER_H / 2
        path = QPainterPath()
        if self._expanded:
            path.moveTo(cx - 4, cy - 2); path.lineTo(cx, cy + 2); path.lineTo(cx + 4, cy - 2)
        else:
            path.moveTo(cx - 2, cy - 4); path.lineTo(cx + 2, cy); path.lineTo(cx - 2, cy + 4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(_c(T.fg_3), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)

    def _paint_rows(self, p: QPainter, w: int) -> None:
        steps = self._snap.steps
        heights = self._row_heights()
        cx = PAD_L + CIRCLE / 2
        # filo della linea del tempo
        y = HEADER_H
        centers = []
        for h in heights:
            centers.append(y + ROW_H / 2)
            y += h
        p.setPen(QPen(_c(T.line_strong), 1))
        r = CIRCLE / 2 + 1
        for a, b in zip(centers, centers[1:]):      # un tratto tra un cerchio e il successivo (niente alone di sfondo)
            p.drawLine(QPointF(cx, a + r), QPointF(cx, b - r))
        now = self._clock()
        for s, cy in zip(steps, centers):
            self._paint_row(p, s, cy, w, now)

    def _paint_row(self, p: QPainter, s, cy: float, w: int, now: float) -> None:
        cx = PAD_L + CIRCLE / 2
        rect = QRectF(cx - CIRCLE / 2, cy - CIRCLE / 2, CIRCLE, CIRCLE)
        label = tr(s.label_key)
        lf = QFont(self.font())
        lf.setPointSizeF(10.0)
        right_text, right_color, right_font = '', _c(T.fg_3), _mono(8.5)
        label_color = _c(T.fg_1)
        strike = False

        p.setPen(Qt.PenStyle.NoPen)

        if s.status == DONE:
            p.setBrush(_c(T.success))
            p.drawEllipse(rect)
            self._check(p, cx, cy, _c(T.on_accent))
            right_text, right_color = tr(_STATE_TEXT_KEY[DONE]), _c(T.success)
        elif s.status == ACTIVE:
            p.setBrush(_c(T.accent, 0.12))
            p.drawEllipse(rect.adjusted(-3, -3, 3, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c(T.accent), 2))
            p.drawEllipse(rect.adjusted(1, 1, -1, -1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(T.accent))
            p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
            lf.setBold(True)
            label_color = _c(T.fg_0)
        elif s.status in (DISABLED, NOT_NEEDED):
            pen = QPen(_c(T.fg_disabled), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            p.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setPen(QPen(_c(T.fg_disabled), 1.3))
            p.drawLine(QPointF(cx - 3, cy - 3), QPointF(cx + 3, cy + 3))
            p.drawLine(QPointF(cx - 3, cy + 3), QPointF(cx + 3, cy - 3))
            label_color = _c(T.fg_disabled)
            strike = True
            right_text, right_color = tr(_STATE_TEXT_KEY[s.status]), _c(T.fg_disabled)
        elif s.status in (FAILED, STOPPED):
            col = _c(T.danger if s.status == FAILED else T.fg_3)
            p.setBrush(col)
            p.drawEllipse(rect)
            p.setPen(QPen(_c(T.on_accent), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if s.status == FAILED:
                p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 1))
                p.drawPoint(QPointF(cx, cy + 5))
            else:
                p.drawRect(QRectF(cx - 3, cy - 3, 6, 6))
            right_text, right_color = tr(_STATE_TEXT_KEY[s.status]), col
            label_color = _c(T.fg_1)
        else:  # PENDING
            p.setBrush(_c(T.bg_1))
            p.setPen(QPen(_c(T.fg_4), 1))
            p.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setFont(_mono(8.0))
            p.setPen(_c(T.fg_3))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(s.order) if s.order is not None else '')

        # testo a destra
        right_x = w - PAD_R
        pct_val = None
        if s.status == ACTIVE:
            pct_val = s.pct if s.pct is not None else (est_pct(s, now) if s.est_tau else None)
        if s.status == ACTIVE and pct_val is not None:
            right_text, right_color, right_font = f"{pct_val}%", _c(T.accent), _mono(8.5, True)
        fm = QFontMetrics(right_font)
        rw = fm.horizontalAdvance(right_text) if right_text else 0
        if right_text:
            p.setFont(right_font)
            p.setPen(right_color)
            p.drawText(QRectF(right_x - rw, cy - 10, rw, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       right_text)
        eta_w = 0
        if s.status == ACTIVE and s.eta:
            ef = _mono(8.0)
            eta_w = QFontMetrics(ef).horizontalAdvance(s.eta) + 8
            p.setFont(ef)
            p.setPen(_c(T.fg_3))
            p.drawText(QRectF(right_x - rw - eta_w, cy - 10, eta_w - 8, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, s.eta)

        # etichetta
        lf.setStrikeOut(strike)
        p.setFont(lf)
        p.setPen(label_color)
        avail = max(0, right_x - rw - eta_w - 10 - LABEL_X)
        p.drawText(QRectF(LABEL_X, cy - 10, avail, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(lf).elidedText(label, Qt.TextElideMode.ElideRight, int(avail)))

        # barra (solo passo attivo)
        if s.status == ACTIVE:
            bx, by, bw, bh = LABEL_X, cy + 15, max(0, w - PAD_R - LABEL_X), 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(T.bg_3))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 2, 2)
            p.setBrush(_c(T.accent))
            if pct_val is not None:
                fw = bw * max(0, min(100, pct_val)) / 100.0
                if fw > 0:
                    p.drawRoundedRect(QRectF(bx, by, max(fw, 4), bh), 2, 2)
            else:   # indeterminata: tratto che scorre
                seg = bw * 0.3
                ph = ((now * 0.8) % 1.0) if self._animated else 0.35
                x0 = bx + (bw + seg) * ph - seg
                a, b = max(bx, x0), min(bx + bw, x0 + seg)
                if b > a:
                    p.drawRoundedRect(QRectF(a, by, b - a, bh), 2, 2)

    @staticmethod
    def _check(p: QPainter, cx: float, cy: float, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(cx - 4, cy + 0.5)
        path.lineTo(cx - 1, cy + 3.5)
        path.lineTo(cx + 4.5, cy - 3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
