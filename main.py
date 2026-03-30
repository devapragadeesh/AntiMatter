"""
main.py
Entry point for ANTI MATTER.

Run from the project root:
    python main.py
"""

import sys
from pathlib import Path

# ensure project root is on path so ui/ can import compressor, selector etc
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.main_window import MainWindow
from ui.styles import DARK_THEME


def main():
    # enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Anti Matter")
    app.setOrganizationName("AntiMatter")

    # apply dark theme
    app.setStyleSheet(DARK_THEME)

    # default font
    font = QFont()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
