"""
styles.py
Full dark theme QSS stylesheet for ANTI MATTER.
"""

DARK_THEME = """
/* ── Global ─────────────────────────────────────────── */
* {
    font-family: "Segoe UI", "Inter", sans-serif;
    color: #ffffff;
    outline: none;
}

QWidget {
    font-size: 13px;        ← move it here instead
    background-color: #0d0d0d;
}

QMainWindow, QDialog {
    background-color: #0d0d0d;
}

QWidget {
    background-color: #0d0d0d;
}

/* ── Section Labels ──────────────────────────────────── */
QLabel#section_label {
    color: #4a9eff;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
}

QLabel#title_label {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#version_label {
    color: #555555;
    font-size: 11px;
}

QLabel#secondary_label {
    color: #888888;
    font-size: 12px;
}

QLabel#value_large {
    color: #ffffff;
    font-size: 28px;
    font-weight: 700;
}

QLabel#value_accent {
    color: #4ade80;
    font-size: 12px;
}

QLabel#value_accent_blue {
    color: #4a9eff;
    font-size: 13px;
    font-weight: 600;
}

QLabel#engine_value {
    color: #4a9eff;
    font-size: 13px;
    font-weight: 600;
}

/* ── Panels ──────────────────────────────────────────── */
QFrame#panel {
    background-color: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
}

QFrame#drop_zone {
    background-color: #111111;
    border: 1.5px dashed #2a2a2a;
    border-radius: 8px;
}

QFrame#drop_zone:hover {
    border-color: #4a9eff;
    background-color: #111a2a;
}

QFrame#drop_zone_active {
    background-color: #111a2a;
    border: 1.5px dashed #4a9eff;
    border-radius: 8px;
}

QFrame#file_card {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 4px;
}

QFrame#divider {
    background-color: #2a2a2a;
    max-width: 1px;
    min-width: 1px;
}

/* ── Tab Bar ─────────────────────────────────────────── */
QTabBar::tab {
    background-color: transparent;
    color: #555555;
    padding: 8px 24px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    border: none;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:selected {
    color: #ffffff;
    border-bottom: 2px solid #4a9eff;
}

QTabBar::tab:hover:!selected {
    color: #aaaaaa;
}

QTabWidget::pane {
    border: none;
    background-color: #0d0d0d;
}

QTabWidget {
    background-color: #0d0d0d;
}

/* ── Dropdowns ───────────────────────────────────────── */
QComboBox {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 12px;
    color: #ffffff;
    font-size: 13px;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #3a3a3a;
}

QComboBox:focus {
    border-color: #4a9eff;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #888888;
    width: 0;
    height: 0;
    margin-right: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    selection-background-color: #4a9eff;
    selection-color: #ffffff;
    padding: 4px;
}

/* ── Buttons ─────────────────────────────────────────── */
QPushButton#cta_button {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 14px 24px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
    min-height: 20px;
}

QPushButton#cta_button:hover {
    background-color: #2563eb;
}

QPushButton#cta_button:pressed {
    background-color: #1d4ed8;
}

QPushButton#cta_button:disabled {
    background-color: #1e3a5f;
    color: #4a6a9f;
}

QPushButton#cancel_button {
    background-color: transparent;
    color: #888888;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 12px;
}

QPushButton#cancel_button:hover {
    color: #ffffff;
    border-color: #4a4a4a;
}

QPushButton#icon_button {
    background-color: transparent;
    border: none;
    color: #555555;
    font-size: 16px;
    padding: 4px;
}

QPushButton#icon_button:hover {
    color: #aaaaaa;
}

QPushButton#browse_button {
    background-color: transparent;
    color: #888888;
    border: none;
    font-size: 14px;
    padding: 2px 6px;
}

QPushButton#browse_button:hover {
    color: #ffffff;
}

/* ── Progress Bar ────────────────────────────────────── */
QProgressBar {
    background-color: #1a1a1a;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 3px;
}

/* ── Scrollbar ───────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #0d0d0d;
    width: 6px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #2a2a2a;
    border-radius: 3px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3a3a3a;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ── Settings Dialog ─────────────────────────────────── */
QDialog#settings_dialog {
    background-color: #111111;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
}

QLineEdit {
    background-color: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 12px;
    color: #ffffff;
    font-size: 13px;
}

QLineEdit:focus {
    border-color: #4a9eff;
}

/* ── Separator ───────────────────────────────────────── */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #2a2a2a;
}

/* ── Tooltip ─────────────────────────────────────────── */
QToolTip {
    background-color: #1a1a1a;
    color: #ffffff;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
"""
