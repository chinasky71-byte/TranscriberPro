# -*- coding: utf-8 -*-
"""
Library Scanner Widget - Pannello collassabile per importare video senza sottotitoli
File: gui/library_scanner_widget.py
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QStackedLayout, QWidget,
    QLabel, QToolButton, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QSpinBox,
    QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QMutexLocker, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QIcon
from pathlib import Path
import logging
import re

from gui.design_tokens import T
from gui.styles import load_qss
from core.services import library_rows as LR
from gui.library_scanner_worker import LibraryScannerWorker
from gui.widgets import ElideLabel
from gui.icons import svg_icon
from gui.theme import set_flat
from utils.config import get_config
from utils.path_map import parse_map, to_local, to_server
from utils.translations import tr

logger = logging.getLogger(__name__)


def _dot_qss(color: str) -> str:
    """QSS del pallino di stato 10x10 (colore calcolato a runtime)."""
    return (
        f"background-color: {color}; border-radius: 5px;"
        "min-width: 10px; max-width: 10px;"
        "min-height: 10px; max-height: 10px;"
    )


def _badge_btn_qss(bg: str, hover: str | None = None) -> str:
    """QSS dei piccoli badge-pulsante colorati (PGS/VOB/ASS)."""
    qss = (
        f"QPushButton {{ background-color: {bg}; color: {T.white}; border: none;"
        " border-radius: 3px; font-size: 7pt; font-weight: bold; padding: 1px 2px; min-height: 0px; }"
    )
    if hover:
        qss += f"QPushButton:hover {{ background-color: {hover}; }}"
    return qss

# ── Italian audio detection ───────────────────────────────────────────────────
# La logica vive in core/services/library_rows.py (senza Qt); i nomi storici restano disponibili qui.
_IT_TAGS_RE = LR.IT_TAGS_RE
_FOREIGN_TAGS_RE = LR.FOREIGN_TAGS_RE
_detect_italian = LR.detect_italian


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


class _ApiCallWorker(QThread):
    """Chiamata API Library Scanner in background.

    Le requests sincrone sul thread GUI (timeout 10-15s) congelavano
    l'interfaccia se il server era lento o spento. done(0, msg) = errore
    di connessione; altrimenti (status_code, body).
    """
    done = pyqtSignal(int, str)

    def __init__(self, method: str, url: str, api_key: str,
                 json_body=None, params=None, timeout: int = 10):
        super().__init__()
        self._method = method
        self._url = url
        self._api_key = api_key
        self._json = json_body
        self._params = params
        self._timeout = timeout

    def run(self):
        try:
            import requests
            r = requests.request(
                self._method, self._url,
                json=self._json, params=self._params,
                headers={"X-API-Key": self._api_key},
                timeout=self._timeout,
            )
            self.done.emit(r.status_code, r.text)
        except Exception as e:
            self.done.emit(0, str(e))


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
        self._api_workers = []          # _ApiCallWorker attivi (no GC finché girano)
        self._ocr_deferred_queue = []   # job OCR in attesa che la pipeline principale si liberi
        self._ocr_mode_override = {}    # {path: 'review' | 'auto'}: scelta per file dal menu della coda (solo job differiti)
        self._ocr_strategy_used = None  # strategia del job OCR in corso (il writeback usa la stessa)
        if hasattr(main_window, 'processing_done'):
            main_window.processing_done.connect(self._drain_deferred_ocr)

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
        layout.setContentsMargins(8, 3, 8, 3)
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
        self.status_dot.setStyleSheet(_dot_qss(T.legacy_grey_888))
        layout.addWidget(self.status_dot)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(svg_icon('sync', 14, T.fg_2))   # icona SVG al posto dell'emoji
        self.refresh_btn.setIconSize(QSize(14, 14))
        self.refresh_btn.setObjectName("scannerRefreshBtn")
        self.refresh_btn.setFixedSize(20, 20)
        self.refresh_btn.setToolTip(tr('refresh'))
        self.refresh_btn.clicked.connect(self.refresh_data)
        layout.addWidget(self.refresh_btn)

        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 2, 8, 6)
        layout.setSpacing(4)

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
        self.days_spinbox.setFixedWidth(80)
        self.days_spinbox.valueChanged.connect(self._on_days_filter_changed)
        filter_layout.addWidget(self.days_spinbox)

        format_label = QLabel(tr('format_filter'))
        format_label.setObjectName("scannerFilterLabel")
        filter_layout.addWidget(format_label)

        self.format_combo = QComboBox()
        self.format_combo.setObjectName("scannerFilter")
        # userData: None=tutti, 'pgs', 'vobsub', 'assssa', 'nosrt'=nessuna traccia subtitle
        self.format_combo.addItem(tr('all_formats'), None)
        self.format_combo.addItem("PGS", "pgs")
        self.format_combo.addItem("VOBSUB", "vobsub")
        self.format_combo.addItem("ASS/SSA", "assssa")
        self.format_combo.addItem("No SRT", "nosrt")
        self.format_combo.currentIndexChanged.connect(self._on_format_filter_changed)
        filter_layout.addWidget(self.format_combo)

        # Tutto su una riga: le tendine si stringono (niente minimo imposto dal
        # testo) cosi' la riga non allarga il pannello e lo splitter lo puo' restringere.
        for combo in (self.type_combo, self.format_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(3)
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            filter_layout.setStretchFactor(combo, 1)
        layout.addLayout(filter_layout)

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
        self.video_table.setMinimumHeight(0)
        self.video_table.verticalHeader().setDefaultSectionSize(22)

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

        layout.addWidget(self.video_table, 1)  # stretch dentro il corpo della card (l'altezza della card resta quella naturale)

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

        self.superpower_btn = QPushButton("Superpower")
        self.superpower_btn.setIcon(svg_icon('sparkle', 14, T.accent))
        self.superpower_btn.setIconSize(QSize(14, 14))
        self.superpower_btn.setObjectName("scannerImportAllBtn")
        self.superpower_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.superpower_btn.setMinimumWidth(0)
        self.superpower_btn.setToolTip(tr('ls_superpower_tip'))
        self.superpower_btn.clicked.connect(self._superpower_ocr)
        buttons_layout.addWidget(self.superpower_btn)

        layout.addLayout(buttons_layout)

        # Avanzamento OCR (visibile solo durante la conversione)
        # ElideLabel: il testo dinamico (path file completo) NON deve mai imporre
        # un minimum width al pannello → niente ridimensionamento finestra.
        # L'avanzamento OCR e le statistiche condividono UNA riga (pila): durante l'OCR si vede l'avanzamento,
        # altrimenti "N senza sub / N totali". Altezza costante: la card non cambia mai di altezza.
        self.ocr_progress_label = ElideLabel("")
        self.ocr_progress_label.setObjectName("scannerStats")
        self.ocr_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Statistiche — anch'essa ElideLabel per non imporre minimum width
        self.stats_label = ElideLabel(tr('waiting_connection'))
        self.stats_label.setObjectName("scannerStats")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        status_row = QWidget()
        status_stack = QStackedLayout(status_row)
        status_stack.setContentsMargins(0, 0, 0, 0)
        status_stack.addWidget(self.stats_label)
        status_stack.addWidget(self.ocr_progress_label)
        _ocr_set_text = self.ocr_progress_label.setText

        def _ocr_text_and_swap(text, _set=_ocr_set_text, _stack=status_stack,
                               _ocr=self.ocr_progress_label, _stats=self.stats_label):
            _set(text)
            _stack.setCurrentWidget(_ocr if text else _stats)

        self.ocr_progress_label.setText = _ocr_text_and_swap
        status_stack.setCurrentWidget(self.stats_label)
        layout.addWidget(status_row)

        body.setMinimumHeight(0)
        return body

    # ========================================================================
    # STILE
    # ========================================================================

    def _apply_styles(self):
        self.setStyleSheet(load_qss('library_scanner'))

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
        text, without = LR.stats_text(stats)
        self.stats_label.setText(text)
        self._update_badge(without)

    def _on_error(self, message: str):
        logger.warning(f"Library Scanner: {message}")
        self.stats_label.setText(tr('error_status').format(message=message))

    def _update_status_dot(self, connected: bool):
        color = T.legacy_mat_green if connected else T.legacy_mat_red
        self.status_dot.setStyleSheet(_dot_qss(color))
        self.status_changed.emit(tr('mw_scanner_active') if connected else tr('mw_scanner_idle'))

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
        pmap = self._path_rules()

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
                name_item.setForeground(QColor(T.legacy_blue_link))
                name_item.setToolTip(tr('ls_audio_ita_tip').format(path=windows_path))
            else:
                name_item.setToolTip(windows_path)

            self.video_table.setItem(row, 0, name_item)

            # Colonna 1: Tipo
            type_item = QTableWidgetItem(LR.type_text(video.get('media_type', '')))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_table.setItem(row, 1, type_item)

            # Colonna 2: Giorni senza sub (ordinamento numerico)
            days = video.get('days_without_subs', 0)
            days_item = _NumericTableWidgetItem(str(days))
            days_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            days_cls = LR.days_class(days)
            if days_cls == 'danger':
                days_item.setForeground(QColor(T.legacy_pink))
            elif days_cls == 'warn':
                days_item.setForeground(QColor(T.legacy_mat_amber))
            self.video_table.setItem(row, 2, days_item)

            # Colonna 3: badge formato subtitle problematico
            kind_of_badge = LR.badge_kind(video)
            if kind_of_badge == 'bitmap':
                badge_widget = self._create_sub_badge(video)
            elif kind_of_badge == 'ass':
                badge_widget = self._create_ass_badge(video)
            else:
                badge_widget = set_flat(QWidget())
            self.video_table.setCellWidget(row, 3, badge_widget)

            # Colonna 4: Bottone import singolo
            already_queued = to_local(windows_path, pmap) in queued_paths
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
        if LR.reload_on_format_change(prev, fmt):
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
            name_item = self.video_table.item(row, 0)
            hide = LR.is_row_hidden(
                days, min_days, fmt,
                name_item.data(Qt.ItemDataRole.UserRole + 1) if name_item else None,
                name_item.data(Qt.ItemDataRole.UserRole + 3) if name_item else False,
                name_item.data(Qt.ItemDataRole.UserRole + 4) if name_item else False)
            self.video_table.setRowHidden(row, hide)
            if not hide:
                visible_count += 1
        self._update_badge(visible_count)
        self.import_all_btn.setEnabled(visible_count > 0)
        if fmt == 'assssa':
            self.import_all_btn.setText(tr('ls_convert_ass'))
        else:
            self.import_all_btn.setText(tr('import_filtered'))

    def _create_sub_badge(self, video: dict) -> QWidget:
        """
        Badge cliccabile per file con solo sottotitoli bitmap italiani.
        Etichetta in base al formato (PGS/VOB/MIX); clic = conversione OCR.
        """
        container = set_flat(QWidget())
        lay = QHBoxLayout(container)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        windows_path = video.get('windows_path', '')
        fmt = video.get('bitmap_format')  # 'pgs' | 'vobsub' | 'mixed' | None
        label, kind = self._badge_label_kind(fmt)

        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_badge_btn_qss(T.legacy_orange_deep, T.legacy_orange_hover))
        btn.setToolTip(tr('ls_bitmap_tip'))
        btn.clicked.connect(lambda _checked, p=windows_path, k=kind: self._start_bitmap_ocr(p, k))
        lay.addWidget(btn)
        return container

    @staticmethod
    def _badge_label_kind(fmt):
        """Mappa bitmap_format → (etichetta badge, kind per il motore OCR)."""
        return LR.badge_label_kind(fmt)

    def _create_ass_badge(self, video: dict) -> QWidget:
        """Badge cliccabile per file con sottotitoli ASS/SSA embedded convertibili in SRT."""
        container = set_flat(QWidget())
        lay = QHBoxLayout(container)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        video_id = video.get('id')
        conversion_status = video.get('conversion_status')

        btn = QPushButton("ASS")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if conversion_status == 'done':
            btn.setStyleSheet(_badge_btn_qss(T.legacy_mat_green_deep))
            btn.setToolTip(tr('ls_ass_done_tip'))
            btn.setEnabled(False)
        else:
            btn.setStyleSheet(_badge_btn_qss(T.legacy_violet, T.legacy_violet_hover))
            btn.setToolTip(tr('ls_ass_tip'))
            btn.clicked.connect(lambda _checked, vid=video_id: self._start_ass_conversion([vid]))
        lay.addWidget(btn)
        return container

    def _start_ass_conversion(self, video_ids: list):
        """Avvia la conversione ASS/SSA→SRT sul server Library Scanner.
        video_ids vuota = converti tutti i pending (stessa semantica del server).
        La POST gira in un _ApiCallWorker: il thread GUI non aspetta il server."""
        url     = self.config.get('library_scanner_url', '').strip().rstrip('/')
        api_key = self.config.get('library_scanner_api_key', '').strip()
        if not url or not api_key:
            QMessageBox.warning(self, tr('ls_ass_title'), tr('ls_not_configured'))
            return
        # Corpo vuoto = server converte tutti i pending; IDs specifici = solo quei file
        body = {"video_ids": video_ids} if video_ids else {}
        worker = _ApiCallWorker('post', f"{url}/api/subtitles/convert/start",
                                api_key, json_body=body, timeout=10)
        worker.done.connect(
            lambda status, text, vids=list(video_ids):
                self._on_ass_conversion_reply(status, text, vids))
        worker.finished.connect(lambda w=worker: self._untrack_api_worker(w))
        self._api_workers.append(worker)
        worker.start()

    def _on_ass_conversion_reply(self, status: int, text: str, video_ids: list):
        if status == 200:
            if video_ids:
                desc = tr('ls_n_files').format(n=len(video_ids))
                self._log(tr('ls_ass_log_started').format(desc=desc))
            else:
                desc = tr('ls_all_pending')
                self._log(tr('ls_ass_log_started_all'))
            QMessageBox.information(
                self, tr('ls_ass_title'),
                tr('ls_ass_started_body').format(desc=desc))
        elif status == 0:
            self._log(tr('ls_ass_log_conn_err').format(text=text))
            QMessageBox.warning(self, tr('ls_ass_title'),
                                tr('ls_conn_err').format(text=text))
        else:
            self._log(tr('ls_ass_log_srv_err').format(status=status))
            QMessageBox.warning(self, tr('ls_ass_title'),
                                tr('ls_srv_err').format(status=status, text=text[:200]))

    def _untrack_api_worker(self, worker):
        try:
            self._api_workers.remove(worker)
        except ValueError:
            pass

    # ========================================================================
    # OCR PGS → SRT
    # ========================================================================

    def is_deferred_ocr(self, path: str) -> bool:
        return any(t[0] == path for t in self._ocr_deferred_queue)

    def set_deferred_ocr_mode(self, paths, mode):
        """Revisione per file dei job OCR ancora in attesa: mode 'review' | 'auto' | None (= predefinita). Restituisce i path cambiati."""
        changed = []
        for p in paths:
            if not self.is_deferred_ocr(p):
                continue
            if mode in ('review', 'auto'):
                self._ocr_mode_override[p] = mode
            else:
                self._ocr_mode_override.pop(p, None)
            changed.append(p)
        return changed

    def _start_bitmap_ocr(self, windows_path: str, kind: str, force_auto: bool = False, strategy_override: str = None):
        """
        Avvia la conversione OCR dei sottotitoli bitmap del file indicato.
        kind: 'pgs' | 'vobsub'. force_auto=True forza la strategia automatica
        (usato dal batch, per evitare decine di dialog di revisione a catena).
        """
        if not windows_path:
            return
        # Se la pipeline di trascrizione è attiva, rinvia il job per evitare OOM
        if getattr(self.main_window, 'is_processing', False):
            kind_label = 'VOBSUB' if kind == 'vobsub' else 'PGS'
            self._ocr_deferred_queue.append((windows_path, kind, force_auto))
            self._ocr_add_job(windows_path, kind_label)
            self._ocr_set_status(windows_path, 'queued', 0)
            self._log(tr('ls_ocr_queued_log').format(name=Path(windows_path).name))
            return
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, tr('ocr_section_title'),
                                    tr('ls_ocr_other_running'))
            return

        from gui.ocr_worker import OcrWorker
        from core.pgs_types import CFG_STRATEGY, DEFAULT_STRATEGY, STRATEGY_AUTO

        config = get_config()
        strategy = STRATEGY_AUTO if force_auto else config.get(CFG_STRATEGY, DEFAULT_STRATEGY)
        if strategy_override in ('review', 'auto'):
            strategy = strategy_override
        self._ocr_strategy_used = strategy

        self._ocr_video_path = windows_path
        self._ocr_kind = kind
        self._ocr_name = Path(windows_path).name
        self._log(tr('ls_ocr_started_log').format(kind=kind, strategy=strategy, name=self._ocr_name))
        # Mostra il job nella coda di processamento (display; non in trascrizione)
        kind_label = 'VOBSUB' if kind == 'vobsub' else 'PGS'
        self._ocr_add_job(windows_path, kind_label)
        self._ocr_set_status(windows_path, 'processing', 0)

        self._ocr_worker = OcrWorker(to_local(windows_path, self._path_rules()), config, strategy, mode="ocr", kind=kind)
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
            self._log(tr('ls_ocr_cancel_log').format(name=self._ocr_name))
            self.ocr_progress_label.setText("")
            self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'failed', 0)

    def _run_ocr_writeback(self, srt_text: str, language: str):
        from gui.ocr_worker import OcrWorker
        from core.pgs_types import CFG_STRATEGY, DEFAULT_STRATEGY
        config = get_config()
        strategy = getattr(self, '_ocr_strategy_used', None) or config.get(CFG_STRATEGY, DEFAULT_STRATEGY)
        self._log(tr('ls_srt_write_log').format(name=self._ocr_name))
        self._ocr_worker = OcrWorker(
            to_local(self._ocr_video_path, self._path_rules()), config, strategy, mode="writeback",
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
                                   tr('ls_conv_done').format(name=self._ocr_name))
            self._auto_refresh()
        else:
            QMessageBox.warning(self, tr('ocr_section_title'),
                                tr('ls_conv_failed').format(name=self._ocr_name))

    def _on_ocr_writeback_done(self, ok: bool):
        self.ocr_progress_label.setText("")
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''),
                             'completed' if ok else 'failed', 100)
        if ok:
            self._mark_row_done(getattr(self, '_ocr_video_path', ''))
            self.notify_subtitle_created(getattr(self, '_ocr_video_path', ''))
            QMessageBox.information(self, tr('ocr_section_title'),
                                   tr('ls_srt_written').format(name=self._ocr_name))
            self._auto_refresh()
        else:
            QMessageBox.warning(self, tr('ocr_section_title'),
                                tr('ls_srt_write_failed').format(name=self._ocr_name))

    def _mark_row_done(self, windows_path: str):
        """Marca la riga del file convertito (bottone ✓ disabilitato)."""
        if not windows_path:
            return
        for row in range(self.video_table.rowCount()):
            item = self.video_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == windows_path:
                btn = self.video_table.cellWidget(row, 4)
                if btn:
                    btn.setIcon(QIcon())
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
                               tr('ls_lang_skipped').format(name=getattr(self, '_ocr_name', ''), msg=msg))

    def _on_ocr_error(self, msg: str):
        self._ocr_set_status(getattr(self, '_ocr_video_path', ''), 'failed', 0)
        if getattr(self, '_ocr_batch_active', False):
            self._ocr_batch_fail += 1
            return
        QMessageBox.warning(self, tr('ocr_section_title'),
                            tr('ls_ocr_error').format(name=self._ocr_name, msg=msg))

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
        if self._ocr_worker is None:
            if getattr(self, '_ocr_batch_active', False):
                self._ocr_batch_advance()
            else:
                self._drain_deferred_ocr()

    # ── Superpower: acquisisce tutti i bitmap dalla Library Scanner e li processa localmente ──
    def _superpower_ocr(self):
        """Recupera tutti i file bitmap (PGS/VOBSUB) dalla Library Scanner e li processa qui."""
        url     = self.config.get('library_scanner_url', '').strip().rstrip('/')
        api_key = self.config.get('library_scanner_api_key', '').strip()
        if not url or not api_key:
            QMessageBox.warning(self, "⚡ Superpower", tr('ls_not_configured'))
            return
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, "⚡ Superpower", tr('ls_ocr_running'))
            return
        reply = QMessageBox.question(
            self, "⚡ Superpower OCR",
            tr('ls_sp_confirm'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # GET in background (_ApiCallWorker): con il server lento/spento la
        # richiesta sincrona bloccava il thread GUI fino a 15s.
        self._log(tr('ls_sp_list_log'))
        worker = _ApiCallWorker('get', f"{url}/api/subtitles/list", api_key,
                                params={"issue_type": "bitmap", "limit": 500},
                                timeout=15)
        worker.done.connect(self._on_superpower_list_reply)
        worker.finished.connect(lambda w=worker: self._untrack_api_worker(w))
        self._api_workers.append(worker)
        worker.start()

    def _on_superpower_list_reply(self, status: int, text: str):
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, "⚡ Superpower", tr('ls_ocr_running'))
            return
        if status != 200:
            err = text if status == 0 else f"HTTP {status}: {text[:200]}"
            QMessageBox.warning(self, "⚡ Superpower",
                                tr('ls_sp_list_err').format(err=err))
            return
        try:
            import json as _json
            data = _json.loads(text)
        except Exception as e:
            QMessageBox.warning(self, "⚡ Superpower",
                                tr('ls_sp_bad_reply').format(err=e))
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
                                    tr('ls_sp_none'))
            return
        self._ocr_superpower_active = True
        self._log(tr('ls_sp_acquired_log').format(n=len(items)))
        self._start_ocr_batch(items)

    def _superpower_reactivate(self):
        """Chiamato al termine del batch Superpower."""
        self._ocr_superpower_active = False
        self._log(tr('ls_sp_done_log'))

    # ── Batch OCR (azione esplicita: Superpower) ───────────────────────────
    def _start_ocr_batch(self, items: list):
        """items: lista di (windows_path, kind). Converte tutti in AUTO, in sequenza."""
        if getattr(self, '_ocr_worker', None) is not None:
            QMessageBox.information(self, tr('ocr_section_title'),
                                    tr('ls_ocr_other_running'))
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
        self._log(tr('ls_batch_started_log').format(n=self._ocr_batch_total))
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
                tr('ls_batch_done').format(ok=self._ocr_batch_ok, fail=self._ocr_batch_fail,
                                           total=self._ocr_batch_total))
            self._auto_refresh()
            # Avvia eventuali job singoli che erano in attesa durante il batch
            self._drain_deferred_ocr()
            return
        path, kind = queue.pop(0)
        self._start_bitmap_ocr(path, kind, force_auto=True)

    def _drain_deferred_ocr(self):
        """Avvia il prossimo job OCR dalla coda differita (chiamato quando la pipeline si libera)."""
        if not self._ocr_deferred_queue:
            return
        if getattr(self, '_ocr_worker', None) is not None:
            return  # OCR già in corso
        if getattr(self.main_window, 'is_processing', False):
            return  # pipeline ripartita (sicurezza)
        windows_path, kind, force_auto = self._ocr_deferred_queue.pop(0)
        self._start_bitmap_ocr(windows_path, kind, force_auto, self._ocr_mode_override.pop(windows_path, None))

    def _create_row_button(self, row: int, already_queued: bool) -> QPushButton:
        btn = QPushButton("✓" if already_queued else "")
        btn.setProperty("class", "scannerAddBtn")
        if not already_queued:
            btn.setIcon(svg_icon('plus', 14, T.success))
            btn.setIconSize(QSize(14, 14))
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

        # File con sottotitoli bitmap (PGS/VOBSUB): entra nella coda come un file
        # normale. La pipeline lo instrada automaticamente all'OCR su "Avvia"
        # (routing STEP 1). NON avviare l'OCR qui: l'import deve solo accodare.
        # Per un OCR immediato l'utente usa il badge arancione o "Superpower".
        added = self._import_paths([path])
        if added > 0:
            btn = self.video_table.cellWidget(row, 4)
            if btn:
                btn.setIcon(QIcon())
                btn.setText("✓")
                btn.setEnabled(False)
                btn.setToolTip(tr('already_queued'))

    def _import_all(self):
        fmt = self._get_selected_format()

        # Filtro ASS/SSA: corpo vuoto → server converte TUTTI i pending, non solo quelli in tabella
        if fmt == 'assssa':
            self._start_ass_conversion([])
            return

        # Filtro bitmap (PGS/VOBSUB): i film entrano nella coda come file normali;
        # la pipeline li instrada all'OCR su "Avvia". L'import NON avvia l'OCR.
        # Per un OCR batch immediato l'utente usa "Superpower".
        # (nessun ramo speciale: cadono nel percorso di import generico sotto)

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
        pmap = self._path_rules()

        for row in range(self.video_table.rowCount()):
            if not self.video_table.isRowHidden(row):
                item = self.video_table.item(row, 0)
                if item:
                    wp = item.data(Qt.ItemDataRole.UserRole)
                    if to_local(wp, pmap) in queued_paths:
                        btn = self.video_table.cellWidget(row, 4)
                        if btn and btn.isEnabled():
                            btn.setIcon(QIcon())
                            btn.setText("✓")
                            btn.setEnabled(False)
                            btn.setToolTip(tr('already_queued'))

        if added > 0:
            self.main_window.log_message(tr('files_imported_log').format(added=added))

    def _import_paths(self, paths: list) -> int:
        if not paths:
            return 0

        added = 0
        pmap = self._path_rules()
        with QMutexLocker(self.main_window.queue_mutex):
            for path in paths:
                path = to_local(path, pmap)   # percorso del server -> file di questo computer (identita' con mappa vuota)
                qs = getattr(self.main_window, 'queue_service', None)
                if qs is not None and path and qs.is_active(path):
                    continue                  # gia' in coda o in lavorazione: il file in corso non e' piu' in processing_queue
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

    def _path_rules(self):
        """Regole server->locale delle Impostazioni (lista vuota = percorsi invariati, comportamento di Windows)."""
        return parse_map(self.config.get('library_scanner_path_map', ''))

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
        w = _NotifyWorker(url, api_key, to_server(str(video_path), self._path_rules()))
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
        return LR.selected_media_type(self.type_combo.currentIndex())

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
