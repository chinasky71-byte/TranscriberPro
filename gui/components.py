"""Componenti UI riusabili di Transcriber Pro (v1.31).

Riproducono ESATTAMENTE le forme gia' presenti nell'interfaccia; lo stile arriva
dal tema globale (regole a ruolo in gui/theme.qss.tpl, sezione "Ruoli") o, dove
il tema non puo' arrivare (container con QSS ereditato dai figli), da funzioni
centralizzate qui. `RoundedLabel` e `section_qss` sono gia' usati (main_window,
translation_model_dialog); Card/Badge/StatusPill/Section sono pronti per le prossime schermate.

API e corrispondenza con i pattern esistenti
--------------------------------------------
Card(variant='card' | 'tile' | 'pill', margins=None, spacing=None)
    QFrame con layout verticale (`card.body`, un QVBoxLayout) e proprieta' role=variant.
      'card'  = QFrame#collapsibleCard   (bg_2, bordo line, raggio 10)
      'tile'  = QFrame#metricCard / netCard / logStatTile / diagTile / historyStatTile
                (bg_1, bordo line, raggio 8)
      'pill'  = QFrame#statusPill        (bg_1, bordo line, raggio 999)

Badge(text='', tone=None)
    QLabel a pillola. tone=None  -> QLabel#overlayStatusPill (neutro: bg_2, fg_1, bordo line)
                      tone='accent' -> QLabel#overlayLangPill (tinta ciano 15%, bordo 35%)
                      tone='success'|'danger'|'warn'|'purple' -> stessa forma, altro colore.
    badge.set_tone(tone) cambia tono a runtime (unpolish/polish incluso).

StatusPill(text='', tone='success')
    Pillola di stato della titlebar (main_window `_build_titlebar`, centro):
    QFrame#statusPill + pallino 8x8 con effetto opacita' + QLabel#titleBarStatusLabel.
      .set_state(text, tone, pulsing=False)  tone in accent|success|danger|warn|purple|None
      .set_text(text) / .set_tone(tone) / .set_pulsing(bool)   (pulsazione 700 ms, 1.0 <-> 0.2)
      .dot (QFrame), .label (QLabel), .pulse_group (QSequentialAnimationGroup)
    Equivale a _set_status_idle (success, fermo) / _set_status_processing (accent, pulsante).

Section(title, border_color=None, title_color=None, content_margins=None)
    Contenitore con titolo e bordo colorato: replica `_section_qss(...)` +
    titolo "font-size:16px; bold; color" di translation_model_dialog.
      border_color: un colore token (T.section_green, T.section_blue, ...); default T.line (neutro).
      title_color:  default = border_color (nessun colore se neutro).
      .title_label (QLabel), .body (QVBoxLayout) per aggiungere il contenuto.
    section_qss(border_color) restituisce la stringa QSS identica a quella storica.

RoundedLabel
    Copia fedele di main_window.RoundedLabel (poster arrotondato / testo mutato), colori da T.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, QSize
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

from gui.design_tokens import T
from gui.theme import set_role


def section_qss(border_color: str) -> str:
    """QSS di un contenitore "sezione" (identico a translation_model_dialog._section_qss)."""
    return f"""
        QFrame {{
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 15px;
            background-color: {T.bg_2};
        }}
    """


class Card(QFrame):
    """QFrame a ruolo 'card' | 'tile' | 'pill' con layout verticale `body`."""

    def __init__(self, variant: str = 'card', margins=None, spacing=None, parent=None):
        super().__init__(parent)
        set_role(self, variant)
        self.body = QVBoxLayout(self)
        if margins is not None:
            self.body.setContentsMargins(*margins)
        if spacing is not None:
            self.body.setSpacing(spacing)


class Badge(QLabel):
    """Pillola testuale; tone=None neutro, altrimenti accent/success/danger/warn/purple."""

    def __init__(self, text: str = '', tone: str | None = None, parent=None):
        super().__init__(text, parent)
        set_role(self, 'badge', tone)

    def set_tone(self, tone: str | None) -> None:
        set_role(self, 'badge', tone)


class StatusPill(QFrame):
    """Pillola di stato: pallino (opzionalmente pulsante) + testo."""

    def __init__(self, text: str = '', tone: str | None = 'success', parent=None):
        super().__init__(parent)
        self.setObjectName("statusPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)

        self.dot = QFrame()
        self.dot.setFixedSize(8, 8)
        set_role(self.dot, 'dot', tone)

        self._effect = QGraphicsOpacityEffect(self.dot)
        self.dot.setGraphicsEffect(self._effect)
        fade_out = QPropertyAnimation(self._effect, b"opacity")
        fade_out.setDuration(700)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.2)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutSine)
        fade_in = QPropertyAnimation(self._effect, b"opacity")
        fade_in.setDuration(700)
        fade_in.setStartValue(0.2)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.pulse_group = QSequentialAnimationGroup()
        self.pulse_group.addAnimation(fade_out)
        self.pulse_group.addAnimation(fade_in)
        self.pulse_group.setLoopCount(-1)

        self.label = QLabel(text)
        self.label.setObjectName("titleBarStatusLabel")

        lay.addWidget(self.dot)
        lay.addWidget(self.label)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def set_tone(self, tone: str | None) -> None:
        set_role(self.dot, 'dot', tone)

    def set_pulsing(self, pulsing: bool) -> None:
        if pulsing:
            self.pulse_group.start()
        else:
            self.pulse_group.stop()
            self._effect.setOpacity(1.0)

    def set_state(self, text: str, tone: str | None = 'success', pulsing: bool = False) -> None:
        self.set_tone(tone)
        self.label.setText(text)
        self.set_pulsing(pulsing)


class Section(QFrame):
    """Contenitore con titolo e bordo colorato (token). `body` e' il QVBoxLayout del contenuto."""

    def __init__(self, title: str = '', border_color: str | None = None,
                 title_color: str | None = None, content_margins=None, parent=None):
        super().__init__(parent)
        border = border_color or T.line
        self.setStyleSheet(section_qss(border))
        self.body = QVBoxLayout(self)
        if content_margins is not None:
            self.body.setContentsMargins(*content_margins)
        self.title_label = QLabel(title)
        color = title_color or (border if border != T.line else None)
        css = "font-size: 16px; font-weight: bold;"
        if color:
            css += f" color: {color};"
        self.title_label.setStyleSheet(css)
        self.body.addWidget(self.title_label)


class RoundedLabel(QLabel):
    """
    QLabel con paintEvent custom: il background arrotondato viene disegnato
    solo nell'area occupata dall'immagine, lasciando il resto trasparente.
    In modalita' testo (nessun pixmap) riempie tutto il widget.
    (Copia di main_window.RoundedLabel con colori da design tokens.)
    """

    _BG = T.poster_bg
    _BORD = T.poster_border
    _RADIU = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig_pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Stile solo per la modalita' testo (text/color ereditati dal tema)
        self.setStyleSheet(
            f"QLabel {{ color: {T.legacy_grey_888}; font-size: 10pt; background: transparent; }}"
        )

    def minimumSizeHint(self):
        return QSize(80, 80)

    def setPixmap(self, px):
        self._orig_pixmap = px
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._orig_pixmap and not self._orig_pixmap.isNull():
            scaled = self._orig_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ix = (self.width() - scaled.width()) // 2
            iy = (self.height() - scaled.height()) // 2
            iw, ih = scaled.width(), scaled.height()

            path = QPainterPath()
            path.addRoundedRect(ix, iy, iw, ih, self._RADIU, self._RADIU)
            p.fillPath(path, QColor(*self._BG))
            p.setClipPath(path)
            p.drawPixmap(ix, iy, scaled)
            p.setClipping(False)
            p.setPen(QPen(QColor(*self._BORD), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ix + 1, iy + 1, iw - 2, ih - 2, self._RADIU - 1, self._RADIU - 1)
        else:
            # Modalita' testo: background su tutto il widget
            r = self._RADIU
            path = QPainterPath()
            path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, r, r)
            p.fillPath(path, QColor(*self._BG))
            p.setPen(QPen(QColor(*self._BORD), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, r, r)
            p.end()
            super().paintEvent(event)  # disegna il testo sopra
            return

        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()
