"""
Opzioni job PREDEFINITE
File: gui/job_options_card.py

Pannello della scheda "Opzioni job" delle Impostazioni: lingua dei sottotitoli, upload OpenSubtitles, muxing, correzione del genere.
Sono i valori di partenza di ogni file; per un file solo si cambiano dal menu tasto destro della coda (eccezioni per file).
Ogni cambio scrive subito in config.json (il processo figlio lo rilegge a ogni file). Lo spegnimento a fine coda
sta nel pannello principale accanto ad Avvia (riguarda tutta la coda, non il singolo file).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox, QComboBox, QLabel, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from utils.config import get_config
from utils.translations import tr
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


class JobOptionsPanel(QWidget):
    """Valori predefiniti delle opzioni job. `go_to_tab(tab_id)`: apre un'altra scheda delle Impostazioni (motore di traduzione, OCR)."""

    summary_changed = pyqtSignal(str)

    def __init__(self, parent=None, go_to_tab=None):
        super().__init__(parent)
        self.config = get_config()
        self.options = JobOptionsService(self.config)
        self._go_to_tab = go_to_tab
        self._build()
        self._refresh_summary()

    # ------------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        opts = self.options.load()

        intro = QLabel(tr('job_defaults_intro'))
        intro.setWordWrap(True)
        intro.setObjectName("mutedLabel")
        layout.addWidget(intro)

        # --- Lingua dei sottotitoli -----------------------------------
        lang_row = QHBoxLayout()
        lang_row.setSpacing(8)
        lang_row.addWidget(QLabel(tr('srt_language_label')))
        self.target_lang_combo = QComboBox()
        self.target_lang_combo.setMinimumWidth(0)
        for display_name, code in SUBTITLE_LANGUAGES:
            self.target_lang_combo.addItem(display_name, code)
        self.target_lang_combo.setCurrentIndex(
            next((i for i, (_, c) in enumerate(SUBTITLE_LANGUAGES) if c == opts.target_language), 0))
        self.target_lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self.target_lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # --- Caselle ---------------------------------------------------
        self.opensubtitles_checkbox = QCheckBox(tr('upload_opensubtitles'))
        self.mux_checkbox = QCheckBox(tr('mux_into_video_checkbox'))
        self.mux_checkbox.setToolTip(tr('mux_into_video_tip'))
        self.gender_correction_checkbox = QCheckBox(tr('gender_correction_checkbox'))
        self.gender_correction_checkbox.setToolTip(tr('gender_correction_tip'))
        for cb, val, slot in ((self.opensubtitles_checkbox, opts.opensubtitles_upload, self._on_os_changed),
                              (self.mux_checkbox, opts.mux_into_video, self._on_mux_changed),
                              (self.gender_correction_checkbox, opts.gender_correction, self._on_gender_changed)):
            cb.setObjectName("modernCheckbox")
            cb.setChecked(val)
            cb.stateChanged.connect(slot)
            layout.addWidget(cb)

        # --- Impostazioni che vivono in altre schede -------------------
        self.engine_label = QLabel()
        self.ocr_label = QLabel()
        for lbl, tab, text_key in ((self.engine_label, 'translation', 'job_defaults_change_engine'),
                                   (self.ocr_label, 'ocr', 'job_defaults_change_ocr')):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(lbl, 1)
            btn = QPushButton(tr(text_key))
            btn.setObjectName("primaryButton")
            btn.clicked.connect(lambda _=False, t=tab: self._go_to_tab and self._go_to_tab(t))
            btn.setEnabled(self._go_to_tab is not None)
            row.addWidget(btn)
            layout.addLayout(row)
        layout.addStretch(1)
        self._refresh_other_labels()

    def _refresh_other_labels(self):
        from gui.services.job_options_service import engine_short, ocr_review_label
        self.engine_label.setText(tr('job_defaults_engine').format(engine=engine_short(self.config)))
        self.ocr_label.setText(tr('job_defaults_ocr').format(mode=ocr_review_label(self.config)))

    def showEvent(self, event):
        """Rilegge i valori dal config: altre schede (OpenSubtitles, Traduzione) possono averli cambiati mentre questa era aperta."""
        super().showEvent(event)
        o = self.options.load()
        for cb, val in ((self.opensubtitles_checkbox, o.opensubtitles_upload), (self.mux_checkbox, o.mux_into_video),
                        (self.gender_correction_checkbox, o.gender_correction)):
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
        self._refresh_other_labels()
        self._refresh_summary()

    # ------------------------------------------------------------------
    def _on_lang_changed(self, index: int):
        self.options.set_target_language(self.target_lang_combo.itemData(index))
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

    def _refresh_summary(self):
        self.summary_changed.emit(JobOptionsService.summary_text(
            self.target_lang_combo.currentData(), self.opensubtitles_checkbox.isChecked(),
            self.mux_checkbox.isChecked(), self.gender_correction_checkbox.isChecked(), False))
