/* Pagina OpenSubtitles: eredita il tema globale (QGroupBox, QLineEdit, QCheckBox, QPushButton).
 * Restano solo le etichette di stato. */
QLabel#statusLabel {
    color: {{fg_0}};
    font-size: 10pt;
    padding: 5px;
}

QLabel#credentialsLabel {
    color: {{fg_2}};
    font-size: 9pt;
    font-style: italic;
    padding: 5px;
}

QCheckBox {
    font-size: 9pt;
    padding: 5px;
}

/* pagina densa (4 gruppi in 840x620): spaziature compatte per non schiacciare i campi */
QGroupBox {
    padding: 26px 12px 8px 12px;
}
QGroupBox::title {
    top: 7px;
}
QLineEdit {
    padding: 4px 8px;
    min-height: 20px;
}
QPushButton {
    padding: 6px 12px;
}
QLabel#statusLabel, QLabel#credentialsLabel {
    padding: 2px;
}
QCheckBox {
    padding: 2px;
}
