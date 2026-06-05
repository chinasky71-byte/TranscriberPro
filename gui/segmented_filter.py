"""
Segmented Filter Widget
File: gui/segmented_filter.py

Barra di filtro mutex-exclusive con badge count per la file_list.
Filtri: Tutti / Attivi / Coda / Completati.

Introdotto in Fase 3 del GUI revamp.
"""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal


FILTERS = [
    ('all',        'Tutti'),
    ('processing', 'Attivi'),
    ('queued',     'Coda'),
    ('completed',  'Completati'),
]


class SegmentedFilter(QFrame):
    """Barra filtro a 4 pulsanti checkable (mutex-exclusive) con badge count."""

    filter_changed = pyqtSignal(str)  # chiave filtro attivo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('segmentedFilter')
        self._current = 'all'
        self._btns: dict[str, QPushButton] = {}
        self._counts: dict[str, int] = {k: 0 for k, _ in FILTERS}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        for key, label in FILTERS:
            btn = QPushButton(f'{label} (0)')
            btn.setCheckable(True)
            btn.setObjectName('segmentFilterBtn')
            btn.setFixedHeight(24)
            btn.setMinimumWidth(0)  # evita che il resize del testo forzi il resize della finestra
            btn.clicked.connect(lambda _checked, k=key: self._on_click(k))
            self._btns[key] = btn
            layout.addWidget(btn)

        layout.addStretch()
        self._btns['all'].setChecked(True)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def current_filter(self) -> str:
        return self._current

    def set_counts(self, counts: dict[str, int]):
        """Aggiorna i badge su tutti i pulsanti. counts = {'queued': N, ...}"""
        for key, label in FILTERS:
            n = counts.get(key, 0)
            self._counts[key] = n
            btn = self._btns[key]
            btn.setText(f'{label} ({n})')

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_click(self, key: str):
        for k, btn in self._btns.items():
            btn.setChecked(k == key)
        self._current = key
        self.filter_changed.emit(key)
