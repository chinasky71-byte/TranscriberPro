"""
Translation Model Selection Dialog
File: gui/translation_model_dialog.py

VERSIONE: v2.1 - CLAUDE API INTEGRATION (Fixed Qt widgets)
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QRadioButton,
                             QLabel, QPushButton, QButtonGroup, QFrame,
                             QProgressBar, QTextEdit, QScrollArea, QWidget,
                             QMessageBox, QLineEdit, QGroupBox, QFileDialog,
                             QCheckBox, QSpinBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon
import shutil
from pathlib import Path

from utils.config import get_config

try:
    from core.translator import BaseTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    BaseTranslator = None
    TRANSLATOR_AVAILABLE = False


class DownloadWorker(QThread):
    """Worker thread per download asincrono modello Aya"""
    
    progress_updated = pyqtSignal(str, int)
    download_completed = pyqtSignal(bool, str)
    
    def run(self):
        try:
            from core.translator import get_translator
            
            self.progress_updated.emit("Avvio caricamento modello Aya-23-8B...", 0)
            
            config = get_config()
            if not config.is_huggingface_token_set():
                self.progress_updated.emit("Token HuggingFace non rilevato. Tentativo anonimo...", 10)
            
            self.progress_updated.emit("Download in corso (può richiedere alcuni minuti)...", 20)
            
            translator = get_translator(model_type='aya')
            
            if translator and isinstance(translator, BaseTranslator):
                self.progress_updated.emit("Modello caricato in memoria.", 100)
                self.download_completed.emit(True, "[OK] Download completato!")
            else:
                self.download_completed.emit(False, "[X] Caricamento fallito")
                
        except ImportError:
            self.download_completed.emit(False, "[X] Impossibile trovare 'get_translator'")
        except Exception as e:
            error_message = str(e)
            if "GatedRepo" in error_message or "401" in error_message:
                error_message = "Errore autenticazione. Token HuggingFace non valido."
            self.download_completed.emit(False, f"[X] Errore: {error_message}")


class TranslationModelDialog(QDialog):
    """Dialog per selezione modello di traduzione"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self.selected_model = self.config.get_translation_model()
        self.download_worker = None
        
        self.setWindowTitle("Translation Models - Select Engine")
        self.setModal(True)
        self.setMinimumWidth(800)
        self.setMinimumHeight(700)
        self.resize(850, 750)
        self.setSizeGripEnabled(True)
        
        if not TRANSLATOR_AVAILABLE:
            self.init_ui_error()
        else:
            self.init_ui()
            self.apply_theme()
    
    def init_ui_error(self):
        """Interfaccia errore se translator non disponibile"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        error_label = QLabel(
            "⚠️ ERRORE CRITICO\n\n"
            "Impossibile importare 'BaseTranslator' da 'core.translator'.\n"
            "Verificare installazione del modulo."
        )
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #d32f2f; font-size: 14px; padding: 20px;")
        
        main_layout.addWidget(error_label)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        main_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.setLayout(main_layout)
    
    def init_ui(self):
        """Interfaccia principale"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # Button group per radio buttons
        self.button_group = QButtonGroup(self)
        
        # NLLB
        nllb_widget, self.nllb_radio = self.create_model_section_nllb()
        scroll_layout.addWidget(nllb_widget)
        self.button_group.addButton(self.nllb_radio)

        # NLLB Fine-Tuned
        nllb_ft_widget, self.nllb_ft_radio = self.create_model_section_nllb_finetuned()
        scroll_layout.addWidget(nllb_ft_widget)
        self.button_group.addButton(self.nllb_ft_radio)

        # Aya
        aya_widget, self.aya_radio = self.create_model_section_aya()
        scroll_layout.addWidget(aya_widget)
        self.button_group.addButton(self.aya_radio)

        # Claude
        claude_widget, self.claude_radio = self.create_model_section_claude()
        scroll_layout.addWidget(claude_widget)
        self.button_group.addButton(self.claude_radio)

        # OpenSubtitles AI
        os_widget, self.os_radio = self.create_model_section_opensubtitles()
        scroll_layout.addWidget(os_widget)
        self.button_group.addButton(self.os_radio)

        # OpenAI GPT
        oai_widget, self.oai_radio = self.create_model_section_openai()
        scroll_layout.addWidget(oai_widget)
        self.button_group.addButton(self.oai_radio)

        # Speaker Diarization
        diarization_widget = self.create_diarization_section()
        scroll_layout.addWidget(diarization_widget)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, stretch=1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        save_btn = QPushButton("Save & Close")
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self.save_selection)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)
        
        self.setLayout(main_layout)
        
        # Set selezione iniziale
        if self.selected_model == 'aya':
            self.aya_radio.setChecked(True)
        elif self.selected_model == 'claude':
            self.claude_radio.setChecked(True)
        elif self.selected_model == 'nllb_finetuned':
            self.nllb_ft_radio.setChecked(True)
        elif self.selected_model == 'opensubtitles':
            self.os_radio.setChecked(True)
        elif self.selected_model == 'openai':
            self.oai_radio.setChecked(True)
        else:
            self.nllb_radio.setChecked(True)
    
    def create_header(self) -> QWidget:
        """Crea header dialog"""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 15)
        
        title = QLabel("Translation Model Selection")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1976d2;")
        
        subtitle = QLabel("Choose the translation engine for subtitle translation")
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        
        return header_widget
    
    def create_model_section_nllb(self):
        """Crea sezione NLLB"""
        radio = QRadioButton()
        radio.setObjectName("nllb")
        
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                background: white;
            }
        """)
        
        layout = QVBoxLayout(container)
        
        title_label = QLabel("NLLB-200")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        layout.addWidget(title_label)
        
        features = (
            "✅ Locale (GPU)\n"
            "✅ 200+ lingue\n"
            "✅ Auto-download (3.3GB)\n"
            "✅ Veloce\n"
            "❌ Qualità media"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)
        
        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)
        
        wrapper = QWidget()
        wrapper.setLayout(main_layout)
        
        return wrapper, radio
    
    def create_model_section_nllb_finetuned(self):
        """Crea sezione NLLB Fine-Tuned (Plex)"""
        radio = QRadioButton()
        radio.setObjectName("nllb_finetuned")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #4caf50;
                border-radius: 8px;
                padding: 15px;
                background: #f1f8f1;
            }
        """)

        layout = QVBoxLayout(container)

        title_label = QLabel("NLLB-200 Fine-Tuned (Plex)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2e7d32;")
        layout.addWidget(title_label)

        features = (
            "✅ Locale (GPU)\n"
            "✅ Fine-tuned sulla tua libreria Plex\n"
            "✅ Stile ottimizzato per sottotitoli\n"
            "✅ Stessa velocità di NLLB base\n"
            "⚠️ Solo EN→IT (dataset di training)"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)

        # Path selector
        path_group = QGroupBox("Cartella modello (merged_model)")
        path_layout = QVBoxLayout()

        path_row = QHBoxLayout()
        self.nllb_ft_path_input = QLineEdit()
        self.nllb_ft_path_input.setPlaceholderText(
            r"C:\...\nllb-subtitles-lora\merged_model"
        )
        current_path = self.config.get_nllb_finetuned_model_path()
        if current_path:
            self.nllb_ft_path_input.setText(current_path)

        browse_btn = QPushButton("Sfoglia...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self.browse_nllb_ft_path)

        path_row.addWidget(self.nllb_ft_path_input)
        path_row.addWidget(browse_btn)
        path_layout.addLayout(path_row)

        save_path_btn = QPushButton("Salva percorso")
        save_path_btn.clicked.connect(self.save_nllb_ft_path)
        path_layout.addWidget(save_path_btn)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # Stato
        self.nllb_ft_status_label = QLabel()
        self.update_nllb_ft_status()
        layout.addWidget(self.nllb_ft_status_label)

        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)

        wrapper = QWidget()
        wrapper.setLayout(main_layout)

        return wrapper, radio

    def browse_nllb_ft_path(self):
        """Apre dialog per selezionare la cartella del modello fine-tuned"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Seleziona cartella merged_model",
            self.nllb_ft_path_input.text() or str(Path.home()),
        )
        if folder:
            self.nllb_ft_path_input.setText(folder)

    def save_nllb_ft_path(self):
        """Salva il path del modello fine-tuned"""
        path = self.nllb_ft_path_input.text().strip()
        if not path:
            QMessageBox.warning(self, "Percorso vuoto", "Inserisci il percorso della cartella merged_model.")
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "Cartella non trovata", f"La cartella non esiste:\n{path}")
            return
        if not (p / 'config.json').exists():
            QMessageBox.warning(
                self, "Cartella non valida",
                "La cartella non sembra contenere un modello HuggingFace valido (config.json non trovato)."
            )
            return

        self.config.set_nllb_finetuned_model_path(path)
        self.update_nllb_ft_status()
        QMessageBox.information(self, "Salvato", "Percorso modello fine-tuned salvato!")

    def update_nllb_ft_status(self):
        """Aggiorna indicatore stato modello fine-tuned"""
        if self.config.is_nllb_finetuned_configured():
            self.nllb_ft_status_label.setText("✅ Modello configurato e pronto")
            self.nllb_ft_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.nllb_ft_status_label.setText("⚠️ Percorso non configurato")
            self.nllb_ft_status_label.setStyleSheet("color: orange;")

    def create_model_section_aya(self):
        """Crea sezione Aya con download"""
        radio = QRadioButton()
        radio.setObjectName("aya")
        
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                background: white;
            }
        """)
        
        layout = QVBoxLayout(container)
        
        title_label = QLabel("Aya-23-8B")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        layout.addWidget(title_label)
        
        features = (
            "✅ Locale (GPU)\n"
            "✅ Qualità superiore\n"
            "✅ Multilingua avanzato\n"
            "⚠️ Download 8GB richiesto\n"
            "⚠️ Più lento di NLLB"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)
        
        # Token HuggingFace
        token_group = QGroupBox("HuggingFace Token (richiesto)")
        token_layout = QVBoxLayout()
        
        self.hf_token_input = QLineEdit()
        self.hf_token_input.setPlaceholderText("hf_...")
        self.hf_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        current_token = self.config.get_huggingface_token()
        if current_token:
            self.hf_token_input.setText(current_token)
        
        save_token_btn = QPushButton("Save Token")
        save_token_btn.clicked.connect(self.save_hf_token)
        
        token_layout.addWidget(self.hf_token_input)
        token_layout.addWidget(save_token_btn)
        token_group.setLayout(token_layout)
        layout.addWidget(token_group)
        
        # Download button
        download_btn = QPushButton("Download Aya Model")
        download_btn.clicked.connect(self.start_aya_download)
        layout.addWidget(download_btn)
        
        # Progress
        self.aya_progress = QProgressBar()
        self.aya_progress.setVisible(False)
        layout.addWidget(self.aya_progress)
        
        # Wrapper
        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)
        
        wrapper = QWidget()
        wrapper.setLayout(main_layout)
        
        return wrapper, radio
    
    def create_model_section_claude(self):
        """Crea sezione Claude API"""
        radio = QRadioButton()
        radio.setObjectName("claude")
        
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                background: #f0f7ff;
            }
        """)
        
        layout = QVBoxLayout(container)
        
        title_label = QLabel("Claude API (Sonnet 4)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1976d2;")
        layout.addWidget(title_label)
        
        features = (
            "✅ Cloud-based (zero GPU)\n"
            "✅ Massima qualità\n"
            "✅ Comprensione contesto TMDB\n"
            "✅ 50+ lingue\n"
            "✅ Instant setup\n"
            "💰 Richiede crediti API separati (≠ piano Pro)"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)
        
        # API Key group
        api_group = QGroupBox("Claude API Key")
        api_layout = QVBoxLayout()
        
        self.claude_api_input = QLineEdit()
        self.claude_api_input.setPlaceholderText("sk-ant-...")
        self.claude_api_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        current_key = self.config.get_claude_api_key()
        if current_key:
            self.claude_api_input.setText(current_key)
        
        # Info label
        info_label = QLabel(
            "⚠️ Ottieni API key da: console.anthropic.com\n"
            "💡 Richiede acquisto crediti API ($5-10 = ~60 film)\n"
            "💡 Separato dal piano Pro (billing diverso)"
        )
        info_label.setStyleSheet("color: #666; font-size: 11px; margin: 5px 0;")
        info_label.setWordWrap(True)
        
        save_api_btn = QPushButton("Save API Key")
        save_api_btn.clicked.connect(self.save_claude_api_key)
        
        api_layout.addWidget(self.claude_api_input)
        api_layout.addWidget(info_label)
        api_layout.addWidget(save_api_btn)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        # Status indicator
        self.claude_status_label = QLabel()
        self.update_claude_status()
        layout.addWidget(self.claude_status_label)
        
        # Wrapper
        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)
        
        wrapper = QWidget()
        wrapper.setLayout(main_layout)
        
        return wrapper, radio
    
    def create_model_section_opensubtitles(self):
        """Crea sezione OpenSubtitles AI"""
        radio = QRadioButton()
        radio.setObjectName("opensubtitles")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #ff9800;
                border-radius: 8px;
                padding: 15px;
                background: #fff8f0;
            }
        """)

        layout = QVBoxLayout(container)

        title_label = QLabel("OpenSubtitles AI")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e65100;")
        layout.addWidget(title_label)

        features = (
            "✅ Cloud-based (zero GPU)\n"
            "✅ 10 traduzioni/periodo VIP free\n"
            "✅ Usa le credenziali OpenSubtitles esistenti\n"
            "✅ Instant setup (nessun download)\n"
            "⚠️ Quota limitata per account non-VIP"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)

        # Status credenziali
        self.os_status_label = QLabel()
        self.update_os_status()
        layout.addWidget(self.os_status_label)

        info_label = QLabel(
            "Le credenziali OpenSubtitles (username / password / API key) si\n"
            "configurano nella scheda Impostazioni > OpenSubtitles."
        )
        info_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)

        wrapper = QWidget()
        wrapper.setLayout(main_layout)

        return wrapper, radio

    def update_os_status(self):
        """Aggiorna indicatore stato credenziali OpenSubtitles"""
        if self.config.is_opensubtitles_configured():
            self.os_status_label.setText("✅ Credenziali configurate")
            self.os_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.os_status_label.setText("⚠️ Credenziali non configurate (vai in Impostazioni > OpenSubtitles)")
            self.os_status_label.setStyleSheet("color: orange;")

    def create_model_section_openai(self):
        """Crea sezione OpenAI GPT"""
        radio = QRadioButton()
        radio.setObjectName("openai")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #2e7d32;
                border-radius: 8px;
                padding: 15px;
                background: #f0fff4;
            }
        """)

        layout = QVBoxLayout(container)

        title_label = QLabel("OpenAI GPT")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1b5e20;")
        layout.addWidget(title_label)

        features = (
            "✅ Cloud-based (zero GPU)\n"
            "✅ Alta qualità (GPT-4o)\n"
            "✅ Economico (GPT-4o-mini)\n"
            "✅ 50+ lingue\n"
            "💰 Pagamento per token (platform.openai.com)"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)

        # API Key group
        api_group = QGroupBox("OpenAI API Key")
        api_layout = QVBoxLayout()

        self.oai_api_input = QLineEdit()
        self.oai_api_input.setPlaceholderText("sk-...")
        self.oai_api_input.setEchoMode(QLineEdit.EchoMode.Password)

        current_key = self.config.get_openai_api_key()
        if current_key:
            self.oai_api_input.setText(current_key)

        # Model selector
        from PyQt6.QtWidgets import QComboBox
        model_row = QHBoxLayout()
        model_label = QLabel("Modello:")
        model_label.setStyleSheet("font-weight: normal;")
        self.oai_model_combo = QComboBox()
        self.oai_model_combo.addItems(['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'])
        current_model = self.config.get_openai_model()
        idx = self.oai_model_combo.findText(current_model)
        if idx >= 0:
            self.oai_model_combo.setCurrentIndex(idx)
        model_row.addWidget(model_label)
        model_row.addWidget(self.oai_model_combo)
        model_row.addStretch()

        info_label = QLabel(
            "⚠️ Ottieni API key da: platform.openai.com\n"
            "💡 GPT-4o-mini: economico e veloce | GPT-4o: massima qualità"
        )
        info_label.setStyleSheet("color: #666; font-size: 11px; margin: 5px 0;")
        info_label.setWordWrap(True)

        save_api_btn = QPushButton("Save")
        save_api_btn.clicked.connect(self.save_openai_api_key)

        api_layout.addWidget(self.oai_api_input)
        api_layout.addLayout(model_row)
        api_layout.addWidget(info_label)
        api_layout.addWidget(save_api_btn)
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        # Status indicator
        self.oai_status_label = QLabel()
        self.update_openai_status()
        layout.addWidget(self.oai_status_label)

        main_layout = QHBoxLayout()
        main_layout.addWidget(radio)
        main_layout.addWidget(container, stretch=1)

        wrapper = QWidget()
        wrapper.setLayout(main_layout)

        return wrapper, radio

    def save_openai_api_key(self):
        """Salva API key OpenAI"""
        key = self.oai_api_input.text().strip()
        is_valid, err = self.config.validate_openai_api_key(key)
        if not is_valid:
            QMessageBox.warning(self, "API key non valida", err)
            return
        self.config.set_openai_api_key(key)
        self.config.set_openai_model(self.oai_model_combo.currentText())
        self.update_openai_status()
        QMessageBox.information(self, "Successo", "✅ API key OpenAI salvata!")

    def update_openai_status(self):
        """Aggiorna indicatore stato OpenAI"""
        if self.config.is_openai_api_key_set():
            self.oai_status_label.setText("✅ API key configurata")
            self.oai_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.oai_status_label.setText("⚠️ API key non configurata")
            self.oai_status_label.setStyleSheet("color: orange;")

    def save_hf_token(self):
        """Salva token HuggingFace"""
        token = self.hf_token_input.text().strip()
        
        if not token:
            QMessageBox.warning(self, "Token vuoto", "Inserisci un token valido.")
            return
        
        is_valid, error = self.config.validate_huggingface_token(token)
        
        if not is_valid:
            QMessageBox.warning(self, "Token non valido", f"Token non valido: {error}")
            return
        
        self.config.set_huggingface_token(token)
        QMessageBox.information(self, "Successo", "Token HuggingFace salvato!")
    
    def save_claude_api_key(self):
        """Salva API key Claude"""
        api_key = self.claude_api_input.text().strip()
        
        if not api_key:
            QMessageBox.warning(self, "API key vuota", "Inserisci un'API key valida.")
            return
        
        is_valid, error = self.config.validate_claude_api_key(api_key)
        
        if not is_valid:
            QMessageBox.warning(self, "API key non valida", f"API key non valida: {error}")
            return
        
        self.config.set_claude_api_key(api_key)
        self.update_claude_status()
        QMessageBox.information(self, "Successo", "✅ API key Claude salvata!\n\nOra puoi usare Claude per tradurre.")
    
    def update_claude_status(self):
        """Aggiorna indicatore stato Claude"""
        if self.config.is_claude_api_key_set():
            self.claude_status_label.setText("✅ API key configurata")
            self.claude_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.claude_status_label.setText("⚠️ API key non configurata")
            self.claude_status_label.setStyleSheet("color: orange;")
    
    def start_aya_download(self):
        """Avvia download Aya"""
        if not self.config.is_huggingface_token_set():
            QMessageBox.warning(
                self, 
                "Token mancante", 
                "Salva prima il token HuggingFace."
            )
            return
        
        self.aya_progress.setVisible(True)
        self.aya_progress.setRange(0, 0)  # Indeterminate
        
        self.download_worker = DownloadWorker()
        self.download_worker.progress_updated.connect(self.on_progress_update)
        self.download_worker.download_completed.connect(self.on_download_complete)
        self.download_worker.start()
    
    def on_progress_update(self, message: str, percent: int):
        """Aggiorna progresso download"""
        if percent > 0:
            self.aya_progress.setRange(0, 100)
            self.aya_progress.setValue(percent)
    
    def on_download_complete(self, success: bool, message: str):
        """Gestisce completamento download"""
        self.aya_progress.setVisible(False)
        
        if success:
            self.config.settings['aya_model_download_status'] = True
            self.config.save()
            QMessageBox.information(self, "Successo", message)
        else:
            QMessageBox.critical(self, "Errore", message)
    
    def get_selected_model(self) -> str:
        """Restituisce il modello selezionato"""
        if self.claude_radio.isChecked():
            return 'claude'
        elif self.aya_radio.isChecked():
            return 'aya'
        elif self.nllb_ft_radio.isChecked():
            return 'nllb_finetuned'
        elif self.os_radio.isChecked():
            return 'opensubtitles'
        elif self.oai_radio.isChecked():
            return 'openai'
        else:
            return 'nllb'
    
    def save_selection(self):
        """Salva selezione modello"""
        # Determina modello selezionato
        if self.claude_radio.isChecked():
            selected_model = 'claude'
            # Verifica API key
            if not self.config.is_claude_api_key_set():
                reply = QMessageBox.question(
                    self,
                    "API key mancante",
                    "Claude API key non configurata. Vuoi configurarla ora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return  # Rimani nel dialog
                else:
                    QMessageBox.warning(self, "Attenzione", "Claude non funzionerà senza API key.")

        elif self.nllb_ft_radio.isChecked():
            selected_model = 'nllb_finetuned'
            # Verifica che il path sia configurato
            if not self.config.is_nllb_finetuned_configured():
                reply = QMessageBox.question(
                    self,
                    "Modello non configurato",
                    "Il percorso del modello fine-tuned non è configurato.\n"
                    "Vuoi configurarlo ora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return  # Rimani nel dialog
                else:
                    QMessageBox.warning(
                        self, "Attenzione",
                        "Il modello fine-tuned non funzionerà senza un percorso valido."
                    )

        elif self.os_radio.isChecked():
            selected_model = 'opensubtitles'
            if not self.config.is_opensubtitles_configured():
                reply = QMessageBox.question(
                    self,
                    "Credenziali mancanti",
                    "Le credenziali OpenSubtitles non sono configurate.\n"
                    "Configurale in Impostazioni > OpenSubtitles, poi riprova.\n\n"
                    "Vuoi comunque salvare questa selezione?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return

        elif self.oai_radio.isChecked():
            selected_model = 'openai'
            if not self.config.is_openai_api_key_set():
                reply = QMessageBox.question(
                    self,
                    "API key mancante",
                    "OpenAI API key non configurata. Vuoi configurarla ora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return
                else:
                    QMessageBox.warning(self, "Attenzione", "OpenAI non funzionerà senza API key.")

        elif self.aya_radio.isChecked():
            selected_model = 'aya'
        else:
            selected_model = 'nllb'

        # Salva in config
        self.config.set_translation_model(selected_model)

        display_names = {
            'nllb': 'NLLB-200',
            'nllb_finetuned': 'NLLB-200 Fine-Tuned (Plex)',
            'aya': 'Aya-23-8B',
            'claude': 'Claude API',
            'opensubtitles': 'OpenSubtitles AI',
            'openai': 'OpenAI GPT',
        }
        display = display_names.get(selected_model, selected_model.upper())

        QMessageBox.information(
            self,
            "Modello aggiornato",
            f"Modello traduzione: {display}\n\n"
            f"Sarà usato per le prossime traduzioni."
        )

        self.accept()
    
    def create_diarization_section(self) -> QWidget:
        """Crea sezione Speaker Diarization"""
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("""
            QFrame {
                border: 1px solid #7b1fa2;
                border-radius: 8px;
                padding: 15px;
                background: #fdf3ff;
            }
        """)

        layout = QVBoxLayout(container)

        title_label = QLabel("🎭 Speaker Diarization")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #6a1b9a;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Identifica chi parla in ogni sottotitolo.\n"
            "Aggiunge un trattino ( - ) al cambio di parlante, stile dialogo cinema."
        )
        desc_label.setStyleSheet("color: #555; font-size: 12px; margin-top: 4px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # --- Token HuggingFace ---
        token_group = QGroupBox("HuggingFace Token")
        token_layout = QVBoxLayout()

        token_row = QHBoxLayout()
        self.diarization_hf_token_input = QLineEdit()
        self.diarization_hf_token_input.setPlaceholderText("hf_...")
        self.diarization_hf_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        current_token = self.config.get_huggingface_token()
        if current_token:
            self.diarization_hf_token_input.setText(current_token)

        save_token_btn = QPushButton("Salva")
        save_token_btn.setFixedWidth(70)
        save_token_btn.clicked.connect(self.save_diarization_hf_token)
        token_row.addWidget(self.diarization_hf_token_input)
        token_row.addWidget(save_token_btn)
        token_layout.addLayout(token_row)

        token_info = QLabel(
            "Crea un token su huggingface.co/settings/tokens\n"
            "Poi accetta i termini su:\n"
            "  • huggingface.co/pyannote/speaker-diarization-3.1\n"
            "  • huggingface.co/pyannote/segmentation-3.0"
        )
        token_info.setStyleSheet("color: #888; font-size: 11px;")
        token_layout.addWidget(token_info)

        # Stato token
        self.diarization_token_status = QLabel()
        self._update_diarization_token_status()
        token_layout.addWidget(self.diarization_token_status)

        token_group.setLayout(token_layout)
        layout.addWidget(token_group)

        # --- Test connessione ---
        test_btn = QPushButton("Testa download modello pyannote")
        test_btn.clicked.connect(self.test_pyannote_download)
        layout.addWidget(test_btn)

        self.diarization_test_label = QLabel("")
        self.diarization_test_label.setWordWrap(True)
        self.diarization_test_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self.diarization_test_label)

        # --- Forced Alignment ---
        self.forced_alignment_checkbox = QCheckBox("Forced Alignment (precisione broadcast/cinema)")
        self.forced_alignment_checkbox.setChecked(self.config.get('enable_forced_alignment', False))
        self.forced_alignment_checkbox.setToolTip(
            "Riallinea ogni parola al millisecondo esatto in cui viene pronunciata.\n"
            "Migliora la precisione dei timestamp del 30%.\n"
            "Consigliato per sottotitoli professionali.\n"
            "Aumenta il tempo di elaborazione del 15-20%.\n"
            "Richiede whisperx installato (pip install whisperx)."
        )
        self.forced_alignment_checkbox.toggled.connect(self.on_forced_alignment_toggled)
        layout.addWidget(self.forced_alignment_checkbox)

        # --- Checkbox abilitazione diarization ---
        self.diarization_checkbox = QCheckBox("Identifica parlanti (Speaker Diarization)")
        self.diarization_checkbox.setChecked(self.config.get('enable_diarization', False))
        self.diarization_checkbox.toggled.connect(self.on_diarization_toggled)
        layout.addWidget(self.diarization_checkbox)

        # --- SpinBox num parlanti ---
        num_row = QHBoxLayout()
        num_label = QLabel("N° parlanti:")
        num_label.setFixedWidth(100)
        self.diarization_num_speakers = QSpinBox()
        self.diarization_num_speakers.setRange(0, 10)
        self.diarization_num_speakers.setValue(self.config.get('diarization_num_speakers', 0))
        self.diarization_num_speakers.setSpecialValueText("auto")
        self.diarization_num_speakers.setToolTip("0 = rilevamento automatico")
        self.diarization_num_speakers.valueChanged.connect(self.on_num_speakers_changed)
        num_row.addWidget(num_label)
        num_row.addWidget(self.diarization_num_speakers)
        num_row.addStretch()
        layout.addLayout(num_row)

        return container

    def save_diarization_hf_token(self):
        """Salva token HuggingFace dalla sezione diarization"""
        token = self.diarization_hf_token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "Token vuoto", "Inserisci un token valido.")
            return
        is_valid, error = self.config.validate_huggingface_token(token)
        if not is_valid:
            QMessageBox.warning(self, "Token non valido", error)
            return
        self.config.set_huggingface_token(token)
        # Sincronizza anche il campo token nella sezione Aya
        if hasattr(self, 'hf_token_input'):
            self.hf_token_input.setText(token)
        self._update_diarization_token_status()
        QMessageBox.information(self, "Salvato", "Token HuggingFace salvato!")

    def _update_diarization_token_status(self):
        if self.config.is_huggingface_token_set():
            self.diarization_token_status.setText("✅ Token configurato")
            self.diarization_token_status.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        else:
            self.diarization_token_status.setText("⚠️ Token non configurato")
            self.diarization_token_status.setStyleSheet("color: orange; font-size: 11px;")

    def test_pyannote_download(self):
        """Testa il download della pipeline pyannote con il token configurato"""
        token = self.config.get_huggingface_token()
        if not token:
            self.diarization_test_label.setText("❌ Token non configurato. Salvalo prima.")
            self.diarization_test_label.setStyleSheet("color: red; font-size: 11px;")
            return

        self.diarization_test_label.setText("⏳ Download in corso (prima volta: ~1 GB)...")
        self.diarization_test_label.setStyleSheet("color: #555; font-size: 11px;")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            import warnings, torch, numpy as np, tempfile, os
            import soundfile as sf
            warnings.filterwarnings("ignore", message="torchcodec is not installed")
            from pyannote.audio import Pipeline

            self.diarization_test_label.setText("⏳ Caricamento pipeline pyannote...")
            QApplication.processEvents()

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=token
            )
            if torch.cuda.is_available():
                pipeline = pipeline.to(torch.device("cuda"))

            # Audio sintetico: 4 secondi, 2 "parlanti" (toni diversi)
            sr = 16000
            t = np.linspace(0, 4.0, sr * 4, dtype=np.float32)
            audio = np.concatenate([
                0.3 * np.sin(2 * np.pi * 200 * t[:sr * 2]),
                0.3 * np.sin(2 * np.pi * 600 * t[sr * 2:]),
            ])

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                tmp_path = f.name
            sf.write(tmp_path, audio, sr)

            try:
                import torchaudio
                waveform, sample_rate = torchaudio.load(tmp_path)
                output = pipeline({'waveform': waveform, 'sample_rate': sample_rate})
                annotation = getattr(output, 'speaker_diarization', output)
                turns = list(annotation.itertracks(yield_label=True))
                del pipeline
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.diarization_test_label.setText(
                    f"✅ Modello OK! Trovati {len(turns)} turni sul test audio.\n"
                    "Puoi abilitare la diarization."
                )
                self.diarization_test_label.setStyleSheet("color: green; font-size: 11px;")
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            err = str(e)
            if "403" in err or "gated" in err.lower() or "restricted" in err.lower():
                msg = (
                    "❌ Accesso negato (403).\n"
                    "Accetta i termini su:\n"
                    "  huggingface.co/pyannote/speaker-diarization-3.1\n"
                    "  huggingface.co/pyannote/segmentation-3.0"
                )
            elif "401" in err or "token" in err.lower():
                msg = "❌ Token non valido o scaduto. Controllalo su huggingface.co/settings/tokens"
            else:
                msg = f"❌ Errore: {err}"
            self.diarization_test_label.setText(msg)
            self.diarization_test_label.setStyleSheet("color: red; font-size: 11px;")

    def on_forced_alignment_toggled(self, checked: bool):
        """Salva stato checkbox forced alignment"""
        self.config.set('enable_forced_alignment', checked)

    def on_diarization_toggled(self, checked: bool):
        """Salva stato checkbox diarization"""
        self.config.set('enable_diarization', checked)

    def on_num_speakers_changed(self, value: int):
        """Salva numero parlanti"""
        self.config.set('diarization_num_speakers', value)

    def apply_theme(self):
        """Applica tema moderno"""
        self.setStyleSheet("""
            QDialog {
                background: #f5f5f5;
            }
            QPushButton {
                background: #1976d2;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #1565c0;
            }
            QPushButton:pressed {
                background: #0d47a1;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 12px;
                background: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
