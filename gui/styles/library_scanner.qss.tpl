QFrame#libraryScannerFrame {
    background-color: {{bg_2}};
    border: none;
    margin-top: 2px;
}

QFrame#scannerHeader {
    background-color: transparent;
    border: none;
}
QFrame#scannerHeader:hover {
    background-color: {{white_a03}};
}

QToolButton#scannerToggle {
    background: transparent;
    border: none;
    color: {{fg_3}};
    font-size: 10pt;
}
QToolButton#scannerRefreshBtn {
    background: transparent;
    border: 1px solid {{line}};
    border-radius: {{rad_chip}};
    font-size: 10pt;
}
QToolButton#scannerRefreshBtn:hover {
    background-color: {{bg_3}};
    border-color: {{line_strong}};
}

QLabel#scannerTitle {
    color: {{fg_0}};
    font-size: 10pt;
    font-weight: bold;
}

QLabel#scannerBadge {
    background-color: {{danger}};
    color: {{white}};
    border-radius: 9px;
    padding: 1px 7px;
    font-size: 8pt;
    font-weight: bold;
    min-width: 18px;
    max-height: 18px;
}

QLabel#scannerFilterLabel {
    color: {{fg_2}};
    font-size: 8pt;
}

QLineEdit#scannerSearch {
    background-color: {{bg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_0}};
    padding: 3px 8px;
    font-size: 8pt;
    min-height: 16px;
}
QLineEdit#scannerSearch:focus {
    border: 1px solid {{accent}};
}

QComboBox#scannerFilter {
    background-color: {{bg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_0}};
    padding: 2px 6px;
    font-size: 8pt;
    min-width: 0px;
    min-height: 16px;
}
QSpinBox#scannerDaysFilter {
    padding: 2px 20px 2px 6px;
    font-size: 8pt;
    min-height: 16px;
}
QComboBox#scannerFilter::drop-down {
    border: none;
    width: 22px;
}
QComboBox#scannerFilter QAbstractItemView {
    background-color: {{bg_1}};
    color: {{fg_0}};
    selection-background-color: {{accent_a18}};
    border: 1px solid {{line}};
}

QTableWidget#scannerTable {
    background-color: {{bg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_0}};
    font-size: 8pt;
    gridline-color: {{white_a03}};
}
QTableWidget#scannerTable::item {
    padding: 2px 4px;
}
QTableWidget#scannerTable::item:selected {
    background-color: {{accent_a15}};
}
QHeaderView {
    background-color: {{bg_2}};
}
QHeaderView::section {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: none;
    border-right: 1px solid {{line}};
    border-bottom: 1px solid {{line}};
    padding: 5px 6px;
    font-size: 8pt;
    font-weight: bold;
}
QHeaderView::section:last {
    border-right: none;
}

QPushButton#scannerImportAllBtn {
    background-color: {{accent_a15}};
    border: 1px solid {{accent_a45}};
    border-radius: {{rad_ctl}};
    color: {{accent}};
    padding: 4px 10px;
    font-size: 8pt;
    font-weight: bold;
    min-height: 16px;
}
QPushButton#scannerImportAllBtn:hover {
    background-color: {{accent_a30}};
    border-color: {{accent}};
}
QPushButton#scannerImportAllBtn:disabled {
    background-color: {{bg_1}};
    border-color: {{bg_2}};
    color: {{fg_disabled}};
}

QPushButton[class="scannerAddBtn"] {
    background-color: {{success_a15}};
    border: 1px solid {{success_a35}};
    border-radius: {{rad_chip}};
    color: {{success}};
    font-size: 9pt;
    font-weight: bold;
    padding: 0px;
    min-height: 0px;
}
QPushButton[class="scannerAddBtn"]:hover {
    background-color: {{success_a35}};
}
QPushButton[class="scannerAddBtn"]:disabled {
    background-color: transparent;
    border-color: transparent;
    color: {{success}};
}

QLabel#scannerStats {
    color: {{fg_3}};
    font-size: 8pt;
    padding: 2px;
}
