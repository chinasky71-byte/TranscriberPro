# -*- coding: utf-8 -*-
"""
Library Scanner Widget - Pannello collassabile per importare video senza sottotitoli
File: gui/library_scanner_widget.py
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QToolButton, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QSpinBox,
    QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QMutexLocker, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from pathlib import Path
import logging
import re

from gui.library_scanner_worker import LibraryScannerWorker
from gui.widgets import ElideLabel
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

    status_changed = pyqtSignal(str)   # "Attivo" / "Inattivo" — per summary CollapsibleCard

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

        self._internal_header = self._build_header()
        main_layout.addWidget(self._internal_header)

        self.body_widget = self._build_body()
        self.body_widget.setVisible(False)
        main_layout.addWidget(self.body_widget)

    def set_embedded(self, embedded: bool = True):
        """Nasconde l'header interno (usato dentro CollapsibleCard).
        refresh_btn e status_dot vengono esposti al chiamante via addHeaderWidget()."""
        self._internal_header.setVisible(not embedded)
        if embedded:
            self.body_widget.setVisible(True)
            self.is_expanded = True
            if not self.is_loaded:
                self.is_loaded = True
                # Ritarda il primo tentativo così lo splash si chiude prima di
                # qualsiasi chiamata di rete (evita blocco su IP non raggiungibile).
                QTimer.singleShot(2500, self.refresh_data)

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

        self._header_title = QLabel(tr('library_scanner_title'))
        self._header_title.setObjectName("scannerTitle")
        layout.addWidget(self._header_title)

        self.badge_label = QLabel("0")
        self.badge_label.setObjectName("scannerBadge")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setVisible(False)
        layout.addWidget(self.badge_label)

        layout.addStretch()

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # Filtro formato bitmap su riga propria (così la riga non allarga il
        # pannello sinistro impedendo allo splitter di restringerlo).
        format_layout = QHBoxLayout()
        format_layout.setSpacing(6)
        format_label = QLabel(tr('format_filter'))
        format_label.setObjectName("scannerFilterLabel")
        format_layout.addWidget(format_label)

        self.format_combo = QComboBox()
        self.format_combo.setObjectName("scannerFilter")
        # userData: None=tutti, 'pgs', 'vobsub', 'assssa', 'nosrt'=nessuna traccia subtitle
        self.format_combo.addItem(tr('all_formats'), None)
        self.format_combo.addItem("PGS", "pgs")
        self.format_combo.addItem("VOBSUB", "vobsub")
        self.format_combo.addItem("ASS/SSA", "assssa")
        self.format_combo.addItem("No SRT", "nosrt")
        self.format_combo.currentIndexChanged.connect(self._on_format_filter_changed)
        format_layout.addWidget(self.format_combo)

        format_layout.addStretch()
        layout.addLayout(format_layout)

        # Tabella video
        self.video_table = QTableWidget()
        self.video_table.setObjectName("scannerTable")
        self.video_table.setColumnCount(5)
        self.video_table.setHorizontalHeaderLabels(
            [tr('file_col'), tr('type_col'), tr('days_col'), "Sub", ""]
        )
        self.video_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.video_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.video_table.verticalHeader().setVisible(False)
        self.video_table.setShowGrid(False)
        self.video_table.setMaximumHeight(250)
        self.video_table.setMinimumHeight(0)
        self.video_table.verticalHeader().setDefaultSectionSize(26)

        header = self.video_table.horizontalHeader()
        header.setMinimumSectionSize(20)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        self.video_table.setColumnWidth(1, 60)
        self.video_table.setColumnWidth(2, 50)
        self.video_table.setColumnWidth(3, 38)
        self.video_table.setColumnWidth(4, 24)
        self.video_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.video_table.setMinimumWidth(0)  # non vincola la larghezza minima del pannello

        layout.addWidget(self.video_table)

        # Bottone Importa Tutti
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(6)

        self.import_all_btn = QPushButton(tr('import_filtered'))
        self.import_all_btn.setObjectName("scannerImportAllBtn")
        self.import_all_btn.clicked.connect(self._import_all)
        self.import_all_btn.setEnabled(False)
        # Policy shrinkable: il cambio testo (Importa filtrati ↔ Converti ASS/SSA)
        # non deve mai allargare il pannello e quindi la finestra.
        self.import_all_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.import_all_btn.setMinimumWidth(0)
        buttons_layout.addWidget(self.import_all_btn)

        self.superpower_btn = QPushButton("⚡ Superpower")
        self.superpower_btn.setObjectName("scannerImportAllBtn")
        self.superpower_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.superpower_btn.setMinimumWidth(0)
        self.superpower_btn.setToolTip(
            "Acquisisci tutti i file bitmap pending dalla Library Scanner\n"
            "e processali qui (più veloce).\n"
            "La Library Scanner OCR viene fermata e riattivata al termine.")
        self.superpower_btn.clicked.connect(self._superpower_ocr)
        buttons_layout.addWidget(self.superpower_btn)

        layout.addLayout(buttons_layout)

        # Avanzamento OCR (visibile solo durante la conversione)
        # ElideLabel: il testo dinamico (path file completo) NON deve mai imporre
        # un minimum width al pannello → niente ridimensionamento finestra.
        self.ocr_progress_label = ElideLabel("")
        self.ocr_progress_label.setObjectName("scannerStats")
        self.ocr_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_progress_label.setFixedHeight(16)  # altezza fissa: non varia mai il layout
        layout.addWidget(self.ocr_progress_label)

        # Statistiche — anch'essa ElideLabel per non imporre minimum width
        self.stats_label = ElideLabel(tr('waiting_connection'))
        self.stats_label.setObjectName("scannerStats")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.stats_label)

        body.setMinimumHeight(0)
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
            media_type=self._get_selected_type(),
            format_filter=self._get_selected_format() or '',
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
        self.status_changed.emit("Attivo" if connected else "Inattivo")

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
            # UserRole+1: bitmap_format ('pgs'|'vobsub'|'mixed'|None) per il filtro Formato
            name_item.setData(Qt.ItemDataRole.UserRole + 1, video.get('bitmap_format'))
            # UserRole+2: video id (int) — per chiamate API conversione ASS/SSA
            name_item.setData(Qt.ItemDataRole.UserRole + 2, video.get('id'))
            # UserRole+3: has_italian_convertible_subs (bool) — True se ha ASS/SSA ITALIANO
            # ancora da convertire (lavoro reale). NON usiamo has_convertible_subs
            # (any-language): un file con solo ASS non-italiano non è un job per questo tool.
            name_item.setData(Qt.ItemDataRole.UserRole + 3, bool(video.get('has_italian_convertible_subs', False)))
            # UserRole+4: has_only_bitmap_subs (bool) — True solo se il file necessita
            # davvero OCR (bitmap ITA e nessun sub testo ITA). bitmap_format indica solo
            # la PRESENZA di uno stream PGS/VOBSUB: un file può avere PGS ma anche un sub
            # testuale ITA (has_only_bitmap_subs=False) → NON è un job OCR e il filtro
            # Formato non deve mostrarlo come PGS/VOBSUB (coerenza col badge, righe ~620).
            name_item.setData(Qt.ItemDataRole.UserRole + 4, bool(video.get('has_only_bitmap_subs', False)))

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

            # Colonna 3: badge formato subtitle problematico
            has_bitmap = video.get('has_only_bitmap_subs', False)
            has_ass    = video.get('has_italian_convertible_subs', False)
            if has_bitmap:
                badge_widget = self._create_sub_badge(video)
            elif has_ass:
                badge_widget = self._create_ass_badge(video)
            else:
                badge_widget = QWidget()
            self.video_table.setCellWidget(row, 3, badge_widget)

            # Colonna 4: Bottone import singolo
            already_queued = windows_path in queued_paths
            btn = self._create_row_button(row, already_queued)
            self.video_table.setCellWidget(row, 4, btn)

        self.video_table.setSortingEnabled(True)
        # Applica filtro giorni (se attivo nasconde le righe fuori range)
        self._apply_days_filter()

    def _on_days_filter_changed(self):
        self._apply_days_filter()

    def _on_format_filter_changed(self):
        fmt = self._get_selected_format()
        prev = getattr(self, '_prev_format_filter', None)
        self._prev_format_filter = fmt
        # ASS/SSA usa un endpoint diverso: serve refresh dal server.
        # Stessa cosa quando si torna da ASS/SSA a un altro filtro.
        if fmt == 'assssa' or prev == 'assssa':
            if self.is_loaded:
                self.refresh_data()
        else:
            self._apply_days_filter()

    def _get_selected_format(self):
        """Ritorna None (tutti) | 'pgs' | 'vobsub' | 'nosrt' (nessuna traccia subtitle)."""
        return self.format_combo.currentData() if hasattr(self, 'format_combo') else None

    def _apply_days_filter(self):
        """Nasconde righe per filtro giorni E filtro formato. Aggiorna badge/bottone."""
        min_days = self.days_spinbox.value()
        fmt = self._get_selected_format()
        visible_count = 0
        for row in range(self.video_table.rowCount()):
            days_item = self.video_table.item(row, 2)
            days = int(days_item.text()) if days_item else 0
            hide = min_days > 0 and days < min_days
            if not hide and fmt:
                name_item = self.video_table.item(row, 0)
                row_fmt = name_item.data(Qt.ItemDataRole.UserRole + 1) if name_item else None
                has_ass = name_item.data(Qt.ItemDataRole.UserRole + 3) if name_item else False
                if fmt == 'nosrt':
                    if row_fmt is not None:
                        hide = True
                elif fmt == 'assssa':
                    if not has_ass:
                        hide = True
                else:
                    # Filtri bitmap (pgs/vobsub): mostra SOLO i file che necessitano
                    # davvero OCR (has_only_bitmap_subs). Un file con stream PGS ma sub
                    # testo ITA presente (es. Dumbo, La fabbrica di cioccolato) ha
                    # bitmap_format='pgs' ma has_only_bitmap_subs=False → non è un job OCR
                    # e non deve apparire qui (coerenza col badge ASS/SSA mostrato in tabella).
                    only_bitmap = name_item.data(Qt.ItemDataRole.UserRole + 4) if name_item else False
                    # 'mixed' soddisfa sia PGS sia VOBSUB
                    if not only_bitmap or not (row_fmt == fmt or row_fmt == 'mixed'):
                        hide = True
            self.video_table.setRowHidden(row, hide)
            if not hide:
                visible_count += 1
        self._update_badge(visible_count)
        self.import_all_btn.setEnabled(visible_count > 0)
        if fmt == 'assssa':
            self.import_all_btn.setText("Converti ASS/SSA")
        else:
            self.import_all_btn.setText(tr('import_filtered'))

    def _create_sub_badge(self, video: dict) -> QWidget:
        """
        Badge cliccabile per file con solo sottotitoli bitmap italiani.
        Etichetta in base al formato (PGS/VOB/MIX); clic = conversione OCR.
        """
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        windows_path = video.get('windows_path', '')
        fmt = video.get('bitmap_format')  # 'pgs' | 'vobsub' | 'mixed' | None
        label, kind = self._badge_label_kind(fmt)

        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "background-color: #E65100;"
            "color: #ffffff;"
            "border: none;"
            "border-radius: 3px;"
            "font-size: 7pt;"
            "font-weight: bold;"
            "padding: 1px 4px;"
            "}"
            "QPushButton:hover { background-color: #FB8C00; }"
        )
        btn.setToolTip(
            "Sottotitoli immagine (PGS/VOBSUB).\n"
            "Clicca per convertirli in SRT testuale tramite OCR\n"
            "(strategia configurabile in Opzioni → OCR Sottotitoli)."
        )
        btn.clicked.connect(lambda _checked, p=windows_path, k=kind: self._start_bitmap_ocr(p, k))
        lay.addWidget(btn)
        return container

    @staticmethod
    def _badge_label_kind(fmt):
        """Mappa bitmap_format → (etichetta badge, kind per il motore OCR)."""
        if fmt == 'vobsub':
            return "VOB", "vobsub"
        if fmt == 'mixed':
            return "MIX", "pgs"   # default PGS per i misti (la traccia PGS è preferibile)
        return "PGS", "pgs"

    def _create_ass_badge(self, video: dict) -> QWidget:
        """Badge cliccabile per file con sottotitoli ASS/SSA embedded convertibili in SRT."""
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        video_id = video.get('id')
        conversion_status = video.get('conversion_status')

        btn = QPushButton("ASS")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if conversion_status == 'done':
            btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: #ffffff; border: none;"
                " border-radius: 3px; font-size: 7pt; font-weight: bold; padding: 1px 4px; }"
            )
            btn.setToolTip("ASS/SSA già convertito in SRT.")
            btn.setEnabled(False)
        else:
            btn.setStyleSheet(
                "QPushButton { background-color: #6A0DAD; color: #ffffff; border: none;"
                " border-radius: 3px; font-size: 7pt; font-weight: bold; padding: 1px 4px; }"
                "QPushButton:hover { background-color: #8B2FC9; }"
            )
            btn.setToolTip(
                "Sottotitoli ASS/SSA embedded.\n"
                "Clicca per convertirli in SRT via FFmpeg sul server Library Scanner."
            )
            btn.clicked.connect(lambda _checked, vid=video_id: self._start_ass_conversion([vid]))
        lay.addWidget(btn)
        return container

    def _start_ass_conversion(self, video_ids: list):
        """Avvia la conversione ASS/SSA→SRT sul server Library Scanner.
        video_ids vuota = converti tutti i pending (stessa semantica del server)."""
        url     = self.config.get('library_scanner_url', '').strip().rstrip('/')
        api_key = self.config.get('library_scanner_api_key', '').strip()
        if not url or not api_key:
            QMessageBox.warning(self, "Conversione ASS/SSA",
                                "Library Scanner non configurato (URL o API key mancante).")
            return
        try:
            import requests
            # Corpo vuoto = server converte tutti i pending; IDs specifici = solo quei file
            body = {"video_ids": video_ids} if video_ids else {}
            resp = requests.post(
                f"{url}/api/subtitles/convert/start",
                json=body,
                headers={"X-API-Key": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                if video_ids:
                    desc = f"{len(video_ids)} file"
                    self._log(f"⚙️ Conversione ASS→SRT avviata sul server: {desc}")
                else:
                    desc = "tutti i file pending"
                    self._log("⚙️ Conversione ASS→SRT avviata sul server (tutti i pending)")
                QMessageBox.information(
                    self, "Conversione ASS/SSA",
                    f"Conversione avviata sul server per {desc}.\n"
                    "Controlla lo stato nell'interfaccia web Library Scanner.")
            else:
                self._log(f"⚠ Conversione ASS: errore server {resp.status_code}")
                QMessageBox.warning(self, "Conversione ASS/SSA",
                                    f"Errore dal server: {resp.status_code}\n{resp.text[:200]}")
        except Exception as e:
            self._log(f"⚠ Conversione ASS: errore connessione: {e}")
            QMessageBox.warning(self, "Conversione ASS/SSA",
                                f"Errore di connessione al server:\n{e}")

    # ========================================================================
    # OCR PGS → SRT
    # ========================================================================

    def _start_bitmap_ocr(self, windows_path: str, kind: str, force_auto: bool = False):
        """
        Avvia la conversione OCR dei sottotitoli bitmap del file indicato.
        kind: 'pgs' | 'vobsub'. force_auto=True forza la strategia automatica
        (usato dal batch, per evitare decine di dialog di revisione a catena).
        """
        if not windows_path:
            return
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, tr('ocr_section_title'),
                                    "Un'altra conversione OCR è già in corso.")
            return

        from gui.ocr_worker import OcrWorker
        from core.pgs_types import CFG_STRATEGY, DEFAULT_STRATEGY, STRATEGY_AUTO

        config = get_config()
        strategy = STRATEGY_AUTO if force_auto else config.get(CFG_STRATEGY, DEFAULT_STRATEGY)

        self._ocr_video_path = windows_path
        self._ocr_kind = kind
        self._ocr_name = Path(windows_path).name
        self._log(f"🔤 OCR avviato ({kind}, {strategy}): {self._ocr_name}")
        # Mostra il job nella coda di processamento (display; non in trascrizione)
        kind_label = 'VOBSUB' if kind == 'vobsub' else 'PGS'
        self._ocr_add_job(windows_path, kind_label)
        self._ocr_set_status(windows_path, 'processing', 0)

        self._ocr_worker = OcrWorker(windows_path, config, strategy, mode="ocr", kind=kind)
        self._ocr_worker.events_ready.connect(self._on_ocr_events_ready)
        self._ocr_worker.auto_done.connect(self._on_ocr_auto_done)
        self._ocr_worker.unsupported.connect(self._on_ocr_unsupported)
        self._ocr_worker.lang_unsupported.connect(self._on_ocr_lang_unsupported)
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.log_message.connect(self._log)
        self._ocr_worker.progress.connect(self._on_ocr_progress)
        self._ocr_worker.finished.connect(self._on_ocr_phase_finished)
        self._ocr_worker.start()

    def _on_ocr_progress(self, percent: int, label: str):
        """Mostra l'avanzamento dello step corrente (estrazione / OCR)."""
        name = getattr(self, '_ocr_name', '')
        if getattr(self, '_ocr_batch_active', False):
            done = getattr(self, '_ocr_batch_ok', 0) + getattr(self, '_ocr_batch_fail', 0)
            total = getattr(self, '_ocr_batch_total', 0)
            prefix = f"OCR batch {min(done + 1, total)}/{total} · "
        else:
            prefix = "OCR · "
        self.ocr_progress_label.setText(f"{prefix}{name} — {label} {percent}%")
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'processing', percent)

    def _log(self, msg: str):
        """Inoltra un messaggio al log della main window, se disponibile."""
        try:
            self.main_window.log_message(msg)
        except Exception:
            logger.info(msg)

    def _ocr_add_job(self, path: str, kind_label: str):
        try:
            self.main_window.add_ocr_jobs([(path, kind_label)])
        except Exception:
            pass

    def _ocr_set_status(self, path: str, status: str, progress: int = 0):
        try:
            self.main_window.set_ocr_job_status(path, status, progress)
        except Exception:
            pass

    def _on_ocr_events_ready(self, events, language):
        """Ramo review: apri la UI di revisione mirata, poi scrivi il risultato."""
        from gui.ocr_review_dialog import OcrReviewDialog
        from PyQt6.QtWidgets import QDialog

        dlg = OcrReviewDialog(events, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            srt_text = dlg.get_srt()
            self._run_ocr_writeback(srt_text, language)
        else:
            self._log(f"OCR annullato in revisione: {self._ocr_name}")
            self.ocr_progress_label.setText("")
            self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'failed', 0)

    def _run_ocr_writeback(self, srt_text: str, language: str):
        from gui.ocr_worker import OcrWorker
        from core.pgs_types import CFG_STRATEGY, DEFAULT_STRATEGY
        config = get_config()
        strategy = config.get(CFG_STRATEGY, DEFAULT_STRATEGY)
        self._log(f"Scrittura SRT: {self._ocr_name}")
        self._ocr_worker = OcrWorker(
            self._ocr_video_path, config, strategy, mode="writeback",
            srt_text=srt_text, language=language, kind=getattr(self, '_ocr_kind', 'pgs'))
        self._ocr_worker.writeback_done.connect(self._on_ocr_writeback_done)
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.log_message.connect(self._log)
        self._ocr_worker.finished.connect(self._on_ocr_phase_finished)
        self._ocr_worker.start()

    def _on_ocr_auto_done(self, ok: bool):
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''),
                             'completed' if ok else 'failed', 100)
        if ok:
            self._mark_row_done(getattr(self, '_ocr_video_path', ''))
            self.notify_subtitle_created(getattr(self, '_ocr_video_path', ''))
        if getattr(self, '_ocr_batch_active', False):
            self._ocr_batch_ok += 1 if ok else 0
            self._ocr_batch_fail += 0 if ok else 1
            return
        self.ocr_progress_label.setText("")
        if ok:
            QMessageBox.information(self, tr('ocr_section_title'),
                                   f"Conversione completata:\n{self._ocr_name}")
            self._auto_refresh()
        else:
            QMessageBox.warning(self, tr('ocr_section_title'),
                                f"Conversione fallita:\n{self._ocr_name}")

    def _on_ocr_writeback_done(self, ok: bool):
        self.ocr_progress_label.setText("")
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''),
                             'completed' if ok else 'failed', 100)
        if ok:
            self._mark_row_done(getattr(self, '_ocr_video_path', ''))
            self.notify_subtitle_created(getattr(self, '_ocr_video_path', ''))
            QMessageBox.information(self, tr('ocr_section_title'),
                                   f"SRT scritto:\n{self._ocr_name}")
            self._auto_refresh()
        else:
            QMessageBox.warning(self, tr('ocr_section_title'),
                                f"Scrittura SRT fallita:\n{self._ocr_name}")

    def _mark_row_done(self, windows_path: str):
        """Marca la riga del file convertito (bottone ✓ disabilitato)."""
        if not windows_path:
            return
        for row in range(self.video_table.rowCount()):
            item = self.video_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == windows_path:
                btn = self.video_table.cellWidget(row, 4)
                if btn:
                    btn.setText("✓")
                    btn.setEnabled(False)
                return

    def _on_ocr_unsupported(self, msg: str):
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'failed', 0)
        if getattr(self, '_ocr_batch_active', False):
            self._ocr_batch_fail += 1
            return
        QMessageBox.information(self, tr('ocr_section_title'),
                               f"{self._ocr_name}\n\n{msg}")

    def _on_ocr_lang_unsupported(self, msg: str):
        """Lingua della traccia senza traineddata Tesseract: file saltato, marcato completato."""
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'completed', 100)
        if getattr(self, '_ocr_batch_active', False):
            # Non conta come fallimento: il file era OK, la lingua non è gestita.
            return
        self.ocr_progress_label.setText("")
        QMessageBox.information(self, tr('ocr_section_title'),
                               f"{getattr(self, '_ocr_name', '')}\n\nLingua non supportata — file saltato.\n{msg}")

    def _on_ocr_error(self, msg: str):
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'failed', 0)
        if getattr(self, '_ocr_batch_active', False):
            self._ocr_batch_fail += 1
            return
        QMessageBox.warning(self, tr('ocr_section_title'),
                            f"Errore OCR:\n{self._ocr_name}\n\n{msg}")

    def _on_ocr_phase_finished(self):
        # Cleanup legato al sender (non all'attributo condiviso): il write-back
        # riassegna self._ocr_worker a un nuovo worker, quindi azzeriamo solo se
        # il worker che ha terminato è ancora quello corrente.
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is getattr(self, '_ocr_worker', None):
            self._ocr_worker = None
        # In modalità batch, avanza al file successivo quando il worker è concluso.
        if getattr(self, '_ocr_batch_active', False) and self._ocr_worker is None:
            self._ocr_batch_advance()

    # ── Superpower: acquisisce tutti i bitmap dalla Library Scanner e li processa localmente ──
    def _superpower_ocr(self):
        """Recupera tutti i file bitmap (PGS/VOBSUB) dalla Library Scanner e li processa qui."""
        url     = self.config.get('library_scanner_url', '').strip().rstrip('/')
        api_key = self.config.get('library_scanner_api_key', '').strip()
        if not url or not api_key:
            QMessageBox.warning(self, "⚡ Superpower",
                                "Library Scanner non configurato (URL o API key mancante).")
            return
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, "⚡ Superpower", "Un OCR è già in corso.")
            return
        reply = QMessageBox.question(
            self, "⚡ Superpower OCR",
            "Recupera tutti i file con sottotitoli bitmap (PGS/VOBSUB) dalla Library Scanner\n"
            "e li converte qui localmente tramite OCR.\n\n"
            "Continuare?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        import requests
        headers = {"X-API-Key": api_key}
        try:
            resp = requests.get(f"{url}/api/subtitles/list",
                                params={"issue_type": "bitmap", "limit": 500},
                                headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            QMessageBox.warning(self, "⚡ Superpower",
                                f"Errore recupero lista dalla Library Scanner:\n{e}")
            return
        items = []
        for v in data.get("videos", []):
            fmt = v.get("bitmap_format")
            if not fmt:
                continue
            wp = v.get("windows_path", "")
            if not wp:
                continue
            _, kind = self._badge_label_kind(fmt)
            items.append((wp, kind))
        if not items:
            QMessageBox.information(self, "⚡ Superpower",
                                    "Nessun file bitmap trovato nella Library Scanner.")
            return
        self._ocr_superpower_active = True
        self._log(f"⚡ Superpower: {len(items)} file bitmap acquisiti dalla Library Scanner")
        self._start_ocr_batch(items)

    def _superpower_reactivate(self):
        """Chiamato al termine del batch Superpower."""
        self._ocr_superpower_active = False
        self._log("⚡ Superpower OCR completato")

    # ── Batch OCR (Importa tutti con filtro formato attivo) ────────────────
    def _start_ocr_batch(self, items: list):
        """items: lista di (windows_path, kind). Converte tutti in AUTO, in sequenza."""
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, tr('ocr_section_title'),
                                    "Un'altra conversione OCR è già in corso.")
            return
        if not items:
            return
        self._ocr_batch_active = True
        self._ocr_batch_queue = list(items)
        self._ocr_batch_total = len(items)
        self._ocr_batch_ok = 0
        self._ocr_batch_fail = 0
        # Pre-popola la coda di processamento con tutti i job (stato "in coda").
        for path, kind in items:
            self._ocr_add_job(path, 'VOBSUB' if kind == 'vobsub' else 'PGS')
        self._log(f"🔤 Batch OCR avviato: {self._ocr_batch_total} file (automatico)")
        self._ocr_batch_advance()

    def _ocr_batch_advance(self):
        queue = getattr(self, '_ocr_batch_queue', [])
        if not queue:
            # batch concluso
            self._ocr_batch_active = False
            self.ocr_progress_label.setText("")
            if getattr(self, '_ocr_superpower_active', False):
                self._superpower_reactivate()
            # Spegni al termine: schedula PRIMA del QMessageBox (che è bloccante ma
            # i singleShot scattano comunque nel nested event loop del dialogo modale).
            if self.main_window.shutdown_checkbox.isChecked():
                QTimer.singleShot(5000, self.main_window.shutdown_system)
            QMessageBox.information(
                self, tr('ocr_section_title'),
                f"Batch OCR completato.\nConvertiti: {self._ocr_batch_ok} · "
                f"Falliti: {self._ocr_batch_fail} (su {self._ocr_batch_total})")
            self._auto_refresh()
            return
        path, kind = queue.pop(0)
        self._start_bitmap_ocr(path, kind, force_auto=True)

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
            if self.video_table.cellWidget(row, 4) is btn:
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

        # File con ASS/SSA: conversione sul server invece di aggiungere in coda locale
        has_ass = item.data(Qt.ItemDataRole.UserRole + 3)
        if has_ass:
            video_id = item.data(Qt.ItemDataRole.UserRole + 2)
            if video_id:
                self._start_ass_conversion([video_id])
            return

        # File con sottotitoli bitmap (PGS/VOBSUB): OCR locale, NON trascrizione audio
        bitmap_format = item.data(Qt.ItemDataRole.UserRole + 1)
        if bitmap_format:
            _, kind = self._badge_label_kind(bitmap_format)
            btn = self.video_table.cellWidget(row, 4)
            if btn:
                btn.setText("✓")
                btn.setEnabled(False)
            self._start_bitmap_ocr(path, kind)
            return

        added = self._import_paths([path])
        if added > 0:
            btn = self.video_table.cellWidget(row, 4)
            if btn:
                btn.setText("✓")
                btn.setEnabled(False)
                btn.setToolTip(tr('already_queued'))

    def _import_all(self):
        fmt = self._get_selected_format()

        # Filtro ASS/SSA: corpo vuoto → server converte TUTTI i pending, non solo quelli in tabella
        if fmt == 'assssa':
            self._start_ass_conversion([])
            return

        # Filtro bitmap (PGS/VOBSUB): batch OCR locale, NON aggiunge in coda trascrizione
        if fmt in ('pgs', 'vobsub'):
            items = []
            for row in range(self.video_table.rowCount()):
                if not self.video_table.isRowHidden(row):
                    item = self.video_table.item(row, 0)
                    if item:
                        path = item.data(Qt.ItemDataRole.UserRole)
                        bf   = item.data(Qt.ItemDataRole.UserRole + 1)
                        if path and bf:
                            _, kind = self._badge_label_kind(bf)
                            items.append((path, kind))
            if items:
                self._start_ocr_batch(items)
            return

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
                        btn = self.video_table.cellWidget(row, 4)
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
                    self.main_window.file_list.addItem(self.main_window._make_file_item(path))
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
        # Tieni vivi i worker (più notifiche concorrenti durante un batch).
        if not hasattr(self, '_notify_workers'):
            self._notify_workers = []
        w = _NotifyWorker(url, api_key, str(video_path))
        w.done.connect(self._on_notify_done)
        w.finished.connect(lambda w=w: self._notify_workers.remove(w)
                           if w in self._notify_workers else None)
        self._notify_workers.append(w)
        w.start()

    def _on_notify_done(self, success: bool):
        # Durante un batch NON ricaricare per ogni file: il refresh avviene a fine batch.
        if success and not getattr(self, '_ocr_batch_active', False):
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
        self.video_table.setColumnWidth(3, 38)
        self.video_table.setColumnWidth(4, 24)
        table_width = self.video_table.viewport().width()
        fixed_cols = 60 + 50 + 38 + 24
        file_width = max(120, table_width - fixed_cols)
        self.video_table.setColumnWidth(0, file_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'video_table'):
            self._auto_resize_file_column()

    def _update_badge(self, count: int):
        self.badge_label.setText(str(count))
        self.badge_label.setVisible(count > 0)
