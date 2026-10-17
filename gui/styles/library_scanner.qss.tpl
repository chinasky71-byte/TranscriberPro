QFrame#libraryScannerFrame {
    background-color: rgba(32, 32, 32, 180);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    margin-top: 5px;
}

QFrame#scannerHeader {
    background-color: transparent;
    border: none;
}
QFrame#scannerHeader:hover {
    background-color: rgba(255, 255, 255, 0.03);
}

QToolButton#scannerToggle {
    background: transparent;
    border: none;
    color: {{legacy_grey_888}};
    font-size: 10pt;
}
QToolButton#scannerRefreshBtn {
    background: transparent;
    border: none;
    font-size: 10pt;
}

QLabel#scannerTitle {
    color: {{white}};
    font-size: 10pt;
    font-weight: bold;
}

QLabel#scannerBadge {
    background-color: {{legacy_pink}};
    color: white;
    border-radius: 9px;
    padding: 1px 7px;
    font-size: 8pt;
    font-weight: bold;
    min-width: 18px;
    max-height: 18px;
}

QLabel#scannerFilterLabel {
    color: {{legacy_grey_aaa}};
    font-size: 9pt;
}

QLineEdit#scannerSearch {
    background-color: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: {{white}};
    padding: 5px 8px;
    font-size: 9pt;
}
QLineEdit#scannerSearch:focus {
    border: 1px solid rgba(33, 150, 243, 0.5);
}

QComboBox#scannerFilter {
    background-color: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: {{white}};
    padding: 4px 8px;
    font-size: 9pt;
    min-width: 80px;
}
QComboBox#scannerFilter::drop-down {
    border: none;
    width: 20px;
}
QComboBox#scannerFilter QAbstractItemView {
    background-color: {{legacy_bg_2a}};
    color: {{white}};
    selection-background-color: rgba(33, 150, 243, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.1);
}

QTableWidget#scannerTable {
    background-color: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: {{white}};
    font-size: 8pt;
    gridline-color: rgba(255, 255, 255, 0.03);
}
QTableWidget#scannerTable::item {
    padding: 2px 4px;
}
QTableWidget#scannerTable::item:selected {
    background-color: rgba(33, 150, 243, 0.15);
}
QHeaderView {
    background-color: {{legacy_black}};
}
QHeaderView::section {
    background-color: {{legacy_black}};
    color: {{white}};
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    padding: 4px 6px;
    font-size: 8pt;
    font-weight: bold;
}
QHeaderView::section:last {
    border-right: none;
}

QPushButton#scannerImportAllBtn {
    background-color: rgba(33, 150, 243, 200);
    border: none;
    border-radius: 6px;
    color: white;
    padding: 7px 12px;
    font-size: 8pt;
    font-weight: bold;
}
QPushButton#scannerImportAllBtn:hover {
    background-color: rgba(33, 150, 243, 255);
}
QPushButton#scannerImportAllBtn:disabled {
    background-color: rgba(60, 60, 60, 150);
    color: rgba(255, 255, 255, 80);
}

QPushButton[class="scannerAddBtn"] {
    background-color: rgba(76, 175, 80, 180);
    border: none;
    border-radius: 4px;
    color: white;
    font-size: 9pt;
    font-weight: bold;
    padding: 0px;
}
QPushButton[class="scannerAddBtn"]:hover {
    background-color: rgba(76, 175, 80, 255);
}
QPushButton[class="scannerAddBtn"]:disabled {
    background-color: transparent;
    color: {{legacy_mat_green}};
}

QLabel#scannerStats {
    color: {{legacy_grey_888}};
    font-size: 8pt;
    padding: 2px;
}
