"""
settings_dialog.py
Settings dialog — output folder, default constraint, DB path.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QFrame, QComboBox,
)
from PySide6.QtCore import Qt

from .state import AppState


class SettingsDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setObjectName("settings_dialog")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # title
        title = QLabel("SETTINGS")
        title.setObjectName("section_label")
        layout.addWidget(title)

        layout.addWidget(self._make_divider())

        # default output folder
        layout.addWidget(self._section("DEFAULT OUTPUT FOLDER"))
        out_row = QHBoxLayout()
        self._output_edit = QLineEdit(
            str(self.state.output_dir) if self.state.output_dir else ""
        )
        out_browse = QPushButton("Browse")
        out_browse.setObjectName("cancel_button")
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._output_edit)
        out_row.addWidget(out_browse)
        layout.addLayout(out_row)

        # default constraint
        layout.addWidget(self._section("DEFAULT CONSTRAINT"))
        self._constraint_combo = QComboBox()
        self._constraint_combo.addItems([
            "Balanced", "Max Compression", "Fast Compression",
            "Fast Decompress", "Low CPU", "Low Memory",
        ])
        constraint_map = {
            "balanced": 0, "max_compression": 1, "fast_compression": 2,
            "fast_decompress": 3, "low_cpu": 4, "low_memory": 5,
        }
        self._constraint_combo.setCurrentIndex(
            constraint_map.get(self.state.constraint, 0)
        )
        layout.addWidget(self._constraint_combo)

        # default degree
        layout.addWidget(self._section("DEFAULT DEGREE"))
        self._degree_combo = QComboBox()
        self._degree_combo.addItems(["Normal", "Balanced", "High", "Max"])
        degree_map = {"normal": 0, "balanced": 1, "high": 2, "max": 3}
        self._degree_combo.setCurrentIndex(
            degree_map.get(self.state.degree, 1)
        )
        layout.addWidget(self._degree_combo)

        # database path
        layout.addWidget(self._section("BENCHMARK DATABASE PATH"))
        db_row = QHBoxLayout()
        self._db_edit = QLineEdit(
            str(self.state.db_path) if self.state.db_path else ""
        )
        db_browse = QPushButton("Browse")
        db_browse.setObjectName("cancel_button")
        db_browse.clicked.connect(self._browse_db)
        db_row.addWidget(self._db_edit)
        db_row.addWidget(db_browse)
        layout.addLayout(db_row)

        layout.addWidget(self._make_divider())

        # about
        about_lbl = QLabel(
            "ANTI MATTER  v1.0  —  Smart Compression Tool\n"
            "Built with Python, PySide6, zstd, lz4, brotli, gzip, lzma, bzip2"
        )
        about_lbl.setObjectName("secondary_label")
        about_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(about_lbl)

        # buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_button")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("cta_button")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self._save)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("secondary_label")
        return lbl

    def _make_divider(self) -> QFrame:
        div = QFrame()
        div.setObjectName("hr")
        div.setFixedHeight(1)
        return div

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self._output_edit.setText(path)

    def _browse_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select benchmark.db", filter="SQLite (*.db)"
        )
        if path:
            self._db_edit.setText(path)

    def _save(self):
        constraint_values = [
            "balanced", "max_compression", "fast_compression",
            "fast_decompress", "low_cpu", "low_memory",
        ]
        degree_values = ["normal", "balanced", "high", "max"]

        out = self._output_edit.text().strip()
        if out:
            self.state.output_dir = Path(out)

        self.state.constraint = constraint_values[self._constraint_combo.currentIndex()]
        self.state.degree     = degree_values[self._degree_combo.currentIndex()]

        db = self._db_edit.text().strip()
        if db:
            self.state.db_path = Path(db)

        self.accept()
