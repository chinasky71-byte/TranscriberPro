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
                             QScrollArea, QWidget)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from utils.config import get_config
from utils.transcription_profiles import ProfileConfig, TranscriptionProfile


class ProfileSelectionDialog(QDialog):
    """
    Dialog per selezione profilo trascrizione
    
    CARATTERISTICHE v3.1:
    - Finestra ridimensionabile liberamente
    - Contenuto scrollabile automatico
    - Layout compatto ottimizzato
    - Altezza iniziale ridotta per compatibilità schermi
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self.selected_profile = self.config.get_transcription_profile()
        
        self.setWindowTitle("Profili Trascrizione")
        self.setModal(True)
        
        # ✅ OTTIMIZZATO: Dimensioni iniziali più compatte
        self.setMinimumWidth(650)
        self.setMinimumHeight(480)  # 600 → 480
        
        # ✅ NUOVO: Dimensione iniziale ragionevole
        self.resize(700, 550)
        
        # ✅ NUOVO: Abilita ridimensionamento completo
        self.setSizeGripEnabled(True)
        
        self.init_ui()
        self.apply_theme()
    
    def init_ui(self):
        """Inizializza interfaccia con scroll area"""
        # Layout principale dialog
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)  # 15 → 12
        main_layout.setContentsMargins(15, 15, 15, 15)  # 20 → 15
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("separator")
        main_layout.addWidget(separator)
        
        # ✅ OTTIMIZZATO: Descrizione più concisa
        desc_label = QLabel(
            "Seleziona il profilo ottimale per il tuo caso d'uso."
        )
        desc_label.setObjectName("descLabel")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)
        
        # ========================================
        # ✅ NUOVO: Scroll Area per contenuto profili
        # ========================================
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setObjectName("profileScrollArea")
        
        # Container interno per profili
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)  # 10 → 8 (più compatto)
        scroll_layout.setContentsMargins(0, 0, 5, 0)  # Margine minimo a destra per scrollbar
        
        # Button group per radio buttons
        self.button_group = QButtonGroup(self)
        
        # Crea widget per ogni profilo
        for profile in TranscriptionProfile:
            profile_widget = self.create_profile_widget(profile)
            scroll_layout.addWidget(profile_widget)
        
        # Stretch per spingere contenuto in alto
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)  # ✅ Stretch per prendere spazio disponibile
        
        # Separator bottom
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setObjectName("separator")
        main_layout.addWidget(separator2)
        
        # ========================================
        # Bottoni OK / Cancel (FISSI in basso)
        # ========================================
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        buttons_layout.addStretch()
        
        cancel_btn = QPushButton("❌ Annulla")
        cancel_btn.setObjectName("cancelButton")
        cancel_btn.setMinimumWidth(110)  # 120 → 110
        cancel_btn.setFixedHeight(36)  # Altezza fissa
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("✅ Conferma")
        ok_btn.setObjectName("okButton")
        ok_btn.setMinimumWidth(110)
        ok_btn.setFixedHeight(36)
        ok_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(ok_btn)
        
        main_layout.addLayout(buttons_layout)
        
        self.setLayout(main_layout)
    
    def create_header(self):
        """Crea header dialog compatto"""
        header = QLabel("⚙️ Profili di Trascrizione")
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
        
        # Get config
        config = ProfileConfig.get_profile_config(profile)
        
        # --- RIGA 1: Nome + Badge ---
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)
        
        name_label = QLabel(f"<b>{config['name']}</b>")
        name_label.setObjectName("profileName")
        name_layout.addWidget(name_label)
        
        # Badge raccomandato per BALANCED
        if profile == TranscriptionProfile.BALANCED:
            badge = QLabel("⭐ RACCOMANDATO")
            badge.setObjectName("recommendedBadge")
            name_layout.addWidget(badge)
        
        name_layout.addStretch()
        info_layout.addLayout(name_layout)
        
        # --- RIGA 2: Descrizione (compatta) ---
        desc_label = QLabel(config['description'])
        desc_label.setObjectName("profileDesc")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)
        
        # --- RIGA 3: Parametri + Tempo (TUTTO SU UNA RIGA) ---
        params_layout = QHBoxLayout()
        params_layout.setSpacing(12)
        
        # Parametri tecnici compatti
        params_text = (
            f"⚙️ W:{config['num_workers']} | "
            f"🎯 B:{config['beam_size']} | "
            f"⚡ {self._format_speed(config['speed_factor'])} | "
            f"✨ {config['quality_percent']:.0f}%"
        )
        params_label = QLabel(params_text)
        params_label.setObjectName("profileParams")
        params_layout.addWidget(params_label)
        
        # Tempo stimato (stesso rigo)
        time_label = QLabel(f"⏱️ ~{config['time_1h_audio_min']}min/h")
        time_label.setObjectName("profileTime")
        params_layout.addWidget(time_label)
        
        params_layout.addStretch()
        info_layout.addLayout(params_layout)
        
        # --- Warning se presente (compatto) ---
        if 'warning' in config:
            warning_label = QLabel(f"⚠️ {config['warning']}")
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
        if speed_factor > 1.0:
            return f"+{int((speed_factor - 1) * 100)}%"
        elif speed_factor < 1.0:
            return f"{int((speed_factor - 1) * 100)}%"
        else:
            return "100%"
    
    def on_profile_toggled(self, profile_value: str, checked: bool):
        """
        Callback quando un radio button viene toggled
        
        Args:
            profile_value: Valore del profilo (es: 'fast', 'quality', ecc.)
            checked: True se il button è stato selezionato, False se deselezionato
        """
        if checked:  # Solo quando il button viene SELEZIONATO (non deselezionato)
            self.selected_profile = profile_value
            print(f"✅ Profilo selezionato nel dialogo: {profile_value}")
    
    def get_selected_profile(self) -> str:
        """
        Ottieni profilo selezionato
        
        Returns:
            Nome profilo ('fast', 'balanced', ecc.)
        """
        return self.selected_profile
    
    def apply_theme(self):
        """Applica tema moderno Windows 11 OTTIMIZZATO"""
        self.setStyleSheet("""
            /* Dialog Background */
            QDialog {
                background-color: #1e1e1e;
            }
            
            /* Header - ✅ COMPATTO */
            QLabel#dialogHeader {
                color: #ffffff;
                padding: 10px;
                background-color: rgba(0, 120, 212, 30);
                border-radius: 6px;
            }
            
            /* Description Label - ✅ COMPATTO */
            QLabel#descLabel {
                color: #d0d0d0;
                font-size: 9pt;
                padding: 6px;
            }
            
            /* Scroll Area */
            QScrollArea#profileScrollArea {
                background-color: transparent;
                border: none;
            }
            
            /* Profile Frame - ✅ OTTIMIZZATO */
            QFrame#profileFrame {
                background-color: rgba(32, 32, 32, 200);
                border: 2px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                min-height: 85px;
                max-height: 110px;
            }
            
            QFrame#profileFrame:hover {
                background-color: rgba(40, 40, 40, 220);
                border: 2px solid rgba(0, 120, 212, 0.4);
            }
            
            /* Radio Button */
            QRadioButton#profileRadio {
                spacing: 5px;
            }
            
            QRadioButton#profileRadio::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                background-color: rgba(45, 45, 45, 200);
            }
            
            QRadioButton#profileRadio::indicator:hover {
                border: 2px solid rgba(0, 120, 212, 0.6);
            }
            
            QRadioButton#profileRadio::indicator:checked {
                background-color: rgba(0, 120, 212, 255);
                border: 2px solid rgba(0, 150, 255, 255);
            }
            
            /* Profile Name - ✅ COMPATTO */
            QLabel#profileName {
                color: #ffffff;
                font-size: 11pt;
            }
            
            /* Profile Description - ✅ COMPATTO */
            QLabel#profileDesc {
                color: #b0b0b0;
                font-size: 8.5pt;
            }
            
            /* Profile Params - ✅ COMPATTO */
            QLabel#profileParams {
                color: #88ccff;
                font-size: 8pt;
                font-family: 'Consolas', monospace;
            }
            
            /* Profile Time - ✅ COMPATTO */
            QLabel#profileTime {
                color: #88ff88;
                font-size: 8pt;
                font-family: 'Consolas', monospace;
            }
            
            /* Recommended Badge - ✅ COMPATTO */
            QLabel#recommendedBadge {
                color: #ffcc00;
                font-size: 7.5pt;
                font-weight: bold;
                background-color: rgba(255, 200, 0, 0.15);
                border: 1px solid rgba(255, 200, 0, 0.4);
                border-radius: 3px;
                padding: 2px 6px;
            }
            
            /* Profile Warning - ✅ COMPATTO */
            QLabel#profileWarning {
                color: #ffaa44;
                font-size: 8pt;
                font-style: italic;
            }
            
            /* Separator */
            QFrame#separator {
                background-color: rgba(255, 255, 255, 0.15);
                min-height: 1px;
                max-height: 1px;
            }
            
            /* Buttons - ✅ OTTIMIZZATI */
            QPushButton#okButton {
                background-color: rgba(50, 180, 50, 180);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 9.5pt;
                font-weight: bold;
            }
            
            QPushButton#okButton:hover {
                background-color: rgba(50, 200, 50, 230);
            }
            
            QPushButton#okButton:pressed {
                background-color: rgba(40, 160, 40, 255);
            }
            
            QPushButton#cancelButton {
                background-color: rgba(80, 80, 80, 180);
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 9.5pt;
                font-weight: bold;
            }
            
            QPushButton#cancelButton:hover {
                background-color: rgba(100, 100, 100, 230);
            }
            
            QPushButton#cancelButton:pressed {
                background-color: rgba(70, 70, 70, 255);
            }
            
            /* Scrollbar - ✅ STILE MODERNO */
            QScrollBar:vertical {
                background-color: rgba(30, 30, 30, 100);
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }
            
            QScrollBar::handle:vertical {
                background-color: rgba(100, 100, 100, 150);
                border-radius: 5px;
                min-height: 30px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: rgba(120, 120, 120, 200);
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)


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