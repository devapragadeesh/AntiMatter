"""
styles.py
Full dark theme QSS stylesheet for ANTI MATTER.
"""

# ── Design tokens ──────────────────────────────────────────
# Keep spacing/radius/color choices here so the rest of the UI
# can reference one source of truth instead of scattering
# inline setStyleSheet() calls.

# Elevation ladder — each step must be clearly distinguishable from the
# last at a glance, not just a few hex units apart.
COLOR_BG          = "#0a0a0f"   # window background (darkest)
COLOR_BG_PANEL    = "#1c1c26"   # cards/panels sitting on the window
COLOR_BG_RAISED   = "#26262f"   # rows/inputs sitting on a panel
COLOR_BG_HOVER    = "#31313c"   # hover state for raised elements
COLOR_BORDER      = "#3a3a46"   # visible border on panels/inputs
COLOR_BORDER_SOFT = "#2a2a34"   # subtler divider lines
COLOR_ACCENT      = "#5b9dff"
COLOR_ACCENT_DARK = "#4c7cf0"
COLOR_ACCENT_HOVER= "#3d68d8"
COLOR_ACCENT_PRESS= "#3358bd"
COLOR_SUCCESS     = "#4ade80"
COLOR_WARNING     = "#facc15"
COLOR_DANGER      = "#f87171"
COLOR_TEXT        = "#f5f5f7"
COLOR_TEXT_DIM    = "#b4b4c0"
COLOR_TEXT_FAINT  = "#7a7a88"

RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10

DARK_THEME = f"""
/* ── Global ─────────────────────────────────────────── */
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    color: {COLOR_TEXT};
    outline: none;
}}

QWidget {{
    background-color: {COLOR_BG};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {COLOR_BG};
}}

QMessageBox {{
    background-color: {COLOR_BG_PANEL};
}}

QMessageBox QLabel {{
    color: {COLOR_TEXT};
    font-size: 13px;
}}

QMessageBox QPushButton {{
    background-color: {COLOR_ACCENT_DARK};
    color: {COLOR_TEXT};
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: 600;
    min-width: 70px;
}}

QMessageBox QPushButton:hover {{
    background-color: {COLOR_ACCENT_HOVER};
}}

QMessageBox QPushButton:pressed {{
    background-color: {COLOR_ACCENT_PRESS};
}}

/* ── Section Labels ──────────────────────────────────── */
QLabel#section_label {{
    color: {COLOR_ACCENT};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
}}

QLabel#title_label {{
    color: {COLOR_TEXT};
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 2px;
}}

QLabel#version_label {{
    color: {COLOR_TEXT_FAINT};
    font-size: 11px;
}}

QLabel#secondary_label {{
    color: {COLOR_TEXT_DIM};
    font-size: 12px;
}}

QLabel#value_large {{
    color: {COLOR_TEXT};
    font-size: 24px;
    font-weight: 700;
}}

QLabel#value_accent {{
    color: {COLOR_SUCCESS};
    font-size: 12px;
}}

QLabel#value_accent_blue {{
    color: {COLOR_ACCENT};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#engine_value {{
    color: {COLOR_ACCENT};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#icon_label {{
    font-size: 20px;
    color: {COLOR_TEXT_DIM};
}}

QLabel#drop_icon {{
    font-size: 30px;
    color: {COLOR_TEXT_FAINT};
}}

QLabel#drop_title {{
    color: {COLOR_TEXT};
    font-size: 14px;
    font-weight: 500;
}}

QLabel#folder_link {{
    color: {COLOR_ACCENT};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
}}

QLabel#folder_link:hover {{
    color: {COLOR_ACCENT_HOVER};
    text-decoration: underline;
}}

/* ── Panels ──────────────────────────────────────────── */
QFrame#panel {{
    background-color: {COLOR_BG_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_MD}px;
}}

QFrame#drop_zone {{
    background-color: {COLOR_BG_PANEL};
    border: 2px dashed {COLOR_BORDER};
    border-radius: {RADIUS_MD}px;
}}

QFrame#drop_zone:hover {{
    border-color: {COLOR_ACCENT};
    background-color: #1a2438;
}}

QFrame#drop_zone_active {{
    background-color: #1a2438;
    border: 2px dashed {COLOR_ACCENT};
    border-radius: {RADIUS_MD}px;
}}

QFrame#file_card {{
    background-color: {COLOR_BG_RAISED};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_MD}px;
}}

QFrame#divider {{
    background-color: {COLOR_BORDER};
    max-width: 1px;
    min-width: 1px;
}}

QFrame#hr {{
    background-color: {COLOR_BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ── Tab Bar ─────────────────────────────────────────── */
QTabBar::tab {{
    background-color: transparent;
    color: {COLOR_TEXT_FAINT};
    padding: 8px 24px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    border: none;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {COLOR_TEXT};
    border-bottom: 2px solid {COLOR_ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: #aaaaaa;
}}

QTabWidget::pane {{
    border: none;
    background-color: {COLOR_BG};
}}

QTabWidget {{
    background-color: {COLOR_BG};
}}

/* ── Dropdowns ───────────────────────────────────────── */
QComboBox {{
    background-color: {COLOR_BG_RAISED};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px 12px;
    color: {COLOR_TEXT};
    font-size: 13px;
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: #3a3a3a;
}}

QComboBox:focus {{
    border-color: {COLOR_ACCENT};
}}

QComboBox:disabled {{
    background-color: {COLOR_BG_PANEL};
    border-color: {COLOR_BORDER_SOFT};
    color: {COLOR_TEXT_FAINT};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #888888;
    width: 0;
    height: 0;
    margin-right: 10px;
}}

QComboBox:disabled::down-arrow {{
    border-top-color: {COLOR_TEXT_FAINT};
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_BG_RAISED};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM}px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_TEXT};
    padding: 4px;
}}

/* ── Buttons ─────────────────────────────────────────── */
QPushButton#cta_button {{
    background-color: {COLOR_ACCENT_DARK};
    color: {COLOR_TEXT};
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 14px 24px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
    min-height: 20px;
}}

QPushButton#cta_button:hover {{
    background-color: {COLOR_ACCENT_HOVER};
}}

QPushButton#cta_button:pressed {{
    background-color: {COLOR_ACCENT_PRESS};
}}

QPushButton#cta_button:disabled {{
    background-color: #1e3a5f;
    color: #4a6a9f;
}}

QPushButton#cancel_button {{
    background-color: transparent;
    color: {COLOR_TEXT_DIM};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px 16px;
    font-size: 12px;
}}

QPushButton#cancel_button:hover {{
    color: {COLOR_TEXT};
    border-color: #4a4a4a;
    background-color: {COLOR_BG_HOVER};
}}

QPushButton#icon_button {{
    background-color: transparent;
    border: none;
    color: {COLOR_TEXT_FAINT};
    font-size: 16px;
    padding: 4px;
    border-radius: {RADIUS_SM}px;
}}

QPushButton#icon_button:hover {{
    color: {COLOR_TEXT};
    background-color: {COLOR_BG_HOVER};
}}

QPushButton#browse_button {{
    background-color: transparent;
    color: {COLOR_TEXT_DIM};
    border: none;
    font-size: 13px;
    padding: 4px 8px;
    border-radius: {RADIUS_SM}px;
}}

QPushButton#browse_button:hover {{
    color: {COLOR_TEXT};
    background-color: {COLOR_BG_HOVER};
}}

/* ── Progress Bar ────────────────────────────────────── */
QProgressBar {{
    background-color: {COLOR_BG_RAISED};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLOR_ACCENT_DARK};
    border-radius: 3px;
}}

/* ── Scrollbar ───────────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {COLOR_BG};
    width: 8px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background-color: {COLOR_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: #3a3a3a;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {COLOR_BG};
    height: 8px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLOR_BORDER};
    border-radius: 4px;
    min-width: 20px;
}}

/* ── Settings Dialog ─────────────────────────────────── */
QDialog#settings_dialog {{
    background-color: #111111;
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_LG}px;
}}

QLineEdit {{
    background-color: {COLOR_BG_RAISED};
    border: 1px solid {COLOR_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px 12px;
    color: {COLOR_TEXT};
    font-size: 13px;
}}

QLineEdit:focus {{
    border-color: {COLOR_ACCENT};
}}

/* ── Separator ───────────────────────────────────────── */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {{
    color: {COLOR_BORDER};
}}

/* ── Tooltip ─────────────────────────────────────────── */
QToolTip {{
    background-color: {COLOR_BG_RAISED};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}
"""
