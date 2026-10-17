QGroupBox {
    font-weight: bold;
    border: 2px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    color: {{white}};
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}

QLabel#statusLabel {
    color: {{white}};
    font-size: 10pt;
    padding: 5px;
}

QLabel#credentialsLabel {
    color: {{legacy_grey_ccc}};
    font-size: 9pt;
    font-style: italic;
    padding: 5px;
}

QCheckBox {
    color: {{white}};
    font-size: 9pt;
    spacing: 8px;
    padding: 5px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 3px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    background-color: rgba(45, 45, 45, 200);
}

QCheckBox::indicator:checked {
    background-color: rgba(0, 120, 212, 200);
    border-color: rgba(0, 120, 212, 255);
}

QCheckBox::indicator:disabled {
    background-color: rgba(60, 60, 60, 100);
    border-color: rgba(255, 255, 255, 0.1);
}

QPushButton {
    background-color: rgba(0, 120, 212, 180);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 9pt;
    font-weight: bold;
}

QPushButton:hover {
    background-color: rgba(0, 120, 212, 230);
}

QPushButton:pressed {
    background-color: rgba(0, 100, 180, 200);
}

QPushButton:disabled {
    background-color: rgba(60, 60, 60, 150);
    color: rgba(255, 255, 255, 100);
}
