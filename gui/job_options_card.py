"""
Job Options Card
File: gui/job_options_card.py

CollapsibleCard che raggruppa le opzioni per-job del pannello sinistro:
target language, upload OpenSubtitles, gender correction, shutdown post-job.

Il summary nell'header riflette lo stato corrente in modo compatto:
"ITA · ↗ OS · ⚧ · ⏻"

Introdotto in Fase 3 del GUI revamp per ridurre densita' del pannello sinistro.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox, QComboBox, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from utils.config import get_config
from utils.translations import tr
from gui.collapsible_card import CollapsibleCard
from gui.services.job_options_service import JobOptionsService


# Lingue sottotitoli supportate (riprese da main_window per compatibilita').
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


class JobOptionsCard(CollapsibleCard):
    """Card per le opzioni di processing condivise da tutti i file in coda."""

    summary_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(title=tr('job_options_title'), parent=parent)
        self.config = get_config()
        self.options = JobOptionsService(self.config)

        body = self._build_options_body()
        self.setBody(body)

        # Stato iniziale (chiuso/aperto da config)
        opened = self.options.card_open()
        self.setExpanded(opened, animated=False)
        self.toggled.connect(self._on_toggled)

        self._refresh_summary()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_options_body(self) -> QWidget:
        body = QWidget()
        body.setMinimumWidth(0)  # non vincola la larghezza minima del pannello sinistro
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        opts = self.options.load()

        # --- Target language ------------------------------------------
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_label = QLabel(tr('srt_language_label'))

        self.target_lang_combo = QComboBox()
        self.target_lang_combo.setMinimumWidth(0)  # "Cinese Semplificato" altrimenti fissa la larghezza
        current_lang = opts.target_language
        for display_name, code in SUBTITLE_LANGUAGES:
            self.target_lang_combo.addItem(display_name, code)
        idx = next(
            (i for i, (_, c) in enumerate(SUBTITLE_LANGUAGES) if c == current_lang),
            0,
        )
        self.target_lang_combo.setCurrentIndex(idx)
        self.target_lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        lang_row.addWidget(lang_label)
        lang_row.addWidget(self.target_lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # --- Upload OpenSubtitles -------------------------------------
        self.opensubtitles_checkbox = QCheckBox(tr('upload_opensubtitles'))
        self.opensubtitles_checkbox.setObjectName("modernCheckbox")
        self.opensubtitles_checkbox.setChecked(opts.opensubtitles_upload)
        self.opensubtitles_checkbox.stateChanged.connect(self._on_os_changed)

        # --- Muxa il sottotitolo creato nel video ---------------------
        self.mux_checkbox = QCheckBox(tr('mux_into_video_checkbox'))
        self.mux_checkbox.setObjectName("modernCheckbox")
        self.mux_checkbox.setToolTip(tr('mux_into_video_tip'))
        self.mux_checkbox.setChecked(opts.mux_into_video)
        self.mux_checkbox.stateChanged.connect(self._on_mux_changed)

        # Le 4 caselle sono disposte in una griglia 2x2 (vedi sotto); politica orizzontale Ignored:
        # il testo non impone una larghezza minima al pannello.

        # --- Gender correction ----------------------------------------
        self.gender_correction_checkbox = QCheckBox(tr('gender_correction_checkbox'))
        self.gender_correction_checkbox.setObjectName("modernCheckbox")
        self.gender_correction_checkbox.setChecked(opts.gender_correction)
        self.gender_correction_checkbox.stateChanged.connect(self._on_gender_changed)

        # --- Shutdown after processing --------------------------------
        self.shutdown_checkbox = QCheckBox(tr('shutdown_checkbox'))
        self.shutdown_checkbox.setObjectName("modernCheckbox")
        self.shutdown_checkbox.setChecked(opts.shutdown_after)
        self.shutdown_checkbox.stateChanged.connect(self._on_shutdown_changed)
        self.gender_correction_checkbox.setToolTip(tr('gender_correction_tip'))
        self.shutdown_checkbox.setToolTip(tr('shutdown_tip'))

        # Genere avanzato e Spegni sulla stessa riga (come Upload/Muxa)
        # Griglia 2x2 a colonne di pari larghezza: le caselle di ogni colonna restano allineate.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for r, row in enumerate(((self.opensubtitles_checkbox, self.mux_checkbox),
                                 (self.gender_correction_checkbox, self.shutdown_checkbox))):
            for c, cb in enumerate(row):
                cb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                grid.addWidget(cb, r, c)
        layout.addLayout(grid)

        return body

    # ------------------------------------------------------------------
    # Persistenza + summary
    # ------------------------------------------------------------------

    def _on_lang_changed(self, index: int):
        code = self.target_lang_combo.itemData(index)
        self.options.set_target_language(code)
        self._refresh_summary()

    def _on_os_changed(self, state):
        self.options.set_opensubtitles_upload(state == Qt.CheckState.Checked.value)
        self._refresh_summary()

    def _on_mux_changed(self, state):
        self.options.set_mux_into_video(state == Qt.CheckState.Checked.value)
        self._refresh_summary()

    def _on_gender_changed(self, state):
        self.options.set_gender_correction(state == Qt.CheckState.Checked.value)
        self._refresh_summary()

    def _on_shutdown_changed(self, state):
        self.options.set_shutdown_after(state == Qt.CheckState.Checked.value)
        self._refresh_summary()

    def _on_toggled(self, opened: bool):
        self.options.set_card_open(opened)

    def _refresh_summary(self):
        text = JobOptionsService.summary_text(
            self.target_lang_combo.currentData(),
            self.opensubtitles_checkbox.isChecked(),
            self.mux_checkbox.isChecked(),
            self.gender_correction_checkbox.isChecked(),
            self.shutdown_checkbox.isChecked(),
        )
        self.setSummary(text)
        self.summary_changed.emit(text)
