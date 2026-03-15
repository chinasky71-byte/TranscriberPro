"""
General Settings Widget
File: gui/general_settings_widget.py

Widget per le impostazioni generali dell'applicazione.
Attualmente contiene: selezione lingua interfaccia.
Pensato per accogliere future impostazioni generali.
"""
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QGroupBox,
    QFormLayout, QLabel, QMessageBox
)

from utils.config import get_config
from utils.translations import tr

logger = logging.getLogger(__name__)


class GeneralSettingsWidget(QWidget):
    """
    Widget per le impostazioni generali.
    Da embeddare in un QDialog aperto da main_window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self._init_ui()
        self._load_values()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Lingua interfaccia ────────────────────────────────────────
        lang_group = QGroupBox(tr('general_settings_lang_group'))
        lang_form = QFormLayout()
        lang_form.setSpacing(8)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem(tr('language_auto'), 'auto')
        self.lang_combo.addItem('Italiano', 'it')
        self.lang_combo.addItem('English', 'en')
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        lang_form.addRow(tr('language_label'), self.lang_combo)
        lang_group.setLayout(lang_form)
        layout.addWidget(lang_group)

        note = QLabel(tr('language_restart_msg'))
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888; font-size: 8pt; padding: 4px 0;")
        layout.addWidget(note)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Logica
    # ------------------------------------------------------------------

    def _load_values(self):
        lang_pref = self.config.get('language', 'auto')
        idx = {'auto': 0, 'it': 1, 'en': 2}.get(lang_pref, 0)
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.blockSignals(False)

    def _on_lang_changed(self, index: int):
        mapping = {0: 'auto', 1: 'it', 2: 'en'}
        chosen = mapping[index]
        self.config.set('language', chosen)
        logger.info(f"Lingua interfaccia cambiata: {chosen}")
        QMessageBox.information(
            self,
            tr('language_restart_title'),
            tr('language_restart_msg'),
        )
