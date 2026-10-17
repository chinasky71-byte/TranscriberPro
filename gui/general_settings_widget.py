"""
General Settings Widget
File: gui/general_settings_widget.py

Widget per le impostazioni generali dell'applicazione.
Contiene: selezione lingua interfaccia, configurazione Library Scanner.
"""
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QGroupBox,
    QFormLayout, QLabel, QLineEdit, QPushButton, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal

from gui.design_tokens import T
from gui.theme import set_flat
from utils.config import get_config
from utils.translations import tr

logger = logging.getLogger(__name__)


class _PingWorker(QThread):
    """Testa la connessione al Library Scanner in background."""
    result = pyqtSignal(bool, str)  # (ok, messaggio)

    def __init__(self, url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._url = url.rstrip('/')
        self._api_key = api_key

    def run(self):
        try:
            import requests
            r = requests.get(
                f"{self._url}/api/stats",
                headers={'X-API-Key': self._api_key},
                timeout=4,
            )
            r.raise_for_status()
            self.result.emit(True, f"Connesso — HTTP {r.status_code}")
        except Exception as e:
            self.result.emit(False, str(e))


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
        note.setStyleSheet(f"color: {T.legacy_grey_888}; font-size: 8pt; padding: 4px 0;")
        layout.addWidget(note)

        # ── Library Scanner ───────────────────────────────────────────
        ls_group = QGroupBox("Library Scanner")
        ls_form = QFormLayout()
        ls_form.setSpacing(8)

        self.ls_url_edit = QLineEdit()
        self.ls_url_edit.setPlaceholderText("http://192.168.1.x:6680")
        self.ls_url_edit.editingFinished.connect(self._on_ls_url_changed)
        ls_form.addRow("URL server:", self.ls_url_edit)

        self.ls_key_edit = QLineEdit()
        self.ls_key_edit.setPlaceholderText("API key")
        self.ls_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ls_key_edit.editingFinished.connect(self._on_ls_key_changed)

        key_row = set_flat(QWidget())
        key_lay = QHBoxLayout(key_row)
        key_lay.setContentsMargins(0, 0, 0, 0)
        key_lay.setSpacing(6)
        key_lay.addWidget(self.ls_key_edit)
        self._show_key_btn = QPushButton("Mostra")
        self._show_key_btn.setFixedWidth(80)
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.toggled.connect(self._toggle_key_visibility)
        key_lay.addWidget(self._show_key_btn)
        ls_form.addRow("API key:", key_row)

        self._ping_btn = QPushButton("Testa connessione")
        self._ping_status = QLabel("")
        self._ping_status.setWordWrap(True)
        ping_row = set_flat(QWidget())
        ping_lay = QHBoxLayout(ping_row)
        ping_lay.setContentsMargins(0, 0, 0, 0)
        ping_lay.setSpacing(8)
        ping_lay.addWidget(self._ping_btn)
        ping_lay.addWidget(self._ping_status, 1)
        self._ping_btn.clicked.connect(self._test_connection)
        ls_form.addRow("", ping_row)

        ls_group.setLayout(ls_form)
        layout.addWidget(ls_group)

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

        self.ls_url_edit.setText(self.config.get('library_scanner_url', ''))
        self.ls_key_edit.setText(self.config.get('library_scanner_api_key', ''))

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

    def _on_ls_url_changed(self):
        val = self.ls_url_edit.text().strip()
        self.config.set('library_scanner_url', val)
        logger.info(f"Library Scanner URL aggiornato: {val}")

    def _on_ls_key_changed(self):
        val = self.ls_key_edit.text().strip()
        self.config.set('library_scanner_api_key', val)
        logger.info("Library Scanner API key aggiornata")

    def _toggle_key_visibility(self, checked: bool):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.ls_key_edit.setEchoMode(mode)
        self._show_key_btn.setText("Nascondi" if checked else "Mostra")

    def _set_ping_color(self, color: str):
        self._ping_status.setStyleSheet(f"color: {color};")

    def _test_connection(self):
        url = self.ls_url_edit.text().strip()
        key = self.ls_key_edit.text().strip()
        if not url:
            self._set_ping_color(T.legacy_red_soft)
            self._ping_status.setText("Inserisci un URL valido.")
            return
        self._ping_btn.setEnabled(False)
        self._set_ping_color(T.legacy_grey_888)
        self._ping_status.setText("Test in corso…")
        self._ping_worker = _PingWorker(url, key, self)
        self._ping_worker.result.connect(self._on_ping_result)
        self._ping_worker.start()

    def _on_ping_result(self, ok: bool, msg: str):
        self._ping_btn.setEnabled(True)
        if ok:
            self._set_ping_color(T.accent)
            self._ping_status.setText(f"✓ {msg}")
        else:
            self._set_ping_color(T.legacy_red_soft)
            self._ping_status.setText(f"✗ {msg}")
