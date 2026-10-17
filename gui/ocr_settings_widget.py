"""
OCR Settings Widget - GUI Controls
File: gui/ocr_settings_widget.py

FUNZIONALITÀ:
- Sezione "OCR Sottotitoli" delle Opzioni.
- Scelta strategia (Revisione mirata / Solo automatico) con commento esplicativo
  visibile sotto ciascuna opzione.
- Lingua OCR Tesseract.
- Soglia di confidenza per la revisione mirata.
- Modalità write-back (mux nell'MKV / file .srt sidecar).
- Path opzionale al binario Tesseract (vuoto = auto-detect dal PATH).

Le chiavi di configurazione e i valori provengono dal contratto core/pgs_types.py.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import pyqtSignal
import logging

from gui.styles import load_qss
from utils.config import get_config
from utils.translations import tr

from core.pgs_types import (
    CFG_STRATEGY, CFG_LANGUAGE, CFG_CONF_THRESHOLD, CFG_WRITEBACK, CFG_TESSERACT_PATH,
    CFG_OCR_WORKERS,
    STRATEGY_REVIEW, STRATEGY_AUTO, WRITEBACK_MUX, WRITEBACK_SIDECAR,
    DEFAULT_STRATEGY, DEFAULT_LANGUAGE, DEFAULT_CONF_THRESHOLD, DEFAULT_WRITEBACK,
    DEFAULT_OCR_WORKERS
)

logger = logging.getLogger(__name__)


class OcrSettingsWidget(QWidget):
    """
    Widget per gestire le impostazioni OCR dei sottotitoli bitmap (PGS→SRT).

    SIGNALS:
    - settings_changed: Emesso quando una qualsiasi impostazione cambia.
    """

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.config = get_config()

        self.init_ui()
        self.update_status()

    def init_ui(self):
        """Inizializza interfaccia"""
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # ========================================
        # GROUP: Strategia
        # ========================================
        strategy_group = QGroupBox(tr('ocr_strategy_group'))
        strategy_layout = QVBoxLayout()
        strategy_layout.setSpacing(6)

        self.strategy_button_group = QButtonGroup(self)

        # --- Opzione: Revisione mirata ---
        self.review_radio = QRadioButton(tr('ocr_strategy_review'))
        self.strategy_button_group.addButton(self.review_radio)
        strategy_layout.addWidget(self.review_radio)

        self.review_comment = QLabel(tr('ocr_strategy_review_comment'))
        self.review_comment.setWordWrap(True)
        self.review_comment.setObjectName("commentLabel")
        strategy_layout.addWidget(self.review_comment)

        # --- Opzione: Solo automatico ---
        self.auto_radio = QRadioButton(tr('ocr_strategy_auto'))
        self.strategy_button_group.addButton(self.auto_radio)
        strategy_layout.addWidget(self.auto_radio)

        self.auto_comment = QLabel(tr('ocr_strategy_auto_comment'))
        self.auto_comment.setWordWrap(True)
        self.auto_comment.setObjectName("commentLabel")
        strategy_layout.addWidget(self.auto_comment)

        self.review_radio.toggled.connect(self.on_strategy_changed)

        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)

        # ========================================
        # GROUP: OCR
        # ========================================
        ocr_group = QGroupBox(tr('ocr_engine_group'))
        ocr_form = QFormLayout()
        ocr_form.setSpacing(8)

        # Lingua OCR
        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText(tr('ocr_language_ph'))
        self.language_input.setToolTip(tr('ocr_language_tip'))
        self.language_input.editingFinished.connect(self.on_language_changed)
        ocr_form.addRow(tr('ocr_language_label'), self.language_input)

        # Soglia confidenza
        self.conf_spin = QSpinBox()
        self.conf_spin.setRange(0, 100)
        self.conf_spin.setSuffix(" %")
        self.conf_spin.setToolTip(tr('ocr_conf_threshold_tip'))
        self.conf_spin.valueChanged.connect(self.on_conf_threshold_changed)
        ocr_form.addRow(tr('ocr_conf_threshold_label'), self.conf_spin)

        # Worker OCR paralleli (0 = automatico)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 32)
        self.workers_spin.setSpecialValueText(tr('ocr_workers_auto'))
        self.workers_spin.setToolTip(tr('ocr_workers_tip'))
        self.workers_spin.valueChanged.connect(self.on_workers_changed)
        ocr_form.addRow(tr('ocr_workers_label'), self.workers_spin)

        # Path Tesseract (opzionale)
        self.tesseract_input = QLineEdit()
        self.tesseract_input.setPlaceholderText(tr('ocr_tesseract_path_ph'))
        self.tesseract_input.setToolTip(tr('ocr_tesseract_path_tip'))
        self.tesseract_input.editingFinished.connect(self.on_tesseract_path_changed)
        ocr_form.addRow(tr('ocr_tesseract_path_label'), self.tesseract_input)

        ocr_group.setLayout(ocr_form)
        layout.addWidget(ocr_group)

        # ========================================
        # GROUP: Write-back
        # ========================================
        writeback_group = QGroupBox(tr('ocr_writeback_group'))
        writeback_layout = QHBoxLayout()

        writeback_label = QLabel(tr('ocr_writeback_label'))
        self.writeback_combo = QComboBox()
        self.writeback_combo.addItem(tr('ocr_writeback_mux'), WRITEBACK_MUX)
        self.writeback_combo.addItem(tr('ocr_writeback_sidecar'), WRITEBACK_SIDECAR)
        self.writeback_combo.setToolTip(tr('ocr_writeback_tip'))
        self.writeback_combo.currentIndexChanged.connect(self.on_writeback_changed)

        writeback_layout.addWidget(writeback_label)
        writeback_layout.addWidget(self.writeback_combo)
        writeback_layout.addStretch()

        writeback_group.setLayout(writeback_layout)
        layout.addWidget(writeback_group)

        # Spacer
        layout.addStretch()

        self.setLayout(layout)

        # Apply styles
        self.apply_styles()

    def apply_styles(self):
        """Applica stili al widget"""
        self.setStyleSheet(load_qss('ocr_settings'))

    def update_status(self):
        """Carica nei controlli i valori correnti dalla configurazione."""
        # Strategia
        strategy = self.config.get(CFG_STRATEGY, DEFAULT_STRATEGY)
        self.review_radio.blockSignals(True)
        self.auto_radio.blockSignals(True)
        if strategy == STRATEGY_AUTO:
            self.auto_radio.setChecked(True)
        else:
            self.review_radio.setChecked(True)
        self.review_radio.blockSignals(False)
        self.auto_radio.blockSignals(False)

        # Lingua
        language = self.config.get(CFG_LANGUAGE, DEFAULT_LANGUAGE)
        self.language_input.blockSignals(True)
        self.language_input.setText(language or DEFAULT_LANGUAGE)
        self.language_input.blockSignals(False)

        # Soglia confidenza
        threshold = self.config.get(CFG_CONF_THRESHOLD, DEFAULT_CONF_THRESHOLD)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_CONF_THRESHOLD
        self.conf_spin.blockSignals(True)
        self.conf_spin.setValue(max(0, min(100, threshold)))
        self.conf_spin.blockSignals(False)

        # Worker OCR
        workers = self.config.get(CFG_OCR_WORKERS, DEFAULT_OCR_WORKERS)
        try:
            workers = int(workers)
        except (TypeError, ValueError):
            workers = DEFAULT_OCR_WORKERS
        self.workers_spin.blockSignals(True)
        self.workers_spin.setValue(max(0, min(32, workers)))
        self.workers_spin.blockSignals(False)

        # Write-back
        writeback = self.config.get(CFG_WRITEBACK, DEFAULT_WRITEBACK)
        idx = self.writeback_combo.findData(writeback)
        if idx < 0:
            idx = self.writeback_combo.findData(DEFAULT_WRITEBACK)
        self.writeback_combo.blockSignals(True)
        self.writeback_combo.setCurrentIndex(max(0, idx))
        self.writeback_combo.blockSignals(False)

        # Path Tesseract
        tesseract_path = self.config.get(CFG_TESSERACT_PATH, '')
        self.tesseract_input.blockSignals(True)
        self.tesseract_input.setText(tesseract_path or '')
        self.tesseract_input.blockSignals(False)

    def on_strategy_changed(self, checked: bool):
        """Handler cambio strategia (collegato al radio 'Revisione mirata')."""
        strategy = STRATEGY_REVIEW if self.review_radio.isChecked() else STRATEGY_AUTO
        self.config.set(CFG_STRATEGY, strategy)
        logger.info(f"Strategia OCR: {strategy}")
        self.settings_changed.emit()

    def on_language_changed(self):
        """Handler cambio lingua OCR."""
        language = self.language_input.text().strip() or DEFAULT_LANGUAGE
        self.config.set(CFG_LANGUAGE, language)
        logger.info(f"Lingua OCR: {language}")
        self.settings_changed.emit()

    def on_conf_threshold_changed(self, value: int):
        """Handler cambio soglia confidenza."""
        self.config.set(CFG_CONF_THRESHOLD, int(value))
        self.settings_changed.emit()

    def on_workers_changed(self, value: int):
        """Handler cambio numero worker OCR."""
        self.config.set(CFG_OCR_WORKERS, int(value))
        self.settings_changed.emit()

    def on_writeback_changed(self, index: int):
        """Handler cambio modalità write-back."""
        writeback = self.writeback_combo.itemData(index) or DEFAULT_WRITEBACK
        self.config.set(CFG_WRITEBACK, writeback)
        logger.info(f"Write-back OCR: {writeback}")
        self.settings_changed.emit()

    def on_tesseract_path_changed(self):
        """Handler cambio path Tesseract."""
        path = self.tesseract_input.text().strip()
        self.config.set(CFG_TESSERACT_PATH, path)
        self.settings_changed.emit()
