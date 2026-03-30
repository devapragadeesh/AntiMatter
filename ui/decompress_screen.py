"""
decompress_screen.py
Decompress screen — left panel (compressed file) + right panel (prediction + action).
"""

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QFileDialog, QSizePolicy, QProgressBar,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from .state import AppState
from .worker import DecompressWorker

# Engine extensions for auto-detection display
EXTENSION_ENGINE = {
    ".zst":   "zstd",
    ".lz4":   "lz4",
    ".gz":    "gzip",
    ".lzma":  "lzma",
    ".br":    "brotli",
}


# ---------------------------------------------------------------------------
# Drop Zone (reused style, different label)
# ---------------------------------------------------------------------------

class DecompressDropZone(QFrame):
    file_dropped = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel("📦")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 32px;")

        title = QLabel("Drag & drop archive")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 500;")

        subtitle = QLabel("or click to browse local files")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("secondary_label")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select compressed file",
            filter="Compressed files (*.zst *.lz4 *.gz *.lzma *.br);;All files (*)"
        )
        if path:
            self.file_dropped.emit(Path(path))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self.setObjectName("drop_zone_active")
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setObjectName("drop_zone")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setObjectName("drop_zone")
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(Path(urls[0].toLocalFile()))


# ---------------------------------------------------------------------------
# File Card
# ---------------------------------------------------------------------------

class FileCard(QFrame):
    def __init__(self, icon: str = "🗜"):
        super().__init__()
        self.setObjectName("file_card")
        self._icon_char = icon
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self._icon = QLabel(self._icon_char)
        self._icon.setStyleSheet("font-size: 22px;")
        self._icon.setFixedWidth(30)

        info = QVBoxLayout()
        info.setSpacing(2)
        self._name = QLabel("—")
        self._name.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._meta = QLabel("—")
        self._meta.setObjectName("secondary_label")
        info.addWidget(self._name)
        info.addWidget(self._meta)

        layout.addWidget(self._icon)
        layout.addLayout(info)
        layout.addStretch()

    def set_file(self, path: Path):
        size_mb = path.stat().st_size / 1024 / 1024
        ext     = path.suffix.upper().lstrip(".")
        self._name.setText(path.name)
        self._meta.setText(f"{ext}  •  {size_mb:.2f} MB")


# ---------------------------------------------------------------------------
# Output Directory Row
# ---------------------------------------------------------------------------

class OutputDirRow(QFrame):
    changed = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("file_card")
        self._path = Path.home() / "Downloads"
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        icon = QLabel("📁")
        icon.setStyleSheet("font-size: 22px;")
        icon.setFixedWidth(30)

        info = QVBoxLayout()
        info.setSpacing(2)
        self._path_label = QLabel(str(self._path))
        self._path_label.setStyleSheet("font-weight: 500; font-size: 12px;")
        self._free_label = QLabel("")
        self._free_label.setObjectName("secondary_label")
        self._update_free()
        info.addWidget(self._path_label)
        info.addWidget(self._free_label)

        edit_btn = QPushButton("✏")
        edit_btn.setObjectName("browse_button")
        edit_btn.setFixedWidth(28)
        edit_btn.clicked.connect(self._browse)

        layout.addWidget(icon)
        layout.addLayout(info)
        layout.addStretch()
        layout.addWidget(edit_btn)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder", str(self._path))
        if path:
            self._path = Path(path)
            self._path_label.setText(str(self._path))
            self._update_free()
            self.changed.emit(self._path)

    def _update_free(self):
        try:
            import psutil
            usage   = psutil.disk_usage(str(self._path))
            free_gb = usage.free / 1024 ** 3
            self._free_label.setText(
                f"<span style='color:#4ade80'>{free_gb:.1f} GB free</span>"
            )
            self._free_label.setTextFormat(Qt.RichText)
        except Exception:
            self._free_label.setText("")

    def get_path(self) -> Path:
        return self._path

    def set_path(self, path: Path):
        self._path = path
        self._path_label.setText(str(path))
        self._update_free()


# ---------------------------------------------------------------------------
# Decompress Prediction Card
# ---------------------------------------------------------------------------

class DecompressPredictionCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("panel")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # engine row
        engine_row = QHBoxLayout()
        engine_lbl = QLabel("Active Engine")
        engine_lbl.setObjectName("secondary_label")
        self._engine_val = QLabel("—")
        self._engine_val.setObjectName("engine_value")
        self._engine_val.setAlignment(Qt.AlignRight)
        engine_row.addWidget(engine_lbl)
        engine_row.addStretch()
        engine_row.addWidget(self._engine_val)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #2a2a2a;")

        # grid
        grid = QHBoxLayout()
        grid.setSpacing(16)

        size_col = QVBoxLayout()
        size_col.setSpacing(4)
        size_lbl = QLabel("EST. RESTORED SIZE")
        size_lbl.setObjectName("section_label")
        self._size_val = QLabel("—")
        self._size_val.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._size_sub = QLabel("")
        self._size_sub.setObjectName("value_accent")
        size_col.addWidget(size_lbl)
        size_col.addWidget(self._size_val)
        size_col.addWidget(self._size_sub)

        dur_col = QVBoxLayout()
        dur_col.setSpacing(4)
        dur_lbl = QLabel("EST. DURATION")
        dur_lbl.setObjectName("section_label")
        self._dur_val = QLabel("—")
        self._dur_val.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._dur_sub = QLabel("")
        self._dur_sub.setObjectName("secondary_label")
        dur_col.addWidget(dur_lbl)
        dur_col.addWidget(self._dur_val)
        dur_col.addWidget(self._dur_sub)

        grid.addLayout(size_col)
        grid.addStretch()
        grid.addLayout(dur_col)

        layout.addLayout(engine_row)
        layout.addWidget(div)
        layout.addLayout(grid)
        layout.addStretch()

    def update(self, path: Path, engine: str):
        """
        For decompression we don't have a predictor lookup,
        but we know the compressed size and can estimate from engine.
        """
        self._engine_val.setText(f"🔵 {engine}")

        compressed_mb = path.stat().st_size / 1024 / 1024

        # estimate restored size from compression_hint in filename or just show compressed
        # for structured/repetitive files decompression is very fast
        decomp_speeds = {
            "zstd":   2500, "lz4": 3500,
            "gzip":   1500, "lzma": 400,
            "brotli": 900,
        }
        speed = decomp_speeds.get(engine, 1000)
        est_time = compressed_mb / speed

        self._size_val.setText(f"~{compressed_mb:.1f} MB")
        self._size_sub.setText("↑ expansion from compressed")

        if est_time < 1:
            self._dur_val.setText("<1s")
        else:
            self._dur_val.setText(f"~{est_time:.1f}s")
        self._dur_sub.setText(f"@ ~{speed} MB/s")

    def show_result(self, result: dict):
        out_mb = result.get("output_size_mb", 0)
        t      = result.get("decompress_time", 0)
        spd    = result.get("decompress_speed", 0)

        if out_mb >= 1024:
            self._size_val.setText(f"{out_mb/1024:.2f} GB")
        else:
            self._size_val.setText(f"{out_mb:.2f} MB")
        self._size_sub.setText("✅ restored")

        self._dur_val.setText(f"{t:.2f}s")
        self._dur_sub.setText(f"@ {spd:.0f} MB/s actual")

    def clear(self):
        self._engine_val.setText("—")
        self._size_val.setText("—")
        self._size_sub.setText("")
        self._dur_val.setText("—")
        self._dur_sub.setText("")


# ---------------------------------------------------------------------------
# Progress Strip
# ---------------------------------------------------------------------------

class ProgressStrip(QWidget):
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        self._build()
        self.hide()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self._status   = QLabel("⟳ DECOMPRESSING")
        self._status.setObjectName("section_label")
        self._filename = QLabel("")
        self._filename.setObjectName("secondary_label")
        self._pct      = QLabel("0%")
        self._pct.setStyleSheet("font-size: 18px; font-weight: 700;")
        top.addWidget(self._status)
        top.addWidget(self._filename)
        top.addStretch()
        top.addWidget(self._pct)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)

        bot = QHBoxLayout()
        cancel_btn = QPushButton("⊗ CANCEL")
        cancel_btn.setObjectName("cancel_button")
        cancel_btn.clicked.connect(self.cancelled)
        bot.addStretch()
        bot.addWidget(cancel_btn)

        layout.addLayout(top)
        layout.addWidget(self._bar)
        layout.addLayout(bot)

    def start(self, filename: str):
        self._filename.setText(filename)
        self._bar.setValue(0)
        self._pct.setText("0%")
        self._status.setText("⟳ DECOMPRESSING")
        self.show()

    def set_progress(self, pct: int):
        self._bar.setValue(pct)
        self._pct.setText(f"{pct}%")

    def finish(self):
        self._bar.setValue(100)
        self._pct.setText("100%")
        self._status.setText("✅ DONE")


# ---------------------------------------------------------------------------
# Decompress Screen
# ---------------------------------------------------------------------------

class DecompressScreen(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state              = state
        self._decompress_worker = None
        self._input_path        = None
        self._detected_engine   = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        panels = QHBoxLayout()
        panels.setContentsMargins(24, 24, 24, 16)
        panels.setSpacing(24)

        panels.addLayout(self._build_left(), stretch=5)

        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.VLine)
        panels.addWidget(div)

        panels.addLayout(self._build_right(), stretch=4)

        root.addLayout(panels)

        self._progress = ProgressStrip()
        self._progress.cancelled.connect(self._cancel)
        root.addWidget(self._progress)

    def _build_left(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        src_lbl = QLabel("COMPRESSED PAYLOAD")
        src_lbl.setObjectName("section_label")

        self._drop_zone = DecompressDropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)

        staged_lbl = QLabel("STAGED ARCHIVE")
        staged_lbl.setObjectName("section_label")

        self._file_card = FileCard("🗜")

        dest_lbl = QLabel("OUTPUT DIRECTORY")
        dest_lbl.setObjectName("section_label")

        self._output_row = OutputDirRow()
        if self.state.output_dir:
            self._output_row.set_path(self.state.output_dir)
        self._output_row.changed.connect(lambda p: setattr(self.state, "output_dir", p))

        layout.addWidget(src_lbl)
        layout.addWidget(self._drop_zone)
        layout.addWidget(staged_lbl)
        layout.addWidget(self._file_card)
        layout.addWidget(dest_lbl)
        layout.addWidget(self._output_row)
        layout.addStretch()

        return layout

    def _build_right(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        params_lbl = QLabel("PARAMETERS")
        params_lbl.setObjectName("section_label")

        alloc_lbl = QLabel("ALLOCATION PROFILE")
        alloc_lbl.setObjectName("secondary_label")

        self._alloc_combo = QComboBox()
        self._alloc_combo.addItems([
            "⚡  Max Speed",
            "⚖  Balanced",
            "💾  Memory Efficient",
        ])

        params_frame = QFrame()
        params_frame.setObjectName("panel")
        params_layout = QVBoxLayout(params_frame)
        params_layout.setContentsMargins(16, 16, 16, 16)
        params_layout.setSpacing(10)
        params_layout.addWidget(alloc_lbl)
        params_layout.addWidget(self._alloc_combo)

        telem_lbl = QLabel("TELEMETRY & PREDICTION")
        telem_lbl.setObjectName("section_label")

        self._pred_card = DecompressPredictionCard()

        self._cta = QPushButton("▶  EXTRACTION IN PROGRESS" if False else "▶  INITIALIZE ENGINE")
        self._cta.setObjectName("cta_button")
        self._cta.setEnabled(False)
        self._cta.clicked.connect(self._start_decompression)

        layout.addWidget(params_lbl)
        layout.addWidget(params_frame)
        layout.addWidget(telem_lbl)
        layout.addWidget(self._pred_card, stretch=1)
        layout.addWidget(self._cta)

        return layout

    def _on_file_dropped(self, path: Path):
        self._input_path = path
        ext = path.suffix.lower()
        self._detected_engine = EXTENSION_ENGINE.get(ext)

        self._file_card.set_file(path)
        self._pred_card.clear()

        if self._detected_engine:
            self._pred_card.update(path, self._detected_engine)
            self._cta.setEnabled(True)
            self._cta.setText("▶  INITIALIZE ENGINE")
        else:
            self._cta.setEnabled(False)
            self._cta.setText("Unknown format")

    def _start_decompression(self):
        if not self._input_path:
            return

        output_dir = self._output_row.get_path()
        self.state.output_dir = output_dir

        self._cta.setEnabled(False)
        self._progress.start(self._input_path.name)

        self._decompress_worker = DecompressWorker(
            self._input_path,
            output_dir,
            self._detected_engine,
        )
        self._decompress_worker.progress.connect(self._progress.set_progress)
        self._decompress_worker.finished.connect(self._on_decompress_done)
        self._decompress_worker.error.connect(self._on_decompress_error)
        self._decompress_worker.start()

    def _on_decompress_done(self, data: dict):
        self._progress.finish()
        self._pred_card.show_result(data)
        self._cta.setText("✅  Decompress another file")
        self._cta.setEnabled(True)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._reset)

    def _on_decompress_error(self, msg: str):
        self._progress.hide()
        self._cta.setEnabled(True)
        self._cta.setText("▶  INITIALIZE ENGINE")

    def _reset(self):
        self._input_path      = None
        self._detected_engine = None
        self._pred_card.clear()
        self._file_card._name.setText("—")
        self._file_card._meta.setText("—")
        self._progress.hide()
        self._cta.setText("▶  INITIALIZE ENGINE")
        self._cta.setEnabled(False)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._start_decompression)

    def _cancel(self):
        if self._decompress_worker:
            self._decompress_worker.quit()
        self._progress.hide()
        self._cta.setEnabled(True)
