"""
Adaptive Batch Size Settings Widget
File: gui/adaptive_batch_settings_widget.py

Pannello GUI per configurare l'AdaptiveBatchSizeManager.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QGroupBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import logging

from utils.config import get_config

logger = logging.getLogger(__name__)

DIALOG_STYLE = """
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
    QSpinBox, QDoubleSpinBox {
        background-color: #2a2a2a;
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 4px;
        color: #ffffff;
        padding: 4px 8px;
        min-width: 80px;
    }
    QSpinBox:focus, QDoubleSpinBox:focus {
        border: 1px solid rgba(33,150,243,0.6);
    }
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
    QPushButton#resetBtn {
        background-color: rgba(120,120,120,160);
    }
    QPushButton#resetBtn:hover { background-color: rgba(150,150,150,200); }
"""


class AdaptiveBatchSettingsWidget(QWidget):
    """
    Widget per configurare il sistema di batch adattivo.

    Segnali:
      settings_changed — emesso dopo ogni salvataggio
    """

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self.init_ui()
        self._load_values()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Abilita/disabilita ─────────────────────────────────────────
        enable_group = QGroupBox("Stato")
        enable_layout = QVBoxLayout()

        self.enable_checkbox = QCheckBox("Abilita Adaptive Batch Size")
        self.enable_checkbox.setToolTip(
            "Se disabilitato, ogni traduttore usa il batch size fisso predefinito."
        )
        self.enable_checkbox.stateChanged.connect(self._on_enable_changed)
        enable_layout.addWidget(self.enable_checkbox)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #888888; font-size: 9pt;")
        enable_layout.addWidget(self.status_label)

        enable_group.setLayout(enable_layout)
        layout.addWidget(enable_group)

        # ── Batch Size ─────────────────────────────────────────────────
        size_group = QGroupBox("Batch Size")
        size_form = QFormLayout()
        size_form.setSpacing(8)

        self.initial_spin = QSpinBox()
        self.initial_spin.setRange(0, 64)
        self.initial_spin.setSpecialValueText("Auto-detect")
        self.initial_spin.setToolTip(
            "0 = auto-detect dalla VRAM disponibile.\n"
            ">= 24 GB → 16  |  >= 12 GB → 8  |  >= 8 GB → 4  |  < 8 GB → 2"
        )
        size_form.addRow("Initial size (0=auto):", self.initial_spin)

        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 16)
        self.min_spin.setToolTip("Minimo assoluto (panic fallback dopo 3 OOM consecutivi).")
        size_form.addRow("Min size:", self.min_spin)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 64)
        self.max_spin.setToolTip("Massimo consentito durante la fase di crescita.")
        size_form.addRow("Max size:", self.max_spin)

        size_group.setLayout(size_form)
        layout.addWidget(size_group)

        # ── Warm-up e Soglie ───────────────────────────────────────────
        tuning_group = QGroupBox("Warm-up e Soglie Memoria")
        tuning_form = QFormLayout()
        tuning_form.setSpacing(8)

        self.warmup_spin = QSpinBox()
        self.warmup_spin.setRange(0, 20)
        self.warmup_spin.setToolTip(
            "Numero di batch iniziali in cui il sistema prova ad aumentare "
            "il batch size se la memoria lo consente."
        )
        tuning_form.addRow("Warmup batches:", self.warmup_spin)

        self.high_spin = QDoubleSpinBox()
        self.high_spin.setRange(0.50, 1.00)
        self.high_spin.setSingleStep(0.05)
        self.high_spin.setDecimals(2)
        self.high_spin.setToolTip(
            "Se utilizzo VRAM > soglia alta → riduci batch di 2.\n"
            "Default: 0.85 (85%)"
        )
        tuning_form.addRow("Soglia alta (riduci):", self.high_spin)

        self.low_spin = QDoubleSpinBox()
        self.low_spin.setRange(0.10, 0.90)
        self.low_spin.setSingleStep(0.05)
        self.low_spin.setDecimals(2)
        self.low_spin.setToolTip(
            "Se utilizzo VRAM < soglia bassa → aumenta batch di 1.\n"
            "Default: 0.60 (60%)"
        )
        tuning_form.addRow("Soglia bassa (aumenta):", self.low_spin)

        tuning_group.setLayout(tuning_form)
        layout.addWidget(tuning_group)

        # ── Note ───────────────────────────────────────────────────────
        note = QLabel(
            "Le modifiche sono applicate al prossimo avvio della traduzione.\n"
            "Il transcriber usa questi valori solo con BatchedInferencePipeline."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 8pt; padding: 4px 0;")
        layout.addWidget(note)

        # ── Bottoni ────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()

        self.reset_btn = QPushButton("Ripristina Default")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.clicked.connect(self._reset_defaults)

        self.save_btn = QPushButton("Salva")
        self.save_btn.clicked.connect(self._save)

        btn_layout.addWidget(self.reset_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Logica
    # ------------------------------------------------------------------

    def _load_values(self):
        """Carica i valori correnti dalla config."""
        cfg = self.config.get_adaptive_batch_config()

        self.enable_checkbox.setChecked(cfg['enabled'])
        self.initial_spin.setValue(self.config.get('adaptive_batch_initial_size', 0))
        self.min_spin.setValue(cfg['min_size'])
        self.max_spin.setValue(cfg['max_size'])
        self.warmup_spin.setValue(cfg['warmup_batches'])
        self.high_spin.setValue(cfg['high_threshold'])
        self.low_spin.setValue(cfg['low_threshold'])

        self._update_status(cfg['enabled'])
        self._update_controls_state(cfg['enabled'])

    def _on_enable_changed(self, state):
        enabled = bool(state)
        self._update_status(enabled)
        self._update_controls_state(enabled)

    def _update_status(self, enabled: bool):
        if enabled:
            cfg = self.config.get_adaptive_batch_config()
            initial_txt = "auto" if not cfg['initial_size'] else str(cfg['initial_size'])
            self.status_label.setText(
                f"Attivo — initial={initial_txt}, "
                f"min={cfg['min_size']}, max={cfg['max_size']}, "
                f"warmup={cfg['warmup_batches']}"
            )
        else:
            self.status_label.setText("Disabilitato — usa batch size fisso dei modelli.")

    def _update_controls_state(self, enabled: bool):
        for w in [self.initial_spin, self.min_spin, self.max_spin,
                  self.warmup_spin, self.high_spin, self.low_spin]:
            w.setEnabled(enabled)

    def _save(self):
        """Salva i valori nel config."""
        self.config.set('adaptive_batch_enabled',       self.enable_checkbox.isChecked(), save=False)
        self.config.set('adaptive_batch_initial_size',  self.initial_spin.value(),         save=False)
        self.config.set('adaptive_batch_min_size',      self.min_spin.value(),             save=False)
        self.config.set('adaptive_batch_max_size',      self.max_spin.value(),             save=False)
        self.config.set('adaptive_batch_warmup_batches',self.warmup_spin.value(),          save=False)
        self.config.set('adaptive_batch_high_threshold',self.high_spin.value(),            save=False)
        self.config.set('adaptive_batch_low_threshold', self.low_spin.value(),             save=False)
        self.config.save()

        self._update_status(self.enable_checkbox.isChecked())
        self.settings_changed.emit()
        logger.info("Adaptive batch settings salvate.")

    def _reset_defaults(self):
        """Ripristina i valori di default."""
        self.enable_checkbox.setChecked(True)
        self.initial_spin.setValue(0)
        self.min_spin.setValue(1)
        self.max_spin.setValue(24)
        self.warmup_spin.setValue(5)
        self.high_spin.setValue(0.85)
        self.low_spin.setValue(0.60)
