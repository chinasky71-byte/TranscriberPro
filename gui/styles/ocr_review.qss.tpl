/* Revisione OCR: tema globale + differenze (immagine, lista eventi, pulsanti primari). */
QLabel { color: {{fg_1}}; }
QLabel#ocrHeader {
    color: {{fg_0}};
    font-weight: bold;
    padding: 8px 12px;
    background-color: {{accent_a10}};
    border-left: 3px solid {{accent}};
    border-radius: {{rad_chip}};
}
QLabel#ocrEventInfo { color: {{accent}}; font-weight: bold; }
QLabel#ocrCounter { color: {{fg_2}}; font-size: 11px; }
QLabel#ocrImage {
    background-color: {{bg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_3}};
}
QListWidget {
    background-color: {{bg_0}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    outline: none;
}
QListWidget::item { padding: 6px 8px; border-radius: {{rad_chip}}; }
QListWidget::item:hover { background-color: {{white_a06}}; }
QListWidget::item:selected {
    background-color: {{accent_a18}};
    color: {{fg_0}};
}
QPlainTextEdit {
    background-color: {{bg_0}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 8px 10px;
    selection-background-color: {{accent_a30}};
}
QPlainTextEdit:focus { border-color: {{accent}}; }
QPushButton { font-weight: 600; }
QPushButton#ocrVerifyBtn, QPushButton#ocrDoneBtn {
    background-color: {{accent}};
    color: {{on_accent}};
    border: 1px solid {{accent}};
}
QPushButton#ocrVerifyBtn:hover, QPushButton#ocrDoneBtn:hover {
    background-color: {{accent_hover}};
    border-color: {{accent_hover}};
}
QPushButton#ocrVerifyBtn:pressed, QPushButton#ocrDoneBtn:pressed {
    background-color: {{accent_press}};
    border-color: {{accent_press}};
}
