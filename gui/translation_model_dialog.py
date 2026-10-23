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


from gui.design_tokens import T
from gui.components import section_qss
from gui.theme import set_role

# Colore del titolo di sezione -> tono del tema (h2 + tone). I colori senza
# tono (viola e rosso-arancio) restano a stile locale con i token.
_TITLE_TONES = {T.success: 'success', T.accent: 'accent', T.warn: 'warn'}


def _section_container(border_color: str) -> QFrame:
    """Contenitore di sezione col bordo colorato (QSS identico allo storico)."""
    container = QFrame()
    container.setFrameShape(QFrame.Shape.Box)
    container.setStyleSheet(section_qss(border_color))
    return container


def _section_title(text: str, color=None) -> QLabel:
    """Titolo di sezione 16px bold, eventualmente colorato."""
    label = QLabel(text)
    tone = _TITLE_TONES.get(color)
    if color is None or tone:
        set_role(label, 'h2', tone)
    else:
        label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")
    return label


def _status_style(label: QLabel, color: str, bold: bool = False, size=None) -> None:
    """Stile di un'etichetta di stato (colore calcolato a runtime)."""
    css = f"color: {color};"
    if bold:
        css += " font-weight: bold;"
    if size:
        css += f" font-size: {size}px;"
    label.setStyleSheet(css)


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
            tr('tmd_error_title') + "\n\n" +
            tr('tmd_import_error')
        )
        error_label.setWordWrap(True)
        error_label.setStyleSheet(
            f"color: {T.legacy_red_deep}; font-size: 14px; padding: 20px;")
        
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

            cancel_btn = QPushButton(tr('tmd_cancel'))
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
        set_role(title, 'h1', 'accent')

        subtitle = QLabel(tr('tmd_subtitle'))
        set_role(subtitle, 'lead')
        
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        
        return header_widget
    
    def create_model_section_nllb(self):
        """Crea sezione NLLB"""
        radio = QRadioButton()
        radio.setObjectName("nllb")

        container = _section_container(T.section_neutral)

        layout = QVBoxLayout(container)

        title_label = _section_title("NLLB-200")
        layout.addWidget(title_label)

        features = tr('tmd_feat_nllb')
        features_label = QLabel(features)
        set_role(features_label, 'body')
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

        container = _section_container(T.section_green)

        layout = QVBoxLayout(container)

        title_label = _section_title("NLLB-200 Fine-Tuned (Plex)", T.success)
        layout.addWidget(title_label)

        features = tr('tmd_feat_nllb_ft')
        features_label = QLabel(features)
        set_role(features_label, 'body')
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
            QMessageBox.warning(self, tr('path_empty'), tr('tmd_enter_merged_path'))
            return

        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, tr('folder_not_found'), tr('tmd_folder_missing_msg').format(path=path))
            return
        if not (p / 'config.json').exists():
            QMessageBox.warning(
                self, tr('folder_invalid'),
                tr('tmd_folder_invalid_msg')
            )
            return

        self.config.set_nllb_finetuned_model_path(path)
        self.update_nllb_ft_status()
        QMessageBox.information(self, tr('path_saved_title'), tr('path_saved_msg'))

    def update_nllb_ft_status(self):
        """Aggiorna indicatore stato modello fine-tuned"""
        if self.config.is_nllb_finetuned_configured():
            self.nllb_ft_status_label.setText(tr('tmd_configured'))
            _status_style(self.nllb_ft_status_label, T.css_green, bold=True)
        else:
            self.nllb_ft_status_label.setText(tr('tmd_not_configured'))
            _status_style(self.nllb_ft_status_label, T.css_orange)

    def browse_llm_model_path(self):
        """Apre dialog per selezionare la cartella dei pesi del modello LLM"""
        folder = QFileDialog.getExistingDirectory(
            self,
            tr('select_model_folder'),
            self.llm_model_path_input.text() or str(Path.home()),
        )
        if folder:
            self.llm_model_path_input.setText(folder)

    def save_llm_model_path(self):
        """Salva il path della cartella del modello LLM (vuoto = default)"""
        path = self.llm_model_path_input.text().strip()
        if path:
            p = Path(path)
            if not p.exists():
                QMessageBox.warning(self, tr('folder_not_found'), tr('tmd_folder_missing_msg').format(path=path))
                return
            if not (p / 'config.json').exists():
                QMessageBox.warning(
                    self, tr('folder_invalid'),
                    tr('tmd_folder_invalid_msg')
                )
                return

        self.config.set_llm_translator_model_path(path)
        QMessageBox.information(self, tr('path_saved_title'), tr('path_saved_msg'))

    def create_model_section_llm(self):
        """Sezione del traduttore LLM locale, col relativo scaricamento.

        Lo slot ospitava Aya, rimossa il 2026-08-18 dopo che aveva perso ogni
        confronto su film reale e che il suo percorso si era rivelato capace di
        disallineare battute e tempi. Ora ospita TranslateGemma-12B con
        l'adattatore addestrato sul nostro corpus di sottotitoli — da cui
        il nome "TranslateGemma_finetuned".

        NON si offre anche il modello base: questo software genera solo
        sottotitoli, e un traduttore non specializzato non ha un caso d'uso.
        Quale modello e quale adattatore ci siano dentro restano chiavi di
        configurazione (`llm_translator_model`, `llm_translator_adapter`).
        """
        radio = QRadioButton()
        radio.setObjectName("llm")

        container = _section_container(T.section_neutral)

        layout = QVBoxLayout(container)

        title_label = _section_title("TranslateGemma_finetuned")
        layout.addWidget(title_label)

        features = tr('tmd_feat_llm')
        features_label = QLabel(features)
        set_role(features_label, 'body')
        layout.addWidget(features_label)

        # Cartella del modello (override locale dei pesi base)
        model_path_group = QGroupBox(tr('model_folder_group'))
        model_path_layout = QVBoxLayout()

        model_path_row = QHBoxLayout()
        self.llm_model_path_input = QLineEdit()
        self.llm_model_path_input.setPlaceholderText(
            tr('tmd_llm_path_placeholder')
        )
        current_llm_path = self.config.get_llm_translator_model_path()
        if current_llm_path:
            self.llm_model_path_input.setText(current_llm_path)

        browse_llm_btn = QPushButton(tr('browse'))
        browse_llm_btn.setFixedWidth(90)
        browse_llm_btn.clicked.connect(self.browse_llm_model_path)

        model_path_row.addWidget(self.llm_model_path_input)
        model_path_row.addWidget(browse_llm_btn)
        model_path_layout.addLayout(model_path_row)

        save_llm_path_btn = QPushButton(tr('save_path'))
        save_llm_path_btn.clicked.connect(self.save_llm_model_path)
        model_path_layout.addWidget(save_llm_path_btn)

        model_path_group.setLayout(model_path_layout)
        layout.addWidget(model_path_group)

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
        
        container = _section_container(T.section_blue)

        layout = QVBoxLayout(container)

        title_label = _section_title("Claude API (Sonnet 4)", T.accent)
        layout.addWidget(title_label)

        features = tr('tmd_feat_claude')
        features_label = QLabel(features)
        set_role(features_label, 'body')
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
        set_role(info_label, 'caption_gap')
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

        container = _section_container(T.section_orange)

        layout = QVBoxLayout(container)

        title_label = _section_title("OpenSubtitles AI", T.warn)
        layout.addWidget(title_label)

        features = tr('tmd_feat_os')
        features_label = QLabel(features)
        set_role(features_label, 'body')
        layout.addWidget(features_label)

        # Status credenziali
        self.os_status_label = QLabel()
        self.update_os_status()
        layout.addWidget(self.os_status_label)

        info_label = QLabel(tr('os_creds_info'))
        set_role(info_label, 'caption_top')
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
        # Il motore di traduzione "OpenSubtitles AI" è sempre REST e richiede
        # sempre l'api_key, indipendentemente da quale implementazione sia
        # selezionata per l'upload dei sottotitoli (che può essere xmlrpc).
        if self.config.is_opensubtitles_rest_configured():
            self.os_status_label.setText(tr('tmd_creds_configured'))
            _status_style(self.os_status_label, T.css_green, bold=True)
        else:
            self.os_status_label.setText(tr('tmd_creds_not_configured'))
            _status_style(self.os_status_label, T.css_orange)

    def create_model_section_openai(self):
        """Crea sezione OpenAI GPT"""
        radio = QRadioButton()
        radio.setObjectName("openai")

        container = _section_container(T.section_green)

        layout = QVBoxLayout(container)

        title_label = _section_title("OpenAI GPT", T.success)
        layout.addWidget(title_label)

        features = tr('tmd_feat_openai')
        features_label = QLabel(features)
        set_role(features_label, 'body')
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
        model_label = QLabel(tr('tmd_model_label'))
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
        set_role(info_label, 'caption_gap')
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
            QMessageBox.warning(self, tr('tmd_api_key_invalid_title'), err)
            return
        self.config.set_openai_api_key(key)
        self.config.set_openai_model(self.oai_model_combo.currentText())
        self.update_openai_status()
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))

    def update_openai_status(self):
        """Aggiorna indicatore stato OpenAI"""
        if self.config.is_openai_api_key_set():
            self.oai_status_label.setText(tr('tmd_creds_configured'))
            _status_style(self.oai_status_label, T.css_green, bold=True)
        else:
            self.oai_status_label.setText(tr('tmd_not_configured'))
            _status_style(self.oai_status_label, T.css_orange)

    def save_hf_token(self):
        """Salva token HuggingFace"""
        token = self.hf_token_input.text().strip()
        
        if not token:
            QMessageBox.warning(self, tr('token_empty'), tr('tmd_enter_valid_token'))
            return

        is_valid, error = self.config.validate_huggingface_token(token)

        if not is_valid:
            QMessageBox.warning(self, tr('tmd_token_invalid_title'), tr('tmd_token_invalid_msg').format(error=error))
            return

        self.config.set_huggingface_token(token)
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))
    
    def save_claude_api_key(self):
        """Salva API key Claude"""
        api_key = self.claude_api_input.text().strip()
        
        if not api_key:
            QMessageBox.warning(self, tr('save_api_key'), tr('tmd_enter_valid_api_key'))
            return

        is_valid, error = self.config.validate_claude_api_key(api_key)

        if not is_valid:
            QMessageBox.warning(self, tr('tmd_api_key_invalid_title'), tr('tmd_api_key_invalid_msg').format(error=error))
            return

        self.config.set_claude_api_key(api_key)
        self.update_claude_status()
        QMessageBox.information(self, tr('creds_saved_title'), tr('creds_saved_msg'))
    
    def update_claude_status(self):
        """Aggiorna indicatore stato Claude"""
        if self.config.is_claude_api_key_set():
            self.claude_status_label.setText(tr('tmd_creds_configured'))
            _status_style(self.claude_status_label, T.css_green, bold=True)
        else:
            self.claude_status_label.setText(tr('tmd_not_configured'))
            _status_style(self.claude_status_label, T.css_orange)
    
    def start_llm_download(self):
        """Avvia lo scaricamento del modello LLM in uso."""
        if not self.config.is_huggingface_token_set():
            QMessageBox.warning(
                self, 
                tr('tmd_token_missing_title'), 
                tr('tmd_save_hf_token_first')
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
            QMessageBox.information(self, tr('tmd_success'), tr('tmd_download_done'))
        else:
            detail = self._llm_last_line or tr('tmd_load_failed')
            QMessageBox.critical(self, tr('tmd_error'), f"[X] {detail}")
    
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
                    tr('tmd_api_key_missing_title'),
                    tr('tmd_claude_key_missing_ask'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return  # Rimani nel dialog
                else:
                    QMessageBox.warning(self, tr('tmd_attention'), tr('tmd_claude_needs_key'))

        elif self.nllb_ft_radio.isChecked():
            selected_model = 'nllb_finetuned'
            # Verifica che il path sia configurato
            if not self.config.is_nllb_finetuned_configured():
                reply = QMessageBox.question(
                    self,
                    tr('tmd_model_not_configured_title'),
                    tr('tmd_ft_path_missing_ask'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return  # Rimani nel dialog
                else:
                    QMessageBox.warning(
                        self, tr('tmd_attention'),
                        tr('tmd_ft_needs_path')
                    )

        elif self.os_radio.isChecked():
            selected_model = 'opensubtitles'
            # Motore di traduzione: sempre REST, richiede sempre l'api_key.
            if not self.config.is_opensubtitles_rest_configured():
                reply = QMessageBox.question(
                    self,
                    tr('tmd_creds_missing_title'),
                    tr('tmd_os_creds_missing_ask'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return

        elif self.oai_radio.isChecked():
            selected_model = 'openai'
            if not self.config.is_openai_api_key_set():
                reply = QMessageBox.question(
                    self,
                    tr('tmd_api_key_missing_title'),
                    tr('tmd_openai_key_missing_ask'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    return
                else:
                    QMessageBox.warning(self, tr('tmd_attention'), tr('tmd_openai_needs_key'))

        elif self.llm_radio.isChecked():
            selected_model = 'llm'
        else:
            selected_model = 'nllb'

        # Salva in config
        self.config.set_translation_model(selected_model)

        display_names = {
            'nllb': 'NLLB-200',
            'nllb_finetuned': 'NLLB-200 Fine-Tuned (Plex)',
            'llm': 'TranslateGemma_finetuned',
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
        container = _section_container(T.section_purple)

        layout = QVBoxLayout(container)

        title_label = _section_title(tr('diarization_title'), T.purple_title)
        layout.addWidget(title_label)

        desc_label = QLabel(tr('diarization_desc'))
        set_role(desc_label, 'body_tight')
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

        # URL allineati al modello davvero configurato (bug-check Opus):
        # community-1 impacchetta segmentation/embedding/plda nello stesso
        # repo (config.yaml verificato), 3.1 punta a repo HF separati —
        # senza questo la schermata manderebbe l'utente ad accettare le
        # condizioni del repo sbagliato se 'diarization_model' è cambiato.
        _diar_model = self.config.get('diarization_model', 'pyannote/speaker-diarization-3.1')
        _diar_urls = f"  • huggingface.co/{_diar_model}"
        if _diar_model == 'pyannote/speaker-diarization-3.1':
            _diar_urls += "\n  • huggingface.co/pyannote/segmentation-3.0"
        token_info = QLabel(
            tr('tmd_hf_token_howto').format(urls=_diar_urls)
        )
        set_role(token_info, 'caption')
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
        set_role(self.diarization_test_label, 'caption')
        layout.addWidget(self.diarization_test_label)

        # --- Forced Alignment ---
        self.forced_alignment_checkbox = QCheckBox(tr('forced_alignment_check'))
        self.forced_alignment_checkbox.setChecked(self.config.get('enable_forced_alignment', False))
        self.forced_alignment_checkbox.setToolTip(
            tr('tmd_align_tooltip')
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
            QMessageBox.warning(self, tr('token_empty'), tr('tmd_enter_valid_token'))
            return
        is_valid, error = self.config.validate_huggingface_token(token)
        if not is_valid:
            QMessageBox.warning(self, tr('tmd_token_invalid_title'), error)
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
            _status_style(self.diarization_token_status, T.css_green, bold=True, size=11)
        else:
            self.diarization_token_status.setText(tr('tmd_not_configured'))
            _status_style(self.diarization_token_status, T.css_orange, size=11)

    def test_pyannote_download(self):
        """Testa il download della pipeline pyannote con il token configurato"""
        token = self.config.get_huggingface_token()
        if not token:
            self.diarization_test_label.setText(tr('tmd_token_not_set_save_first'))
            _status_style(self.diarization_test_label, T.css_red, size=11)
            return

        # Il test gira in SUBPROCESS (core.env_check_cli): prima importava
        # torch+pyannote nel thread GUI congelando l'interfaccia per decine
        # di secondi. La GUI resta fluida e mostra le righe di progresso.
        if (getattr(self, '_diar_test_worker', None) is not None
                and self._diar_test_worker.isRunning()):
            return  # test già in corso

        self.diarization_test_label.setText(
            tr('tmd_diar_test_started'))
        _status_style(self.diarization_test_label, T.css_grey_555, size=11)

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
            else tr('tmd_no_test_output')
        self.diarization_test_label.setText(tail)
        color = T.css_green if exit_code == 0 else T.css_red
        _status_style(self.diarization_test_label, color, size=11)

    # ── Gender Correction ─────────────────────────────────────────────────

    def create_gender_correction_section(self) -> QWidget:
        """Crea sezione Gender Correction (EXPERIMENTAL)."""
        container = _section_container(T.section_red_orange)

        layout = QVBoxLayout(container)

        title_label = _section_title(tr('tmd_gender_title'), T.section_red_orange)
        layout.addWidget(title_label)

        desc_label = QLabel(tr('tmd_gender_desc'))
        set_role(desc_label, 'body_tight')
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # --- Stato prerequisiti (venv NLP + token HF) ---
        self.gender_env_status = QLabel()
        self._update_gender_env_status()
        layout.addWidget(self.gender_env_status)

        # --- Checkbox abilitazione ---
        self.gender_correction_checkbox = QCheckBox(
            tr('tmd_gender_enable')
        )
        self.gender_correction_checkbox.setChecked(
            self.config.get('gender_correction_enabled', False)
        )
        self.gender_correction_checkbox.toggled.connect(self._on_gender_correction_toggled)
        layout.addWidget(self.gender_correction_checkbox)

        # --- Checkbox 2ª persona ---
        self.gender_p2_checkbox = QCheckBox(
            tr('tmd_gender_p2')
        )
        self.gender_p2_checkbox.setChecked(
            self.config.get('gender_correction_second_person', True)
        )
        self.gender_p2_checkbox.toggled.connect(
            lambda c: self.config.set('gender_correction_second_person', c))
        layout.addWidget(self.gender_p2_checkbox)

        info_label = QLabel(tr('tmd_gender_info'))
        info_label.setStyleSheet(
            f"color: {T.warn}; font-size: 11px; font-style: italic; margin-top: 4px;"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        return container

    def _update_gender_env_status(self):
        """Verifica prerequisiti v2: venv NLP (spaCy) e token HuggingFace."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        from utils.platform_compat import venv_python
        cands = [self.config.get('gender_selector_python', ''),
                 venv_python(root / 'venv_nlp'),
                 venv_python(root / 'gender_eval' / '.venv_spacy')]
        nlp_ok = any(p and Path(p).exists() for p in cands)
        hf_ok = bool(self.config.get('huggingface_token', ''))
        if nlp_ok and hf_ok:
            self.gender_env_status.setText(tr('tmd_gender_prereq_ok'))
            _status_style(self.gender_env_status, T.css_green, bold=True, size=11)
        else:
            missing = []
            if not nlp_ok:
                missing.append(tr('tmd_gender_missing_nlp'))
            if not hf_ok:
                missing.append(tr('tmd_gender_missing_hf'))
            self.gender_env_status.setText(" — ".join(missing))
            _status_style(self.gender_env_status, T.css_red, size=11)

    def refresh_from_config(self):
        """Allinea la casella del genere al config (la scheda 'Opzioni job' delle Impostazioni puo' averla cambiata)."""
        cb = getattr(self, 'gender_correction_checkbox', None)
        if cb is not None:
            cb.blockSignals(True)
            cb.setChecked(bool(self.config.get('gender_correction_enabled', False)))
            cb.blockSignals(False)

    def _on_gender_correction_toggled(self, checked: bool):
        """Salva stato checkbox gender correction."""
        self.config.set('gender_correction_enabled', checked)

    # ── Force audio transcription ─────────────────────────────────────────

    def create_force_transcription_section(self) -> QWidget:
        """Crea sezione 'Forza trascrizione da audio'."""
        container = _section_container(T.section_blue)

        layout = QVBoxLayout(container)

        title_label = _section_title(tr('force_audio_title'), T.accent)
        layout.addWidget(title_label)

        self.force_audio_checkbox = QCheckBox(tr('force_audio_checkbox'))
        self.force_audio_checkbox.setChecked(
            self.config.get('force_audio_transcription', False)
        )
        self.force_audio_checkbox.toggled.connect(self._on_force_audio_toggled)
        layout.addWidget(self.force_audio_checkbox)

        info_label = QLabel(tr('force_audio_info'))
        set_role(info_label, 'caption_top')
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
