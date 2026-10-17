# -*- coding: utf-8 -*-
"""
OcrReviewDialog — Revisione mirata OCR sottotitoli bitmap (PGS → SRT).
File: gui/ocr_review_dialog.py

Scopo (verbatim): l'utente verifica che il testo OCR corrisponda ESATTAMENTE al
bitmap. Nessuna correzione automatica: l'utente è l'unica fonte di verità.

Contratto dati: core/pgs_types.py (OcrEvent, events_to_srt). NON inventare lo schema.

Possiede SOLO questo file. Stringhe UI solo via tr(). Stile dark slate, accent ciano (T.accent).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QPlainTextEdit, QCheckBox, QSplitter, QWidget, QFrame,
)
from PyQt6.QtCore import Qt, QByteArray, QBuffer, QIODevice, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtGui import QPixmap, QImage, QFont

from core.pgs_types import OcrEvent, events_to_srt
from gui.design_tokens import T
from gui.icons import svg_icon
from gui.styles import load_qss
from utils.translations import tr

logger = logging.getLogger(__name__)

ACCENT = T.accent

# Soglia colore badge confidenza (puramente visiva; il flag autorevole è is_flagged).
_CONF_OK = 85.0
_CONF_WARN = 70.0


def _pil_to_qpixmap(image) -> Optional[QPixmap]:
    """Converte una PIL.Image in QPixmap.

    Prova prima PIL.ImageQt; in fallback serializza in PNG (bytes) e carica via
    QImage. Ritorna None se l'immagine è None o la conversione fallisce.
    """
    if image is None:
        return None
    # 1) Via ImageQt (preferito, niente copie di byte espliciti)
    try:
        from PIL.ImageQt import ImageQt
        qimg = ImageQt(image.convert("RGBA"))
        pm = QPixmap.fromImage(QImage(qimg))
        if not pm.isNull():
            return pm
    except Exception:
        logger.debug("ImageQt non disponibile o fallita; fallback su bytes", exc_info=True)
    # 2) Fallback: bytes RGBA grezzi → QImage
    try:
        rgba = image.convert("RGBA")
        w, h = rgba.size
        data = rgba.tobytes("raw", "RGBA")
        qimg = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        # QImage non possiede 'data': copia per sicurezza prima che 'data' venga GC.
        pm = QPixmap.fromImage(qimg.copy())
        if not pm.isNull():
            return pm
    except Exception:
        logger.warning("Conversione PIL→QPixmap fallita", exc_info=True)
    # 3) Ultimo tentativo: salva PNG in buffer e carica
    try:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        image.convert("RGBA").save(buf, format="PNG")  # type: ignore[arg-type]
        buf.close()
        pm = QPixmap()
        if pm.loadFromData(ba, "PNG") and not pm.isNull():
            return pm
    except Exception:
        logger.warning("Conversione PIL→QPixmap (PNG buffer) fallita", exc_info=True)
    return None


class OcrReviewDialog(QDialog):
    """Dialog di revisione mirata degli eventi OCR.

    API pubblica:
        OcrReviewDialog(events: list[OcrEvent], parent=None)
        get_srt()    -> str               # events_to_srt con le correzioni applicate
        get_events() -> list[OcrEvent]    # gli stessi eventi (mutati in-place)
    """

    def __init__(self, events: List[OcrEvent], parent=None):
        super().__init__(parent)
        self.events: List[OcrEvent] = list(events or [])
        self._current: int = -1  # indice nella lista self.events dell'evento mostrato

        self.setWindowTitle(tr('ocr_review_title'))
        self.setModal(True)
        self.resize(1000, 680)

        self._init_ui()
        self._apply_styles()
        self._populate_list()

        # Seleziona il primo evento dubbio se presente, altrimenti il primo.
        first = self._next_flagged_from(-1)
        if first is None and self.events:
            first = 0
        if first is not None:
            self._select_index(first)
        else:
            self._show_event(-1)

    # ── UI ──────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header con istruzione VERBATIM
        header = QLabel(tr('ocr_review_instruction'))
        header.setWordWrap(True)
        header.setObjectName("ocrHeader")
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Sinistra: filtro + lista ─────────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        self.only_flagged_cb = QCheckBox(tr('ocr_only_flagged'))
        self.only_flagged_cb.toggled.connect(self._on_filter_toggled)
        left_lay.addWidget(self.only_flagged_cb)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_list_row_changed)
        left_lay.addWidget(self.list_widget, 1)

        self.counter_label = QLabel("")
        self.counter_label.setObjectName("ocrCounter")
        left_lay.addWidget(self.counter_label)

        splitter.addWidget(left)

        # ── Destra: immagine + testo + comandi ───────────────────────────────
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        # Timecode / stato evento
        self.event_info = QLabel("")
        self.event_info.setObjectName("ocrEventInfo")
        right_lay.addWidget(self.event_info)

        # Immagine PGS originale
        self.image_label = QLabel(tr('ocr_no_image'))
        self.image_label.setObjectName("ocrImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(160)
        self.image_label.setFrameShape(QFrame.Shape.StyledPanel)
        right_lay.addWidget(self.image_label, 1)

        # Etichetta testo OCR
        text_lbl = QLabel(tr('ocr_text_label'))
        right_lay.addWidget(text_lbl)

        # Editor testo OCR (multilinea, preserva \n)
        self.text_edit = _PlainTextEditEnter(self)
        self.text_edit.setFont(QFont("Segoe UI", 11))
        self.text_edit.enterPressed.connect(self._on_enter_save_next)
        right_lay.addWidget(self.text_edit, 1)

        # Barra comandi
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)

        self.italic_btn = QPushButton(svg_icon('language', 16, ACCENT), tr('ocr_toggle_italic'))
        self.italic_btn.setToolTip(tr('ocr_toggle_italic_tip'))
        self.italic_btn.clicked.connect(self._toggle_italic)
        cmd_row.addWidget(self.italic_btn)

        cmd_row.addStretch(1)

        # Nota: icons.py non ha 'chevLeft'; Prev resta senza icona direzionale.
        self.prev_btn = QPushButton(tr('ocr_prev'))
        self.prev_btn.clicked.connect(self._go_prev)
        cmd_row.addWidget(self.prev_btn)

        self.next_btn = QPushButton(svg_icon('chevRight', 16, T.legacy_grey_ccc), tr('ocr_next'))
        self.next_btn.clicked.connect(self._go_next)
        cmd_row.addWidget(self.next_btn)

        self.verify_btn = QPushButton(svg_icon('check', 16, T.legacy_bg_dialog), tr('ocr_verified'))
        self.verify_btn.setObjectName("ocrVerifyBtn")
        self.verify_btn.setToolTip(tr('ocr_verified_tip'))
        self.verify_btn.clicked.connect(self._mark_verified)
        cmd_row.addWidget(self.verify_btn)

        right_lay.addLayout(cmd_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 680])
        root.addWidget(splitter, 1)

        # Pulsanti di chiusura
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.close_btn = QPushButton(tr('ocr_done'))
        self.close_btn.setObjectName("ocrDoneBtn")
        self.close_btn.setFixedWidth(160)
        self.close_btn.clicked.connect(self._on_done)
        footer.addWidget(self.close_btn)
        root.addLayout(footer)

    def _apply_styles(self):
        self.setStyleSheet(load_qss('ocr_review'))

    # ── Lista ────────────────────────────────────────────────────────────────

    def _conf_dot(self, ev: OcrEvent) -> str:
        """Pallino colorato (unicode) in base alla confidenza."""
        c = ev.confidence or 0.0
        if c >= _CONF_OK:
            return "🟢"
        if c >= _CONF_WARN:
            return "🟡"
        return "🔴"

    def _item_label(self, ev: OcrEvent) -> str:
        snippet = (ev.text or "").replace("\n", " ").strip()
        if len(snippet) > 40:
            snippet = snippet[:40] + "…"
        if not snippet:
            snippet = tr('ocr_empty_text')
        check = "✓ " if ev.verified else ""
        return f"{self._conf_dot(ev)} #{ev.index}  {check}{snippet}"

    def _populate_list(self):
        """Ricostruisce la lista rispettando il filtro 'solo dubbi'.

        Ogni item memorizza in UserRole l'indice nell'array self.events.
        """
        only_flagged = self.only_flagged_cb.isChecked()
        prev_data_idx = self._current

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        target_row = -1
        for data_idx, ev in enumerate(self.events):
            if only_flagged and not ev.is_flagged:
                continue
            item = QListWidgetItem(self._item_label(ev))
            item.setData(Qt.ItemDataRole.UserRole, data_idx)
            self.list_widget.addItem(item)
            if data_idx == prev_data_idx:
                target_row = self.list_widget.count() - 1
        self.list_widget.blockSignals(False)

        if target_row >= 0:
            self.list_widget.setCurrentRow(target_row)
        self._update_counter()

    def _refresh_current_item_label(self):
        """Aggiorna l'etichetta dell'item attualmente selezionato (testo/verified)."""
        row = self.list_widget.currentRow()
        if row < 0:
            return
        item = self.list_widget.item(row)
        if item is None:
            return
        data_idx = item.data(Qt.ItemDataRole.UserRole)
        if data_idx is None or data_idx >= len(self.events):
            return
        item.setText(self._item_label(self.events[data_idx]))

    def _update_counter(self):
        total = len(self.events)
        flagged = sum(1 for ev in self.events if ev.is_flagged)
        self.counter_label.setText(
            tr('ocr_counter').format(total=total, flagged=flagged)
        )

    # ── Navigazione ────────────────────────────────────────────────────────

    def _data_index_at_row(self, row: int) -> int:
        if row < 0:
            return -1
        item = self.list_widget.item(row)
        if item is None:
            return -1
        d = item.data(Qt.ItemDataRole.UserRole)
        return -1 if d is None else int(d)

    def _row_for_data_index(self, data_idx: int) -> int:
        for row in range(self.list_widget.count()):
            if self._data_index_at_row(row) == data_idx:
                return row
        return -1

    def _next_flagged_from(self, data_idx: int) -> Optional[int]:
        """Primo evento dubbio con indice > data_idx (None se nessuno)."""
        for i in range(data_idx + 1, len(self.events)):
            if self.events[i].is_flagged:
                return i
        # wrap-around: cerca dall'inizio
        for i in range(0, data_idx + 1):
            if self.events[i].is_flagged:
                return i
        return None

    def _select_index(self, data_idx: int):
        """Seleziona nella lista l'evento con dato indice (se visibile)."""
        row = self._row_for_data_index(data_idx)
        if row < 0:
            # Evento filtrato fuori: disattiva filtro per mostrarlo.
            if self.only_flagged_cb.isChecked():
                self.only_flagged_cb.blockSignals(True)
                self.only_flagged_cb.setChecked(False)
                self.only_flagged_cb.blockSignals(False)
                self._populate_list()
                row = self._row_for_data_index(data_idx)
        if row >= 0:
            self.list_widget.setCurrentRow(row)
        else:
            self._show_event(data_idx)

    def _on_list_row_changed(self, row: int):
        self._show_event(self._data_index_at_row(row))

    def _go_prev(self):
        self._save_current_text()
        if self._current <= 0:
            return
        self._select_index(self._current - 1)

    def _go_next(self):
        self._save_current_text()
        if self._current < 0 or self._current >= len(self.events) - 1:
            return
        self._select_index(self._current + 1)

    def _on_enter_save_next(self):
        """Invio nel testo: salva la modifica e salta alla prossima riga dubbia."""
        self._save_current_text()
        nxt = self._next_flagged_from(self._current)
        if nxt is not None and nxt != self._current:
            self._select_index(nxt)
        elif nxt is not None and nxt == self._current:
            # Unico dubbio rimasto: nessun salto.
            pass

    # ── Visualizzazione evento ───────────────────────────────────────────────

    def _show_event(self, data_idx: int):
        """Mostra l'evento di indice data_idx (-1 = nessuno)."""
        self._current = data_idx
        has = 0 <= data_idx < len(self.events)

        self.text_edit.setEnabled(has)
        self.italic_btn.setEnabled(has)
        self.verify_btn.setEnabled(has)
        self.prev_btn.setEnabled(has and data_idx > 0)
        self.next_btn.setEnabled(has and data_idx < len(self.events) - 1)

        if not has:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(tr('ocr_no_image'))
            self.text_edit.blockSignals(True)
            self.text_edit.setPlainText("")
            self.text_edit.blockSignals(False)
            self.event_info.setText("")
            return

        ev = self.events[data_idx]

        # Immagine
        self._render_image(ev)

        # Testo (preserva \n)
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(ev.text or "")
        self.text_edit.blockSignals(False)
        self.text_edit.setFocus()

        # Info evento
        from core.pgs_types import ms_to_srt_timestamp
        state = tr('ocr_state_verified') if ev.verified else (
            tr('ocr_state_flagged') if ev.is_flagged else tr('ocr_state_ok')
        )
        self.event_info.setText(
            f"#{ev.index}  "
            f"{ms_to_srt_timestamp(ev.start_ms)} → {ms_to_srt_timestamp(ev.end_ms)}  "
            f"·  {tr('ocr_confidence')}: {ev.confidence:.0f}  ·  {state}"
        )

    def _render_image(self, ev: OcrEvent):
        pm = _pil_to_qpixmap(ev.image)
        self._current_pixmap = pm  # conserva per il rescale su resize
        if pm is None:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(tr('ocr_no_image'))
            return
        self._rescale_image()

    def _rescale_image(self):
        pm = getattr(self, "_current_pixmap", None)
        if pm is None or pm.isNull():
            return
        area = self.image_label.size()
        scaled = pm.scaled(
            area,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_image()

    # ── Editing ────────────────────────────────────────────────────────────

    def _save_current_text(self):
        """Scrive il testo dell'editor nell'OcrEvent corrente."""
        if not (0 <= self._current < len(self.events)):
            return
        new_text = self.text_edit.toPlainText()
        ev = self.events[self._current]
        if ev.text != new_text:
            ev.text = new_text
            self._refresh_current_item_label()

    def _mark_verified(self):
        """Marca l'evento come verificato: salva testo, verified=True, pulisce i flag."""
        if not (0 <= self._current < len(self.events)):
            return
        self._save_current_text()
        ev = self.events[self._current]
        ev.verified = True
        ev.flags = set()  # rimuove il flag → non più "dubbio"
        self._refresh_current_item_label()
        self._update_counter()

        # Salta alla prossima riga dubbia, se presente.
        nxt = self._next_flagged_from(self._current)
        if nxt is not None and nxt != self._current:
            self._select_index(nxt)
        else:
            # Se il filtro è attivo, l'item appena verificato sparisce: ripopola.
            if self.only_flagged_cb.isChecked():
                self._populate_list()

    def _toggle_italic(self):
        """Avvolge/rimuove <i>...</i> sulla selezione, o sull'intero testo."""
        if not (0 <= self._current < len(self.events)):
            return
        cursor = self.text_edit.textCursor()
        full = self.text_edit.toPlainText()

        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            segment = full[start:end]
            new_segment = self._toggle_italic_on(segment)
            new_full = full[:start] + new_segment + full[end:]
            self.text_edit.setPlainText(new_full)
            # Ripristina una selezione plausibile sul nuovo segmento.
            cur = self.text_edit.textCursor()
            cur.setPosition(start)
            cur.setPosition(start + len(new_segment), QTextCursor.MoveMode.KeepAnchor)
            self.text_edit.setTextCursor(cur)
        else:
            self.text_edit.setPlainText(self._toggle_italic_on(full))

        self._save_current_text()

    @staticmethod
    def _toggle_italic_on(text: str) -> str:
        s = text.strip()
        if s.startswith("<i>") and s.endswith("</i>"):
            # Rimuove i tag preservando spazi esterni.
            lead = text[:len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            inner = s[3:-4]
            return f"{lead}{inner}{trail}"
        if not s:
            return text
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        return f"{lead}<i>{s}</i>{trail}"

    # ── Filtro ───────────────────────────────────────────────────────────────

    def _on_filter_toggled(self, _checked: bool):
        self._save_current_text()
        self._populate_list()
        # Se l'item corrente è sparito, seleziona il primo disponibile.
        if self.list_widget.currentRow() < 0 and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        elif self.list_widget.count() == 0:
            self._show_event(-1)

    # ── Chiusura / API pubblica ──────────────────────────────────────────────

    def _on_done(self):
        self._save_current_text()
        self.accept()

    def closeEvent(self, event):
        self._save_current_text()
        super().closeEvent(event)

    def get_events(self) -> List[OcrEvent]:
        """Ritorna gli eventi (mutati in-place con le correzioni umane)."""
        self._save_current_text()
        return self.events

    def get_srt(self) -> str:
        """Ritorna l'SRT ricostruito con le correzioni applicate (timestamp invariati)."""
        self._save_current_text()
        return events_to_srt(self.events)


class _PlainTextEditEnter(QPlainTextEdit):
    """QPlainTextEdit che emette enterPressed su Invio (senza Shift) e usa
    Shift+Invio / Ctrl+Invio per inserire una nuova riga reale."""

    enterPressed = pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = event.modifiers()
            if mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                # Nuova riga reale nel testo OCR.
                super().keyPressEvent(event)
                return
            # Invio semplice: salva e salta.
            self.enterPressed.emit()
            return
        super().keyPressEvent(event)
