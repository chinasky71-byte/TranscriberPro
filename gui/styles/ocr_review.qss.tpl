QDialog {
    background-color: {{legacy_bg_dialog}};
    color: {{white}};
}
QLabel { color: {{legacy_grey_ccc}}; }
QLabel#ocrHeader {
    color: {{white}};
    font-weight: bold;
    padding: 6px 8px;
    background-color: rgba(60,193,224,0.10);
    border-left: 3px solid {{accent}};
    border-radius: 4px;
}
QLabel#ocrEventInfo { color: {{accent}}; font-weight: bold; }
QLabel#ocrCounter { color: {{fg_2}}; font-size: 11px; }
QLabel#ocrImage {
    background-color: {{legacy_bg_ocr}};
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px;
    color: {{fg_3}};
}
QCheckBox { color: {{legacy_grey_ccc}}; }
QListWidget {
    background-color: rgba(15,15,25,220);
    color: {{legacy_grey_d0}};
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
    outline: none;
}
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected {
    background-color: rgba(60,193,224,0.25);
    color: {{white}};
}
QPlainTextEdit {
    background-color: rgba(15,15,25,230);
    color: {{white}};
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {{accent}};
}
QPushButton {
    background-color: rgba(45,45,60,220);
    color: {{white}};
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: bold;
}
QPushButton:hover { background-color: rgba(60,60,80,230); }
QPushButton:disabled {
    background-color: rgba(60,60,60,120);
    color: rgba(255,255,255,90);
}
QPushButton#ocrVerifyBtn, QPushButton#ocrDoneBtn {
    background-color: {{accent}};
    color: {{legacy_on_accent_ocr}};
    border: none;
}
QPushButton#ocrVerifyBtn:hover, QPushButton#ocrDoneBtn:hover {
    background-color: {{legacy_accent_ocr_hover}};
}
