# -*- coding: utf-8 -*-
"""
GUI Main Window - VERSIONE INTEGRALE DEFINITIVA
Fix: Emoji Log + Colori UI + Selezione Poster Automatica
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QListWidget, QTextEdit, QProgressBar,
                             QFileDialog, QMessageBox, QCheckBox, QLabel,
                             QFrame, QToolButton, QSizePolicy, QLayout, QDialog)
from PyQt6.QtCore import Qt, QTimer, QSize, QMutex, QMutexLocker
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QTextCursor
import os
import subprocess
import re
from pathlib import Path
from datetime import datetime

from gui.widgets import ResourceMonitorWidget
from gui.workers import ProcessingWorker, PosterLoaderWorker
from gui.profile_dialog import ProfileSelectionDialog
from gui.translation_model_dialog import TranslationModelDialog
from gui.library_scanner_widget import LibraryScannerWidget
from gui.opensubtitles_settings_widget import OpenSubtitlesSettingsWidget
from utils.file_handler import FileHandler
from utils.logger import setup_logger
from utils.config import get_config
from utils.tmdb_client import get_tmdb_client

# Log setup
logger = setup_logger()

# Testi interfaccia
TEXTS = {
    'it': {
        'title': 'Transcriber Pro',
        'add_files': '📄 Aggiungi File',
        'add_folder': '📂 Aggiungi Cartella',
        'clear': '🗑️ Pulisci',
        'start': '▶️ Avvia',
        'stop': '⏸️ Ferma',
        'shutdown_when_done': '💤 Spegni al completamento',
        'files_to_process': 'Coda di elaborazione',
        'processing_log': 'Log di elaborazione',
        'compact_log': '📋 Log Sintetico',
        'enable_opensubtitles_upload': '📤 Upload OpenSubtitles',
        'select_videos': 'Seleziona file video',
        'select_folder': 'Seleziona cartella',
        'added': '✅ Aggiunto:',
        'added_during_processing': '➕ Aggiunto alla coda (in elaborazione):',
        'items_via_dragdrop': 'file tramite drag & drop',
        'confirm_exit': 'Conferma uscita',
        'processing_in_progress': 'Elaborazione in corso. Sei sicuro di voler uscire?',
        'error': 'Errore',
        'all_completed': '🎉 Elaborazione Completata',
        'all_files_processed': 'Tutti i file sono stati elaborati correttamente!',
        'no_preview': 'Nessuna anteprima\ndisponibile',
        'loading_preview': 'Caricamento\nanteprima...',
        'profile_settings': 'Impostazioni Profilo',
        'current_profile': 'Profilo:',
        'files_remaining': 'File rimanenti:',
    }
}

def get_text(key):
    return TEXTS['it'].get(key, key)

class RoundedLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                background-color: rgba(32, 32, 32, 180);
                border-radius: 12px;
                border: 2px solid rgba(255, 255, 255, 0.1);
                color: #888888;
                font-size: 10pt;
                padding: 20px;
            }
        """)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = get_config()
        self.processing_queue = []
        self.queue_mutex = QMutex() 
        self.is_processing = False
        self.worker = None
        self.file_handler = FileHandler()
        self.tmdb_client = get_tmdb_client()
        self.poster_loading = False
        self.last_loaded_file = None
        self.poster_worker = None
        self.compact_log_enabled = False
        self.resource_monitor = ResourceMonitorWidget()
        
        self.init_ui()
        self.apply_modern_theme()
        
        self.log_message("🎬 Transcriber Pro avviato")
        self.log_message(f"🎨 TMDB Client: {'✅ Attivo' if self.tmdb_client.api_key else '❌ Disattivo'}")
        
        current_profile = self.config.get_transcription_profile()
        profile_info = self.config.get_profile_info(current_profile)
        self.log_message(f"⚙️ Profilo attivo: {profile_info['name']}")
        
        self.resource_monitor.start_monitoring()
    
    def init_ui(self):
        self.setWindowTitle(get_text('title'))
        self.resize(1400, 900)
        self.setMinimumSize(QSize(1100, 700))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        left_panel = self.create_left_panel()
        center_panel = self.create_center_panel()
        right_panel = self.create_right_panel()
        
        left_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        main_layout.addWidget(left_panel, stretch=2)
        main_layout.addWidget(center_panel, stretch=3)
        main_layout.addWidget(right_panel, stretch=3)
        
        central_widget.setLayout(main_layout)
        self.setAcceptDrops(True)
    
    def create_left_panel(self):
        panel = QFrame()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        header_layout = QHBoxLayout()
        title = QLabel(get_text('files_to_process'))
        title.setObjectName("panelTitle")
        header_layout.addWidget(title)
        
        self.profile_indicator = QLabel()
        self.profile_indicator.setObjectName("profileIndicator")
        self.update_profile_indicator()
        header_layout.addWidget(self.profile_indicator)
        header_layout.addStretch()
        
        self.remaining_files_label = QLabel("")
        self.remaining_files_label.setObjectName("remainingFilesLabel")
        self.remaining_files_label.setFixedSize(180, 28)
        header_layout.addWidget(self.remaining_files_label)
        
        self.translation_model_btn = QToolButton()
        self.translation_model_btn.setText("🌐")
        self.translation_model_btn.setFixedSize(32, 32)
        self.translation_model_btn.clicked.connect(self.open_translation_model_settings)
        header_layout.addWidget(self.translation_model_btn)

        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙️")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.clicked.connect(self.open_profile_settings)
        header_layout.addWidget(self.settings_btn)
        
        layout.addLayout(header_layout)
        
        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        layout.addWidget(self.file_list)
        
        buttons_layout = QHBoxLayout()
        self.add_files_btn = QPushButton(get_text('add_files'))
        self.add_files_btn.setObjectName("primaryButton")
        self.add_files_btn.clicked.connect(self.add_files)
        
        self.add_folder_btn = QPushButton(get_text('add_folder'))
        self.add_folder_btn.setObjectName("primaryButton")
        self.add_folder_btn.clicked.connect(self.add_folder)
        
        self.clear_btn = QPushButton(get_text('clear'))
        self.clear_btn.setObjectName("primaryButton")
        self.clear_btn.clicked.connect(self.clear_queue)
        
        buttons_layout.addWidget(self.add_files_btn)
        buttons_layout.addWidget(self.add_folder_btn)
        buttons_layout.addWidget(self.clear_btn)
        layout.addLayout(buttons_layout)
        
        options_layout = QVBoxLayout()
        self.shutdown_checkbox = QCheckBox(get_text('shutdown_when_done'))
        self.shutdown_checkbox.setObjectName("modernCheckbox")
        self.shutdown_checkbox.setChecked(self.config.get('shutdown_after_processing', False))
        self.shutdown_checkbox.stateChanged.connect(self.on_shutdown_checkbox_changed)
        
        self.opensubtitles_checkbox = QCheckBox(get_text('enable_opensubtitles_upload'))
        self.opensubtitles_checkbox.setObjectName("modernCheckbox")
        self.opensubtitles_checkbox.setChecked(self.config.get('opensubtitles_upload_enabled', True))
        self.opensubtitles_checkbox.stateChanged.connect(self.on_opensubtitles_checkbox_changed)

        self.opensubtitles_settings_btn = QToolButton()
        self.opensubtitles_settings_btn.setText("⚙️")
        self.opensubtitles_settings_btn.setFixedSize(24, 24)
        self.opensubtitles_settings_btn.setToolTip("Credenziali e impostazioni OpenSubtitles")
        self.opensubtitles_settings_btn.clicked.connect(self.open_opensubtitles_settings)

        os_row = QHBoxLayout()
        os_row.setSpacing(4)
        os_row.addWidget(self.opensubtitles_checkbox)
        os_row.addWidget(self.opensubtitles_settings_btn)
        os_row.addStretch()

        options_layout.addWidget(self.shutdown_checkbox)
        options_layout.addLayout(os_row)
        layout.addLayout(options_layout)

        # Library Scanner Widget
        self.library_scanner = LibraryScannerWidget(main_window=self)
        layout.addWidget(self.library_scanner)

        control_layout = QHBoxLayout()
        self.start_btn = QPushButton(get_text('start'))
        self.start_btn.setObjectName("startButton")
        self.start_btn.clicked.connect(self.start_processing)
        
        self.stop_btn = QPushButton(get_text('stop'))
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_processing)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        layout.addLayout(control_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("modernProgress")
        layout.addWidget(self.progress_bar)
        
        return panel
    
    def create_center_panel(self):
        panel = QFrame()
        panel.setObjectName("centerPanel")
        layout = QVBoxLayout(panel)
        self.poster_label = RoundedLabel()
        self.poster_label.setText("🎬\n\n" + get_text('no_preview'))
        self.poster_label.setMinimumHeight(400)
        layout.addWidget(self.poster_label, stretch=3)
        layout.addWidget(self.resource_monitor, stretch=2)
        return panel
    
    def create_right_panel(self):
        panel = QFrame()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        header_layout = QHBoxLayout()
        title = QLabel(get_text('processing_log'))
        title.setObjectName("panelTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self.compact_log_checkbox = QCheckBox(get_text('compact_log'))
        self.compact_log_checkbox.setObjectName("modernCheckbox")
        self.compact_log_checkbox.stateChanged.connect(self.on_compact_log_changed)
        header_layout.addWidget(self.compact_log_checkbox)
        layout.addLayout(header_layout)
        self.log_text = QTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        return panel

    def fix_mojibake(self, text):
        """Ripara le emoji e rimuove caratteri sporchi residui"""
        if not text: return text
        try:
            # Tenta riparazione encoding
            if any(c in text for c in ['ð', 'â', 'ï', 'œ', '™']):
                text = text.encode('cp1252').decode('utf-8')
        except:
            try:
                text = text.encode('latin-1').decode('utf-8')
            except:
                pass
        # Rimuove glifi corrotti residui mantenendo le emoji buone
        text = re.sub(r'[ðâïœ™]+', '', text)
        return text.strip()

    def log_message(self, message: str):
        message = self.fix_mojibake(message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"

        if "Progresso:" in message:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            block = cursor.block()
            if "Progresso:" in block.text():
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                    QTextCursor.MoveMode.KeepAnchor)
                cursor.insertText(formatted)
                self.log_text.setTextCursor(cursor)
            else:
                self.log_text.append(formatted)
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )
        elif not self.compact_log_enabled or any(k in message for k in ['✅', '⚙️', '🎉', '❌', '➕', '🎬']):
            self.log_text.append(formatted)

    def on_file_selected(self):
        if self.file_list.currentRow() >= 0:
            name = self.file_list.currentItem().text()
            path = next((p for p in self.processing_queue if Path(p).name == name), None)
            if path: self.load_poster(path)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, get_text('select_videos'), self.config.get('last_input_folder', ''), "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v)")
        if files:
            self.config.set('last_input_folder', str(Path(files[0]).parent))
            with QMutexLocker(self.queue_mutex):
                for f in files:
                    if f not in self.processing_queue:
                        self.processing_queue.append(f)
                        self.file_list.addItem(Path(f).name)
            self.update_remaining_files_label()
            self.file_list.setCurrentRow(self.file_list.count() - 1)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, get_text('select_folder'), self.config.get('last_input_folder', ''))
        if folder:
            self.config.set('last_input_folder', folder)
            exts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
            with QMutexLocker(self.queue_mutex):
                for f_path in Path(folder).rglob('*'):
                    if f_path.suffix.lower() in exts and str(f_path) not in self.processing_queue:
                        self.processing_queue.append(str(f_path))
                        self.file_list.addItem(f_path.name)
            self.update_remaining_files_label()
            if self.file_list.count() > 0:
                self.file_list.setCurrentRow(self.file_list.count() - 1)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        with QMutexLocker(self.queue_mutex):
            for url in event.mimeData().urls():
                f_path = url.toLocalFile()
                if Path(f_path).is_file() and f_path not in self.processing_queue:
                    self.processing_queue.append(f_path)
                    self.file_list.addItem(Path(f_path).name)
        self.update_remaining_files_label()
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(self.file_list.count() - 1)

    def load_poster(self, video_path: str):
        if video_path == self.last_loaded_file: return
        if self.poster_worker and self.poster_worker.isRunning():
            self.poster_worker.cancel()
            self.poster_worker.wait(500)
        self.last_loaded_file = video_path
        self.poster_label.setText("\n\n" + get_text('loading_preview'))
        self.poster_worker = PosterLoaderWorker(video_path, self.tmdb_client)
        self.poster_worker.poster_loaded.connect(self._on_poster_loaded)
        self.poster_worker.poster_failed.connect(self._on_poster_failed)
        self.poster_worker.start()

    def _on_poster_loaded(self, pixmap):
        if pixmap and not pixmap.isNull():
            self.poster_label.setPixmap(pixmap.scaled(self.poster_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else: self._on_poster_failed()

    def _on_poster_failed(self):
        self.poster_label.setText("❌\n\n" + get_text('no_preview'))

    def start_processing(self):
        if not self.processing_queue: return
        self.is_processing = True
        self.worker = ProcessingWorker(self.processing_queue, self.queue_mutex)
        self.worker.progress.connect(self.update_progress)
        self.worker.log_message.connect(self.log_message)
        self.worker.finished.connect(self.processing_finished)
        self.worker.file_completed.connect(self.on_file_completed)
        self.worker.queue_updated.connect(self.on_queue_updated) 
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_btn.setEnabled(False)
        self.worker.start()

    def stop_processing(self):
        if self.worker: self.worker.is_cancelled = True

    def on_file_completed(self, file_path: str):
        file_name = Path(file_path).name
        items = self.file_list.findItems(file_name, Qt.MatchFlag.MatchExactly)
        for item in items:
            self.file_list.takeItem(self.file_list.row(item))
            break
        self.update_remaining_files_label()

    def on_queue_updated(self, total: int):
        self.update_remaining_files_label()

    def update_remaining_files_label(self):
        with QMutexLocker(self.queue_mutex):
            remaining = len(self.processing_queue)
        self.remaining_files_label.setText(f"📊 {get_text('files_remaining')} {remaining}" if self.is_processing else "")

    def processing_finished(self):
        self.is_processing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_btn.setEnabled(True)
        self.log_message("🎉 Elaborazione Completata")
        if self.shutdown_checkbox.isChecked():
            QTimer.singleShot(5000, self.shutdown_system)

    def shutdown_system(self):
        cmd = ['shutdown', '/s', '/t', '60'] if os.name == 'nt' else ['shutdown', '-h', '+1']
        subprocess.run(cmd)

    def update_progress(self, value: int):
        self.progress_bar.setValue(value)

    def open_profile_settings(self):
        dialog = ProfileSelectionDialog(self)
        if dialog.exec():
            selected_profile = dialog.get_selected_profile()
            if selected_profile:
                self.config.set_transcription_profile(selected_profile)
                self.update_profile_indicator()
                self.log_message(f"⚙️ Profilo cambiato: {selected_profile}")

    def open_opensubtitles_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("OpenSubtitles — Credenziali e Impostazioni")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet("""
            QDialog, QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QLabel { color: #cccccc; }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                color: #ffffff;
                padding: 4px 8px;
            }
            QLineEdit:focus { border: 1px solid rgba(33,150,243,0.6); }
            QCheckBox { color: #ffffff; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 3px;
                background-color: #2a2a2a;
            }
            QCheckBox::indicator:checked { background-color: #2196F3; border-color: #2196F3; }
            QPushButton {
                background-color: rgba(33,150,243,200);
                border: none;
                border-radius: 6px;
                color: white;
                padding: 7px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(33,150,243,255); }
            QPushButton:disabled { background-color: rgba(60,60,60,150); color: rgba(255,255,255,80); }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        widget = OpenSubtitlesSettingsWidget(parent=dialog)
        layout.addWidget(widget)
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def open_translation_model_settings(self):
        dialog = TranslationModelDialog(self)
        if dialog.exec():
            selected_model = dialog.get_selected_model()
            if selected_model:
                self.config.set_translation_model(selected_model)
                self.log_message(f"🌐 Modello traduzione cambiato: {selected_model}")

    def update_profile_indicator(self):
        current_profile = self.config.get_transcription_profile()
        profile_info = self.config.get_profile_info(current_profile)
        self.profile_indicator.setText(f"⚙️ {profile_info['name']}")

    def clear_queue(self):
        if self.is_processing: return
        with QMutexLocker(self.queue_mutex):
            self.processing_queue.clear()
            self.file_list.clear()
        self.poster_label.setText("🎬\n\n" + get_text('no_preview'))

    def on_shutdown_checkbox_changed(self, state):
        self.config.set('shutdown_after_processing', state == Qt.CheckState.Checked.value)
    
    def on_opensubtitles_checkbox_changed(self, state):
        self.config.set('opensubtitles_upload_enabled', state == Qt.CheckState.Checked.value)
    
    def on_compact_log_changed(self, state):
        self.compact_log_enabled = state == Qt.CheckState.Checked.value

    def closeEvent(self, event):
        if self.is_processing:
            reply = QMessageBox.question(self, "Conferma", "Elaborazione in corso. Uscire?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes: event.accept()
            else: event.ignore()
        else: event.accept()

    def apply_modern_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QFrame#leftPanel, QFrame#centerPanel, QFrame#rightPanel {
                background-color: rgba(32, 32, 32, 180); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.1); padding: 15px;
            }
            QLabel { color: #ffffff; }
            QLabel#panelTitle { font-size: 11pt; font-weight: bold; }
            
            /* Coda file - TESTO BIANCO */
            QListWidget#fileList {
                background-color: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px; color: #ffffff; padding: 5px; font-size: 9pt;
            }
            QListWidget#fileList::item { color: #ffffff; }
            QListWidget#fileList::item:selected { background-color: rgba(33, 150, 243, 0.3); color: #ffffff; }

            /* Checkbox - TESTO BIANCO */
            QCheckBox#modernCheckbox { color: #ffffff; spacing: 8px; font-size: 9pt; }
            QCheckBox#modernCheckbox::indicator { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.3); border-radius: 4px; }
            QCheckBox#modernCheckbox::indicator:checked { background-color: #2196F3; }

            /* Messaggi di conferma - TESTO NERO */
            QMessageBox QLabel { color: #000000; }
            QMessageBox QPushButton { color: #000000; min-width: 80px; }

            QPushButton#primaryButton {
                background-color: #2196F3; border: none; border-radius: 8px; color: #ffffff;
                padding: 10px; font-weight: bold; font-size: 9pt;
            }
            QPushButton#startButton { background-color: #4CAF50; border-radius: 8px; color: white; padding: 12px; font-weight: bold; }
            QPushButton#stopButton { background-color: #f44336; border-radius: 8px; color: white; padding: 12px; font-weight: bold; }
            
            QProgressBar#modernProgress {
                border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px;
                background-color: rgba(0, 0, 0, 0.3); text-align: center; color: white;
            }
            QProgressBar#modernProgress::chunk { background-color: #2196F3; border-radius: 7px; }
            QTextEdit#logText { background-color: rgba(0, 0, 0, 0.5); color: #ffffff; font-family: 'Consolas', monospace; }
            QToolButton { background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; color: white; }
        """)