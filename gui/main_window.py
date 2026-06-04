# -*- coding: utf-8 -*-
"""
GUI Main Window - VERSIONE INTEGRALE DEFINITIVA
Fix: Emoji Log + Colori UI + Selezione Poster Automatica
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QListWidget, QTextEdit, QProgressBar,
                             QFileDialog, QMessageBox, QCheckBox, QLabel,
                             QFrame, QToolButton, QSizePolicy, QLayout, QDialog,
                             QComboBox, QSplitter, QMenu, QTabBar, QStackedWidget,
                             QGraphicsOpacityEffect)
from PyQt6.QtCore import (Qt, QTimer, QSize, QMutex, QMutexLocker,
                          QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QTextCursor, QAction
import os
import subprocess
import re
import time
import html as _html
from pathlib import Path
from datetime import datetime

from gui.widgets import ResourceMonitorWidget, ElideLabel
from gui.icons import svg_icon
from gui.workers import ProcessingWorker, PosterLoaderWorker
from gui.profile_dialog import ProfileSelectionDialog
from gui.translation_model_dialog import TranslationModelDialog
from gui.library_scanner_widget import LibraryScannerWidget
from gui.opensubtitles_settings_widget import OpenSubtitlesSettingsWidget
from gui.adaptive_batch_settings_widget import AdaptiveBatchSettingsWidget, DIALOG_STYLE
from gui.general_settings_widget import GeneralSettingsWidget
from gui.settings_dialog import (
    SettingsDialog,
    TAB_GENERAL, TAB_TRANSCRIPTION, TAB_TRANSLATION, TAB_BATCH, TAB_OPENSUBTITLES,
)
from gui.collapsible_card import CollapsibleCard
from gui.job_options_card import JobOptionsCard
from gui.file_row_delegate import FileRowDelegate
from gui.segmented_filter import SegmentedFilter
from utils.file_handler import FileHandler
from utils.logger import setup_logger
from utils.config import get_config
from utils.tmdb_client import get_tmdb_client
from utils.translations import tr

# Log setup
logger = setup_logger()

SUBTITLE_LANGUAGES = [
    ("Italiano",             "ita"),
    ("Inglese",              "eng"),
    ("Francese",             "fra"),
    ("Spagnolo",             "spa"),
    ("Tedesco",              "deu"),
    ("Portoghese",           "por"),
    ("Russo",                "rus"),
    ("Giapponese",           "jpn"),
    ("Cinese Semplificato",  "zho"),
    ("Arabo",                "ara"),
    ("Coreano",              "kor"),
    ("Olandese",             "nld"),
    ("Polacco",              "pol"),
    ("Turco",                "tur"),
]


class RoundedLabel(QLabel):
    """
    QLabel con paintEvent custom: il background arrotondato viene disegnato
    solo nell'area occupata dall'immagine, lasciando il resto trasparente.
    In modalità testo (nessun pixmap) riempie tutto il widget.
    """

    _BG    = (32, 32, 32, 180)
    _BORD  = (255, 255, 255, 26)
    _RADIU = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig_pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Stile solo per la modalità testo (text/color ereditati dal tema)
        self.setStyleSheet(
            "QLabel { color: #888888; font-size: 10pt; background: transparent; }"
        )

    def minimumSizeHint(self):
        return QSize(80, 80)

    def setPixmap(self, px):
        self._orig_pixmap = px
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._orig_pixmap and not self._orig_pixmap.isNull():
            scaled = self._orig_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ix = (self.width()  - scaled.width())  // 2
            iy = (self.height() - scaled.height()) // 2
            iw, ih = scaled.width(), scaled.height()

            path = QPainterPath()
            path.addRoundedRect(ix, iy, iw, ih, self._RADIU, self._RADIU)
            p.fillPath(path, QColor(*self._BG))
            p.setClipPath(path)
            p.drawPixmap(ix, iy, scaled)
            p.setClipping(False)
            p.setPen(QPen(QColor(*self._BORD), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ix + 1, iy + 1, iw - 2, ih - 2, self._RADIU - 1, self._RADIU - 1)
        else:
            # Modalità testo: background su tutto il widget
            r = self._RADIU
            path = QPainterPath()
            path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, r, r)
            p.fillPath(path, QColor(*self._BG))
            p.setPen(QPen(QColor(*self._BORD), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, r, r)
            p.end()
            super().paintEvent(event)  # disegna il testo sopra
            return

        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

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

        # Stato per log stats / diagnostic panel
        self._proc_start_time: float = 0.0
        self._completed_count: int = 0
        self._error_count: int = 0
        self._proc_elapsed_timer = None

        self.init_ui()
        self.apply_modern_theme()

        self.log_message(tr('app_started'))
        self.log_message(f"🎨 TMDB Client: {'✅ Attivo' if self.tmdb_client.api_key else '❌ Disattivo'}")

        current_profile = self.config.get_transcription_profile()
        self.log_message(f"⚙️ Profilo attivo: {tr(f'profile_{current_profile}_name')}")

        self.resource_monitor.start_monitoring()
    
    def init_ui(self):
        self.setWindowTitle(tr('window_title'))
        self.resize(1400, 900)
        self.setMinimumSize(QSize(1100, 700))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        outer_layout = QVBoxLayout()
        outer_layout.setSpacing(0)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Mini-titlebar con singolo pulsante settings a destra
        outer_layout.addWidget(self._create_mini_titlebar())

        # Splitter orizzontale per i 3 panel
        left_panel = self.create_left_panel()
        center_panel = self.create_center_panel()
        right_panel = self.create_right_panel()

        for p in (left_panel, center_panel, right_panel):
            p.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(center_panel)
        self.main_splitter.addWidget(right_panel)

        # Ripristina dimensioni salvate, altrimenti default 2:3:3
        saved_sizes = self.config.get('ui_splitter_sizes', None)
        if isinstance(saved_sizes, list) and len(saved_sizes) == 3 and all(
            isinstance(x, int) and x > 0 for x in saved_sizes
        ):
            self.main_splitter.setSizes(saved_sizes)
        else:
            total = max(self.width(), 1400)
            self.main_splitter.setSizes([
                int(total * 2 / 8), int(total * 3 / 8), int(total * 3 / 8),
            ])
        self.main_splitter.splitterMoved.connect(self._on_splitter_moved)

        # Wrapper con padding intorno allo splitter
        splitter_wrap = QWidget()
        splitter_wrap_layout = QHBoxLayout(splitter_wrap)
        splitter_wrap_layout.setContentsMargins(15, 12, 15, 15)
        splitter_wrap_layout.setSpacing(0)
        splitter_wrap_layout.addWidget(self.main_splitter)

        # Tab bar principale (Coda / Cronologia)
        self.main_tab_bar = self._create_tab_bar()
        outer_layout.addWidget(self.main_tab_bar)

        # QStackedWidget: 0=coda (splitter_wrap), 1=cronologia
        from gui.history_widget import HistoryWidget
        self.history_widget = HistoryWidget()
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(splitter_wrap)
        self.main_stack.addWidget(self.history_widget)
        self.main_tab_bar.currentChanged.connect(self._on_tab_changed)

        outer_layout.addWidget(self.main_stack, stretch=1)

        # Aggiorna badge Cronologia con il totale già caricato da history.json
        QTimer.singleShot(0, self._update_history_badge)

        central_widget.setLayout(outer_layout)
        self.setAcceptDrops(True)

    def _create_mini_titlebar(self) -> QFrame:
        """Titlebar espansa: brand sinistra · status pill centro · profilo+settings destra."""
        bar = QFrame()
        bar.setObjectName("miniTitleBar")
        bar.setFixedHeight(52)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 0, 12, 0)
        layout.setSpacing(12)

        # ── SINISTRA: brand ──────────────────────────────────────────────
        brand_widget = QWidget()
        brand_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        brand_lay = QHBoxLayout(brand_widget)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(6)

        mark = QLabel("◈")
        mark.setObjectName("titleBarMark")
        brand_name = QLabel("Transcriber Pro")
        brand_name.setObjectName("titleBarBrand")
        sep = QFrame()
        sep.setObjectName("titleBarSep")
        sep.setFixedSize(1, 16)
        brand_subtitle = QLabel("AI Subtitle Processor")
        brand_subtitle.setObjectName("titleBarSubtitle")

        brand_lay.addWidget(mark)
        brand_lay.addWidget(brand_name)
        brand_lay.addWidget(sep)
        brand_lay.addWidget(brand_subtitle)
        layout.addWidget(brand_widget)

        layout.addStretch(1)

        # ── CENTRO: status pill ──────────────────────────────────────────
        status_pill = QFrame()
        status_pill.setObjectName("statusPill")
        status_lay = QHBoxLayout(status_pill)
        status_lay.setContentsMargins(10, 4, 10, 4)
        status_lay.setSpacing(6)

        self._status_dot = QFrame()
        self._status_dot.setObjectName("statusDot")
        self._status_dot.setFixedSize(8, 8)

        self._status_dot_effect = QGraphicsOpacityEffect(self._status_dot)
        self._status_dot.setGraphicsEffect(self._status_dot_effect)

        fade_out = QPropertyAnimation(self._status_dot_effect, b"opacity")
        fade_out.setDuration(700)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.2)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutSine)

        fade_in = QPropertyAnimation(self._status_dot_effect, b"opacity")
        fade_in.setDuration(700)
        fade_in.setStartValue(0.2)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._status_dot_anim_group = QSequentialAnimationGroup()
        self._status_dot_anim_group.addAnimation(fade_out)
        self._status_dot_anim_group.addAnimation(fade_in)
        self._status_dot_anim_group.setLoopCount(-1)

        self._status_label = QLabel("Pronto")
        self._status_label.setObjectName("titleBarStatusLabel")

        status_lay.addWidget(self._status_dot)
        status_lay.addWidget(self._status_label)
        layout.addWidget(status_pill)

        layout.addStretch(1)

        # ── DESTRA: profilo + settings ───────────────────────────────────
        self.profile_button = QPushButton()
        self.profile_button.setObjectName("profileButton")
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)

        profile_menu = QMenu(self.profile_button)
        profile_menu.setObjectName("profileMenu")
        for pk in ('fast', 'balanced', 'quality', 'maximum', 'batch'):
            action = QAction(tr(f'profile_{pk}_name'), profile_menu)
            action.triggered.connect(
                lambda checked=False, _pk=pk: self._on_profile_selected(_pk)
            )
            profile_menu.addAction(action)
        self.profile_button.setMenu(profile_menu)

        self.profile_indicator = self.profile_button  # backward-compat alias

        self.sync_btn = QToolButton()
        self.sync_btn.setObjectName("titleBarSyncBtn")
        self.sync_btn.setText('')
        self.sync_btn.setIcon(svg_icon('sync', 18, '#9095a0'))
        self.sync_btn.setIconSize(QSize(18, 18))
        self.sync_btn.setFixedSize(32, 32)
        self.sync_btn.setToolTip(tr('sync_dialog_title'))
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.clicked.connect(self._open_sync_dialog)

        layout.addWidget(self.sync_btn)

        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("titleBarSettingsBtn")
        self.settings_btn.setText('')
        self.settings_btn.setIcon(svg_icon('settings', 18, '#9095a0'))
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setToolTip(tr('settings_dialog_title'))
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings_dialog)

        layout.addWidget(self.settings_btn)

        self.update_profile_indicator()
        return bar

    def open_settings_dialog(self, initial_tab: str | None = None):
        """Apre il SettingsDialog unificato sulla tab indicata (default: ultima usata)."""
        prev_profile = self.config.get_transcription_profile()
        prev_model = self.config.get_translation_model()

        dialog = SettingsDialog(self, initial_tab=initial_tab)
        dialog.exec()

        # Aggiorna indicatori — incondizionale per evitare race condition embed
        self._diag_modello._val.setText(
            tr(f"profile_{self.config.get_transcription_profile()}_name")
        )
        self._diag_traduttore._val.setText(self.config.get_translation_model())

        # Sync checkbox upload OS (può essere cambiato dal settings dialog)
        self.opensubtitles_checkbox.blockSignals(True)
        self.opensubtitles_checkbox.setChecked(
            self.config.get('opensubtitles_upload_enabled', True)
        )
        self.opensubtitles_checkbox.blockSignals(False)

        if self.config.get_transcription_profile() != prev_profile:
            self.update_profile_indicator()
            self.log_message(
                f"⚙️ Profilo cambiato: {self.config.get_transcription_profile()}"
            )

        new_model = self.config.get_translation_model()
        if new_model != prev_model:
            self.log_message(tr('translation_model_changed').format(model=new_model))

    def _on_splitter_moved(self, *_args):
        try:
            sizes = self.main_splitter.sizes()
            if all(s > 0 for s in sizes):
                self.config.set('ui_splitter_sizes', list(sizes))
        except Exception:
            pass
    
    def create_left_panel(self):
        panel = QFrame()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        remaining_header = QHBoxLayout()
        remaining_header.addStretch()
        self.remaining_files_label = QLabel("")
        self.remaining_files_label.setObjectName("remainingFilesLabel")
        self.remaining_files_label.setVisible(False)
        remaining_header.addWidget(self.remaining_files_label)
        layout.addLayout(remaining_header)
        
        self.segmented_filter = SegmentedFilter()
        self.segmented_filter.filter_changed.connect(self._apply_filter)
        layout.addWidget(self.segmented_filter)

        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setItemDelegate(FileRowDelegate(self.file_list))
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        # Il testo è già eliso dal delegato: la scrollbar orizzontale non serve
        # e nasconderla evita jitter da apparizione/scomparsa nel layout.
        self.file_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.file_list)
        
        buttons_layout = QHBoxLayout()
        self.add_files_btn = QPushButton(tr('add_files'))
        self.add_files_btn.setObjectName("primaryButton")
        self.add_files_btn.setIcon(svg_icon('plus', 14, '#9095a0'))
        self.add_files_btn.setIconSize(QSize(14, 14))
        self.add_files_btn.clicked.connect(self.add_files)

        self.add_folder_btn = QPushButton(tr('add_folder'))
        self.add_folder_btn.setObjectName("primaryButton")
        self.add_folder_btn.setIcon(svg_icon('folder', 14, '#9095a0'))
        self.add_folder_btn.setIconSize(QSize(14, 14))
        self.add_folder_btn.clicked.connect(self.add_folder)

        self.clear_btn = QPushButton(tr('clear_queue'))
        self.clear_btn.setObjectName("primaryButton")
        self.clear_btn.setIcon(svg_icon('trash', 14, '#9095a0'))
        self.clear_btn.setIconSize(QSize(14, 14))
        self.clear_btn.clicked.connect(self.clear_queue)
        
        buttons_layout.addWidget(self.add_files_btn)
        buttons_layout.addWidget(self.add_folder_btn)
        buttons_layout.addWidget(self.clear_btn)
        layout.addLayout(buttons_layout)
        
        # Job Options Card (collassabile, raggruppa lang/os/gender/shutdown)
        self.job_options_card = JobOptionsCard()
        # Alias attributi pubblici per non rompere le API esterne
        self.target_lang_combo = self.job_options_card.target_lang_combo
        self.opensubtitles_checkbox = self.job_options_card.opensubtitles_checkbox
        self.gender_correction_checkbox = self.job_options_card.gender_correction_checkbox
        self.shutdown_checkbox = self.job_options_card.shutdown_checkbox
        layout.addWidget(self.job_options_card)

        # Library Scanner Widget (avvolto in CollapsibleCard)
        self.library_scanner = LibraryScannerWidget(main_window=self)
        self.library_scanner_card = CollapsibleCard(title=tr('library_scanner_title'))
        self.library_scanner_card.setBody(self.library_scanner)
        self.library_scanner.set_embedded(True)
        # Inietta status dot e refresh button nell'header del card
        self.library_scanner_card.addHeaderWidget(self.library_scanner.status_dot)
        self.library_scanner_card.addHeaderWidget(self.library_scanner.refresh_btn)
        # Propaga stato connessione come summary del card
        self.library_scanner_card.setSummary("Inattivo")
        self.library_scanner.status_changed.connect(self.library_scanner_card.setSummary)
        scanner_open = bool(self.config.get('ui_scanner_card_open', False))
        self.library_scanner_card.setExpanded(scanner_open, animated=False)
        self.library_scanner_card.toggled.connect(
            lambda v: self.config.set('ui_scanner_card_open', v)
        )
        layout.addWidget(self.library_scanner_card)

        control_layout = QHBoxLayout()
        self.start_btn = QPushButton(tr('start'))
        self.start_btn.setObjectName("startButton")
        self.start_btn.setIcon(svg_icon('play', 15, '#1f2126'))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.clicked.connect(self.start_processing)

        self.stop_btn = QPushButton(tr('stop'))
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setIcon(svg_icon('stop', 15, '#f5f6f8'))
        self.stop_btn.setIconSize(QSize(15, 15))
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header: "Anteprima" + filename pill
        preview_header = QFrame()
        preview_header.setObjectName("previewHeader")
        hlay = QHBoxLayout(preview_header)
        hlay.setContentsMargins(14, 10, 14, 8)
        hlay.setSpacing(8)
        hdr_title = QLabel("Anteprima")
        hdr_title.setObjectName("panelTitle")
        hlay.addWidget(hdr_title)
        self.preview_filename_pill = ElideLabel()
        self.preview_filename_pill.setObjectName("previewFilenamePill")
        self.preview_filename_pill.setVisible(False)
        hlay.addWidget(self.preview_filename_pill)
        hlay.addStretch()
        layout.addWidget(preview_header)

        # Poster stage: poster + info strip in basso
        poster_stage = QFrame()
        poster_stage.setObjectName("posterStage")
        stage_lay = QVBoxLayout(poster_stage)
        stage_lay.setContentsMargins(0, 0, 0, 0)
        stage_lay.setSpacing(0)

        self.poster_label = RoundedLabel()
        self.poster_label.setText("🎬\n\n" + tr('no_preview'))
        self.poster_label.setMinimumHeight(200)
        stage_lay.addWidget(self.poster_label, stretch=1)

        # Info strip (nascosta di default, mostrata su file selezionato)
        self._info_strip = QFrame()
        self._info_strip.setObjectName("posterInfoStrip")
        self._info_strip.setVisible(False)
        strip_lay = QVBoxLayout(self._info_strip)
        strip_lay.setContentsMargins(12, 8, 12, 10)
        strip_lay.setSpacing(4)

        pills_row = QHBoxLayout()
        self._overlay_lang_pill = QLabel()
        self._overlay_lang_pill.setObjectName("overlayLangPill")
        self._overlay_status_pill = QLabel()
        self._overlay_status_pill.setObjectName("overlayStatusPill")
        pills_row.addWidget(self._overlay_lang_pill)
        pills_row.addStretch()
        pills_row.addWidget(self._overlay_status_pill)
        strip_lay.addLayout(pills_row)

        self._overlay_title = ElideLabel()
        self._overlay_title.setObjectName("overlayTitle")
        strip_lay.addWidget(self._overlay_title)

        self._overlay_meta = QLabel()
        self._overlay_meta.setObjectName("overlayMeta")
        strip_lay.addWidget(self._overlay_meta)

        self._overlay_progress = QProgressBar()
        self._overlay_progress.setObjectName("overlayProgress")
        self._overlay_progress.setTextVisible(False)
        self._overlay_progress.setFixedHeight(4)
        self._overlay_progress.setValue(0)
        strip_lay.addWidget(self._overlay_progress)

        stage_lay.addWidget(self._info_strip)

        # Splitter verticale: poster stage / resource monitor
        center_splitter = QSplitter(Qt.Orientation.Vertical)
        center_splitter.setObjectName("centerSplitter")
        center_splitter.setChildrenCollapsible(False)
        center_splitter.addWidget(poster_stage)
        center_splitter.addWidget(self.resource_monitor)

        saved = self.config.get('ui_center_split', None)
        if isinstance(saved, list) and len(saved) == 2:
            center_splitter.setSizes(saved)
        else:
            center_splitter.setSizes([450, 200])
        center_splitter.splitterMoved.connect(
            lambda: self.config.set('ui_center_split', center_splitter.sizes())
        )

        layout.addWidget(center_splitter, stretch=1)
        return panel
    
    def create_right_panel(self):
        panel = QFrame()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel(tr('processing_log'))
        title.setObjectName("panelTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self.compact_log_checkbox = QCheckBox(tr('compact_log'))
        self.compact_log_checkbox.setObjectName("modernCheckbox")
        self.compact_log_checkbox.stateChanged.connect(self.on_compact_log_changed)
        header_layout.addWidget(self.compact_log_checkbox)
        layout.addLayout(header_layout)

        # Log stats (4 tile: Completati / In corso / In coda / ETA)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)
        self._stat_completati = self._make_log_stat("0", "Completati")
        self._stat_in_corso   = self._make_log_stat("0", "In corso")
        self._stat_in_coda    = self._make_log_stat("0", "In coda")
        self._stat_eta        = self._make_log_stat("–", "ETA")
        for w in (self._stat_completati, self._stat_in_corso,
                  self._stat_in_coda, self._stat_eta):
            stats_row.addWidget(w)
        layout.addLayout(stats_row)

        # Log text
        self.log_text = QTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, stretch=1)

        # Diagnostic footer
        diag_title = QLabel("Diagnostica")
        diag_title.setObjectName("sectionTitle")
        layout.addWidget(diag_title)

        diag_row1 = QHBoxLayout()
        diag_row1.setSpacing(6)
        self._diag_tempo    = self._make_diag_tile("–", "Tempo",      'clock')
        self._diag_errori   = self._make_diag_tile("0", "Errori",     'alert')
        diag_row1.addWidget(self._diag_tempo)
        diag_row1.addWidget(self._diag_errori)
        layout.addLayout(diag_row1)

        diag_row2 = QHBoxLayout()
        diag_row2.setSpacing(6)
        cur_profile = tr(f"profile_{self.config.get_transcription_profile()}_name")
        cur_model   = self.config.get_translation_model()
        self._diag_modello    = self._make_diag_tile(cur_profile, "Modello",    'mic')
        self._diag_traduttore = self._make_diag_tile(cur_model,   "Traduttore", 'globe')
        diag_row2.addWidget(self._diag_modello)
        diag_row2.addWidget(self._diag_traduttore)
        layout.addLayout(diag_row2)

        return panel

    def _make_log_stat(self, value: str, label: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("logStatTile")
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(1)
        val = QLabel(value)
        val.setObjectName("logStatValue")
        lbl = QLabel(label)
        lbl.setObjectName("logStatLabel")
        lay.addWidget(val)
        lay.addWidget(lbl)
        tile._val = val  # type: ignore[attr-defined]
        return tile

    def _make_diag_tile(self, value: str, label: str, icon: str = '') -> QFrame:
        tile = QFrame()
        tile.setObjectName("diagTile")
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        val = ElideLabel(value)
        val.setObjectName("diagValue")
        lbl_row = QHBoxLayout()
        lbl_row.setSpacing(4)
        lbl_row.setContentsMargins(0, 0, 0, 0)
        if icon:
            ico = QLabel()
            ico.setPixmap(svg_icon(icon, 12, '#6a6f7a').pixmap(12, 12))
            ico.setFixedSize(12, 12)
            lbl_row.addWidget(ico)
        lbl = QLabel(label)
        lbl.setObjectName("diagLabel")
        lbl_row.addWidget(lbl)
        lbl_row.addStretch()
        lay.addWidget(val)
        lay.addLayout(lbl_row)
        tile._val = val  # type: ignore[attr-defined]
        return tile

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

    UPDATABLE_PATTERNS = ["Progresso:", "Demucs: [", "Traduzione: [", "Trascrizione: [", "Warm-up: [", "Correzione genere: ["]

    _LOG_COLORS = {
        'success': '#3fcf8e',
        'danger':  '#ef5a5a',
        'warn':    '#f5b450',
        'info':    '#3cc1e0',
        'muted':   '#9095a0',
    }

    def _log_color_html(self, text: str) -> str:
        if any(k in text for k in ('✅', '🎉')):
            color = self._LOG_COLORS['success']
        elif '❌' in text:
            color = self._LOG_COLORS['danger']
        elif '⚠' in text:
            color = self._LOG_COLORS['warn']
        elif any(k in text for k in ('🎬', '⚙️', '➕', '===', '---')):
            color = self._LOG_COLORS['info']
        else:
            color = self._LOG_COLORS['muted']
        safe = _html.escape(text).replace('\n', '<br>').replace('  ', '&nbsp;&nbsp;')
        return (
            f'<span style="color:{color};font-family:\'JetBrains Mono\',monospace;'
            f'font-size:11px;">{safe}</span>'
        )

    def log_message(self, message: str):
        message = self.fix_mojibake(message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        html_text = self._log_color_html(formatted)

        if any(p in message for p in self.UPDATABLE_PATTERNS):
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            block = cursor.block()
            if any(p in block.text() for p in self.UPDATABLE_PATTERNS):
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                    QTextCursor.MoveMode.KeepAnchor)
                cursor.insertHtml(html_text)
            else:
                if cursor.position() > 0:
                    cursor.insertBlock()
                cursor.insertHtml(html_text)
            self.log_text.setTextCursor(cursor)
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )
        elif not self.compact_log_enabled or any(k in message for k in ['✅', '⚙️', '🎉', '❌', '➕', '🎬']):
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if cursor.position() > 0:
                cursor.insertBlock()
            cursor.insertHtml(html_text)
            self.log_text.setTextCursor(cursor)
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )

    def on_file_selected(self):
        item = self.file_list.currentItem()
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            path = data.get('path') or next(
                (p for p in self.processing_queue if Path(p).name == item.text()), None
            )
            if path:
                self.load_poster(path)
        self._update_overlay()

    # ------------------------------------------------------------------
    # File list helpers
    # ------------------------------------------------------------------

    def _format_file_size(self, path: str) -> str:
        try:
            s = float(Path(path).stat().st_size)
            for unit in ('B', 'KB', 'MB', 'GB'):
                if s < 1024:
                    return f'{s:.0f} {unit}'
                s /= 1024
            return f'{s:.1f} TB'
        except Exception:
            return ''

    def _make_file_item(self, path: str):
        from PyQt6.QtWidgets import QListWidgetItem
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, {
            'path':     path,
            'filename': Path(path).name,
            'status':   'queued',
            'progress': 0,
            'size':     self._format_file_size(path),
        })
        return item

    def _find_item_by_path(self, file_path: str):
        """Restituisce il QListWidgetItem corrispondente al path, o None."""
        name = Path(file_path).name
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            if data.get('path') == file_path or data.get('filename') == name:
                return item
        return None

    def _update_filter_badges(self):
        counts = {'all': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            s = data.get('status', 'queued')
            counts[s] = counts.get(s, 0) + 1
        counts['all'] = sum(v for k, v in counts.items() if k != 'all')
        self.segmented_filter.set_counts(counts)
        self._update_tab_badge()

    def _apply_filter(self, key: str):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            status = data.get('status', 'queued')
            item.setHidden(key != 'all' and status != key)

    # ------------------------------------------------------------------
    # Job OCR (conversione sottotitoli bitmap dal Library Scanner)
    # Compaiono nella coda con stato/avanzamento ma NON entrano in
    # processing_queue: il pulsante "Avvia" (trascrizione audio) li ignora.
    # ------------------------------------------------------------------
    def _make_ocr_item(self, path: str, kind_label: str):
        from PyQt6.QtWidgets import QListWidgetItem
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, {
            'path':     path,
            'filename': Path(path).name,
            'status':   'queued',
            'progress': 0,
            'size':     f'OCR · {kind_label}',
            'kind':     'ocr',
        })
        return item

    def add_ocr_jobs(self, items: list):
        """items: lista di (windows_path, kind_label). Aggiunge job OCR alla coda
        (solo visualizzazione; NON in processing_queue)."""
        for path, kind_label in items:
            if self._find_item_by_path(path) is None:
                self.file_list.addItem(self._make_ocr_item(path, kind_label))
        self._update_filter_badges()

    def set_ocr_job_status(self, path: str, status: str, progress: int = 0):
        """Aggiorna stato/avanzamento di un job OCR nella coda."""
        item = self._find_item_by_path(path)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        if data.get('kind') != 'ocr':
            return
        prev_status = data.get('status')
        data['status'] = status
        data['progress'] = int(progress)
        item.setData(Qt.ItemDataRole.UserRole, data)
        self.file_list.update()
        # _update_filter_badges ricalcola le label dei contatori e può causare
        # un micro-ricalcolo del layout (jitter della finestra). Lo chiamiamo
        # SOLO quando lo status cambia (queued→processing, processing→completed…),
        # mai sui semplici aggiornamenti di percentuale a status invariato.
        if status != prev_status:
            self._update_filter_badges()

    # ------------------------------------------------------------------

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr('select_video_files'), self.config.get('last_input_folder', ''), "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v)")
        if files:
            self.config.set('last_input_folder', str(Path(files[0]).parent))
            with QMutexLocker(self.queue_mutex):
                for f in files:
                    if f not in self.processing_queue:
                        self.processing_queue.append(f)
                        self.file_list.addItem(self._make_file_item(f))
            self.update_remaining_files_label()
            self._update_filter_badges()
            self.file_list.setCurrentRow(self.file_list.count() - 1)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('select_folder'), self.config.get('last_input_folder', ''))
        if folder:
            self.config.set('last_input_folder', folder)
            exts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
            with QMutexLocker(self.queue_mutex):
                for f_path in Path(folder).rglob('*'):
                    if f_path.suffix.lower() in exts and str(f_path) not in self.processing_queue:
                        self.processing_queue.append(str(f_path))
                        self.file_list.addItem(self._make_file_item(str(f_path)))
            self.update_remaining_files_label()
            self._update_filter_badges()
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
                    self.file_list.addItem(self._make_file_item(f_path))
        self.update_remaining_files_label()
        self._update_filter_badges()
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(self.file_list.count() - 1)

    def load_poster(self, video_path: str):
        if video_path == self.last_loaded_file: return
        if self.poster_worker and self.poster_worker.isRunning():
            self.poster_worker.cancel()
            self.poster_worker.wait(500)
        self.last_loaded_file = video_path
        self.poster_label.setText("\n\n" + tr('loading_preview'))
        self.poster_worker = PosterLoaderWorker(video_path, self.tmdb_client)
        self.poster_worker.poster_loaded.connect(self._on_poster_loaded)
        self.poster_worker.poster_failed.connect(self._on_poster_failed)
        self.poster_worker.start()

    def _on_poster_loaded(self, pixmap):
        if pixmap and not pixmap.isNull():
            self.poster_label.setPixmap(pixmap)
        else:
            self._on_poster_failed()

    def _on_poster_failed(self):
        self.poster_label.setText("❌\n\n" + tr('no_preview'))

    def start_processing(self):
        if not self.processing_queue: return
        self.is_processing = True
        self.worker = ProcessingWorker(self.processing_queue, self.queue_mutex)
        self.worker.progress.connect(self.update_progress)
        self.worker.log_message.connect(self.log_message)
        self.worker.finished.connect(self.processing_finished)
        self.worker.file_completed.connect(self.on_file_completed)
        self.worker.file_started.connect(self.on_file_started)
        self.worker.file_progress.connect(self.on_file_progress)
        self.worker.file_history_entry.connect(self._on_file_history_entry)
        self.worker.queue_updated.connect(self.on_queue_updated) 
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_btn.setEnabled(False)
        self._set_status_processing()
        # Reset stats/diagnostic
        self._completed_count = 0
        self._error_count = 0
        self._proc_start_time = time.time()
        self._stat_completati._val.setText("0")
        self._stat_in_corso._val.setText("0")
        self._stat_in_coda._val.setText(str(self.file_list.count()))
        self._stat_eta._val.setText("–")
        self._diag_errori._val.setText("0")
        self._diag_tempo._val.setText("00:00")
        self._diag_modello._val.setText(tr(f"profile_{self.config.get_transcription_profile()}_name"))
        self._diag_traduttore._val.setText(self.config.get_translation_model())
        if self._proc_elapsed_timer:
            self._proc_elapsed_timer.stop()
        self._proc_elapsed_timer = QTimer(self)
        self._proc_elapsed_timer.timeout.connect(self._on_elapsed_tick)
        self._proc_elapsed_timer.start(1000)
        self.worker.error.connect(self._on_worker_error)
        self.worker.start()

    def stop_processing(self):
        reply = QMessageBox.question(
            self,
            tr('confirm_stop_title'),
            tr('confirm_stop_text'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.stop_btn.setEnabled(False)
        self.log_message(tr('stop_requested'))
        if self.worker:
            self.worker.is_cancelled = True
            if self.worker.pipeline:
                self.worker.pipeline.cancel()

    def on_file_completed(self, file_path: str):
        item = self._find_item_by_path(file_path)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            data['status'] = 'completed'
            data['progress'] = 100
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.file_list.update()
            self._apply_filter(self.segmented_filter.current_filter())
        self.update_remaining_files_label()
        self._update_filter_badges()
        self.library_scanner.notify_subtitle_created(file_path)
        self._completed_count += 1
        self._update_overlay()
        self._update_log_stats()

    def on_file_started(self, file_path: str):
        item = self._find_item_by_path(file_path)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            data['status'] = 'processing'
            data['progress'] = 0
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.file_list.update()
            self._apply_filter(self.segmented_filter.current_filter())
        self._update_filter_badges()
        self._update_overlay()
        self._update_log_stats()

    def on_file_progress(self, file_path: str, percent: int):
        item = self._find_item_by_path(file_path)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            data['progress'] = percent
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.file_list.update()
        self._update_overlay()
        self._update_log_stats()

    def on_queue_updated(self, total: int):
        self.update_remaining_files_label()

    def update_remaining_files_label(self):
        with QMutexLocker(self.queue_mutex):
            remaining = len(self.processing_queue)
        if self.is_processing:
            self.remaining_files_label.setText(f"📊 {tr('remaining_files')} {remaining}")
            self.remaining_files_label.setVisible(True)
        else:
            self.remaining_files_label.clear()
            self.remaining_files_label.setVisible(False)

    def processing_finished(self):
        self.is_processing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_btn.setEnabled(True)
        self._set_status_idle()
        if self._proc_elapsed_timer:
            self._proc_elapsed_timer.stop()
            self._proc_elapsed_timer = None
        self._update_log_stats()
        self.log_message(tr('processing_completed'))
        if self.shutdown_checkbox.isChecked():
            QTimer.singleShot(5000, self.shutdown_system)

    def shutdown_system(self):
        cmd = ['shutdown', '/s', '/t', '60'] if os.name == 'nt' else ['shutdown', '-h', '+1']
        subprocess.run(cmd)

    def update_progress(self, value: int):
        self.progress_bar.setValue(value)

    # Le vecchie open_*_settings sono ora thin wrapper su SettingsDialog: il
    # dialog unificato apre la tab giusta e gestisce la persistenza interna.

    def open_profile_settings(self):
        self.open_settings_dialog(initial_tab=TAB_TRANSCRIPTION)

    def open_opensubtitles_settings(self):
        self.open_settings_dialog(initial_tab=TAB_OPENSUBTITLES)

    def open_adaptive_batch_settings(self):
        self.open_settings_dialog(initial_tab=TAB_BATCH)

    def open_translation_model_settings(self):
        self.open_settings_dialog(initial_tab=TAB_TRANSLATION)

    def update_profile_indicator(self):
        current_profile = self.config.get_transcription_profile()
        self.profile_button.setText(f"⚙️  {tr(f'profile_{current_profile}_name')}  ▾")

    def _on_profile_selected(self, profile_key: str):
        self.config.set_transcription_profile(profile_key)
        self.update_profile_indicator()
        self.log_message(f"⚙️ Profilo: {tr(f'profile_{profile_key}_name')}")

    def _create_tab_bar(self) -> QTabBar:
        bar = QTabBar()
        bar.setObjectName("mainTabBar")
        bar.addTab(svg_icon('list', 15, '#9095a0'), "Coda di processamento")
        bar.addTab(svg_icon('history', 15, '#9095a0'), "Cronologia")
        bar.setExpanding(False)
        return bar

    def _on_tab_changed(self, index: int):
        self.main_stack.setCurrentIndex(index)

    def _on_file_history_entry(self, entry: dict):
        self.history_widget.append_entry(entry)
        self._update_history_badge()

    def _update_history_badge(self):
        n = self.history_widget.total_count()
        self.main_tab_bar.setTabText(1, f"Cronologia  ({n})" if n else "Cronologia")

    def _update_tab_badge(self):
        active = sum(
            1 for i in range(self.file_list.count())
            if (self.file_list.item(i).data(Qt.ItemDataRole.UserRole) or {}).get('status')
            in ('queued', 'processing')
        )
        label = f"Coda di processamento  ({active})" if active else "Coda di processamento"
        self.main_tab_bar.setTabText(0, label)

    def _set_status_processing(self):
        self._status_dot.setStyleSheet(
            "QFrame#statusDot { background: #3cc1e0; border-radius: 4px; }"
        )
        self._status_label.setText("In elaborazione")
        self._status_dot_anim_group.start()

    def _set_status_idle(self):
        self._status_dot_anim_group.stop()
        self._status_dot_effect.setOpacity(1.0)
        self._status_dot.setStyleSheet(
            "QFrame#statusDot { background: #3fcf8e; border-radius: 4px; }"
        )
        self._status_label.setText("Pronto")

    # ------------------------------------------------------------------
    # Overlay / stats / diagnostic helpers
    # ------------------------------------------------------------------

    def _update_overlay(self):
        item = self.file_list.currentItem()
        if not item:
            self._info_strip.setVisible(False)
            self.preview_filename_pill.setVisible(False)
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        status   = data.get('status', 'queued')
        progress = data.get('progress', 0)
        size     = data.get('size', '')
        filename = data.get('filename', '')
        path     = data.get('path', '')

        self.preview_filename_pill.setText(filename)
        self.preview_filename_pill.setVisible(True)

        if status == 'queued':
            self._info_strip.setVisible(False)
            return

        self._info_strip.setVisible(True)
        dst = self.config.get_target_language().upper()
        self._overlay_lang_pill.setText(f"→ {dst}")
        status_map = {
            'processing': '⟳ Elaborazione',
            'completed':  '✅ Completato',
            'failed':     '❌ Fallito',
        }
        self._overlay_status_pill.setText(status_map.get(status, status))
        stem = Path(path).stem if path else filename
        self._overlay_title.setText(stem)
        parts = [size] if size else []
        if progress > 0:
            parts.append(f"{progress}%")
        self._overlay_meta.setText(" · ".join(parts))
        self._overlay_progress.setValue(progress)

    def _update_log_stats(self):
        in_prog = sum(
            1 for i in range(self.file_list.count())
            if (self.file_list.item(i).data(Qt.ItemDataRole.UserRole) or {}).get('status') == 'processing'
        )
        queued = sum(
            1 for i in range(self.file_list.count())
            if (self.file_list.item(i).data(Qt.ItemDataRole.UserRole) or {}).get('status') == 'queued'
        )
        self._stat_completati._val.setText(str(self._completed_count))
        self._stat_in_corso._val.setText(str(in_prog))
        self._stat_in_coda._val.setText(str(queued))
        remaining = queued + in_prog
        if self._completed_count > 0 and remaining > 0 and self._proc_start_time > 0:
            elapsed = time.time() - self._proc_start_time
            eta_s = int((elapsed / self._completed_count) * remaining)
            h, r = divmod(eta_s, 3600)
            m, s = divmod(r, 60)
            self._stat_eta._val.setText(f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s")
        else:
            self._stat_eta._val.setText("–")

    def _on_elapsed_tick(self):
        if self._proc_start_time > 0:
            elapsed = int(time.time() - self._proc_start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self._diag_tempo._val.setText(
                f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            )

    def _on_worker_error(self, _msg: str):
        self._error_count += 1
        self._diag_errori._val.setText(str(self._error_count))

    # ------------------------------------------------------------------

    def clear_queue(self):
        if self.is_processing: return
        with QMutexLocker(self.queue_mutex):
            self.processing_queue.clear()
            self.file_list.clear()
        self.poster_label.setText("🎬\n\n" + tr('no_preview'))

    # Le 4 funzioni on_*_changed (shutdown/os/gender/target_language) sono ora
    # gestite dentro JobOptionsCard, che persiste i valori in config alla
    # variazione. Rimosse da MainWindow per evitare duplicazione.

    def on_compact_log_changed(self, state):
        self.compact_log_enabled = state == Qt.CheckState.Checked.value

    def open_general_settings(self):
        self.open_settings_dialog(initial_tab=TAB_GENERAL)

    def _open_sync_dialog(self):
        """Apre il dialog di sincronizzazione SRT."""
        from gui.sync_dialog import SyncDialog
        current_video = None
        selected = self.file_list.currentItem()
        if selected:
            data = selected.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                current_video = data.get('path')
            elif isinstance(data, str):
                current_video = data
        dlg = SyncDialog(video_path=current_video, parent=self)
        dlg.exec()

    def closeEvent(self, event):
        if self.is_processing:
            reply = QMessageBox.question(self, tr('confirm_exit'), tr('processing_in_progress'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes: event.accept()
            else: event.ignore()
        else: event.accept()

    def apply_modern_theme(self):
        # Neutralizzato in Fase 1 del GUI revamp.
        # Lo styling globale e' ora caricato in main.py da gui/theme.qss tramite
        # app.setStyleSheet(...). Questo metodo resta per compatibilita' (e'
        # chiamato da __init__) ma non sovrascrive piu' il tema globale.
        return