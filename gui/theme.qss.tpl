/*
 * Transcriber Pro - Tema globale (Fase 1)
 * Palette dark slate + accent ciano (mockup interface revamp/styles-v2.css)
 *
 * Variabili colore (riferimento - QSS non supporta var()):
 *   --bg-0:  {{bg_0}}   --fg-0: {{fg_0}}
 *   --bg-1:  {{bg_1}}   --fg-1: {{fg_1}}
 *   --bg-2:  {{bg_2}}   --fg-2: {{fg_2}}
 *   --bg-3:  {{bg_3}}   --fg-3: {{fg_3}}
 *   --bg-4:  {{bg_4}}   --line: {{line}}
 *   --accent:  {{accent}}
 *   --success: {{success}}
 *   --danger:  {{danger}}
 *   --warn:    {{warn}}
 */

/* ============================================================
 * Base
 * ============================================================ */
QWidget {
    background-color: {{bg_0}};
    color: {{fg_0}};
    font-family: {{FONT_SANS}};
    font-size: 10pt;
}

QMainWindow {
    background-color: {{bg_0}};
}

/* contenitori "piatti" (gui.theme.set_flat) e aree scorrevoli: niente toppe di fondo dentro le card */
QWidget[flat="true"] {
    background-color: transparent;
}
QScrollArea {
    background-color: transparent;
    border: none;
}
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QToolTip {
    background-color: {{bg_2}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    padding: 6px 8px;
    border-radius: 6px;
}

/* ============================================================
 * Pannelli principali
 * ============================================================ */
QFrame#leftPanel,
QFrame#centerPanel,
QFrame#rightPanel {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    padding: 14px;
}

QLabel {
    background: transparent;
    color: {{fg_0}};
}

QLabel#panelTitle {
    color: {{fg_0}};
    font-size: 13px;
    font-weight: 600;
    padding: 2px 0px 8px 0px;
    background: transparent;
}

QLabel#sectionTitle {
    color: {{fg_1}};
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}

QLabel#mutedLabel {
    color: {{fg_2}};
    background: transparent;
}

QLabel#remainingFilesLabel {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
}

/* ============================================================
 * Pulsanti
 * ============================================================ */
QPushButton {
    background-color: {{bg_2}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 8px 14px;
    min-height: 18px;
    font-size: 10pt;
}
QPushButton:hover {
    background-color: {{bg_3}};
    border-color: {{line_strong}};
}
QPushButton:pressed {
    background-color: {{bg_1}};
}
QPushButton:focus {
    border-color: {{accent_a55}};
}
QPushButton:disabled {
    color: {{fg_disabled}};
    background-color: {{bg_1}};
    border-color: {{bg_2}};
}

QPushButton#primaryButton {
    background-color: {{bg_2}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 8px 14px;
    font-weight: 500;
}
QPushButton#primaryButton:hover {
    background-color: {{bg_3}};
    border-color: {{accent}};
}
QPushButton#primaryButton:pressed {
    background-color: {{accent_a10}};
    border-color: {{accent}};
}

QPushButton#startButton {
    background-color: {{accent}};
    color: {{on_accent}};
    border: 1px solid {{accent}};
    border-radius: {{rad_ctl}};
    padding: 12px 20px;
    font-weight: 600;
    font-size: 10.5pt;
}
QPushButton#startButton:hover {
    background-color: {{accent_hover}};
    border-color: {{accent_hover}};
}
QPushButton#startButton:pressed {
    background-color: {{accent_press}};
    border-color: {{accent_press}};
}
QPushButton#startButton:disabled {
    background-color: {{bg_2}};
    color: {{fg_disabled}};
    border-color: {{line}};
}

QPushButton#stopButton {
    background-color: {{danger}};
    color: {{white}};
    border: 1px solid {{danger}};
    border-radius: {{rad_ctl}};
    padding: 12px 20px;
    font-weight: 600;
    font-size: 10.5pt;
}
QPushButton#stopButton:hover {
    background-color: {{danger_hover}};
    border-color: {{danger_hover}};
}
QPushButton#stopButton:pressed {
    background-color: {{danger_press}};
    border-color: {{danger_press}};
}
QPushButton#stopButton:disabled {
    background-color: {{bg_2}};
    color: {{fg_disabled}};
    border-color: {{line}};
}

/* ============================================================
 * QToolButton (icone settings, ⚙️ ecc.)
 * ============================================================ */
QToolButton {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_0}};
    padding: 4px;
    min-width: 32px;
    min-height: 32px;
}
QToolButton:hover {
    background-color: {{bg_3}};
    border-color: {{line_strong}};
}
QToolButton:pressed {
    background-color: {{bg_1}};
}
QToolButton:checked {
    background-color: {{accent}};
    color: {{on_accent}};
    border-color: {{accent}};
}

/* Mini-titlebar settings button: senza bordo, hover discreto, perfettamente
 * tondo nei 4 angoli (override del QToolButton generico sopra). */
QFrame#miniTitleBar {
    background-color: {{bg_0}};
    border-bottom: 1px solid {{line}};
}
QToolButton#titleBarSettingsBtn,
QToolButton#titleBarToolsBtn,
QToolButton#titleBarSyncBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0;
    min-width: 32px;
    min-height: 32px;
    font-size: 16px;
}
QToolButton#titleBarSettingsBtn:hover,
QToolButton#titleBarToolsBtn:hover,
QToolButton#titleBarSyncBtn:hover {
    background-color: {{bg_2}};
    border-color: {{line}};
}
QToolButton#titleBarSettingsBtn:pressed,
QToolButton#titleBarToolsBtn:pressed,
QToolButton#titleBarSyncBtn:pressed {
    background-color: {{bg_1}};
}
QToolButton#titleBarToolsBtn::menu-indicator {
    image: none;
    width: 0;
}

/* ============================================================
 * Collapsible Card (Fase 3)
 * ============================================================ */
QFrame#collapsibleCard {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
}
QFrame#collapsibleHeader {
    background-color: transparent;
    border: none;
}
QFrame#collapsibleHeader:hover {
    background-color: {{bg_3}};
    border-top-left-radius: {{rad_card}};
    border-top-right-radius: {{rad_card}};
}
QFrame#collapsibleBody {
    background-color: transparent;
    border: none;
}
/* il widget contenuto non deve "bucare" la card con il fondo di finestra */
QFrame#collapsibleBody > QWidget {
    background-color: transparent;
}
QLabel#collapsibleTitle {
    font-weight: 600;
    font-size: 10pt;
    color: {{fg_0}};
}
QLabel#collapsibleSummary {
    font-size: 9pt;
    color: {{fg_2}};
}
QToolButton#collapsibleChevron {
    background-color: transparent;
    border: none;
    color: {{fg_2}};
    font-size: 12pt;
    min-width: 20px;
    min-height: 20px;
    padding: 0;
}
QToolButton#collapsibleChevron:hover {
    color: {{fg_0}};
}
QToolButton#scannerRefreshBtn {
    background-color: transparent;
    border: 1px solid {{line}};
    border-radius: {{rad_chip}};
    padding: 0;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    font-size: 11px;
}
QToolButton#scannerRefreshBtn:hover {
    background-color: {{bg_2}};
}

/* ============================================================
 * Segmented filter
 * ============================================================ */
QFrame#segmentedFilter {
    background-color: transparent;
    border: none;
}
QPushButton#segmentFilterBtn {
    background-color: {{bg_1}};
    color: {{fg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_chip}};
    padding: 0 10px;
    font-size: 9pt;
    min-width: 44px;
}
QPushButton#segmentFilterBtn:hover {
    background-color: {{bg_2}};
    color: {{fg_row}};
}
QPushButton#segmentFilterBtn:checked {
    background-color: {{accent_a15}};
    color: {{accent}};
    border-color: {{accent_a45}};
}

/* ============================================================
 * Lista file
 * ============================================================ */
QListWidget#fileList {
    background-color: transparent;
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    color: {{fg_0}};
    padding: 6px;
    font-size: 10pt;
    outline: 0;
}
QListWidget#fileList::item {
    background-color: transparent;
    padding: 0;
    margin: 1px 0;
}
QListWidget#fileList::item:hover {
    background-color: transparent;
}
QListWidget#fileList::item:selected {
    background-color: transparent;
    border: none;
    color: {{fg_0}};
}

/* QListWidget generica (es. sidebar SettingsDialog) */
QListWidget {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    color: {{fg_0}};
    padding: 4px;
    outline: 0;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 8px;
    margin: 1px 0px;
}
QListWidget::item:hover {
    background-color: {{bg_2}};
}
QListWidget::item:selected {
    background-color: {{accent_a12}};
    color: {{fg_0}};
}

/* ============================================================
 * Progress bar
 * ============================================================ */
QProgressBar {
    background-color: {{bg_3}};
    color: {{fg_0}};
    border: none;
    border-radius: 999px;
    text-align: center;
    height: 14px;
    font-size: 9pt;
}
QProgressBar::chunk {
    background-color: {{accent}};
    border-radius: 999px;
}

/* barra principale: capsula alta 12px; la percentuale e' una QLabel a destra (progressPct) */
QProgressBar#modernProgress {
    background-color: {{bg_3}};
    border: none;
    border-radius: 6px;
    min-height: 12px;
    max-height: 12px;
}
QProgressBar#modernProgress::chunk {
    background-color: {{accent}};
    border-radius: 6px;
}
QLabel#progressPct {
    color: {{fg_1}};
    font-family: {{FONT_MONO}};
    font-size: 11px;
    font-weight: 600;
    min-width: 36px;
    background: transparent;
}

/* ============================================================
 * Checkbox - default + modern (pill switch 34x20)
 * ============================================================ */
QCheckBox {
    color: {{fg_0}};
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid {{fg_3}};
    border-radius: 5px;
    background-color: {{bg_2}};
}
QCheckBox::indicator:hover {
    border-color: {{accent}};
}
QCheckBox::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
    image: url({{ICONS}}/check.svg);
}
QCheckBox::indicator:disabled {
    background-color: {{bg_1}};
    border-color: {{fg_disabled}};
}
QCheckBox::indicator:checked:disabled {
    background-color: {{bg_3}};
    border-color: {{bg_3}};
    image: url({{ICONS}}/check-disabled.svg);
}

/* Checkbox "modern": stesso stile della default ma piu' compatta */
QCheckBox#modernCheckbox {
    color: {{fg_0}};
    spacing: 6px;
    font-size: 9pt;
    background: transparent;
}
QCheckBox#modernCheckbox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 5px;
    border: 1.5px solid {{fg_3}};
    background-color: {{bg_2}};
}
QCheckBox#modernCheckbox::indicator:hover {
    border-color: {{accent}};
}
QCheckBox#modernCheckbox::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
    image: url({{ICONS}}/check.svg);
}

/* ============================================================
 * RadioButton
 * ============================================================ */
QRadioButton {
    color: {{fg_0}};
    spacing: 8px;
    background: transparent;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid {{fg_3}};
    border-radius: 8px;
    background-color: {{bg_2}};
}
QRadioButton::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent}};
    image: url({{ICONS}}/dot.svg);
}
QRadioButton::indicator:hover {
    border-color: {{accent}};
}

/* ============================================================
 * Input (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox)
 * ============================================================ */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: {{bg_0}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 7px 10px;
    selection-background-color: {{accent_a30}};
    selection-color: {{fg_0}};
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: {{line_strong}};
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: {{accent}};
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: {{fg_disabled}};
    background-color: {{bg_1}};
    border-color: {{bg_2}};
}
QSpinBox, QDoubleSpinBox {
    padding: 4px 24px 4px 10px;
    min-height: 22px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 20px;
    border: none;
    background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-position: top right;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url({{ICONS}}/chev-up.svg);
    width: 10px;
    height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url({{ICONS}}/chev-down.svg);
    width: 10px;
    height: 10px;
}
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {
    image: url({{ICONS}}/chev-up-hover.svg);
}
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {
    image: url({{ICONS}}/chev-down-hover.svg);
}

QTextEdit#logText {
    background-color: {{bg_0}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    font-family: {{FONT_MONO_BASE}};
    font-size: 11px;
    padding: 12px 14px;
    selection-background-color: {{accent_a30}};
}

/* ============================================================
 * QComboBox
 * ============================================================ */
QComboBox {
    background-color: {{bg_2}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 6px 10px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: {{line_strong}};
}
QComboBox:focus, QComboBox:on {
    border-color: {{accent}};
}
QComboBox:disabled {
    color: {{fg_disabled}};
    background-color: {{bg_1}};
    border-color: {{bg_2}};
}
QComboBox::drop-down {
    border: none;
    width: 26px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}
QComboBox::down-arrow {
    image: url({{ICONS}}/chev-down.svg);
    width: 12px;
    height: 12px;
}
QComboBox::down-arrow:hover {
    image: url({{ICONS}}/chev-down-hover.svg);
}
QComboBox QAbstractItemView {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    selection-background-color: {{accent_a18}};
    selection-color: {{fg_0}};
    outline: 0;
    padding: 4px;
}

/* ============================================================
 * QGroupBox
 * ============================================================ */
/* titolo DENTRO la card (niente piu' "toppa" di colore sul bordo) */
QGroupBox {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    margin-top: 0px;
    padding: 34px 14px 14px 14px;
    color: {{fg_0}};
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 14px;
    top: 10px;
    padding: 0px;
    color: {{fg_1}};
    background-color: transparent;
}

/* ============================================================
 * Tabs
 * ============================================================ */
QTabWidget::pane {
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    background-color: {{bg_1}};
    top: -1px;
}
QTabBar::tab {
    background-color: transparent;
    color: {{fg_2}};
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: {{fg_1}};
}
QTabBar::tab:selected {
    color: {{fg_0}};
    border-bottom: 2px solid {{accent}};
}

/* ============================================================
 * Scrollbar
 * ============================================================ */
QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: {{bg_3}};
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: {{bg_4}};
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 8px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: {{bg_3}};
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background-color: {{bg_4}};
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ============================================================
 * Splitter
 * ============================================================ */
QSplitter::handle {
    background-color: transparent;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
QSplitter::handle:hover {
    background-color: {{accent_a12}};
}

/* ============================================================
 * Menu / Menubar
 * ============================================================ */
QMenuBar {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border-bottom: 1px solid {{line}};
}
QMenuBar::item {
    background: transparent;
    padding: 6px 10px;
}
QMenuBar::item:selected {
    background-color: {{bg_2}};
}

QMenu {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 4px;
}
QMenu::item {
    padding: 7px 16px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: {{accent_a14}};
}
QMenu::separator {
    height: 1px;
    background-color: {{line}};
    margin: 4px 6px;
}

/* ============================================================
 * Dialog / MessageBox
 * ============================================================ */
QDialog {
    background-color: {{bg_1}};
    color: {{fg_0}};
}

QMessageBox {
    background-color: {{bg_1}};
    color: {{fg_0}};
}
QMessageBox QLabel {
    color: {{fg_0}};
    background: transparent;
}
QMessageBox QPushButton {
    background-color: {{bg_2}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: 6px;
    padding: 6px 14px;
    min-width: 80px;
}
QMessageBox QPushButton:hover {
    background-color: {{bg_3}};
}
QMessageBox QPushButton:default {
    background-color: {{accent}};
    color: {{on_accent}};
    border-color: {{accent}};
}

/* ============================================================
 * Slider
 * ============================================================ */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background-color: {{bg_3}};
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: {{accent}};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: {{accent_hover}};
}

/* ============================================================
 * QHeaderView (per QTableView - usato in Fase 4A)
 * ============================================================ */
QHeaderView::section {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: none;
    border-bottom: 1px solid {{line}};
    padding: 8px 10px;
    font-weight: 600;
}

QTableView, QTreeView {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    gridline-color: {{bg_2}};
    selection-background-color: {{accent_a16}};
    selection-color: {{fg_0}};
    outline: 0;
}
QTableView::item, QTreeView::item {
    padding: 6px 8px;
}

/* ============================================================
 * Titlebar espansa (Fase 4A)
 * ============================================================ */
QLabel#titleBarMark {
    color: {{accent}};
    font-size: 18px;
    font-weight: 700;
    background: transparent;
    padding: 0;
}
QLabel#titleBarBrand {
    color: {{fg_0}};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}
QFrame#titleBarSep {
    background-color: {{line}};
}
QLabel#titleBarSubtitle {
    color: {{fg_4}};
    font-size: 10px;
    background: transparent;
}
QFrame#statusPill {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: 13px;   /* = meta' dell'altezza fissa (26px, vedi main_window) */
}
QFrame#statusDot {
    background: {{success}};
    border-radius: 4px;
}
QLabel#titleBarStatusLabel {
    color: {{fg_1}};
    font-size: 11px;
    background: transparent;
}
QPushButton#profileButton {
    background-color: {{bg_1}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
    min-height: 28px;
    min-width: 120px;
    text-align: center;
}
QPushButton#profileButton:hover {
    background-color: {{bg_2}};
    border-color: {{accent}};
    color: {{fg_0}};
}
QPushButton#profileButton:pressed {
    background-color: {{bg_0}};
}
QPushButton#profileButton::menu-indicator {
    image: none;
    width: 0;
}

/* ============================================================
 * Tab bar principale (Fase 4A)
 * ============================================================ */
QTabBar#mainTabBar {
    background: {{bg_0}};
    border-bottom: 1px solid {{line}};
}
QTabBar#mainTabBar::tab {
    background: transparent;
    color: {{fg_2}};
    padding: 9px 20px;
    font-size: 12px;
    font-weight: 500;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}
QTabBar#mainTabBar::tab:selected {
    color: {{accent}};
    border-bottom: 2px solid {{accent}};
}
QTabBar#mainTabBar::tab:hover:!selected {
    color: {{fg_1}};
    background: {{white_a03}};
}
QTabBar#mainTabBar::tab:focus {
    outline: none;
}

/* ============================================================
 * HistoryWidget (Fase 4A Tronco 2)
 * ============================================================ */
QLineEdit#historySearch {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
    padding: 7px 12px;
    font-size: 12px;
}
QLineEdit#historySearch:focus {
    border-color: {{accent}};
}

QFrame#historyStatTile {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    min-width: 130px;
}
QLabel#historyStatValue {
    color: {{fg_0}};
    font-family: {{FONT_MONO}};
    font-size: 20px;
    font-weight: 700;
    background: transparent;
}
QLabel#historyStatLabel {
    color: {{fg_2}};
    font-size: 11px;
    background: transparent;
}

QTableWidget#historyTable {
    background-color: {{bg_1}};
    color: {{fg_0}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    gridline-color: transparent;
    selection-background-color: {{accent_a12}};
    selection-color: {{fg_0}};
    outline: 0;
}
QTableWidget#historyTable::item {
    padding: 6px 10px;
    border-bottom: 1px solid {{bg_2}};
}
QTableWidget#historyTable::item:selected {
    background-color: {{accent_a14}};
}
QHeaderView::section {
    background-color: {{bg_2}};
    color: {{fg_2}};
    border: none;
    border-bottom: 1px solid {{line}};
    padding: 7px 10px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton#historyActionBtn {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_chip}};
    padding: 2px 10px;
    font-size: 11px;
    min-height: 20px;
}
QPushButton#historyActionBtn:hover {
    background-color: {{bg_3}};
    border-color: {{accent}};
    color: {{fg_0}};
}
QPushButton#historyActionBtn:disabled {
    color: {{fg_disabled}};
    border-color: {{bg_2}};
}

QLabel#historyPlaceholder {
    color: {{fg_4}};
    font-size: 14px;
    background: transparent;
}

/* ============================================================
 * Center panel — preview header + info strip (Fase 4B)
 * ============================================================ */
QFrame#previewHeader {
    background: transparent;
    border-bottom: 1px solid {{line}};
}
QLabel#previewFilenamePill {
    background-color: {{bg_2}};
    color: {{fg_2}};
    border: 1px solid {{line}};
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 10px;
    font-family: {{FONT_MONO}};
}
QFrame#posterStage {
    background: transparent;
}
QFrame#posterInfoStrip {
    background-color: {{bg_1}};
    border-top: 1px solid {{line}};
}
QLabel#overlayLangPill {
    background-color: {{accent_a15}};
    color: {{accent}};
    border: 1px solid {{accent_a35}};
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#overlayStatusPill {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 10px;
}
QLabel#overlayTitle {
    color: {{fg_0}};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}
QLabel#overlayMeta {
    color: {{fg_2}};
    font-size: 10px;
    font-family: {{FONT_MONO}};
    background: transparent;
}
QProgressBar#overlayProgress {
    background: {{bg_3}};
    border: none;
    border-radius: 2px;
    min-height: 4px;
    max-height: 4px;
}
QProgressBar#overlayProgress::chunk {
    background: {{accent}};
    border-radius: 2px;
}

/* ============================================================
 * ResourceMonitorWidget — metric cards (Fase 4B)
 * ============================================================ */
QLabel#resourceTitle {
    color: {{fg_0}};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QLabel#uptimeLabel {
    color: {{fg_4}};
    font-size: 10px;
    font-family: {{FONT_MONO}};
    background: transparent;
}
QFrame#metricCard {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QLabel#metricName {
    color: {{fg_2}};
    font-size: 10px;
    font-weight: 600;
    background: transparent;
}
QLabel#metricValue {
    color: {{fg_0}};
    font-size: 12px;
    font-weight: 700;
    font-family: {{FONT_MONO}};
    background: transparent;
}
QFrame#netCard {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QLabel#netIcon {
    font-size: 13px;
    background: transparent;
}
QLabel#netSpeedLabel {
    color: {{fg_1}};
    font-size: 11px;
    font-family: {{FONT_MONO}};
    background: transparent;
}

/* ============================================================
 * Right panel — log stats + diagnostic tiles (Fase 4B)
 * ============================================================ */
QFrame#logStatTile {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QLabel#logStatValue {
    color: {{fg_0}};
    font-family: {{FONT_MONO}};
    font-size: 18px;
    font-weight: 700;
    background: transparent;
}
QLabel#logStatLabel {
    color: {{fg_2}};
    font-size: 10px;
    background: transparent;
}
QFrame#diagTile {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QLabel#diagValue {
    color: {{fg_1}};
    font-size: 11px;
    font-weight: 600;
    font-family: {{FONT_MONO}};
    background: transparent;
}
QLabel#diagLabel {
    color: {{fg_4}};
    font-size: 10px;
    background: transparent;
}

/* ============================================================
 * Ruoli (v1.31)
 * Regole a proprieta' dinamica: si attivano SOLO sui widget che hanno
 * `role` (e `tone`) impostati, es. gui.theme.set_role(label, 'muted').
 * Nessun widget storico ha queste proprieta': non alterano nulla.
 * ============================================================ */

/* -- Colore del testo (QLabel) -- */
QLabel[role="primary"] { color: {{fg_0}}; }
QLabel[role="text"] { color: {{fg_1}}; }
QLabel[role="muted"] { color: {{fg_2}}; }
QLabel[role="subtle"] { color: {{fg_3}}; }
QLabel[role="dim"] { color: {{fg_4}}; }
QLabel[role="accent"] { color: {{accent}}; }
QLabel[role="success"] { color: {{success}}; }
QLabel[role="danger"] { color: {{danger}}; }
QLabel[role="warn"] { color: {{warn}}; }
QLabel[role="purple"] { color: {{purple}}; }

/* Tono: colore del testo senza cambiare ruolo tipografico (set_role(w, 'h2', tone='success')) */
QLabel[tone="accent"] { color: {{accent}}; }
QLabel[tone="success"] { color: {{success}}; }
QLabel[tone="danger"] { color: {{danger}}; }
QLabel[tone="warn"] { color: {{warn}}; }
QLabel[tone="purple"] { color: {{purple}}; }
QLabel[tone="muted"] { color: {{fg_2}}; }

/* -- Tipografia (QLabel) -- */
QLabel[role="h1"]          { font-size: 20px; font-weight: bold; }
QLabel[role="h2"]          { font-size: 16px; font-weight: bold; }
QLabel[role="lead"]        { font-size: 13px; }
QLabel[role="body"]        { font-size: 12px; margin-top: 8px; }
QLabel[role="body_tight"]  { font-size: 12px; margin-top: 4px; }
QLabel[role="caption"]     { font-size: 11px; }
QLabel[role="caption_top"] { font-size: 11px; margin-top: 4px; }
QLabel[role="caption_gap"] { font-size: 11px; margin: 5px 0; }
QLabel[role="status"]      { font-size: 11px; font-weight: bold; }
QLabel[role="hint"]        { font-size: 8pt; padding: 4px 0; }

/* -- Card / tile / pill (QFrame; forme di collapsibleCard, metricCard, statusPill) -- */
QFrame[role="card"] {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
}
QFrame[role="tile"] {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: {{rad_ctl}};
}
QFrame[role="pill"] {
    background-color: {{bg_1}};
    border: 1px solid {{line}};
    border-radius: 999px;
}

/* -- Sezione: card con bordo colorato (forma di _section_qss in translation_model_dialog) -- */
QFrame[role="section"] {
    background-color: {{bg_2}};
    border: 1px solid {{line}};
    border-radius: {{rad_card}};
    padding: 15px;
}
QFrame[role="section"][tone="accent"]  { border-color: {{section_blue}}; }
QFrame[role="section"][tone="success"] { border-color: {{section_green}}; }
QFrame[role="section"][tone="warn"]    { border-color: {{section_orange}}; }
QFrame[role="section"][tone="purple"]  { border-color: {{section_purple}}; }
QFrame[role="section"][tone="danger"]  { border-color: {{section_red_orange}}; }

/* -- Badge (QLabel; forma di overlayLangPill / overlayStatusPill) -- */
QLabel[role="badge"] {
    background-color: {{bg_2}};
    color: {{fg_1}};
    border: 1px solid {{line}};
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 10px;
}
QLabel[role="badge"][tone="accent"] {
    background-color: {{accent_a15}};
    color: {{accent}};
    border: 1px solid {{accent_a35}};
    font-weight: 600;
}
QLabel[role="badge"][tone="success"] {
    background-color: {{success_a15}};
    color: {{success}};
    border: 1px solid {{success_a35}};
    font-weight: 600;
}
QLabel[role="badge"][tone="danger"] {
    background-color: {{danger_a15}};
    color: {{danger}};
    border: 1px solid {{danger_a35}};
    font-weight: 600;
}
QLabel[role="badge"][tone="warn"] {
    background-color: {{warn_a15}};
    color: {{warn}};
    border: 1px solid {{warn_a35}};
    font-weight: 600;
}
QLabel[role="badge"][tone="purple"] {
    background-color: {{purple_a15}};
    color: {{purple}};
    border: 1px solid {{purple_a35}};
    font-weight: 600;
}

/* -- Pallino di stato (QFrame 8x8 come statusDot) -- */
QFrame[role="dot"] { background: {{fg_4}}; border-radius: 4px; }
QFrame[role="dot"][tone="accent"] { background: {{accent}}; }
QFrame[role="dot"][tone="success"] { background: {{success}}; }
QFrame[role="dot"][tone="danger"] { background: {{danger}}; }
QFrame[role="dot"][tone="warn"] { background: {{warn}}; }
QFrame[role="dot"][tone="purple"] { background: {{purple}}; }
