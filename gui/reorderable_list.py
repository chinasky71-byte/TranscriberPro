"""Lista file con riordino via drag & drop dei soli elementi 'spostabili'.

Non tocca layout/geometria: è un QListWidget normale (stesso objectName e
stesso stile) che in più permette di trascinare le righe in attesa.
Il drag è gestito interamente qui (niente move di default di Qt, che
rimuoverebbe/duplicherebbe righe e rimescolerebbe selezione e dati).
"""
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QDropEvent
from PyQt6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem


class ReorderableFileList(QListWidget):
    """QListWidget con riordino controllato.

    can_move(item) -> bool: True se la riga può essere trascinata e fa da
        riferimento per l'ordine (es. stato 'queued').
    apply_order(items_in_new_order, moved_item) -> bool: chiamata PRIMA di
        spostare la riga; deve aggiornare la coda reale (con mutex) e
        restituire False per annullare lo spostamento.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.can_move: Callable[[QListWidgetItem], bool] = lambda item: False
        self.apply_order: Callable[[List[QListWidgetItem], QListWidgetItem], bool] = (
            lambda items, moved: False
        )
        self._drag_item: Optional[QListWidgetItem] = None
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    # ------------------------------------------------------------------
    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or not self.can_move(item):
            return
        if len(self.selectedItems()) > 1:
            return          # selezione multipla: il riordino per trascinamento vale solo per una riga alla volta
        index = self.indexFromItem(item)
        mime: Optional[QMimeData] = self.model().mimeData([index])
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = self.viewport().grab(self.visualRect(index))
        if not pix.isNull():
            drag.setPixmap(pix)
            drag.setHotSpot(pix.rect().center())
        # Il risultato di exec() è ignorato di proposito: la riga viene
        # spostata da dropEvent, mai rimossa da Qt.
        # La riga trascinata va memorizzata: durante exec() currentItem()
        # può cambiare (file avviato, scansione cartella, ecc.).
        self._drag_item = item
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drag_item = None

    def dragMoveEvent(self, event):
        if event.source() is not self:
            return  # trascinamenti esterni: gestiti dalla MainWindow, niente autoscroll
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.source() is not self:
            super().dragLeaveEvent(QDragLeaveEvent())
            event.ignore()
            return
        try:
            self._handle_drop(event)
        finally:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            # Ferma autoscroll e ripristina lo stato della vista
            # (quello che farebbe il dropEvent di base).
            super().dragLeaveEvent(QDragLeaveEvent())

    # ------------------------------------------------------------------
    def _drop_row(self, pos) -> int:
        """Riga (nello stato attuale) davanti alla quale si rilascia."""
        target = self.itemAt(pos)
        if target is None:
            return self.count()
        row = self.row(target)
        rect = self.visualItemRect(target)
        return row + 1 if pos.y() > rect.center().y() else row

    def _handle_drop(self, event: QDropEvent):
        moved = self._drag_item
        if moved is None or self.row(moved) < 0 or not self.can_move(moved):
            return
        old_row = self.row(moved)
        drop_row = self._drop_row(event.position().toPoint())

        movable_before = [
            self.item(r) for r in range(self.count())
            if self.item(r) is not moved and self.can_move(self.item(r))
        ]
        # posizione tra i soli elementi spostabili
        k = sum(1 for it in movable_before if self.row(it) < drop_row)
        new_order = movable_before[:k] + [moved] + movable_before[k:]
        current_order = [
            self.item(r) for r in range(self.count()) if self.can_move(self.item(r))
        ]
        if new_order == current_order:
            return
        if not self.apply_order(new_order, moved):
            return

        # Sposta fisicamente la riga senza emettere segnali (nessun reload
        # locandina) e ripristina la selezione corrente.
        previous_current = self.currentItem()
        self.blockSignals(True)
        try:
            self.takeItem(old_row)
            if k < len(movable_before):
                new_row = self.row(movable_before[k])
            elif movable_before:
                new_row = self.row(movable_before[-1]) + 1
            else:
                new_row = old_row
            self.insertItem(new_row, moved)
            if previous_current is not None:
                self.setCurrentItem(previous_current)
        finally:
            self.blockSignals(False)
        self.viewport().update()
