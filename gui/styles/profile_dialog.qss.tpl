/* Dialog Background */
QDialog {
    background-color: {{legacy_bg_1e}};
}

/* Header - ✅ COMPATTO */
QLabel#dialogHeader {
    color: {{white}};
    padding: 10px;
    background-color: rgba(0, 120, 212, 30);
    border-radius: 6px;
}

/* Description Label - ✅ COMPATTO */
QLabel#descLabel {
    color: {{legacy_grey_d0}};
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
    color: {{white}};
    font-size: 11pt;
}

/* Profile Description - ✅ COMPATTO */
QLabel#profileDesc {
    color: {{legacy_grey_b0}};
    font-size: 8.5pt;
}

/* Profile Params - ✅ COMPATTO */
QLabel#profileParams {
    color: {{legacy_blue_soft}};
    font-size: 8pt;
    font-family: 'Consolas', monospace;
}

/* Profile Time - ✅ COMPATTO */
QLabel#profileTime {
    color: {{legacy_green_soft}};
    font-size: 8pt;
    font-family: 'Consolas', monospace;
}

/* Recommended Badge - ✅ COMPATTO */
QLabel#recommendedBadge {
    color: {{legacy_yellow}};
    font-size: 7.5pt;
    font-weight: bold;
    background-color: rgba(255, 200, 0, 0.15);
    border: 1px solid rgba(255, 200, 0, 0.4);
    border-radius: 3px;
    padding: 2px 6px;
}

/* Profile Warning - ✅ COMPATTO */
QLabel#profileWarning {
    color: {{legacy_orange_soft}};
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
