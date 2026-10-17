/* Profili Faster-Whisper: tema globale + card dei profili in palette slate/accent. */
QLabel#dialogHeader {
    color: {{fg_0}};
    padding: 10px;
    background-color: {{accent_a10}};
    border: 1px solid {{accent_a30}};
    border-radius: {{rad_ctl}};
}

QLabel#descLabel {
    color: {{fg_1}};
    font-size: 9pt;
    padding: 6px;
}

QScrollArea#profileScrollArea {
    background-color: transparent;
    border: none;
}

QFrame#profileFrame {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    min-height: 85px;
    max-height: 110px;
}

QFrame#profileFrame:hover {
    background-color: {{bg_3}};
    border: 1px solid {{accent_a45}};
}

QRadioButton#profileRadio {
    spacing: 5px;
}

QRadioButton#profileRadio::indicator {
    width: 18px;
    height: 18px;
    border-radius: 10px;
    border: 1.5px solid {{fg_3}};
    background-color: {{bg_1}};
}

QRadioButton#profileRadio::indicator:hover {
    border: 1.5px solid {{accent}};
}

QRadioButton#profileRadio::indicator:checked {
    background-color: {{accent}};
    border: 1.5px solid {{accent}};
    image: url({{ICONS}}/dot.svg);
}

QLabel#profileName {
    color: {{fg_0}};
    font-size: 11pt;
    font-weight: 600;
}

QLabel#profileDesc {
    color: {{fg_2}};
    font-size: 8.5pt;
}

QLabel#profileParams {
    color: {{accent}};
    font-size: 8pt;
    font-family: {{FONT_MONO_BASE}};
}

QLabel#profileTime {
    color: {{success}};
    font-size: 8pt;
    font-family: {{FONT_MONO_BASE}};
}

QLabel#recommendedBadge {
    color: {{warn}};
    font-size: 7.5pt;
    font-weight: bold;
    background-color: {{warn_a15}};
    border: 1px solid {{warn_a35}};
    border-radius: 9px;
    padding: 2px 8px;
}

QLabel#profileWarning {
    color: {{warn}};
    font-size: 8pt;
    font-style: italic;
}

QFrame#separator {
    border: none;
    background-color: {{line}};
    min-height: 1px;
    max-height: 1px;
}

/* Conferma = primario accent; Annulla = secondario (stile globale QPushButton) */
QPushButton#okButton {
    background-color: {{accent}};
    color: {{on_accent}};
    border: 1px solid {{accent}};
    padding: 8px 20px;
    font-weight: 600;
}

QPushButton#okButton:hover {
    background-color: {{accent_hover}};
    border-color: {{accent_hover}};
}

QPushButton#okButton:pressed {
    background-color: {{accent_press}};
    border-color: {{accent_press}};
}

QPushButton#cancelButton {
    padding: 8px 20px;
    font-weight: 600;
}
