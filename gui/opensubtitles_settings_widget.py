"""
OpenSubtitles Settings Widget - GUI Controls
File: gui/opensubtitles_settings_widget.py

FUNZIONALITÀ:
- Visualizza stato configurazione OpenSubtitles
- Toggle upload enabled/disabled
- Scelta metodo API (XML-RPC/REST) e le RISPETTIVE credenziali —
  opensubtitles.org (XML-RPC) e opensubtitles.com (REST) sono due account
  separati con credenziali proprie, anche a parità di username.
- Test connessione
- Link a documentazione
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QGroupBox, QMessageBox,
    QLineEdit, QFormLayout, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import logging

from core.services.opensubtitles_settings_service import OpenSubtitlesSettingsService
from gui.styles import load_qss
from utils.config import get_config
from utils.translations import tr

logger = logging.getLogger(__name__)


class OpenSubtitlesSettingsWidget(QWidget):
    """
    Widget per gestire impostazioni OpenSubtitles Upload

    SIGNALS:
    - settings_changed: Emesso quando configurazione cambia
    """

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.app_config = get_config()
        self._svc = OpenSubtitlesSettingsService(self.app_config)

        self.init_ui()
        self.update_status()

    def init_ui(self):
        """Inizializza interfaccia"""
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # ========================================
        # GROUP: Status
        # ========================================
        status_group = QGroupBox(tr('os_upload_group'))
        status_layout = QVBoxLayout()

        # Status label
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusLabel")
        status_layout.addWidget(self.status_label)

        # Info credentials
        self.credentials_label = QLabel()
        self.credentials_label.setObjectName("credentialsLabel")
        status_layout.addWidget(self.credentials_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # ========================================
        # GROUP: Credenziali .org (XML-RPC) — quelle usate per l'upload
        # ========================================
        xmlrpc_creds_group = QGroupBox(tr('os_credentials_group_org'))
        xmlrpc_creds_form = QFormLayout()
        xmlrpc_creds_form.setSpacing(8)

        self.xmlrpc_username_input = QLineEdit()
        self.xmlrpc_username_input.setPlaceholderText(tr('os_username_ph'))
        xmlrpc_creds_form.addRow("Username:", self.xmlrpc_username_input)

        self.xmlrpc_password_input = QLineEdit()
        self.xmlrpc_password_input.setPlaceholderText(tr('os_password_ph'))
        self.xmlrpc_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        xmlrpc_creds_form.addRow("Password:", self.xmlrpc_password_input)

        self.save_xmlrpc_creds_btn = QPushButton(tr('os_save_creds'))
        self.save_xmlrpc_creds_btn.clicked.connect(self.save_xmlrpc_credentials)
        xmlrpc_creds_form.addRow("", self.save_xmlrpc_creds_btn)

        xmlrpc_creds_group.setLayout(xmlrpc_creds_form)
        layout.addWidget(xmlrpc_creds_group)

        # ========================================
        # GROUP: Credenziali .com (REST + traduttore "OpenSubtitles AI")
        # ========================================
        creds_group = QGroupBox(tr('os_credentials_group_com'))
        creds_form = QFormLayout()
        creds_form.setSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText(tr('os_username_ph'))
        creds_form.addRow("Username:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText(tr('os_password_ph'))
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        creds_form.addRow("Password:", self.password_input)

        self.apikey_input = QLineEdit()
        self.apikey_input.setPlaceholderText(tr('os_apikey_ph'))
        self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
        creds_form.addRow("API Key:", self.apikey_input)

        self.save_creds_btn = QPushButton(tr('os_save_creds'))
        self.save_creds_btn.clicked.connect(self.save_credentials)
        creds_form.addRow("", self.save_creds_btn)

        creds_group.setLayout(creds_form)
        layout.addWidget(creds_group)

        # ========================================
        # GROUP: Controls
        # ========================================
        controls_group = QGroupBox(tr('os_settings_group'))
        controls_layout = QVBoxLayout()

        # Checkbox: Upload abilitato (master toggle)
        self.upload_enabled_checkbox = QCheckBox(tr('upload_opensubtitles'))
        self.upload_enabled_checkbox.toggled.connect(self.on_upload_enabled_toggled)
        controls_layout.addWidget(self.upload_enabled_checkbox)

        # Combo: API method
        method_layout = QHBoxLayout()
        method_label = QLabel(tr('os_api_method'))
        method_label.setToolTip(tr('os_api_method_tip'))
        self.implementation_combo = QComboBox()
        self.implementation_combo.addItem('XML-RPC (opensubtitles.org)', 'xmlrpc')
        self.implementation_combo.setItemData(
            0, tr('os_xmlrpc_tooltip'), Qt.ItemDataRole.ToolTipRole
        )
        self.implementation_combo.addItem('REST (opensubtitles.com)', 'rest')
        self.implementation_combo.setItemData(
            1, tr('os_rest_tooltip'), Qt.ItemDataRole.ToolTipRole
        )
        self.implementation_combo.setToolTip(tr('os_api_method_tip'))
        self.implementation_combo.currentIndexChanged.connect(self.on_implementation_changed)
        method_layout.addWidget(method_label)
        method_layout.addWidget(self.implementation_combo)
        method_layout.addStretch()
        controls_layout.addLayout(method_layout)

        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)

        # ========================================
        # Buttons
        # ========================================
        buttons_layout = QHBoxLayout()

        # Test connection button
        self.test_btn = QPushButton(tr('os_test_conn'))
        self.test_btn.setToolTip(tr('os_test_conn_tip'))
        self.test_btn.clicked.connect(self.test_connection)
        buttons_layout.addWidget(self.test_btn)

        # Configure button
        self.config_btn = QPushButton(tr('os_configure'))
        self.config_btn.setToolTip(tr('os_configure_tip'))
        self.config_btn.clicked.connect(self.open_config_help)
        buttons_layout.addWidget(self.config_btn)

        layout.addLayout(buttons_layout)

        # Spacer
        layout.addStretch()

        self.setLayout(layout)

        # Apply styles
        self.apply_styles()

    def apply_styles(self):
        """Applica stili al widget"""
        self.setStyleSheet(load_qss('opensubtitles_settings'))

    def update_status(self, refresh_inputs: bool = True):
        """
        Aggiorna visualizzazione stato.

        refresh_inputs=False quando la chiamata parte da un cambio interno
        (es. cambio metodo API) che non deve ripopolare i campi credenziali:
        farlo sempre cancellava testo che l'utente stava ancora digitando e
        non aveva ancora salvato.
        """
        # Verifica credenziali — stessa fonte e stessa logica di
        # is_opensubtitles_configured(), l'unica realmente letta dalla
        # pipeline in produzione (core/pipeline.py:_upload_opensubtitles).
        # È implementation-aware: guarda il set di credenziali (.org o .com)
        # rilevante per il metodo API attualmente selezionato.
        st = self._svc.status()
        credentials_ok, impl, username = st.configured, st.implementation, st.username

        if credentials_ok:
            self.status_label.setText(tr('os_configured'))
            self.credentials_label.setText(tr('os_account').format(username=username))

            # Abilita controlli
            self.test_btn.setEnabled(True)

        else:
            self.status_label.setText(
                tr('os_not_configured') + '\n' + tr('os_not_available')
            )
            self.credentials_label.setText(tr('os_configure_hint'))

            # Disabilita controlli
            self.upload_enabled_checkbox.setEnabled(False)
            self.test_btn.setEnabled(False)

        if refresh_inputs:
            # Popola entrambi i gruppi di credenziali dai valori salvati —
            # indipendentemente da quale sia il metodo API selezionato ora,
            # sono due account distinti e l'utente deve poter gestire
            # entrambi.
            saved = self._svc.credentials_com()
            self.username_input.setText(saved.get('username') or '')
            self.password_input.setText(saved.get('password') or '')
            self.apikey_input.setText(saved.get('api_key') or '')

            saved_xmlrpc = self._svc.credentials_org()
            self.xmlrpc_username_input.setText(saved_xmlrpc.get('username') or '')
            self.xmlrpc_password_input.setText(saved_xmlrpc.get('password') or '')

        # Carica stato corrente
        if credentials_ok:
            upload_enabled = self._svc.upload_enabled()

            self.upload_enabled_checkbox.blockSignals(True)
            self.upload_enabled_checkbox.setChecked(upload_enabled)
            self.upload_enabled_checkbox.setEnabled(True)
            self.upload_enabled_checkbox.blockSignals(False)

        # Carica metodo API selezionato
        idx = self.implementation_combo.findData(impl)
        self.implementation_combo.blockSignals(True)
        if idx >= 0:
            self.implementation_combo.setCurrentIndex(idx)
        else:
            # Valore in config non riconosciuto dal combo: non lasciare che la
            # GUI mostri silenziosamente 'xmlrpc' mentendo sullo stato reale.
            logger.warning(f"Implementazione OpenSubtitles sconosciuta in config: {impl!r}. Normalizzo a 'xmlrpc'.")
            self._svc.normalize_implementation()
            self.implementation_combo.setCurrentIndex(self.implementation_combo.findData('xmlrpc'))
        self.implementation_combo.blockSignals(False)

    def on_implementation_changed(self, index: int):
        """Handler cambio metodo API"""
        impl = self.implementation_combo.itemData(index)
        self._svc.set_implementation(impl)
        logger.info(f"Metodo API OpenSubtitles: {impl}")
        # Il metodo scelto cambia anche quale set di credenziali (.org o
        # .com) è rilevante per is_opensubtitles_configured(): riallinea
        # subito lo stato mostrato, ma senza toccare i campi credenziali —
        # l'utente potrebbe averli appena digitati e non ancora salvati.
        self.update_status(refresh_inputs=False)
        self.settings_changed.emit()

    def refresh_from_config(self):
        """Allinea la casella dell'upload al config (la scheda 'Opzioni job' delle Impostazioni puo' averla cambiata)."""
        cb = self.upload_enabled_checkbox
        cb.blockSignals(True)
        cb.setChecked(bool(self._svc.upload_enabled()))
        cb.blockSignals(False)

    def on_upload_enabled_toggled(self, checked: bool):
        """Handler toggle upload abilitato (master)"""
        self._svc.set_upload_enabled(checked)
        self.settings_changed.emit()

    def save_credentials(self):
        """Salva username, password e API key .com (REST) nel config principale."""
        if not self._svc.save_com(self.username_input.text(), self.password_input.text(), self.apikey_input.text()):
            QMessageBox.warning(self, tr('os_missing_fields_title'), tr('os_missing_fields_msg'))
            return

        self.update_status()
        self.settings_changed.emit()

        QMessageBox.information(self, tr('os_creds_saved_title'), tr('os_creds_saved_msg'))

    def save_xmlrpc_credentials(self):
        """Salva username e password .org (XML-RPC) nel config principale."""
        if not self._svc.save_org(self.xmlrpc_username_input.text(), self.xmlrpc_password_input.text()):
            QMessageBox.warning(self, tr('os_missing_fields_title'), tr('os_missing_fields_msg'))
            return

        self.update_status()
        self.settings_changed.emit()

        QMessageBox.information(self, tr('os_creds_saved_title'), tr('os_creds_saved_msg'))

    def test_connection(self):
        """Test connessione e autenticazione per il metodo API attualmente selezionato."""
        try:
            def _busy():
                self.test_btn.setEnabled(False)
                self.test_btn.setText(tr('os_testing'))

            res = self._svc.test_connection(on_start=_busy)
            if res.kind == 'missing_creds':
                QMessageBox.warning(self, tr('os_missing_creds_title'), tr('os_missing_creds_msg'))
            elif res.kind == 'ok':
                QMessageBox.information(self, tr('os_test_ok_title'), tr('os_test_ok_msg'))
            elif res.kind == 'fail':
                # Per XML-RPC il motivo più comune è aver messo qui le
                # credenziali .com invece di quelle .org (account separati).
                msg = tr('os_test_fail_msg')
                if res.implementation == 'xmlrpc':
                    msg += '\n\n' + tr('os_xmlrpc_org_com_hint')
                QMessageBox.critical(self, tr('os_test_fail_title'), msg)
            else:
                QMessageBox.critical(self, tr('os_error_title'), tr('os_error_msg').format(error=res.error))
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText(tr('os_test_conn'))

    def open_config_help(self):
        """Apri guida configurazione"""
        help_text = """
        <h3>📖 Configurazione Credenziali OpenSubtitles</h3>

        <p><b>⚠️ Due account separati, non uno solo:</b></p>
        <p>opensubtitles.<b>org</b> (XML-RPC) e opensubtitles.<b>com</b> (REST)
        sono database utenti indipendenti: anche con lo stesso username, le
        password possono essere diverse. Vanno configurate entrambe qui sotto
        SOLO se usi entrambi i metodi.</p>

        <p><b>Passo 1: XML-RPC (opensubtitles.org) — consigliato per l'upload</b></p>
        <p>Se non hai un account .org, registrati su:<br>
        <a href="https://www.opensubtitles.org/en/newuser">
        https://www.opensubtitles.org/en/newuser</a></p>
        <p>Inserisci le sue credenziali nel riquadro "Credenziali .org" e premi "Salva".</p>

        <p><b>Passo 2 (opzionale): REST (opensubtitles.com)</b></p>
        <p>Usata dal traduttore "OpenSubtitles AI" e, se in futuro
        OpenSubtitles abiliterà l'upload sulla tua API key, anche per
        l'upload. Richiede una API Key gratuita da
        <a href="https://www.opensubtitles.com/en/consumers">
        opensubtitles.com/consumers</a>. Oggi l'upload REST risponde
        "uploads_not_enabled" per le API key normali: va richiesto a
        OpenSubtitles (pagina contatti del sito) prima di poterlo usare.</p>

        <p><b>⚠️ Sicurezza:</b></p>
        <p>• Usa password uniche per questi account<br>
        • Le credenziali rimangono locali al tuo sistema</p>
        """

        msg = QMessageBox(self)
        msg.setWindowTitle(tr('os_guide_title'))
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)

        # Rendi la dialog più grande
        msg.setStyleSheet("""
            QMessageBox {
                min-width: 600px;
            }
            QLabel {
                min-width: 550px;
            }
        """)

        msg.exec()
