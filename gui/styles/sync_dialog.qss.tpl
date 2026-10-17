QDialog {
    background-color: {{legacy_bg_dialog}};
    color: {{white}};
}
QGroupBox {
    font-weight: bold;
    border: 2px solid rgba(255,255,255,0.1);
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
QLabel {
    color: {{legacy_grey_ccc}};
}
QLineEdit {
    background-color: rgba(45,45,60,200);
    color: {{white}};
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 4px;
    padding: 4px 8px;
}
QTextEdit {
    background-color: rgba(15,15,25,220);
    color: {{legacy_grey_d0}};
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 4px;
}
QProgressBar {
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 4px;
    background-color: rgba(30,30,50,200);
    color: {{white}};
    text-align: center;
    height: 20px;
}
QProgressBar::chunk {
    background-color: rgba(0,120,212,200);
    border-radius: 3px;
}
QPushButton {
    background-color: rgba(0,120,212,180);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: bold;
}
QPushButton:hover  { background-color: rgba(0,120,212,230); }
QPushButton:pressed { background-color: rgba(0,100,180,200); }
QPushButton:disabled {
    background-color: rgba(60,60,60,150);
    color: rgba(255,255,255,100);
}
