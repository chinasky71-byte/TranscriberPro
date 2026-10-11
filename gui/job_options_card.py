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
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from utils.config import get_config
from utils.translations import tr
from gui.collapsible_card import CollapsibleCard


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

        body = self._build_options_body()
        self.setBody(body)

        # Stato iniziale (chiuso/aperto da config)
        opened = bool(self.config.get('ui_job_card_open', False))
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
        layout.setSpacing(8)

        # --- Target language ------------------------------------------
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_label = QLabel(tr('srt_language_label'))

        self.target_lang_combo = QComboBox()
        self.target_lang_combo.setMinimumWidth(0)  # "Cinese Semplificato" altrimenti fissa la larghezza
        current_lang = self.config.get_target_language()
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
        self.opensubtitles_checkbox.setChecked(
            self.config.get('opensubtitles_upload_enabled', True)
        )
        self.opensubtitles_checkbox.stateChanged.connect(self._on_os_changed)

        # --- Muxa il sottotitolo creato nel video ---------------------
        self.mux_checkbox = QCheckBox(tr('mux_into_video_checkbox'))
        self.mux_checkbox.setObjectName("modernCheckbox")
        self.mux_checkbox.setToolTip(tr('mux_into_video_tip'))
        self.mux_checkbox.setChecked(
            self.config.get('mux_subtitle_into_video', False)
        )
        self.mux_checkbox.stateChanged.connect(self._on_mux_changed)

        # Upload OpenSubtitles e Muxa nel video sulla STESSA riga. Politica orizzontale Ignored: il testo
        # delle caselle non impone una larghezza minima al pannello (il ridimensionamento delle colonne
        # resta libero); le caselle si dividono la riga in proporzione alla lunghezza del testo.
        os_mux_row = QHBoxLayout()
        os_mux_row.setSpacing(12)
        for cb in (self.opensubtitles_checkbox, self.mux_checkbox):
            cb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            os_mux_row.addWidget(cb, max(1, len(cb.text())))
        layout.addLayout(os_mux_row)

        # --- Gender correction ----------------------------------------
        self.gender_correction_checkbox = QCheckBox(tr('gender_correction_checkbox'))
        self.gender_correction_checkbox.setObjectName("modernCheckbox")
        self.gender_correction_checkbox.setChecked(
            self.config.get('gender_correction_enabled', False)
        )
        self.gender_correction_checkbox.stateChanged.connect(self._on_gender_changed)
        layout.addWidget(self.gender_correction_checkbox)

        # --- Shutdown after processing --------------------------------
        self.shutdown_checkbox = QCheckBox(tr('shutdown_checkbox'))
        self.shutdown_checkbox.setObjectName("modernCheckbox")
        self.shutdown_checkbox.setChecked(
            self.config.get('shutdown_after_processing', False)
        )
        self.shutdown_checkbox.stateChanged.connect(self._on_shutdown_changed)
        layout.addWidget(self.shutdown_checkbox)

        return body

    # ------------------------------------------------------------------
    # Persistenza + summary
    # ------------------------------------------------------------------

    def _on_lang_changed(self, index: int):
        code = self.target_lang_combo.itemData(index)
        if code:
            self.config.set_target_language(code)
        self._refresh_summary()

    def _on_os_changed(self, state):
        self.config.set(
            'opensubtitles_upload_enabled',
            state == Qt.CheckState.Checked.value,
        )
        self._refresh_summary()

    def _on_mux_changed(self, state):
        self.config.set(
            'mux_subtitle_into_video',
            state == Qt.CheckState.Checked.value,
        )
        self._refresh_summary()

    def _on_gender_changed(self, state):
        self.config.set(
            'gender_correction_enabled',
            state == Qt.CheckState.Checked.value,
        )
        self._refresh_summary()

    def _on_shutdown_changed(self, state):
        self.config.set(
            'shutdown_after_processing',
            state == Qt.CheckState.Checked.value,
        )
        self._refresh_summary()

    def _on_toggled(self, opened: bool):
        try:
            self.config.set('ui_job_card_open', opened)
        except Exception:
            pass

    def _refresh_summary(self):
        parts = []

        code = self.target_lang_combo.currentData() or ""
        parts.append(code.upper() if code else "—")

        if self.opensubtitles_checkbox.isChecked():
            parts.append("↗ OS")
        if self.mux_checkbox.isChecked():
            parts.append("⧉ mux")
        if self.gender_correction_checkbox.isChecked():
            parts.append("⚧")
        if self.shutdown_checkbox.isChecked():
            parts.append("⏻")

        text = " · ".join(parts)
        self.setSummary(text)
        self.summary_changed.emit(text)
