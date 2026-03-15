# -*- coding: utf-8 -*-
"""
Library Scanner Widget - Pannello collassabile per importare video senza sottotitoli
File: gui/library_scanner_widget.py
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QToolButton, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QSpinBox
)
from PyQt6.QtCore import Qt, QTimer, QMutexLocker, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from pathlib import Path
import logging
import re

from gui.library_scanner_worker import LibraryScannerWorker
from utils.config import get_config
from utils.translations import tr

logger = logging.getLogger(__name__)

# ── Italian audio detection ───────────────────────────────────────────────────
# (?<![a-zA-Z]) / (?![a-zA-Z]) gestisce separatori come punto, trattino,
# underscore, parentesi — più robusto di \b che tratta _ come parola
_IT_TAGS_RE = re.compile(
    r'(?<![a-zA-Z])(ita|nuita|italian|italiano)(?![a-zA-Z])',
    re.IGNORECASE,
)
_FOREIGN_TAGS_RE = re.compile(
    r'(?<![a-zA-Z])(eng|nueng|english|fra|french|fre|spa|spanish|ger|german|deu|'
    r'por|portuguese|rus|russian|jpn|japanese|kor|korean|chi|chinese|nld|dutch)(?![a-zA-Z])',
    re.IGNORECASE,
)


def _detect_italian(filename: str) -> str:
    """
    Rileva la lingua audio dal filename tramite tag espliciti.

    Ritorna:
        'ita'     – italiano confermato (tag esplicito nel filename)
        'foreign' – lingua straniera confermata (tag esplicito, no italiano)
        'unknown' – nessun tag lingua trovato
    """
    if _IT_TAGS_RE.search(filename):
        return 'ita'
    if _FOREIGN_TAGS_RE.search(filename):
        return 'foreign'
    return 'unknown'


class _NotifyWorker(QThread):
    """Invia POST /api/videos/notify-subtitle in background (fire-and-forget)."""
    done = pyqtSignal(bool)   # True = HTTP 200 OK

    def __init__(self, server_url: str, api_key: str, windows_path: str):
        super().__init__()
        self.server_url   = server_url.rstrip('/')
        self.api_key      = api_key
        self.windows_path = windows_path

    def run(self):
        try:
            import requests
            resp = requests.post(
                f"{self.server_url}/api/videos/notify-subtitle",
                json={"windows_path": self.windows_path},
                headers={"X-API-Key": self.api_key},
                timeout=10,
            )
            self.done.emit(resp.status_code == 200)
        except Exception:
            self.done.emit(False)


class _NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem con ordinamento numerico (intero) invece di lessicografico."""
    def __lt__(self, other):
        try:
            return int(self.text()) < int(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)


class LibraryScannerWidget(QFrame):
    """Widget collassabile che mostra i video senza sottotitoli italiani dal server Library Scanner."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.config = get_config()
        self.is_expanded = False
        self.is_loaded = False
        self.worker = None
        self.videos_data = []

        self.setObjectName("libraryScannerFrame")
        self._init_ui()
        self._apply_styles()
        self._setup_auto_refresh()

        if not self.config.get('library_scanner_enabled', True):
            self.setVisible(False)

    # ========================================================================
    # COSTRUZIONE UI
    # ========================================================================

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        main_layout.addWidget(self._build_header())

        self.body_widget = self._build_body()
        self.body_widget.setVisible(False)
        main_layout.addWidget(self.body_widget)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("scannerHeader")
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda e: self.toggle_expanded()

        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("▶")
        self.toggle_btn.setObjectName("scannerToggle")
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_expanded)
        layout.addWidget(self.toggle_btn)

        title = QLabel(tr('library_scanner_title'))
        title.setObjectName("scannerTitle")
        layout.addWidget(title)

        self.badge_label = QLabel("0")
        self.badge_label.setObjectName("scannerBadge")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setVisible(False)
        layout.addWidget(self.badge_label)

        layout.addStretch()

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet(
            "background-color: #888888; border-radius: 5px;"
            "min-width: 10px; max-width: 10px;"
            "min-height: 10px; max-height: 10px;"
        )
        layout.addWidget(self.status_dot)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("🔄")
        self.refresh_btn.setObjectName("scannerRefreshBtn")
        self.refresh_btn.setFixedSize(24, 24)
        self.refresh_btn.setToolTip(tr('refresh'))
        self.refresh_btn.clicked.connect(self.refresh_data)
        layout.addWidget(self.refresh_btn)

        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)

        # Barra di ricerca
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("scannerSearch")
        self.search_bar.setPlaceholderText(tr('search_placeholder'))
        self.search_bar.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_bar)

        # Filtro tipo + filtro giorni
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        type_label = QLabel(tr('type_filter'))
        type_label.setObjectName("scannerFilterLabel")
        filter_layout.addWidget(type_label)

        self.type_combo = QComboBox()
        self.type_combo.setObjectName("scannerFilter")
        self.type_combo.addItems([tr('all_types'), tr('film_type'), tr('tv_series_type')])
        self.type_combo.currentIndexChanged.connect(self._on_type_filter_changed)
        filter_layout.addWidget(self.type_combo)

        days_label = QLabel(tr('days_filter'))
        days_label.setObjectName("scannerFilterLabel")
        filter_layout.addWidget(days_label)

        self.days_spinbox = QSpinBox()
        self.days_spinbox.setObjectName("scannerDaysFilter")
        self.days_spinbox.setRange(0, 9999)
        self.days_spinbox.setValue(0)
        self.days_spinbox.setSpecialValueText(tr('all_days'))
        self.days_spinbox.setFixedWidth(85)
        self.days_spinbox.valueChanged.connect(self._on_days_filter_changed)
        filter_layout.addWidget(self.days_spinbox)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Tabella video
        self.video_table = QTableWidget()
        self.video_table.setObjectName("scannerTable")
        self.video_table.setColumnCount(4)
        self.video_table.setHorizontalHeaderLabels([tr('file_col'), tr('type_col'), tr('days_col'), ""])
        self.video_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.video_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.video_table.verticalHeader().setVisible(False)
        self.video_table.setShowGrid(False)
        self.video_table.setMaximumHeight(250)
        self.video_table.verticalHeader().setDefaultSectionSize(26)

        header = self.video_table.horizontalHeader()
        header.setMinimumSectionSize(20)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self.video_table.setColumnWidth(1, 60)
        self.video_table.setColumnWidth(2, 50)
        self.video_table.setColumnWidth(3, 24)
        self.video_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        layout.addWidget(self.video_table)

        # Bottone Importa Tutti
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(6)

        self.import_all_btn = QPushButton(tr('import_filtered'))
        self.import_all_btn.setObjectName("scannerImportAllBtn")
        self.import_all_btn.clicked.connect(self._import_all)
        self.import_all_btn.setEnabled(False)
        buttons_layout.addWidget(self.import_all_btn)

        layout.addLayout(buttons_layout)

        # Statistiche
        self.stats_label = QLabel(tr('waiting_connection'))
        self.stats_label.setObjectName("scannerStats")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.stats_label)

        return body

    # ========================================================================
    # STILE
    # ========================================================================

    def _apply_styles(self):
        self.setStyleSheet("""
            QFrame#libraryScannerFrame {
                background-color: rgba(32, 32, 32, 180);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                margin-top: 5px;
            }

            QFrame#scannerHeader {
                background-color: transparent;
                border: none;
            }
            QFrame#scannerHeader:hover {
                background-color: rgba(255, 255, 255, 0.03);
            }

            QToolButton#scannerToggle {
                background: transparent;
                border: none;
                color: #888888;
                font-size: 10pt;
            }
            QToolButton#scannerRefreshBtn {
                background: transparent;
                border: none;
                font-size: 10pt;
            }

            QLabel#scannerTitle {
                color: #ffffff;
                font-size: 10pt;
                font-weight: bold;
            }

            QLabel#scannerBadge {
                background-color: #e94560;
                color: white;
                border-radius: 9px;
                padding: 1px 7px;
                font-size: 8pt;
                font-weight: bold;
                min-width: 18px;
                max-height: 18px;
            }

            QLabel#scannerFilterLabel {
                color: #aaaaaa;
                font-size: 9pt;
            }

            QLineEdit#scannerSearch {
                background-color: rgba(0, 0, 0, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #ffffff;
                padding: 5px 8px;
                font-size: 9pt;
            }
            QLineEdit#scannerSearch:focus {
                border: 1px solid rgba(33, 150, 243, 0.5);
            }

            QComboBox#scannerFilter {
                background-color: rgba(0, 0, 0, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #ffffff;
                padding: 4px 8px;
                font-size: 9pt;
                min-width: 80px;
            }
            QComboBox#scannerFilter::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox#scannerFilter QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: rgba(33, 150, 243, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.1);
            }

            QTableWidget#scannerTable {
                background-color: rgba(0, 0, 0, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #ffffff;
                font-size: 8pt;
                gridline-color: rgba(255, 255, 255, 0.03);
            }
            QTableWidget#scannerTable::item {
                padding: 2px 4px;
            }
            QTableWidget#scannerTable::item:selected {
                background-color: rgba(33, 150, 243, 0.15);
            }
            QHeaderView {
                background-color: #000000;
            }
            QHeaderView::section {
                background-color: #000000;
                color: #ffffff;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.1);
                padding: 4px 6px;
                font-size: 8pt;
                font-weight: bold;
            }
            QHeaderView::section:last {
                border-right: none;
            }

            QPushButton#scannerImportAllBtn {
                background-color: rgba(33, 150, 243, 200);
                border: none;
                border-radius: 6px;
                color: white;
                padding: 7px 12px;
                font-size: 8pt;
                font-weight: bold;
            }
            QPushButton#scannerImportAllBtn:hover {
                background-color: rgba(33, 150, 243, 255);
            }
            QPushButton#scannerImportAllBtn:disabled {
                background-color: rgba(60, 60, 60, 150);
                color: rgba(255, 255, 255, 80);
            }

            QPushButton[class="scannerAddBtn"] {
                background-color: rgba(76, 175, 80, 180);
                border: none;
                border-radius: 4px;
                color: white;
                font-size: 9pt;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton[class="scannerAddBtn"]:hover {
                background-color: rgba(76, 175, 80, 255);
            }
            QPushButton[class="scannerAddBtn"]:disabled {
                background-color: transparent;
                color: #4CAF50;
            }

            QLabel#scannerStats {
                color: #888888;
                font-size: 8pt;
                padding: 2px;
            }
        """)

    # ========================================================================
    # ESPANDI / COMPRIMI
    # ========================================================================

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.body_widget.setVisible(self.is_expanded)
        self.toggle_btn.setText("▼" if self.is_expanded else "▶")

        if self.is_expanded:
            QTimer.singleShot(50, self._auto_resize_file_column)

        if self.is_expanded and not self.is_loaded:
            self.is_loaded = True
            self.refresh_data()

    # ========================================================================
    # CARICAMENTO DATI
    # ========================================================================

    def refresh_data(self):
        if self.worker and self.worker.isRunning():
            return

        url = self.config.get('library_scanner_url')
        api_key = self.config.get('library_scanner_api_key')

        if not url or not api_key:
            self.stats_label.setText(tr('config_missing'))
            self._update_status_dot(False)
            return

        self.stats_label.setText(tr('loading'))

        self.worker = LibraryScannerWorker(
            server_url=url,
            api_key=api_key,
            request_type='both',
            search=self.search_bar.text().strip(),
            media_type=self._get_selected_type()
        )
        self.worker.data_loaded.connect(self._on_videos_loaded)
        self.worker.stats_loaded.connect(self._on_stats_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.connection_status.connect(self._update_status_dot)
        self.worker.start()

    def _on_videos_loaded(self, data: dict):
        self.videos_data = data.get('videos', [])
        self._populate_table()
        self._update_badge(len(self.videos_data))
        self.import_all_btn.setEnabled(len(self.videos_data) > 0)

    def _on_stats_loaded(self, stats: dict):
        without = stats.get('without_subs', 0)
        total = stats.get('total_files', 0)
        self.stats_label.setText(tr('files_stats').format(without=without, total=total))
        self._update_badge(without)

    def _on_error(self, message: str):
        logger.warning(f"Library Scanner: {message}")
        self.stats_label.setText(tr('error_status').format(message=message))

    def _update_status_dot(self, connected: bool):
        color = "#4CAF50" if connected else "#f44336"
        self.status_dot.setStyleSheet(
            f"background-color: {color}; border-radius: 5px;"
            f"min-width: 10px; max-width: 10px;"
            f"min-height: 10px; max-height: 10px;"
        )

    # ========================================================================
    # TABELLA
    # ========================================================================

    def _populate_table(self):
        self.video_table.setSortingEnabled(False)
        self.video_table.setRowCount(0)
        self.video_table.setRowCount(len(self.videos_data))

        # Controlla quali path sono gia' in coda
        queued_paths = set()
        with QMutexLocker(self.main_window.queue_mutex):
            queued_paths = set(self.main_window.processing_queue)

        for row, video in enumerate(self.videos_data):
            windows_path = video.get('windows_path', '')
            filename     = video.get('filename', '')

            # Colonna 0: Nome file — UserRole contiene windows_path per accesso post-sort
            name_item = QTableWidgetItem(filename)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, windows_path)

            # Rileva lingua audio dal filename e colora di conseguenza
            if _detect_italian(filename) == 'ita':
                name_item.setForeground(QColor("#82aaff"))
                name_item.setToolTip(f"🇮🇹 Audio ITA · {windows_path}")
            else:
                name_item.setToolTip(windows_path)

            self.video_table.setItem(row, 0, name_item)

            # Colonna 1: Tipo
            media_type = video.get('media_type', '')
            type_text = tr('film_type') if media_type == 'movie' else tr('tv_series_type') if media_type == 'tvshow' else media_type
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 1, type_item)

            # Colonna 2: Giorni senza sub (ordinamento numerico)
            days = video.get('days_without_subs', 0)
            days_item = _NumericTableWidgetItem(str(days))
            days_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if days > 30:
                days_item.setForeground(QColor("#e94560"))
            elif days > 14:
                days_item.setForeground(QColor("#FFC107"))
            self.video_table.setItem(row, 2, days_item)

            # Colonna 3: Bottone import singolo
            already_queued = windows_path in queued_paths
            btn = self._create_row_button(row, already_queued)
            self.video_table.setCellWidget(row, 3, btn)

        self.video_table.setSortingEnabled(True)
        # Applica filtro giorni (se attivo nasconde le righe fuori range)
        self._apply_days_filter()

    def _on_days_filter_changed(self):
        self._apply_days_filter()

    def _apply_days_filter(self):
        """Nasconde le righe con days_without_subs < min_days. Aggiorna badge e bottone importa."""
        min_days = self.days_spinbox.value()
        visible_count = 0
        for row in range(self.video_table.rowCount()):
            days_item = self.video_table.item(row, 2)
            days = int(days_item.text()) if days_item else 0
            hide = min_days > 0 and days < min_days
            self.video_table.setRowHidden(row, hide)
            if not hide:
                visible_count += 1
        self._update_badge(visible_count)
        self.import_all_btn.setEnabled(visible_count > 0)

    def _create_row_button(self, row: int, already_queued: bool) -> QPushButton:
        btn = QPushButton("✓" if already_queued else "➕")
        btn.setProperty("class", "scannerAddBtn")
        btn.setFixedSize(20, 20)
        btn.setEnabled(not already_queued)
        if not already_queued:
            btn.clicked.connect(lambda checked, b=btn: self._import_single_by_btn(b))
        else:
            btn.setToolTip(tr('already_queued'))
        return btn

    def _import_single_by_btn(self, btn: QPushButton):
        """Trova la riga corrente del bottone (dopo eventuale sort) e importa."""
        for row in range(self.video_table.rowCount()):
            if self.video_table.cellWidget(row, 3) is btn:
                self._import_single(row)
                return

    # ========================================================================
    # IMPORT
    # ========================================================================

    def _import_single(self, row: int):
        item = self.video_table.item(row, 0)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return

        added = self._import_paths([path])
        if added > 0:
            btn = self.video_table.cellWidget(row, 3)
            if btn:
                btn.setText("✓")
                btn.setEnabled(False)
                btn.setToolTip(tr('already_queued'))

    def _import_all(self):
        # Solo righe visibili (rispetta filtro giorni + tipo)
        paths = []
        for row in range(self.video_table.rowCount()):
            if not self.video_table.isRowHidden(row):
                item = self.video_table.item(row, 0)
                if item:
                    path = item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        paths.append(path)
        if not paths:
            return

        added = self._import_paths(paths)

        # Aggiorna bottoni delle righe importate
        queued_paths = set()
        with QMutexLocker(self.main_window.queue_mutex):
            queued_paths = set(self.main_window.processing_queue)

        for row in range(self.video_table.rowCount()):
            if not self.video_table.isRowHidden(row):
                item = self.video_table.item(row, 0)
                if item:
                    wp = item.data(Qt.ItemDataRole.UserRole)
                    if wp in queued_paths:
                        btn = self.video_table.cellWidget(row, 3)
                        if btn and btn.isEnabled():
                            btn.setText("✓")
                            btn.setEnabled(False)
                            btn.setToolTip(tr('already_queued'))

        if added > 0:
            self.main_window.log_message(tr('files_imported_log').format(added=added))

    def _import_paths(self, paths: list) -> int:
        if not paths:
            return 0

        added = 0
        with QMutexLocker(self.main_window.queue_mutex):
            for path in paths:
                if path and path not in self.main_window.processing_queue:
                    self.main_window.processing_queue.append(path)
                    self.main_window.file_list.addItem(Path(path).name)
                    added += 1

        if added > 0:
            self.main_window.update_remaining_files_label()
            if self.main_window.file_list.count() > 0:
                self.main_window.file_list.setCurrentRow(
                    self.main_window.file_list.count() - 1
                )

        return added

    # ========================================================================
    # NOTIFICA SOTTOTITOLO CREATO (chiamata da main_window)
    # ========================================================================

    def notify_subtitle_created(self, video_path: str):
        """Chiamato da main_window al termine elaborazione di un file.
        Notifica il server che un sottotitolo è stato creato, poi aggiorna la lista."""
        if not self.is_loaded:
            return
        url     = self.config.get('library_scanner_url', '').strip()
        api_key = self.config.get('library_scanner_api_key', '').strip()
        if not url or not api_key:
            return
        self._notify_worker = _NotifyWorker(url, api_key, str(video_path))
        self._notify_worker.done.connect(self._on_notify_done)
        self._notify_worker.start()

    def _on_notify_done(self, success: bool):
        if success:
            logger.debug("Library Scanner notificato — aggiorno la lista")
            self.refresh_data()

    # ========================================================================
    # AUTO-REFRESH
    # ========================================================================

    def _setup_auto_refresh(self):
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh)
        self.refresh_timer.start(5 * 60 * 1000)

    def _auto_refresh(self):
        if self.is_expanded:
            self.refresh_data()

    # ========================================================================
    # RICERCA E FILTRI
    # ========================================================================

    def _on_search_changed(self):
        if hasattr(self, '_search_timer') and self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._search_timer.start(500)

    def _do_search(self):
        if self.is_loaded:
            self.refresh_data()

    def _on_type_filter_changed(self):
        if self.is_loaded:
            self.refresh_data()

    def _get_selected_type(self) -> str:
        index = self.type_combo.currentIndex()
        if index == 1:
            return 'movie'
        if index == 2:
            return 'tvshow'
        return ''

    # ========================================================================
    # UTILITY
    # ========================================================================

    def _auto_resize_file_column(self):
        """Calcola la larghezza della colonna File per riempire lo spazio disponibile."""
        self.video_table.setColumnWidth(1, 60)
        self.video_table.setColumnWidth(2, 50)
        self.video_table.setColumnWidth(3, 24)
        table_width = self.video_table.viewport().width()
        fixed_cols = 60 + 50 + 24
        file_width = max(120, table_width - fixed_cols)
        self.video_table.setColumnWidth(0, file_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'video_table'):
            self._auto_resize_file_column()

    def _update_badge(self, count: int):
        self.badge_label.setText(str(count))
        self.badge_label.setVisible(count > 0)
