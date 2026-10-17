/* Sync dialog: eredita il tema globale (QDialog, QGroupBox, QLineEdit, QPushButton, QTableView...).
 * Qui restano solo le differenze: testo secondario, log e barra di avanzamento. */
QLabel {
    color: {{fg_1}};
}
QTextEdit {
    background-color: {{bg_0}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QProgressBar {
    border: 1px solid {{line}};
    border-radius: 10px;
    background-color: {{bg_3}};
    color: {{fg_0}};
    text-align: center;
    min-height: 20px;
    max-height: 20px;
    font-weight: 600;
}
QProgressBar::chunk {
    background-color: {{accent_a45}};
    border: 1px solid {{accent}};
    border-radius: 8px;
}
