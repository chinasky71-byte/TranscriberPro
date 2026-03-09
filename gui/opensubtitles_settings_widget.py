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
        status_group = QGroupBox("📤 OpenSubtitles Upload")
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
        creds_group = QGroupBox("🔑 Credenziali")
        creds_form = QFormLayout()
        creds_form.setSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username OpenSubtitles")
        creds_form.addRow("Username:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        creds_form.addRow("Password:", self.password_input)

        self.apikey_input = QLineEdit()
        self.apikey_input.setPlaceholderText("REST API Key (da opensubtitles.com/consumers)")
        self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
        creds_form.addRow("API Key:", self.apikey_input)

        self.save_creds_btn = QPushButton("💾 Salva Credenziali")
        self.save_creds_btn.clicked.connect(self.save_credentials)
        creds_form.addRow("", self.save_creds_btn)

        creds_group.setLayout(creds_form)
        layout.addWidget(creds_group)

        # ========================================
        # GROUP: Controls
        # ========================================
        controls_group = QGroupBox("⚙️ Impostazioni")
        controls_layout = QVBoxLayout()
        
        # Checkbox: Auto-upload
        self.auto_upload_checkbox = QCheckBox("Upload automatico al termine elaborazione")
        self.auto_upload_checkbox.setToolTip(
            "Esegui automaticamente l'upload dopo ogni trascrizione/traduzione.\n"
            "Se disabilitato, upload solo su richiesta manuale."
        )
        self.auto_upload_checkbox.toggled.connect(self.on_auto_upload_toggled)
        controls_layout.addWidget(self.auto_upload_checkbox)
        
        # Checkbox: Check duplicates
        self.check_duplicates_checkbox = QCheckBox("Verifica duplicati prima dell'upload")
        self.check_duplicates_checkbox.setToolTip(
            "Controlla se il sottotitolo esiste già nel database\n"
            "prima di procedere con l'upload (raccomandato)."
        )
        self.check_duplicates_checkbox.setChecked(True)
        controls_layout.addWidget(self.check_duplicates_checkbox)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # ========================================
        # Buttons
        # ========================================
        buttons_layout = QHBoxLayout()
        
        # Test connection button
        self.test_btn = QPushButton("🔍 Test Connessione")
        self.test_btn.setToolTip("Verifica autenticazione con OpenSubtitles")
        self.test_btn.clicked.connect(self.test_connection)
        buttons_layout.addWidget(self.test_btn)
        
        # Configure button
        self.config_btn = QPushButton("⚙️ Configura Credenziali")
        self.config_btn.setToolTip("Apri documentazione per configurare credenziali")
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
            
            self.status_label.setText(
                "✅ Sistema configurato e pronto per l'upload"
            )
            self.credentials_label.setText(
                f"👤 Account: {username}"
            )
            
            # Abilita controlli
            self.test_btn.setEnabled(True)
            
        else:
            self.status_label.setText(
                "⚠️ Credenziali non configurate\n"
                "L'upload su OpenSubtitles non è disponibile."
            )
            self.credentials_label.setText(
                "💡 Clicca 'Configura Credenziali' per iniziare"
            )
            
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
            QMessageBox.warning(self, "Campi mancanti",
                                "Username e Password sono obbligatori.")
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

        QMessageBox.information(self, "Credenziali Salvate",
                                "✅ Credenziali salvate correttamente.")

    def test_connection(self):
        """Test connessione e autenticazione"""
        creds = self.app_config.get_opensubtitles_credentials()
        if not creds.get('username') or not creds.get('password'):
            QMessageBox.warning(
                self,
                "Credenziali Mancanti",
                "Le credenziali OpenSubtitles non sono configurate.\n\n"
                "Inserisci username, password e API key, poi clicca Salva."
            )
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
            self.test_btn.setText("⏳ Test in corso...")
            
            if uploader.authenticate():
                uploader.logout()
                
                QMessageBox.information(
                    self,
                    "Test Riuscito",
                    "✅ Connessione e autenticazione riuscite!\n\n"
                    "Il tuo account OpenSubtitles è valido e funzionante.\n"
                    "Puoi procedere con l'upload di sottotitoli."
                )
            else:
                QMessageBox.critical(
                    self,
                    "Test Fallito",
                    "❌ Autenticazione fallita.\n\n"
                    "Possibili cause:\n"
                    "• Username o password errati\n"
                    "• Account non attivato (verifica email)\n"
                    "• Problemi di rete\n\n"
                    "Verifica le credenziali su:\n"
                    "https://www.opensubtitles.org"
                )
        
        except Exception as e:
            logger.error(f"Errore test connessione: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Errore",
                f"❌ Errore durante il test:\n\n{str(e)}\n\n"
                "Verifica la connessione internet e riprova."
            )
        
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("🔍 Test Connessione")
    
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
        msg.setWindowTitle("Guida Configurazione")
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
