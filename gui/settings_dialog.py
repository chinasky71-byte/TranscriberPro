"""
Settings Dialog (unificato)
File: gui/settings_dialog.py

Finestra unica con sidebar (QListWidget) + contenuto (QStackedWidget) che
raccoglie le 5 sezioni di impostazioni dell'app:

  - Generali        -> GeneralSettingsWidget
  - Trascrizione    -> ProfileSelectionDialog(embed=True)
  - Traduzione     -> TranslationModelDialog(embed=True)
  - Batch Adattivo  -> AdaptiveBatchSettingsWidget
  - OpenSubtitles   -> OpenSubtitlesSettingsWidget

Introdotta in Fase 2 del GUI revamp per sostituire le 4 finestre separate
aperte dai pulsanti dell'header sinistro di MainWindow.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QLabel, QPushButton, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from utils.config import get_config
from utils.translations import tr
from gui.icons import svg_icon
from gui.design_tokens import T
from gui.theme import set_role


# Identificatori stabili delle tab (usati per initial_tab e per la
# persistenza in config 'ui_settings_last_tab').
TAB_GENERAL = 'general'
TAB_JOBS = 'jobs'
TAB_TRANSCRIPTION = 'transcription'
TAB_TRANSLATION = 'translation'
TAB_BATCH = 'batch'
TAB_OPENSUBTITLES = 'opensubtitles'
TAB_OCR = 'ocr'

_TAB_ORDER = (
    TAB_GENERAL,
    TAB_JOBS,
    TAB_TRANSCRIPTION,
    TAB_TRANSLATION,
    TAB_BATCH,
    TAB_OPENSUBTITLES,
    TAB_OCR,
)

_TAB_ICON = {
    TAB_GENERAL:       'wrench',
    TAB_JOBS:          'list',
    TAB_TRANSCRIPTION: 'mic',
    TAB_TRANSLATION:   'globe',
    TAB_BATCH:         'target',
    TAB_OPENSUBTITLES: 'cloud',
    TAB_OCR:           'caption',
}


class SettingsDialog(QDialog):
    """Dialog di impostazioni con sidebar + stacked content."""

    def __init__(self, parent=None, initial_tab: str | None = None):
        super().__init__(parent)
        self.config = get_config()

        self.setWindowTitle(tr('settings_dialog_title'))
        self.setModal(True)
        self.setMinimumSize(840, 620)
        self.resize(840, 620)
        self.setSizeGripEnabled(True)

        # Mappa tab_id -> (label, widget)
        self._pages: dict[str, QWidget] = {}

        self._build_ui()

        # Esc chiude
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.accept)

        # Tab iniziale: parametro esplicito > ultimo usato > primo
        wanted = initial_tab or self.config.get('ui_settings_last_tab', TAB_GENERAL)
        if wanted not in _TAB_ORDER:
            wanted = TAB_GENERAL
        self._select_tab(wanted)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Header ----------------------------------------------------
        header = QFrame()
        header.setObjectName("settingsHeader")
        header.setFixedHeight(48)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 12, 0)
        header_layout.setSpacing(8)

        title = QLabel(tr('settings_dialog_title'))
        title.setObjectName("settingsTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")

        header_layout.addWidget(title)

        outer.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("settingsHeaderSep")
        outer.addWidget(sep)

        # --- Body: sidebar + stacked ----------------------------------
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar.setSpacing(2)
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.currentRowChanged.connect(self._on_row_changed)

        # Stacked content
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")

        # Wrapper per il content con padding
        content_wrap = QWidget()
        content_wrap.setObjectName("settingsContentWrap")
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.stack)

        body.addWidget(self.sidebar)
        body.addWidget(content_wrap, stretch=1)

        outer.addLayout(body, stretch=1)

        # Costruzione delle 5 pagine. La logica di cablaggio sta in un
        # metodo separato cosi' eventuali errori di import di una singola
        # pagina non rompono l'intero dialog.
        self._populate_pages()

    def _populate_pages(self):
        """Registra le tab nella sidebar con placeholder vuoti.

        I widget reali vengono istanziati in modo lazy al momento della
        prima selezione di ciascuna tab (_on_row_changed), per evitare
        import pesanti che bloccano il main thread all'apertura del dialog.
        """
        labels = {
            TAB_GENERAL: tr('settings_tab_general'),
            TAB_JOBS: tr('settings_tab_jobs'),
            TAB_TRANSCRIPTION: tr('settings_tab_transcription'),
            TAB_TRANSLATION: tr('settings_tab_translation'),
            TAB_BATCH: tr('settings_tab_batch'),
            TAB_OPENSUBTITLES: tr('settings_tab_opensubtitles'),
            TAB_OCR: tr('ocr_section_title'),
        }

        self._page_built: list[bool] = [False] * len(_TAB_ORDER)

        for tab_id in _TAB_ORDER:
            self._pages[tab_id] = None
            self.stack.addWidget(QWidget())  # placeholder vuoto

            item = QListWidgetItem(labels[tab_id])
            item.setIcon(svg_icon(_TAB_ICON.get(tab_id, 'settings'), 16, T.fg_2))
            item.setData(Qt.ItemDataRole.UserRole, tab_id)
            item.setSizeHint(QSize(0, 36))
            self.sidebar.addItem(item)

    def _build_page(self, tab_id: str) -> QWidget:
        """Istanzia il widget concreto per la tab indicata."""
        if tab_id == TAB_GENERAL:
            from gui.general_settings_widget import GeneralSettingsWidget
            return GeneralSettingsWidget(parent=self)

        if tab_id == TAB_JOBS:
            from gui.job_options_card import JobOptionsPanel
            return JobOptionsPanel(parent=self, go_to_tab=self._select_tab)

        if tab_id == TAB_TRANSCRIPTION:
            from gui.profile_dialog import ProfileSelectionDialog
            return ProfileSelectionDialog(parent=self, embed=True)

        if tab_id == TAB_TRANSLATION:
            from gui.translation_model_dialog import TranslationModelDialog
            return TranslationModelDialog(parent=self, embed=True)

        if tab_id == TAB_BATCH:
            from gui.adaptive_batch_settings_widget import AdaptiveBatchSettingsWidget
            return AdaptiveBatchSettingsWidget(parent=self)

        if tab_id == TAB_OPENSUBTITLES:
            from gui.opensubtitles_settings_widget import OpenSubtitlesSettingsWidget
            return OpenSubtitlesSettingsWidget(parent=self)

        if tab_id == TAB_OCR:
            from gui.ocr_settings_widget import OcrSettingsWidget
            return OcrSettingsWidget(parent=self)

        raise ValueError(f"Unknown settings tab: {tab_id}")

    @staticmethod
    def _build_error_page(tab_id: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(f"[{tab_id}]\n\n{message}")
        label.setWordWrap(True)
        set_role(label, 'danger')
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignTop)
        return page

    # ------------------------------------------------------------------
    # Logica
    # ------------------------------------------------------------------

    def _select_tab(self, tab_id: str):
        if tab_id not in _TAB_ORDER:
            tab_id = TAB_GENERAL
        idx = _TAB_ORDER.index(tab_id)
        self.sidebar.setCurrentRow(idx)

    def _on_row_changed(self, row: int):
        if row < 0 or row >= len(_TAB_ORDER):
            return
        tab_id = _TAB_ORDER[row]

        # Lazy build DIFFERITO: prima si mostra il placeholder "Caricamento…"
        # (feedback immediato al click), poi al tick successivo dell'event
        # loop si costruisce il widget reale. Così anche una pagina lenta
        # non lascia mai l'utente davanti a un click "morto".
        if not self._page_built[row]:
            self._page_built[row] = True
            placeholder = self.stack.widget(row)
            if isinstance(placeholder, QWidget) and placeholder.layout() is None:
                lay = QVBoxLayout(placeholder)
                lbl = QLabel(tr('loading_preview'))
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                set_role(lbl, 'muted')
                lay.addWidget(lbl)
            self.stack.setCurrentIndex(row)
            QTimer.singleShot(0, lambda r=row, t=tab_id: self._deferred_build(r, t))
        else:
            self.stack.setCurrentIndex(row)
            page = self._pages.get(tab_id)
            refresh = getattr(page, 'refresh_from_config', None)
            if callable(refresh):               # un'altra scheda puo' aver cambiato lo stesso valore (upload, genere)
                try:
                    refresh()
                except Exception:
                    pass

        # Persisti l'ultima tab visitata
        try:
            self.config.set('ui_settings_last_tab', tab_id)
        except Exception:
            pass

    def _deferred_build(self, row: int, tab_id: str):
        """Costruisce il widget reale della tab e sostituisce il placeholder."""
        try:
            widget = self._build_page(tab_id)
        except Exception as exc:
            widget = self._build_error_page(tab_id, str(exc))
        self._pages[tab_id] = widget
        was_current = (self.stack.currentIndex() == row)
        placeholder = self.stack.widget(row)
        host = widget
        if tab_id == TAB_OPENSUBTITLES:
            # pagina piu' alta dei 620px del dialog: scorre invece di schiacciare i campi uno sull'altro
            from PyQt6.QtWidgets import QScrollArea
            widget.setMinimumHeight(widget.sizeHint().height())
            host = QScrollArea()
            host.setFrameShape(QFrame.Shape.NoFrame)
            host.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # niente fermata di Tab sull'area di scorrimento
            host.setWidgetResizable(True)
            host.setWidget(widget)
        self.stack.insertWidget(row, host)
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        if was_current:
            self.stack.setCurrentIndex(row)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    @property
    def current_tab(self) -> str:
        row = self.sidebar.currentRow()
        if row < 0 or row >= len(_TAB_ORDER):
            return TAB_GENERAL
        return _TAB_ORDER[row]
