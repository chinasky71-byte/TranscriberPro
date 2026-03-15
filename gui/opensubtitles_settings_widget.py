"""
OpenSubtitles Settings Widget - GUI Controls
File: gui/opensubtitles_settings_widget.py

FUNZIONALITÀ:
- Visualizza stato configurazione OpenSubtitles
- Toggle upload enabled/disabled
- Toggle auto-upload
- Test connessione
- Link a documentazione
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QGroupBox, QMessageBox,
    QLineEdit, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import logging

from utils.opensubtitles_config import get_opensubtitles_config
from utils.subtitle_uploader_interface import UploaderFactory
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
        
        self.os_config = get_opensubtitles_config()
        self.app_config = get_config()
        
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
        # GROUP: Credenziali
        # ========================================
        creds_group = QGroupBox(tr('os_credentials_group'))
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
        
        # Checkbox: Auto-upload
        self.auto_upload_checkbox = QCheckBox(tr('os_auto_upload'))
        self.auto_upload_checkbox.setToolTip(tr('os_auto_upload_tip'))
        self.auto_upload_checkbox.toggled.connect(self.on_auto_upload_toggled)
        controls_layout.addWidget(self.auto_upload_checkbox)
        
        # Checkbox: Check duplicates
        self.check_duplicates_checkbox = QCheckBox(tr('os_check_duplicates'))
        self.check_duplicates_checkbox.setToolTip(tr('os_check_dup_tip'))
        self.check_duplicates_checkbox.setChecked(True)
        controls_layout.addWidget(self.check_duplicates_checkbox)
        
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
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                color: #ffffff;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            
            QLabel#statusLabel {
                color: #ffffff;
                font-size: 10pt;
                padding: 5px;
            }
            
            QLabel#credentialsLabel {
                color: #cccccc;
                font-size: 9pt;
                font-style: italic;
                padding: 5px;
            }
            
            QCheckBox {
                color: #ffffff;
                font-size: 9pt;
                spacing: 8px;
                padding: 5px;
            }
            
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                background-color: rgba(45, 45, 45, 200);
            }
            
            QCheckBox::indicator:checked {
                background-color: rgba(0, 120, 212, 200);
                border-color: rgba(0, 120, 212, 255);
            }
            
            QCheckBox::indicator:disabled {
                background-color: rgba(60, 60, 60, 100);
                border-color: rgba(255, 255, 255, 0.1);
            }
            
            QPushButton {
                background-color: rgba(0, 120, 212, 180);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 9pt;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: rgba(0, 120, 212, 230);
            }
            
            QPushButton:pressed {
                background-color: rgba(0, 100, 180, 200);
            }
            
            QPushButton:disabled {
                background-color: rgba(60, 60, 60, 150);
                color: rgba(255, 255, 255, 100);
            }
        """)
    
    def update_status(self):
        """Aggiorna visualizzazione stato"""
        # Verifica credenziali
        credentials_ok = self.os_config.is_configured()
        
        if credentials_ok:
            credentials = self.os_config.get_credentials()
            username = credentials.get('username', 'N/A')
            
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
            self.auto_upload_checkbox.setEnabled(False)
            self.test_btn.setEnabled(False)
        
        # Popola campi credenziali dai valori salvati nel config
        saved = self.app_config.get_opensubtitles_credentials() or {}
        self.username_input.setText(saved.get('username') or '')
        self.password_input.setText(saved.get('password') or '')
        self.apikey_input.setText(saved.get('api_key') or '')

        # Carica stato corrente
        if credentials_ok:
            upload_enabled = self.app_config.get('opensubtitles_upload_enabled', True)
            auto_upload    = self.app_config.get('opensubtitles_auto_upload', True)

            self.auto_upload_checkbox.setChecked(auto_upload)
            self.auto_upload_checkbox.setEnabled(upload_enabled)
    
    def on_auto_upload_toggled(self, checked: bool):
        """Handler toggle auto-upload"""
        self.app_config.set('opensubtitles_auto_upload', checked)
        
        logger.info(f"Auto-upload: {'Abilitato' if checked else 'Disabilitato'}")
        
        self.settings_changed.emit()
    
    def save_credentials(self):
        """Salva username, password e API key nel config principale."""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        api_key  = self.apikey_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, tr('os_missing_fields_title'), tr('os_missing_fields_msg'))
            return

        self.app_config.set_opensubtitles_credentials(
            username=username,
            password=password,
            api_key=api_key
        )

        # Aggiorna anche os_config in memoria così il check is_configured() passa subito
        self.os_config.set_credentials(username, password)

        self.update_status()
        self.settings_changed.emit()

        QMessageBox.information(self, tr('os_creds_saved_title'), tr('os_creds_saved_msg'))

    def test_connection(self):
        """Test connessione e autenticazione"""
        creds = self.app_config.get_opensubtitles_credentials()
        if not creds.get('username') or not creds.get('password'):
            QMessageBox.warning(self, tr('os_missing_creds_title'), tr('os_missing_creds_msg'))
            return

        try:
            import utils.opensubtitles_rest_uploader
            import utils.opensubtitles_xmlrpc_uploader

            implementation = self.app_config.get(
                'opensubtitles_preferred_implementation', 'rest'
            )
            uploader = UploaderFactory.create_uploader(
                implementation,
                **creds
            )
            
            # Test autenticazione
            self.test_btn.setEnabled(False)
            self.test_btn.setText(tr('os_testing'))
            
            if uploader.authenticate():
                uploader.logout()
                
                QMessageBox.information(self, tr('os_test_ok_title'), tr('os_test_ok_msg'))
            else:
                QMessageBox.critical(self, tr('os_test_fail_title'), tr('os_test_fail_msg'))
        
        except Exception as e:
            logger.error(f"Errore test connessione: {e}", exc_info=True)
            QMessageBox.critical(self, tr('os_error_title'), tr('os_error_msg').format(error=str(e)))
        
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText(tr('os_test_conn'))
    
    def open_config_help(self):
        """Apri guida configurazione"""
        help_text = """
        <h3>📖 Configurazione Credenziali OpenSubtitles</h3>
        
        <p><b>Passo 1: Crea Account</b></p>
        <p>Se non hai un account, registrati su:<br>
        <a href="https://www.opensubtitles.org/en/newuser">
        https://www.opensubtitles.org/en/newuser</a></p>
        
        <p><b>Passo 2: Crea File Credenziali</b></p>
        <p>Crea uno di questi file:</p>
        <ul>
        <li><code>~/.transcriberpro/opensubtitles_credentials.json</code></li>
        <li><code>~/.transcriberpro/opensubtitles_credentials.txt</code></li>
        </ul>
        
        <p><b>Formato JSON (Consigliato):</b></p>
        <pre>{
    "username": "tuo_username",
    "password": "tua_password",
    "auto_upload": false
}</pre>
        
        <p><b>Formato TXT (Semplice):</b></p>
        <pre>tuo_username
tua_password</pre>
        
        <p><b>Passo 3: Riavvia</b></p>
        <p>Chiudi e riapri l'applicazione per caricare le credenziali.</p>
        
        <p><b>⚠️ Sicurezza:</b></p>
        <p>• NON committare questo file nel repository<br>
        • Usa una password unica per OpenSubtitles<br>
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
