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
import sys
from pathlib import Path

from utils.translations import tr
from utils.config import get_config
from utils.logger import setup_logger

logger = setup_logger('gui.translation_model_dialog')

# REGOLA: questo modulo NON deve mai importare core.translator/torch/
# transformers nel processo GUI (freeze + RAM). Le operazioni ML girano
# in subprocess via core.env_check_cli (EnvCliWorker).


# Stylesheet container coerenti col tema dark globale (theme.qss).
# Cambia solo il colore del bordo per distinguere visivamente le sezioni.
def _section_qss(border_color: str) -> str:
    return f"""
        QFrame {{
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 15px;
            background-color: #2c2e36;
        }}
    """

_SECTION_QSS_NEUTRAL = _section_qss("#3a3d47")
_SECTION_QSS_GREEN = _section_qss("#3fcf8e")
_SECTION_QSS_BLUE = _section_qss("#3cc1e0")
_SECTION_QSS_ORANGE = _section_qss("#f5b450")
_SECTION_QSS_PURPLE = _section_qss("#9b6bc7")
_SECTION_QSS_RED_ORANGE = _section_qss("#ef8a5a")


class EnvCliWorker(QThread):
    """Esegue core.env_check_cli in subprocess e streamma le righe di stato.

    Il vecchio DownloadWorker importava core.translator (torch+transformers)
    nel processo GUI; ora il lavoro ML gira in un processo separato che
    muore alla fine restituendo RAM/VRAM all'OS, e il thread GUI non viene
    mai toccato dagli import ML.
    """

    line_out = pyqtSignal(str)      # riga di stato dal CLI
    finished_code = pyqtSignal(int)  # exit code (0 = ok)

    def __init__(self, command: str, parent=None):
        super().__init__(parent)
        self._command = command

    def run(self):
        import os
        import subprocess
        import threading

        root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['TP_SUBPROCESS'] = '1'
        env['TQDM_DISABLE'] = '1'
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-m', 'core.env_check_cli', self._command],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(root), env=env, text=True, encoding='utf-8',
                errors='replace', bufsize=1, creationflags=flags)
        except Exception as e:
            self.line_out.emit(f"❌ Avvio subprocess fallito: {e}")
            self.finished_code.emit(1)
            return

        def _drain(stream):
            # Rumore librerie: solo nel file di log, mai in GUI
            try:
                for eline in stream:
                    eline = eline.rstrip()
                    if eline:
                        logger.debug(f"[env-cli-stderr] {eline}")
            except Exception:
                pass

        threading.Thread(target=_drain, args=(proc.stderr,),
                         daemon=True).start()
        for line in proc.stdout:
            line = line.strip()
            if line:
                self.line_out.emit(line)
        self.finished_code.emit(proc.wait())


class TranslationModelDialog(QDialog):
    """Dialog per selezione modello di traduzione"""
    
    def __init__(self, parent=None, embed=False):
        super().__init__(parent)
        self.config = get_config()
        self.selected_model = self.config.get_translation_model()
        self.download_worker = None
        self.embed = embed

        # Check disponibilità SENZA import reale: importare core.translator
        # qui caricava torch+transformers sul thread GUI (3.7-9s di freeze
        # misurati dalla telemetria [UI-STALL]). find_spec verifica solo che
        # il pacchetto esista sul disco, costo ~0.
        import importlib.util
        _translator_available = (
            importlib.util.find_spec('transformers') is not None
            and importlib.util.find_spec('torch') is not None)

        if not embed:
            self.setWindowTitle(tr('tmd_title'))
            self.setModal(True)
            self.setMinimumWidth(800)
            self.setMinimumHeight(700)
            self.resize(850, 750)
            self.setSizeGripEnabled(True)

        if not _translator_available:
            self.init_ui_error()
        else:
            self.init_ui()
            if not embed:
                self.apply_theme()
    
    def init_ui_error(self):
        """Interfaccia errore se translator non disponibile"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        error_label = QLabel(
            tr('tmd_error_title') + "\n\n"
            "Impossibile importare 'BaseTranslator' da 'core.translator'.\n"
            "Verificare installazione del modulo."
        )
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #d32f2f; font-size: 14px; padding: 20px;")
        
        main_layout.addWidget(error_label)
        
        close_btn = QPushButton(tr('close_btn'))
        close_btn.clicked.connect(self.reject)
        main_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.setLayout(main_layout)
    
    def init_ui(self):
        """Interfaccia principale"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Body (header + scroll area con tutte le sezioni)
        body = self._build_body()
        main_layout.addWidget(body, stretch=1)

        # Buttons (solo in modalita' standalone)
        if not self.embed:
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()

            save_btn = QPushButton(tr('save_close'))
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
        if self.selected_model in ('llm', 'aya'):
            self.llm_radio.setChecked(True)
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

        # In embed mode il toggle salva direttamente (no Save button).
        if self.embed:
            self.button_group.buttonToggled.connect(self._on_radio_toggled_embed)

    def _build_body(self) -> QWidget:
        """Costruisce il corpo: header + scroll area con tutte le sezioni.

        Riusabile sia in modalita' standalone (init_ui aggiunge button bar)
        sia in modalita' embedded (SettingsDialog usa solo questo body).
        """
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(15)
        body_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = self.create_header()
        body_layout.addWidget(header)

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

        # Parametri NLLB (condivisi tra NLLB base e Fine-Tuned)
        scroll_layout.addWidget(self.create_nllb_params_section())

        # Traduttore LLM locale
        llm_widget, self.llm_radio = self.create_model_section_llm()
        scroll_layout.addWidget(llm_widget)
        self.button_group.addButton(self.llm_radio)

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

        # Force audio transcription (ignora sottotitoli embedded)
        force_audio_widget = self.create_force_transcription_section()
        scroll_layout.addWidget(force_audio_widget)

        # Gender Correction
        gender_widget = self.create_gender_correction_section()
        scroll_layout.addWidget(gender_widget)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        body_layout.addWidget(scroll, stretch=1)

        return body

    def _on_radio_toggled_embed(self, button, checked: bool):
        """Auto-persist della selezione in embed mode (no Save button).

        Chiamato per ogni toggle del button_group; salva solo per il radio
        appena attivato (checked=True). Niente QMessageBox: la conferma e'
        gestita dal SettingsDialog di livello superiore.
        """
        if not checked:
            return
        name = button.objectName()
        valid = {'nllb', 'nllb_finetuned', 'llm', 'claude', 'opensubtitles', 'openai'}
        if name in valid:
            self.config.set_translation_model(name)
            self.selected_model = name
    
    def create_header(self) -> QWidget:
        """Crea header dialog"""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 15)

        title = QLabel(tr('tmd_header'))
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #3cc1e0;")

        subtitle = QLabel(tr('tmd_subtitle'))
        subtitle.setStyleSheet("font-size: 13px;")
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        
        return header_widget
    
    def create_model_section_nllb(self):
        """Crea sezione NLLB"""
        radio = QRadioButton()
        radio.setObjectName("nllb")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_NEUTRAL)

        layout = QVBoxLayout(container)

        title_label = QLabel("NLLB-200")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)

        features = (
            "✅ Locale (GPU)\n"
            "✅ 200+ lingue\n"
            "✅ Auto-download (3.3GB)\n"
            "✅ Veloce\n"
            "❌ Qualità media"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
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
        container.setStyleSheet(_SECTION_QSS_GREEN)

        layout = QVBoxLayout(container)

        title_label = QLabel("NLLB-200 Fine-Tuned (Plex)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3fcf8e;")
        layout.addWidget(title_label)

        features = (
            "✅ Locale (GPU)\n"
            "✅ Fine-tuned sulla tua libreria Plex\n"
            "✅ Stile ottimizzato per sottotitoli\n"
            "✅ Stessa velocità di NLLB base\n"
            "⚠️ Solo EN→IT (dataset di training)"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)

        # Path selector
        path_group = QGroupBox(tr('model_folder_group'))
        path_layout = QVBoxLayout()

        path_row = QHBoxLayout()
        self.nllb_ft_path_input = QLineEdit()
        self.nllb_ft_path_input.setPlaceholderText(
            r"C:\...\nllb-subtitles-lora\merged_model"
        )
        current_path = self.config.get_nllb_finetuned_model_path()
        if current_path:
            self.nllb_ft_path_input.setText(current_path)

        browse_btn = QPushButton(tr('browse'))
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self.browse_nllb_ft_path)

        path_row.addWidget(self.nllb_ft_path_input)
        path_row.addWidget(browse_btn)
        path_layout.addLayout(path_row)

        save_path_btn = QPushButton(tr('save_path'))
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

    def create_nllb_params_section(self) -> QWidget:
        """Sezione parametri NLLB condivisi (base + fine-tuned)."""
        group = QGroupBox(tr('nllb_params_group'))
        layout = QHBoxLayout(group)
        layout.setContentsMargins(12, 8, 12, 8)

        label = QLabel(tr('nllb_num_beams_label'))
        layout.addWidget(label)

        self.nllb_beams_spin = QSpinBox()
        self.nllb_beams_spin.setRange(1, 20)
        self.nllb_beams_spin.setValue(self.config.get_nllb_num_beams())
        self.nllb_beams_spin.setFixedWidth(70)
        self.nllb_beams_spin.setToolTip(tr('nllb_num_beams_tooltip'))
        self.nllb_beams_spin.valueChanged.connect(self._on_nllb_beams_changed)
        layout.addWidget(self.nllb_beams_spin)

        layout.addStretch()
        return group

    def _on_nllb_beams_changed(self, value: int):
        self.config.set_nllb_num_beams(value)

    def browse_nllb_ft_path(self):
        """Apre dialog per selezionare la cartella del modello fine-tuned"""
        folder = QFileDialog.getExistingDirectory(
            self,
            tr('select_model_folder'),
            self.nllb_ft_path_input.text() or str(Path.home()),
        )
        if folder:
            self.nllb_ft_path_input.setText(folder)

    def save_nllb_ft_path(self):
        """Salva il path del modello fine-tuned"""
        path = self.nllb_ft_path_input.text().strip()
        if not path:
            QMessageBox.warning(self, tr('path_empty'), "Inserisci il percorso della cartella merged_model.")
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, tr('folder_not_found'), f"La cartella non esiste:\n{path}")
            return
        if not (p / 'config.json').exists():
            QMessageBox.warning(
                self, tr('folder_invalid'),
                "La cartella non sembra contenere un modello HuggingFace valido (config.json non trovato)."
            )
            return

        self.config.set_nllb_finetuned_model_path(path)
        self.update_nllb_ft_status()
        QMessageBox.information(self, tr('path_saved_title'), tr('path_saved_msg'))

    def update_nllb_ft_status(self):
        """Aggiorna indicatore stato modello fine-tuned"""
        if self.config.is_nllb_finetuned_configured():
            self.nllb_ft_status_label.setText(tr('tmd_configured'))
            self.nllb_ft_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.nllb_ft_status_label.setText(tr('tmd_not_configured'))
            self.nllb_ft_status_label.setStyleSheet("color: orange;")

    def create_model_section_llm(self):
        """Sezione del traduttore LLM locale, col relativo scaricamento.

        Lo slot ospitava Aya, rimossa il 2026-08-18 dopo che aveva perso ogni
        confronto su film reale e che il suo percorso si era rivelato capace di
        disallineare battute e tempi. Ora ospita TranslateGemma-12B; quale
        modello ci sia dentro resta una chiave di configurazione.
        """
        radio = QRadioButton()
        radio.setObjectName("llm")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_NEUTRAL)

        layout = QVBoxLayout(container)

        title_label = QLabel("TranslateGemma 12B")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)

        features = (
            "✅ Locale (GPU)\n"
            "✅ Qualità superiore\n"
            "✅ Multilingua avanzato\n"
            "⚠️ Download 8GB richiesto\n"
            "⚠️ Più lento di NLLB"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)
        
        # Token HuggingFace
        token_group = QGroupBox(tr('hf_token_group'))
        token_layout = QVBoxLayout()
        
        self.hf_token_input = QLineEdit()
        self.hf_token_input.setPlaceholderText("hf_...")
        self.hf_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        current_token = self.config.get_huggingface_token()
        if current_token:
            self.hf_token_input.setText(current_token)
        
        save_token_btn = QPushButton(tr('save_token'))
        save_token_btn.clicked.connect(self.save_hf_token)
        
        token_layout.addWidget(self.hf_token_input)
        token_layout.addWidget(save_token_btn)
        token_group.setLayout(token_layout)
        layout.addWidget(token_group)
        
        # Download button
        download_btn = QPushButton(tr('download_llm_model'))
        download_btn.clicked.connect(self.start_llm_download)
        layout.addWidget(download_btn)
        
        # Progress
        self.llm_progress = QProgressBar()
        self.llm_progress.setVisible(False)
        layout.addWidget(self.llm_progress)
        
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
        container.setStyleSheet(_SECTION_QSS_BLUE)

        layout = QVBoxLayout(container)

        title_label = QLabel("Claude API (Sonnet 4)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3cc1e0;")
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
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
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
        info_label = QLabel(tr('api_key_info_claude'))
        info_label.setStyleSheet("font-size: 11px; margin: 5px 0;")
        info_label.setWordWrap(True)

        save_api_btn = QPushButton(tr('save_api_key'))
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
        container.setStyleSheet(_SECTION_QSS_ORANGE)

        layout = QVBoxLayout(container)

        title_label = QLabel("OpenSubtitles AI")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f5b450;")
        layout.addWidget(title_label)

        features = (
            "✅ Cloud-based (zero GPU)\n"
            "✅ 10 traduzioni/periodo VIP free\n"
            "✅ Usa le credenziali OpenSubtitles esistenti\n"
            "✅ Instant setup (nessun download)\n"
            "⚠️ Quota limitata per account non-VIP"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
        layout.addWidget(features_label)

        # Status credenziali
        self.os_status_label = QLabel()
        self.update_os_status()
        layout.addWidget(self.os_status_label)

        info_label = QLabel(tr('os_creds_info'))
        info_label.setStyleSheet("font-size: 11px; margin-top: 4px;")
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
            self.os_status_label.setText(tr('tmd_creds_configured'))
            self.os_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.os_status_label.setText(tr('tmd_creds_not_configured'))
            self.os_status_label.setStyleSheet("color: orange;")

    def create_model_section_openai(self):
        """Crea sezione OpenAI GPT"""
        radio = QRadioButton()
        radio.setObjectName("openai")

        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_GREEN)

        layout = QVBoxLayout(container)

        title_label = QLabel("OpenAI GPT")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3fcf8e;")
        layout.addWidget(title_label)

        features = (
            "✅ Cloud-based (zero GPU)\n"
            "✅ Alta qualità (GPT-4o)\n"
            "✅ Economico (GPT-4o-mini)\n"
            "✅ 50+ lingue\n"
            "💰 Pagamento per token (platform.openai.com)"
        )
        features_label = QLabel(features)
        features_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
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

        info_label = QLabel(tr('api_key_info_openai'))
        info_label.setStyleSheet("font-size: 11px; margin: 5px 0;")
        info_label.setWordWrap(True)

        save_api_btn = QPushButton(tr('save'))
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
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))

    def update_openai_status(self):
        """Aggiorna indicatore stato OpenAI"""
        if self.config.is_openai_api_key_set():
            self.oai_status_label.setText(tr('tmd_creds_configured'))
            self.oai_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.oai_status_label.setText(tr('tmd_not_configured'))
            self.oai_status_label.setStyleSheet("color: orange;")

    def save_hf_token(self):
        """Salva token HuggingFace"""
        token = self.hf_token_input.text().strip()
        
        if not token:
            QMessageBox.warning(self, tr('token_empty'), "Inserisci un token valido.")
            return

        is_valid, error = self.config.validate_huggingface_token(token)

        if not is_valid:
            QMessageBox.warning(self, "Token non valido", f"Token non valido: {error}")
            return

        self.config.set_huggingface_token(token)
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))
    
    def save_claude_api_key(self):
        """Salva API key Claude"""
        api_key = self.claude_api_input.text().strip()
        
        if not api_key:
            QMessageBox.warning(self, tr('save_api_key'), "Inserisci un'API key valida.")
            return

        is_valid, error = self.config.validate_claude_api_key(api_key)

        if not is_valid:
            QMessageBox.warning(self, "API key non valida", f"API key non valida: {error}")
            return

        self.config.set_claude_api_key(api_key)
        self.update_claude_status()
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))
    
    def update_claude_status(self):
        """Aggiorna indicatore stato Claude"""
        if self.config.is_claude_api_key_set():
            self.claude_status_label.setText(tr('tmd_creds_configured'))
            self.claude_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.claude_status_label.setText(tr('tmd_not_configured'))
            self.claude_status_label.setStyleSheet("color: orange;")
    
    def start_llm_download(self):
        """Avvia lo scaricamento del modello LLM in uso."""
        if not self.config.is_huggingface_token_set():
            QMessageBox.warning(
                self, 
                "Token mancante", 
                "Salva prima il token HuggingFace."
            )
            return
        
        if self.download_worker is not None and self.download_worker.isRunning():
            return  # download già in corso

        self.llm_progress.setVisible(True)
        self.llm_progress.setRange(0, 0)  # Indeterminate

        self._llm_last_line = ''
        self.download_worker = EnvCliWorker('llm-download')
        self.download_worker.line_out.connect(self._on_llm_line)
        self.download_worker.finished_code.connect(self.on_download_complete)
        self.download_worker.start()

    def _on_llm_line(self, line: str):
        self._llm_last_line = line

    def on_download_complete(self, exit_code: int):
        """Gestisce completamento download (subprocess terminato)"""
        self.llm_progress.setVisible(False)

        if exit_code == 0:
            QMessageBox.information(self, "Successo", "[OK] Download completato!")
        else:
            detail = self._llm_last_line or "Caricamento fallito"
            QMessageBox.critical(self, "Errore", f"[X] {detail}")
    
    def get_selected_model(self) -> str:
        """Restituisce il modello selezionato"""
        if self.claude_radio.isChecked():
            return 'claude'
        elif self.llm_radio.isChecked():
            return 'llm'
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

        elif self.llm_radio.isChecked():
            selected_model = 'llm'
        else:
            selected_model = 'nllb'

        # Salva in config
        self.config.set_translation_model(selected_model)

        display_names = {
            'nllb': 'NLLB-200',
            'nllb_finetuned': 'NLLB-200 Fine-Tuned (Plex)',
            'llm': 'TranslateGemma 12B',
            'claude': 'Claude API',
            'opensubtitles': 'OpenSubtitles AI',
            'openai': 'OpenAI GPT',
        }
        display = display_names.get(selected_model, selected_model.upper())

        QMessageBox.information(
            self,
            tr('model_updated_title'),
            tr('model_updated_msg').format(model=display)
        )

        self.accept()
    
    def create_diarization_section(self) -> QWidget:
        """Crea sezione Speaker Diarization"""
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_PURPLE)

        layout = QVBoxLayout(container)

        title_label = QLabel(tr('diarization_title'))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #b78ee0;")
        layout.addWidget(title_label)

        desc_label = QLabel(tr('diarization_desc'))
        desc_label.setStyleSheet("font-size: 12px; margin-top: 4px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # --- Token HuggingFace ---
        token_group = QGroupBox(tr('hf_token_label'))
        token_layout = QVBoxLayout()

        token_row = QHBoxLayout()
        self.diarization_hf_token_input = QLineEdit()
        self.diarization_hf_token_input.setPlaceholderText("hf_...")
        self.diarization_hf_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        current_token = self.config.get_huggingface_token()
        if current_token:
            self.diarization_hf_token_input.setText(current_token)

        save_token_btn = QPushButton(tr('save'))
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
        token_info.setStyleSheet("font-size: 11px;")
        token_layout.addWidget(token_info)

        # Stato token
        self.diarization_token_status = QLabel()
        self._update_diarization_token_status()
        token_layout.addWidget(self.diarization_token_status)

        token_group.setLayout(token_layout)
        layout.addWidget(token_group)

        # --- Test connessione ---
        test_btn = QPushButton(tr('test_download'))
        test_btn.clicked.connect(self.test_pyannote_download)
        layout.addWidget(test_btn)

        self.diarization_test_label = QLabel("")
        self.diarization_test_label.setWordWrap(True)
        self.diarization_test_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.diarization_test_label)

        # --- Forced Alignment ---
        self.forced_alignment_checkbox = QCheckBox(tr('forced_alignment_check'))
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
        self.diarization_checkbox = QCheckBox(tr('diarization_check'))
        self.diarization_checkbox.setChecked(self.config.get('enable_diarization', False))
        self.diarization_checkbox.toggled.connect(self.on_diarization_toggled)
        layout.addWidget(self.diarization_checkbox)

        # --- SpinBox num parlanti ---
        num_row = QHBoxLayout()
        num_label = QLabel(tr('speakers_label'))
        num_label.setFixedWidth(100)
        self.diarization_num_speakers = QSpinBox()
        self.diarization_num_speakers.setRange(0, 10)
        self.diarization_num_speakers.setValue(self.config.get('diarization_num_speakers', 0))
        self.diarization_num_speakers.setSpecialValueText(tr('auto_speakers'))
        self.diarization_num_speakers.setToolTip(tr('speakers_tip'))
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
            QMessageBox.warning(self, tr('token_empty'), "Inserisci un token valido.")
            return
        is_valid, error = self.config.validate_huggingface_token(token)
        if not is_valid:
            QMessageBox.warning(self, "Token non valido", error)
            return
        self.config.set_huggingface_token(token)
        # Sincronizza anche il campo token nella sezione del traduttore LLM
        if hasattr(self, 'hf_token_input'):
            self.hf_token_input.setText(token)
        self._update_diarization_token_status()
        QMessageBox.information(self, tr('path_saved_title'), tr('creds_saved_msg'))

    def _update_diarization_token_status(self):
        if self.config.is_huggingface_token_set():
            self.diarization_token_status.setText(tr('tmd_creds_configured'))
            self.diarization_token_status.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        else:
            self.diarization_token_status.setText(tr('tmd_not_configured'))
            self.diarization_token_status.setStyleSheet("color: orange; font-size: 11px;")

    def test_pyannote_download(self):
        """Testa il download della pipeline pyannote con il token configurato"""
        token = self.config.get_huggingface_token()
        if not token:
            self.diarization_test_label.setText("❌ Token non configurato. Salvalo prima.")
            self.diarization_test_label.setStyleSheet("color: red; font-size: 11px;")
            return

        # Il test gira in SUBPROCESS (core.env_check_cli): prima importava
        # torch+pyannote nel thread GUI congelando l'interfaccia per decine
        # di secondi. La GUI resta fluida e mostra le righe di progresso.
        if (getattr(self, '_diar_test_worker', None) is not None
                and self._diar_test_worker.isRunning()):
            return  # test già in corso

        self.diarization_test_label.setText(
            "⏳ Test avviato in background (prima volta: download ~1 GB)...")
        self.diarization_test_label.setStyleSheet("color: #555; font-size: 11px;")

        self._diar_test_lines = []
        self._diar_test_worker = EnvCliWorker('diarization-test')
        self._diar_test_worker.line_out.connect(self._on_diar_test_line)
        self._diar_test_worker.finished_code.connect(self._on_diar_test_done)
        self._diar_test_worker.start()

    def _on_diar_test_line(self, line: str):
        self._diar_test_lines.append(line)
        # Durante il run mostra l'ultima riga di stato
        self.diarization_test_label.setText(line)

    def _on_diar_test_done(self, exit_code: int):
        # A fine run mostra il messaggio completo (il CLI emette le stesse
        # righe finali del vecchio test in-process: OK/403/401/errore).
        # Le righe di progresso "⏳" non fanno parte del verdetto.
        final_lines = [l for l in self._diar_test_lines
                       if not l.startswith('⏳')]
        tail = "\n".join(final_lines[-4:]) if final_lines \
            else "❌ Nessun output dal test."
        self.diarization_test_label.setText(tail)
        color = "green" if exit_code == 0 else "red"
        self.diarization_test_label.setStyleSheet(
            f"color: {color}; font-size: 11px;")

    # ── Gender Correction ─────────────────────────────────────────────────

    def create_gender_correction_section(self) -> QWidget:
        """Crea sezione Gender Correction (EXPERIMENTAL)."""
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_RED_ORANGE)

        layout = QVBoxLayout(container)

        title_label = QLabel("Correzione Genere (v2 — audio-driven)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ef8a5a;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Corregge il genere grammaticale nei sottotitoli italiani deducendo "
            "il genere di CHI PARLA dalla voce (diarization + classificatore) e "
            "riscrivendo solo le forme di 1ª/2ª persona con un flip morfologico "
            "deterministico validato. Nessun LLM, nessuna VRAM aggiuntiva.\n"
            "Eseguito in un processo separato dopo la traduzione."
        )
        desc_label.setStyleSheet("font-size: 12px; margin-top: 4px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # --- Stato prerequisiti (venv NLP + token HF) ---
        self.gender_env_status = QLabel()
        self._update_gender_env_status()
        layout.addWidget(self.gender_env_status)

        # --- Checkbox abilitazione ---
        self.gender_correction_checkbox = QCheckBox(
            "Abilita correzione genere (solo sottotitoli italiani)"
        )
        self.gender_correction_checkbox.setChecked(
            self.config.get('gender_correction_enabled', False)
        )
        self.gender_correction_checkbox.toggled.connect(self._on_gender_correction_toggled)
        layout.addWidget(self.gender_correction_checkbox)

        # --- Checkbox 2ª persona ---
        self.gender_p2_checkbox = QCheckBox(
            "Correggi anche la 2ª persona (“sei stanca?” — genere "
            "dell'interlocutore dai turni di dialogo)"
        )
        self.gender_p2_checkbox.setChecked(
            self.config.get('gender_correction_second_person', True)
        )
        self.gender_p2_checkbox.toggled.connect(
            lambda c: self.config.set('gender_correction_second_person', c))
        layout.addWidget(self.gender_p2_checkbox)

        info_label = QLabel(
            "Prudente per costruzione: righe con parlante incerto, dialoghi "
            "doppi e riscritture non plausibili restano intatte."
        )
        info_label.setStyleSheet(
            "color: #f5b450; font-size: 11px; font-style: italic; margin-top: 4px;"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        return container

    def _update_gender_env_status(self):
        """Verifica prerequisiti v2: venv NLP (spaCy) e token HuggingFace."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        cands = [self.config.get('gender_selector_python', ''),
                 root / 'venv_nlp' / 'Scripts' / 'python.exe',
                 root / 'gender_eval' / '.venv_spacy' / 'Scripts' / 'python.exe']
        nlp_ok = any(p and Path(p).exists() for p in cands)
        hf_ok = bool(self.config.get('huggingface_token', ''))
        if nlp_ok and hf_ok:
            self.gender_env_status.setText("Prerequisiti OK (venv NLP + token HuggingFace)")
            self.gender_env_status.setStyleSheet(
                "color: green; font-weight: bold; font-size: 11px;")
        else:
            missing = []
            if not nlp_ok:
                missing.append("venv NLP (spaCy) non trovato")
            if not hf_ok:
                missing.append("token HuggingFace mancante")
            self.gender_env_status.setText(" — ".join(missing))
            self.gender_env_status.setStyleSheet("color: red; font-size: 11px;")

    def _on_gender_correction_toggled(self, checked: bool):
        """Salva stato checkbox gender correction."""
        self.config.set('gender_correction_enabled', checked)

    # ── Force audio transcription ─────────────────────────────────────────

    def create_force_transcription_section(self) -> QWidget:
        """Crea sezione 'Forza trascrizione da audio'."""
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet(_SECTION_QSS_BLUE)

        layout = QVBoxLayout(container)

        title_label = QLabel(tr('force_audio_title'))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #3cc1e0;")
        layout.addWidget(title_label)

        self.force_audio_checkbox = QCheckBox(tr('force_audio_checkbox'))
        self.force_audio_checkbox.setChecked(
            self.config.get('force_audio_transcription', False)
        )
        self.force_audio_checkbox.toggled.connect(self._on_force_audio_toggled)
        layout.addWidget(self.force_audio_checkbox)

        info_label = QLabel(tr('force_audio_info'))
        info_label.setStyleSheet("font-size: 11px; margin-top: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        return container

    def _on_force_audio_toggled(self, checked: bool):
        """Salva stato checkbox forza trascrizione da audio."""
        self.config.set('force_audio_transcription', checked)

    # ── Forced Alignment / Diarization ────────────────────────────────────

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
        """Tema dialog: neutralizzato in Fase 2 del GUI revamp.

        Lo styling globale (dark slate + accent ciano) e' caricato in main.py
        da gui/theme.qss. Il metodo resta come no-op per compatibilita' con il
        chiamante in init_ui (modalita' standalone).
        """
        return
