"""
main_window.py
Main application window — header, tab bar, screen switcher.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QFrame,
)
from PySide6.QtCore import Qt

from .state import AppState
from .compress_screen import CompressScreen
from .decompress_screen import DecompressScreen
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        # pre-warm DB cache on startup in background
        from threading import Thread
        def _warm_cache():
            try:
                import sys
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).parent.parent))
                from selector import get_db_rows
                get_db_rows()
            except Exception:
                pass

        Thread(target=_warm_cache, daemon=True).start()
        self.setWindowTitle("ANTI MATTER")
        self.setMinimumSize(960, 680)
        self.resize(1040, 720)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_divider())
        root.addWidget(self._build_tabs(), stretch=1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(12)

        # App name
        title = QLabel("ANTI MATTER")
        title.setObjectName("title_label")

        # right side — settings + version
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("icon_button")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)

        sep = QFrame()
        sep.setObjectName("divider")
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(20)

        version = QLabel("v1.0")
        version.setObjectName("version_label")

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(settings_btn)
        layout.addWidget(sep)
        layout.addWidget(version)

        return header

    def _build_divider(self) -> QFrame:
        div = QFrame()
        div.setObjectName("hr")
        div.setFixedHeight(1)
        return div

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setTabPosition(QTabWidget.North)

        self._compress_screen   = CompressScreen(self.state)
        self._decompress_screen = DecompressScreen(self.state)

        tabs.addTab(self._compress_screen,   "COMPRESS")
        tabs.addTab(self._decompress_screen, "DECOMPRESS")

        # sync output dir between tabs
        self._compress_screen._output_row.changed.connect(
            self._decompress_screen._output_row.set_path
        )
        self._decompress_screen._output_row.changed.connect(
            self._compress_screen._output_row.set_path
        )

        return tabs

    def _open_settings(self):
        dialog = SettingsDialog(self.state, self)
        dialog.exec()
