"""
Collapsible Card widget
File: gui/collapsible_card.py

QFrame con header (titolo + summary + chevron) sempre visibile e body
collassabile via QPropertyAnimation su maximumHeight.

Introdotto in Fase 3 del GUI revamp per ridurre densita' del pannello sinistro
(JobOptionsCard, LibraryScannerWidget, ecc.).
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QSize
from gui.icons import svg_icon


class CollapsibleCard(QFrame):
    """Card collassabile con header (titolo + summary + chevron) e body animato.

    Uso:
        card = CollapsibleCard("Opzioni job")
        card.setBody(my_widget)
        card.setSummary("ITA · OS · ⚧")
        card.setExpanded(False)
        card.toggled.connect(lambda is_open: ...)
    """

    toggled = pyqtSignal(bool)  # True = aperta, False = chiusa

    ANIMATION_MS = 200

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("collapsibleCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._expanded = True
        self._body_widget: QWidget | None = None

        self._build_ui(title)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, title: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Header ----------------------------------------------------
        self._header = QFrame()
        self._header.setObjectName("collapsibleHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = self._on_header_clicked  # type: ignore[assignment]

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 8, 10, 8)
        header_layout.setSpacing(8)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("collapsibleTitle")

        self._summary_label = QLabel("")
        self._summary_label.setObjectName("collapsibleSummary")

        self._chevron = QToolButton()
        self._chevron.setObjectName("collapsibleChevron")
        self._chevron.setText('')
        self._chevron.setIcon(svg_icon('chevDown', 16, '#6a6f7a'))
        self._chevron.setIconSize(QSize(16, 16))
        self._chevron.setFixedSize(20, 20)
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.clicked.connect(self.toggle)

        header_layout.addWidget(self._title_label)
        header_layout.addStretch()
        header_layout.addWidget(self._summary_label)
        header_layout.addWidget(self._chevron)

        outer.addWidget(self._header)

        # --- Body container --------------------------------------------
        self._body_container = QFrame()
        self._body_container.setObjectName("collapsibleBody")
        self._body_layout = QVBoxLayout(self._body_container)
        self._body_layout.setContentsMargins(12, 4, 12, 12)
        self._body_layout.setSpacing(8)

        outer.addWidget(self._body_container)

        # Animazione su maximumHeight
        self._animation = QPropertyAnimation(self._body_container, b"maximumHeight")
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def setBody(self, widget: QWidget):
        """Imposta il widget contenuto. Sostituisce il body precedente."""
        if self._body_widget is not None:
            self._body_layout.removeWidget(self._body_widget)
            self._body_widget.deleteLater()
        self._body_widget = widget
        self._body_layout.addWidget(widget)

    def setSummary(self, text: str):
        """Aggiorna il testo summary mostrato a destra del titolo."""
        self._summary_label.setText(text)

    def addHeaderWidget(self, widget: QWidget):
        """Inserisce un widget nell'header prima del chevron."""
        layout = self._header.layout()
        layout.insertWidget(layout.count() - 1, widget)

    def summary(self) -> str:
        return self._summary_label.text()

    def setTitle(self, title: str):
        self._title_label.setText(title)

    def title(self) -> str:
        return self._title_label.text()

    def isExpanded(self) -> bool:
        return self._expanded

    def setExpanded(self, expanded: bool, animated: bool = True):
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._chevron.setIcon(svg_icon('chevDown' if expanded else 'chevRight', 16, '#6a6f7a'))

        if not animated:
            self._body_container.setMaximumHeight(
                16777215 if expanded else 0
            )
            self._body_container.setVisible(expanded)
            self.toggled.emit(expanded)
            return

        self._animation.stop()
        if expanded:
            self._body_container.setVisible(True)
            target = self._body_container.sizeHint().height()
            self._animation.setStartValue(0)
            self._animation.setEndValue(target)

            def _on_finished():
                self._body_container.setMaximumHeight(16777215)
                try:
                    self._animation.finished.disconnect(_on_finished)
                except TypeError:
                    pass

            self._animation.finished.connect(_on_finished)
        else:
            current = self._body_container.height()
            self._animation.setStartValue(current)
            self._animation.setEndValue(0)

            def _on_finished():
                self._body_container.setVisible(False)
                try:
                    self._animation.finished.disconnect(_on_finished)
                except TypeError:
                    pass

            self._animation.finished.connect(_on_finished)

        self._animation.start()
        self.toggled.emit(expanded)

    def toggle(self):
        self.setExpanded(not self._expanded)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_header_clicked(self, event):
        # Click ovunque sull'header alterna espansione (escluso click direttamente
        # sul chevron che gestisce gia' il proprio signal)
        self.toggle()
