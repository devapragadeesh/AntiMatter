"""
decompress_screen.py
Decompress screen — left panel (compressed file) + right panel (prediction + action).
"""

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QFileDialog, QSizePolicy, QProgressBar,
    QMessageBox,
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
    ".bz2":   "bzip2",
}

ARCHIVE_EXTENSION = ".szip"

# Extensions for the standard-format interop path (extraction only for .rar).
STANDARD_ARCHIVE_EXTENSIONS = (".zip", ".rar", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")


def _has_standard_archive_extension(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(STANDARD_ARCHIVE_EXTENSIONS)

NARROW_BREAKPOINT = 760


# ---------------------------------------------------------------------------
# Drop Zone (reused style, different label)
# ---------------------------------------------------------------------------

class DecompressDropZone(QFrame):
    file_dropped = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel("\U0001F4E6")
        icon.setObjectName("drop_icon")
        icon.setAlignment(Qt.AlignCenter)

        title = QLabel("Drag & drop archive")
        title.setObjectName("drop_title")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("or click to browse local files")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("secondary_label")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select compressed file",
            filter=(
                "Compressed files (*.zst *.lz4 *.gz *.lzma *.br *.bz2 *.szip "
                "*.zip *.rar *.tar *.tar.gz *.tar.bz2 *.tar.xz *.tgz);;"
                "All files (*)"
            )
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
    def __init__(self, icon: str = "\U0001F5DC"):
        super().__init__()
        self.setObjectName("file_card")
        self._icon_char = icon
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self._icon = QLabel(self._icon_char)
        self._icon.setObjectName("icon_label")
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

    def clear(self):
        self._name.setText("—")
        self._meta.setText("—")


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

        icon = QLabel("\U0001F4C1")
        icon.setObjectName("icon_label")
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

        edit_btn = QPushButton("Change")
        edit_btn.setObjectName("browse_button")
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
        div.setObjectName("hr")
        div.setFixedHeight(1)

        grid = QHBoxLayout()
        grid.setSpacing(16)

        size_col = QVBoxLayout()
        size_col.setSpacing(4)
        size_lbl = QLabel("EST. RESTORED SIZE")
        size_lbl.setObjectName("section_label")
        self._size_val = QLabel("—")
        self._size_val.setObjectName("value_large")
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
        self._dur_val.setObjectName("value_large")
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
        self._engine_val.setText(engine)

        compressed_mb = path.stat().st_size / 1024 / 1024

        decomp_speeds = {
            "zstd":   2500, "lz4": 3500,
            "gzip":   1500, "lzma": 400,
            "brotli": 900,  "bzip2": 20,
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

    def update_archive(self, path: Path):
        """Archive mode: read the .szip manifest (engine/level/size per
        entry are already recorded there) and compute a real weighted
        decompress-time estimate instead of a flat placeholder."""
        self._engine_val.setText("szip (per-file)")

        try:
            from ..archiver import predict_archive_decompress

            pred = predict_archive_decompress(path)
            output_mb = pred["predicted_output_size"] / 1024 / 1024
            est_time = pred["predicted_decompress_time"]

            breakdown_str = ", ".join(
                f"{eng}({n})" for eng, n in sorted(pred["engine_breakdown"].items())
            )
            self._engine_val.setText(breakdown_str or "szip (per-file)")

            self._size_val.setText(f"~{output_mb:.1f} MB")
            self._size_sub.setText("↑ expansion from archive")

            if est_time < 1:
                self._dur_val.setText("<1s")
            else:
                self._dur_val.setText(f"~{est_time:.1f}s")
            self._dur_sub.setText(f"{pred['file_count']} files, estimated")

        except Exception:
            # Corrupt/foreign file, or manifest failed to parse — fall back
            # to the old generic display rather than crashing the UI.
            compressed_mb = path.stat().st_size / 1024 / 1024
            self._size_val.setText(f"~{compressed_mb:.1f} MB")
            self._size_sub.setText("↑ expansion from archive")
            self._dur_val.setText("—")
            self._dur_sub.setText("varies per file")

    def update_standard_archive(self, path: Path):
        """Standard-format (zip/tar/rar) mode: no per-file benchmark data
        exists for these codecs, so just list contents for a size/count
        preview rather than a speed/ratio prediction."""
        try:
            from ..standard_formats import list_archive_contents, _sniff_format

            fmt = _sniff_format(path)
            self._engine_val.setText(f"{fmt} (standard)")

            entries = list_archive_contents(path)
            file_entries = [e for e in entries if not e["is_dir"]]
            total_size_mb = sum(e["size"] for e in file_entries) / 1024 / 1024

            self._size_val.setText(f"~{total_size_mb:.1f} MB")
            self._size_sub.setText("↑ expansion from archive")
            self._dur_val.setText("—")
            self._dur_sub.setText(f"{len(file_entries)} files")

        except Exception:
            compressed_mb = path.stat().st_size / 1024 / 1024
            self._engine_val.setText("standard archive")
            self._size_val.setText(f"~{compressed_mb:.1f} MB")
            self._size_sub.setText("↑ expansion from archive")
            self._dur_val.setText("—")
            self._dur_sub.setText("preview unavailable")

    def show_result(self, result: dict):
        out_mb = result.get("output_size_mb", 0)
        t      = result.get("decompress_time", 0)
        spd    = result.get("decompress_speed", 0)

        if out_mb >= 1024:
            self._size_val.setText(f"{out_mb/1024:.2f} GB")
        else:
            self._size_val.setText(f"{out_mb:.2f} MB")

        if result.get("is_folder"):
            self._size_sub.setText(f"Restored  •  {result.get('file_count', 0)} files")
            self._dur_val.setText(f"{t:.2f}s")
            self._dur_sub.setText("total, sequential")
        else:
            self._size_sub.setText("Restored")
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
        self.setFixedHeight(76)
        self._build()
        self.hide()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self._status   = QLabel("DECOMPRESSING")
        self._status.setObjectName("section_label")
        self._filename = QLabel("")
        self._filename.setObjectName("secondary_label")
        self._pct      = QLabel("0%")
        self._pct.setObjectName("value_accent_blue")
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
        cancel_btn = QPushButton("Cancel")
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
        self._status.setText("DECOMPRESSING")
        self.show()

    def set_progress(self, pct: int):
        self._bar.setValue(pct)
        self._pct.setText(f"{pct}%")

    def finish(self):
        self._bar.setValue(100)
        self._pct.setText("100%")
        self._status.setText("DONE")


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
        self._open_btn          = None
        self._narrow            = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._panels_container = QWidget()
        self._panels = QHBoxLayout(self._panels_container)
        self._panels.setContentsMargins(24, 24, 24, 16)
        self._panels.setSpacing(24)

        self._left_layout  = self._build_left()
        self._right_layout = self._build_right()

        self._left_widget  = QWidget()
        self._left_widget.setLayout(self._left_layout)
        self._right_widget = QWidget()
        self._right_widget.setLayout(self._right_layout)

        self._divider = QFrame()
        self._divider.setObjectName("divider")
        self._divider.setFrameShape(QFrame.VLine)

        self._panels.addWidget(self._left_widget, stretch=5)
        self._panels.addWidget(self._divider)
        self._panels.addWidget(self._right_widget, stretch=4)

        root.addWidget(self._panels_container, stretch=1)

        self._progress = ProgressStrip()
        self._progress.cancelled.connect(self._cancel)
        root.addWidget(self._progress)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < NARROW_BREAKPOINT
        if narrow != self._narrow:
            self._narrow = narrow
            self._apply_layout_mode(narrow)

    def _apply_layout_mode(self, narrow: bool):
        if narrow:
            self._panels.setDirection(QVBoxLayout.TopToBottom)
            self._divider.hide()
            self._panels.setStretchFactor(self._left_widget, 0)
            self._panels.setStretchFactor(self._right_widget, 0)
        else:
            self._panels.setDirection(QHBoxLayout.LeftToRight)
            self._divider.show()
            self._panels.setStretchFactor(self._left_widget, 5)
            self._panels.setStretchFactor(self._right_widget, 4)

    def _build_left(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        src_lbl = QLabel("COMPRESSED PAYLOAD")
        src_lbl.setObjectName("section_label")

        self._drop_zone = DecompressDropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)

        staged_lbl = QLabel("STAGED ARCHIVE")
        staged_lbl.setObjectName("section_label")

        self._file_card = FileCard("\U0001F5DC")

        dest_lbl = QLabel("OUTPUT DIRECTORY")
        dest_lbl.setObjectName("section_label")

        self._output_row = OutputDirRow()
        if self.state.output_dir:
            self._output_row.set_path(self.state.output_dir)
        self._output_row.changed.connect(lambda p: setattr(self.state, "output_dir", p))

        self._result_extras = QVBoxLayout()
        self._result_extras.setSpacing(8)

        layout.addWidget(src_lbl)
        layout.addWidget(self._drop_zone)
        layout.addWidget(staged_lbl)
        layout.addWidget(self._file_card)
        layout.addWidget(dest_lbl)
        layout.addWidget(self._output_row)
        layout.addLayout(self._result_extras)
        layout.addStretch()

        return layout

    def _build_right(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        telem_lbl = QLabel("TELEMETRY & PREDICTION")
        telem_lbl.setObjectName("section_label")

        self._pred_card = DecompressPredictionCard()

        self._cta = QPushButton("INITIALIZE ENGINE")
        self._cta.setObjectName("cta_button")
        self._cta.setEnabled(False)
        self._cta.clicked.connect(self._start_decompression)

        layout.addWidget(telem_lbl)
        layout.addWidget(self._pred_card, stretch=1)
        layout.addWidget(self._cta)

        return layout

    def _on_file_dropped(self, path: Path):
        ext = path.suffix.lower()
        is_standard = _has_standard_archive_extension(path)

        if path.is_dir() or (ext != ARCHIVE_EXTENSION and ext not in EXTENSION_ENGINE and not is_standard):
            QMessageBox.warning(
                self,
                "Not a compressed file",
                f"'{path.name}' isn't a compressed file this app recognizes "
                f"and can't be selected for decompression.",
            )
            return

        self._input_path = path
        self._file_card.set_file(path)
        self._pred_card.clear()

        if ext == ARCHIVE_EXTENSION:
            self._detected_engine = None
            self._pred_card.update_archive(path)
            self._cta.setEnabled(True)
            self._cta.setText("INITIALIZE ENGINE")
            return

        if is_standard:
            self._detected_engine = None
            self._pred_card.update_standard_archive(path)
            self._cta.setEnabled(True)
            self._cta.setText("INITIALIZE ENGINE")
            return

        self._detected_engine = EXTENSION_ENGINE.get(ext)
        self._pred_card.update(path, self._detected_engine)
        self._cta.setEnabled(True)
        self._cta.setText("INITIALIZE ENGINE")

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
        self._cta.setText("Decompress another file")
        self._cta.setEnabled(True)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._reset)

        if self._open_btn is None:
            self._open_btn = QPushButton("Open output folder")
            self._open_btn.setObjectName("cancel_button")
            self._open_btn.clicked.connect(self._open_output_folder)
            self._result_extras.addWidget(self._open_btn)
        self._open_btn.show()

    def _open_output_folder(self):
        if os.name == "nt":
            import subprocess
            subprocess.Popen(["explorer", str(self.state.output_dir)])

    def _on_decompress_error(self, msg: str):
        self._progress.hide()
        self._cta.setEnabled(True)
        self._cta.setText("INITIALIZE ENGINE")

    def _reset(self):
        self._input_path      = None
        self._detected_engine = None
        self._pred_card.clear()
        self._file_card.clear()
        self._progress.hide()
        self._cta.setText("INITIALIZE ENGINE")
        self._cta.setEnabled(False)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._start_decompression)
        if self._open_btn:
            self._open_btn.hide()

    def _cancel(self):
        if self._decompress_worker:
            self._decompress_worker.quit()
        self._progress.hide()
        self._cta.setEnabled(True)
