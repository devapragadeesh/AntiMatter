"""
main_window.py
Main application window — header, tab bar, screen switcher.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent, QMovie

from ..paths import ASSETS_DIR
from .state import AppState
from .compress_screen import CompressScreen
from .decompress_screen import DecompressScreen
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, initial_path: Optional[Path] = None, initial_mode: Optional[str] = None):
        super().__init__()
        self.state = AppState()
        self._initial_path = initial_path
        self._initial_mode = initial_mode
        # pre-warm DB cache on startup in background
        from threading import Thread
        def _warm_cache():
            try:
                from ..selector import get_db_rows
                get_db_rows()
            except Exception:
                pass

        Thread(target=_warm_cache, daemon=True).start()

        # calibrate local compress speed vs benchmark.db once, in the
        # background, so predicted compress/decompress time adapts to this
        # machine's actual hardware instead of the DB's reference machine.
        # Cached after the first run — subsequent launches skip straight to
        # get_speed_factor() reading the cache.
        def _calibrate():
            try:
                from ..calibration import run_calibration, CACHE_PATH
                if not CACHE_PATH.exists():
                    run_calibration()
            except Exception:
                pass

        Thread(target=_calibrate, daemon=True).start()
        self.setWindowTitle("ANTI MATTER")
        self.setMinimumSize(960, 680)
        self.resize(1040, 720)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)

        self._bg_label = QLabel(central)
        self._bg_label.setScaledContents(True)
        self._movie = QMovie(str(ASSETS_DIR / "bg_loop.gif"))
        self._bg_label.setMovie(self._movie)
        self._movie.start()
        self._bg_label.lower()

        content = QWidget(central)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_divider())
        root.addWidget(self._build_tabs(), stretch=1)

        self._content = content
        self._sync_bg_layout()

    def _sync_bg_layout(self):
        size = self.centralWidget().size()
        self._bg_label.setGeometry(0, 0, size.width(), size.height())
        self._content.setGeometry(0, 0, size.width(), size.height())

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        if hasattr(self, "_bg_label"):
            self._sync_bg_layout()

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

        self._tabs = tabs
        self._apply_initial_path()

        return tabs

    def _apply_initial_path(self):
        """
        Pre-stages a path passed via --context-compress / --context-extract by
        reusing the screens' existing drop-handling logic, and switches to the
        matching tab. No-op if MainWindow was constructed with no initial path
        (the normal launch case).
        """
        if not self._initial_path:
            return

        path = self._initial_path
        if not path.exists():
            # stale path (e.g. deleted/moved between right-click and launch) —
            # fail quietly to a normal empty GUI rather than crashing on startup
            return

        if self._initial_mode == "extract":
            self._tabs.setCurrentIndex(1)
            self._decompress_screen._on_file_dropped(path)
        else:
            self._tabs.setCurrentIndex(0)
            self._compress_screen._on_file_dropped(path)

    def _open_settings(self):
        dialog = SettingsDialog(self.state, self)
        dialog.exec()
