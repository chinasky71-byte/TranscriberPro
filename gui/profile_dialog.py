"""
Profile Selection Dialog - VERSIONE OTTIMIZZATA
File: gui/profile_dialog.py

VERSIONE: v3.1 - Finestra Ridimensionabile Compatta

MODIFICHE v3.1:
✅ Altezza iniziale ridotta (600 → 480)
✅ Finestra completamente ridimensionabile
✅ Contenuto scrollabile automatico
✅ Widget profili compattati (padding ridotto 40%)
✅ Layout più efficiente con informazioni raggruppate
✅ Spaziature ottimizzate per risoluzioni basse
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QRadioButton,
                             QLabel, QPushButton, QButtonGroup, QFrame,
                             QScrollArea, QWidget, QComboBox, QGroupBox,
                             QCheckBox)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from core.services import transcription_settings_service as TS
from gui.design_tokens import T
from gui.styles import load_qss
from utils.config import get_config
from utils.transcription_profiles import TranscriptionProfile
from utils.translations import tr


# Decisione 02/10/2026: i profili sono fissi su 'maximum' (Config.get_transcription_profile
# con transcription_profile_locked=True): Qwen3 e Canary non ne traggono vantaggio e Whisper
# resta sempre alla massima qualita'. Le schede dei profili restano nel codice ma NON vengono
# mostrate. Per riattivarle: SHOW_PROFILE_CARDS = True e transcription_profile_locked = false
# nel config.json (la chiave viene scritta al primo salvataggio: cambiare il default non basta).
SHOW_PROFILE_CARDS = False


class ProfileSelectionDialog(QDialog):
    """
    Dialog per selezione profilo trascrizione
    
    CARATTERISTICHE v3.1:
    - Finestra ridimensionabile liberamente
    - Contenuto scrollabile automatico
    - Layout compatto ottimizzato
    - Altezza iniziale ridotta per compatibilità schermi
    """
    
    def __init__(self, parent=None, embed=False):
        super().__init__(parent)
        self.config = get_config()
        self._svc = TS.TranscriptionSettingsService(self.config)
        self.selected_profile = self._svc.current_profile()
        self.embed = embed

        if not embed:
            self.setWindowTitle(tr('profiles_title'))
            self.setModal(True)
            self.setMinimumWidth(650)
            self.setMinimumHeight(480)
            self.resize(700, 550)
            self.setSizeGripEnabled(True)

        self.init_ui()
        if not embed:
            self.apply_theme()
    
    def init_ui(self):
        """Inizializza interfaccia con scroll area"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Body (header + descrizione + scroll profili)
        body = self._build_body()
        main_layout.addWidget(body, stretch=1)

        # Button bar - solo se NON embedded (in SettingsDialog usiamo "Salva e chiudi" globale)
        if not self.embed:
            separator2 = QFrame()
            separator2.setFrameShape(QFrame.Shape.HLine)
            separator2.setObjectName("separator")
            main_layout.addWidget(separator2)

            buttons_layout = QHBoxLayout()
            buttons_layout.setSpacing(10)
            buttons_layout.addStretch()

            cancel_btn = QPushButton(tr('cancel'))
            cancel_btn.setObjectName("cancelButton")
            cancel_btn.setMinimumWidth(110)
            cancel_btn.setFixedHeight(36)
            cancel_btn.clicked.connect(self.reject)
            buttons_layout.addWidget(cancel_btn)

            ok_btn = QPushButton(tr('confirm'))
            ok_btn.setObjectName("okButton")
            ok_btn.setMinimumWidth(110)
            ok_btn.setFixedHeight(36)
            ok_btn.clicked.connect(self.accept)
            buttons_layout.addWidget(ok_btn)

            main_layout.addLayout(buttons_layout)

        self.setLayout(main_layout)

    def _build_body(self) -> QWidget:
        """Costruisce il body widget (header + scroll profili).

        Usato sia in modalita' standalone (init_ui lo wrappa con button bar)
        sia in modalita' embed (chiamato direttamente dal SettingsDialog).
        """
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(10)
        body_layout.setContentsMargins(0, 0, 0, 0)

        if SHOW_PROFILE_CARDS:
            header = self.create_header()
            body_layout.addWidget(header)

            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setObjectName("separator")
            body_layout.addWidget(separator)

            desc_label = QLabel(tr('profiles_desc'))
            desc_label.setObjectName("descLabel")
            desc_label.setWordWrap(True)
            body_layout.addWidget(desc_label)

        # ── Motore di trascrizione (sistema multi-engine) ──
        # Pattern userData: addItem(label, valore_config) + findData/itemData;
        # salvataggio immediato su cambio (stesso stile embed del resto del tab).
        engine_group = QGroupBox(tr('engine_group'))
        engine_outer = QVBoxLayout()
        engine_layout = QHBoxLayout()
        engine_label = QLabel(tr('engine_label'))
        self.engine_combo = QComboBox()
        for label, value in TS.engine_choices():
            self.engine_combo.addItem(label, value)
        self.engine_combo.setToolTip(tr('engine_tip'))

        current_mode = self._svc.engine_mode()
        idx = self.engine_combo.findData(current_mode)
        if idx < 0:
            idx = self.engine_combo.findData('auto')
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(max(0, idx))
        self.engine_combo.blockSignals(False)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)

        engine_layout.addWidget(engine_label)
        engine_layout.addWidget(self.engine_combo)
        engine_layout.addStretch()
        engine_outer.addLayout(engine_layout)
        # Tempi tipici per motore (misure 02/10/2026) + nota sul profilo fisso.
        times_label = QLabel(tr('engine_times_info'))
        times_label.setObjectName("engineTimesInfo")
        times_label.setStyleSheet(f"color: {T.fg_2}; font-size: 11px; font-weight: 400;")
        times_label.setWordWrap(True)
        engine_outer.addWidget(times_label)
        engine_group.setLayout(engine_outer)
        body_layout.addWidget(engine_group)

        # ── Stile dialoghi professionale (trattini Netflix) ──
        # Attiva la diarization automatica + SubtitleFormatter per ogni
        # trascrizione; persistenza immediata come il resto del tab.
        dialogue_group = QGroupBox(tr('dialogue_style_group'))
        dialogue_layout = QHBoxLayout()
        self.dialogue_checkbox = QCheckBox(tr('dialogue_style_label'))
        self.dialogue_checkbox.setToolTip(tr('dialogue_style_tip'))
        self.dialogue_checkbox.blockSignals(True)
        self.dialogue_checkbox.setChecked(
            self._svc.dialogue_style())
        self.dialogue_checkbox.blockSignals(False)
        self.dialogue_checkbox.toggled.connect(self._on_dialogue_style_toggled)
        dialogue_layout.addWidget(self.dialogue_checkbox)
        dialogue_layout.addStretch()
        dialogue_group.setLayout(dialogue_layout)
        body_layout.addWidget(dialogue_group)

        if not SHOW_PROFILE_CARDS:
            body_layout.addStretch(1)
            return body

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setObjectName("profileScrollArea")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(0, 0, 5, 0)

        self.button_group = QButtonGroup(self)
        for profile in TranscriptionProfile:
            profile_widget = self.create_profile_widget(profile)
            scroll_layout.addWidget(profile_widget)
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        body_layout.addWidget(scroll_area, stretch=1)
        return body
    
    def create_header(self):
        """Crea header dialog compatto"""
        header = QLabel(tr('profiles_header'))
        header.setObjectName("dialogHeader")
        
        font = QFont()
        font.setPointSize(14)  # 16 → 14 (più compatto)
        font.setBold(True)
        header.setFont(font)
        
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return header
    
    def create_profile_widget(self, profile: TranscriptionProfile):
        """
        Crea widget COMPATTO per singolo profilo
        
        OTTIMIZZAZIONI v3.1:
        - Padding ridotto 40%
        - Informazioni raggruppate su singole righe
        - Font size ridotto per compattezza
        """
        # Container
        frame = QFrame()
        frame.setObjectName("profileFrame")
        
        layout = QHBoxLayout()
        # ✅ OTTIMIZZATO: Margins ridotti (15,12 → 10,8)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)  # 15 → 12
        
        # Radio button
        radio = QRadioButton()
        radio.setObjectName("profileRadio")
        radio.setProperty("profile", profile.value)
        
        # Seleziona se è il profilo corrente
        if profile.value == self.selected_profile:
            radio.setChecked(True)
        
        # Connetti al button group
        self.button_group.addButton(radio)
        
        # Collega toggled con lambda usando parametro di default per cattura corretta del profilo
        # IMPORTANTE: profile=profile crea una closure corretta catturando il valore corrente
        radio.toggled.connect(lambda checked, p=profile.value: self.on_profile_toggled(p, checked))
        
        layout.addWidget(radio, 0)  # No stretch
        
        # ========================================
        # ✅ OTTIMIZZATO: Info profilo COMPATTE
        # ========================================
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)  # 5 → 4
        
        card = next(c for c in TS.profile_cards() if c.value == profile.value)

        # --- RIGA 1: Nome + Badge ---
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)

        name_label = QLabel(card.name_html)
        name_label.setObjectName("profileName")
        name_layout.addWidget(name_label)

        # Badge raccomandato per BALANCED
        if card.recommended_badge:
            badge = QLabel(card.recommended_badge)
            badge.setObjectName("recommendedBadge")
            name_layout.addWidget(badge)

        name_layout.addStretch()
        info_layout.addLayout(name_layout)

        # --- RIGA 2: Descrizione (compatta) ---
        desc_label = QLabel(card.description)
        desc_label.setObjectName("profileDesc")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        # --- RIGA 3: Parametri + Tempo (TUTTO SU UNA RIGA) ---
        params_layout = QHBoxLayout()
        params_layout.setSpacing(12)

        # Parametri tecnici compatti
        params_label = QLabel(card.params)
        params_label.setObjectName("profileParams")
        params_layout.addWidget(params_label)

        # Tempo stimato (stesso rigo)
        time_label = QLabel(card.time)
        time_label.setObjectName("profileTime")
        params_layout.addWidget(time_label)

        params_layout.addStretch()
        info_layout.addLayout(params_layout)

        # --- Warning se presente (compatto) ---
        if card.warning:
            warning_label = QLabel(card.warning)
            warning_label.setObjectName("profileWarning")
            warning_label.setWordWrap(True)
            info_layout.addWidget(warning_label)

        layout.addLayout(info_layout, stretch=1)
        
        frame.setLayout(layout)
        return frame
    
    def _format_speed(self, speed_factor: float) -> str:
        """
        Formatta speed factor in percentuale leggibile
        """
        return TS.format_speed(speed_factor)

    def _on_engine_changed(self, index: int):
        """Callback cambio motore di trascrizione: persistenza immediata."""
        self._svc.set_engine_mode(self.engine_combo.itemData(index))

    def _on_dialogue_style_toggled(self, checked: bool):
        """Callback stile dialoghi professionale: persistenza immediata."""
        self._svc.set_dialogue_style(checked)

    def on_profile_toggled(self, profile_value: str, checked: bool):
        """
        Callback quando un radio button viene toggled

        In embed mode (SettingsDialog) la selezione viene persistita immediatamente.
        In standalone mode resta come prima: persistita solo su accept().
        """
        if checked:
            self.selected_profile = profile_value
            self._svc.select_profile(profile_value, self.embed)
    
    def get_selected_profile(self) -> str:
        """
        Ottieni profilo selezionato
        
        Returns:
            Nome profilo ('fast', 'balanced', ecc.)
        """
        return self.selected_profile
    
    def apply_theme(self):
        """Applica tema moderno Windows 11 OTTIMIZZATO"""
        self.setStyleSheet(load_qss('profile_dialog'))


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    """Test dialog ottimizzata"""
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    dialog = ProfileSelectionDialog()
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        selected = dialog.get_selected_profile()
        print(f"✅ Profilo selezionato: {selected}")
    else:
        print("❌ Annullato")
    
    sys.exit()