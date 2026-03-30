"""
compress_screen.py
Full compress screen — left panel (file) + right panel (params + prediction).
"""
from PySide6.QtCore import Qt, Signal, QThread
import os
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QFileDialog, QSizePolicy,
    QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from .state import AppState
from .worker import ProfileWorker, CompressWorker, ProgressTickerWorker


# ---------------------------------------------------------------------------
# Drop Zone
# ---------------------------------------------------------------------------

class DropZone(QFrame):
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

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 32px; color: #444444;")

        title = QLabel("Drag & drop file")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 500;")

        subtitle = QLabel("or click to browse local files")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("secondary_label")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
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
    def __init__(self, icon: str = "📄"):
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
        self._meta.setText(f"{ext}  •  {size_mb:.1f} MB")

    def set_compressed(self, path: Path):
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
            usage = psutil.disk_usage(str(self._path))
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
# Prediction Card
# ---------------------------------------------------------------------------

class PredictionCard(QFrame):
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

        # divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #2a2a2a;")

        # size + duration grid
        grid = QHBoxLayout()
        grid.setSpacing(16)

        # left: est final size
        size_col = QVBoxLayout()
        size_col.setSpacing(4)
        size_lbl = QLabel("EST. FINAL SIZE")
        size_lbl.setObjectName("section_label")
        self._size_val = QLabel("—")
        self._size_val.setObjectName("value_large")
        self._size_val.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._size_sub = QLabel("")
        self._size_sub.setObjectName("value_accent")
        size_col.addWidget(size_lbl)
        size_col.addWidget(self._size_val)
        size_col.addWidget(self._size_sub)

        # right: est duration
        dur_col = QVBoxLayout()
        dur_col.setSpacing(4)
        dur_lbl = QLabel("EST. DURATION")
        dur_lbl.setObjectName("section_label")
        self._dur_val = QLabel("—")
        self._dur_val.setObjectName("value_large")
        self._dur_val.setStyleSheet("font-size: 24px; font-weight: 700;")
        self._dur_sub = QLabel("")
        self._dur_sub.setObjectName("secondary_label")
        dur_col.addWidget(dur_lbl)
        dur_col.addWidget(self._dur_val)
        dur_col.addWidget(self._dur_sub)

        grid.addLayout(size_col)
        grid.addStretch()
        grid.addLayout(dur_col)

        # range row
        range_row = QHBoxLayout()
        range_lbl = QLabel("Ratio range")
        range_lbl.setObjectName("secondary_label")
        self._range_val = QLabel("—")
        self._range_val.setObjectName("secondary_label")
        self._range_val.setAlignment(Qt.AlignRight)
        range_row.addWidget(range_lbl)
        range_row.addStretch()
        range_row.addWidget(self._range_val)

        # memory row
        mem_row = QHBoxLayout()
        mem_lbl = QLabel("Est. memory")
        mem_lbl.setObjectName("secondary_label")
        self._mem_val = QLabel("—")
        self._mem_val.setObjectName("secondary_label")
        self._mem_val.setAlignment(Qt.AlignRight)
        mem_row.addWidget(mem_lbl)
        mem_row.addStretch()
        mem_row.addWidget(self._mem_val)

        # confidence row
        conf_row = QHBoxLayout()
        conf_lbl = QLabel("Confidence")
        conf_lbl.setObjectName("secondary_label")
        self._conf_val = QLabel("—")
        self._conf_val.setAlignment(Qt.AlignRight)
        conf_row.addWidget(conf_lbl)
        conf_row.addStretch()
        conf_row.addWidget(self._conf_val)

        layout.addLayout(engine_row)
        layout.addWidget(div)
        layout.addLayout(grid)
        layout.addLayout(range_row)
        layout.addLayout(mem_row)
        layout.addLayout(conf_row)
        layout.addStretch()

    def update(self, data: dict, file_size_mb: float):
        engine = data.get("engine", "")
        level  = data.get("level", 0)
        self._engine_val.setText(f"🔵 {engine} L{level}")

        ratio   = data.get("predicted_ratio", 0)
        out_mb  = file_size_mb / ratio if ratio > 0 else 0
        cmp_s   = data.get("predicted_compress_speed", 0)
        cmp_t   = data.get("predicted_compress_time", 0)

        # size
        if out_mb >= 1024:
            self._size_val.setText(f"~{out_mb/1024:.2f} GB")
        else:
            self._size_val.setText(f"~{out_mb:.1f} MB")

        reduction = (1 - 1/ratio) * 100 if ratio > 1 else 0
        self._size_sub.setText(f"↓ {reduction:.0f}% reduction")

        # duration
        if cmp_t >= 60:
            self._dur_val.setText(f"~{cmp_t/60:.0f} min")
        elif cmp_t >= 1:
            self._dur_val.setText(f"~{cmp_t:.1f}s")
        else:
            self._dur_val.setText(f"<1s")
        self._dur_sub.setText(f"@ ~{cmp_s:.0f} MB/s")

        # range
        lo = data.get("ratio_low", 0)
        hi = data.get("ratio_high", 0)
        self._range_val.setText(f"{lo:.1f}x – {hi:.1f}x")

        # memory
        mem = data.get("predicted_memory_mb", 0)
        self._mem_val.setText(f"~{mem:.0f} MB")

        # confidence
        conf = data.get("confidence", "")
        emoji = {"high": "✅ high", "medium": "⚠️ medium", "low": "❌ low"}.get(conf, conf)
        self._conf_val.setText(emoji)

    def clear(self):
        for lbl in [self._engine_val, self._size_val, self._size_sub,
                    self._dur_val, self._dur_sub, self._range_val,
                    self._mem_val, self._conf_val]:
            lbl.setText("—")


# ---------------------------------------------------------------------------
# Progress Strip (bottom)
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

        # top row
        top = QHBoxLayout()
        self._status = QLabel("⟳ COMPRESSING")
        self._status.setObjectName("section_label")
        self._filename = QLabel("")
        self._filename.setObjectName("secondary_label")
        self._pct = QLabel("0%")
        self._pct.setStyleSheet("font-size: 18px; font-weight: 700;")
        top.addWidget(self._status)
        top.addWidget(self._filename)
        top.addStretch()
        top.addWidget(self._pct)

        # bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)

        # bottom row
        bot = QHBoxLayout()
        self._bytes_lbl  = QLabel("")
        self._bytes_lbl.setObjectName("secondary_label")
        self._speed_lbl  = QLabel("")
        self._speed_lbl.setObjectName("secondary_label")
        self._remain_lbl = QLabel("")
        self._remain_lbl.setObjectName("secondary_label")

        cancel_btn = QPushButton("⊗ CANCEL")
        cancel_btn.setObjectName("cancel_button")
        cancel_btn.clicked.connect(self.cancelled)

        bot.addWidget(self._bytes_lbl)
        bot.addWidget(QLabel("•"))
        bot.addWidget(self._speed_lbl)
        bot.addStretch()
        bot.addWidget(self._remain_lbl)
        bot.addWidget(cancel_btn)

        layout.addLayout(top)
        layout.addWidget(self._bar)
        layout.addLayout(bot)

    def start(self, filename: str, predicted_time_s: float):
        self._filename.setText(filename)
        self._predicted_time = max(predicted_time_s, 0.5)
        self._bar.setValue(0)
        self._pct.setText("0%")
        self._status.setText("⟳ COMPRESSING")
        self.show()

    def set_progress(self, pct: int, speed_mbs: float = 0, elapsed: float = 0):
        self._bar.setValue(pct)
        self._pct.setText(f"{pct}%")
        if speed_mbs > 0:
            self._speed_lbl.setText(f"↓ {speed_mbs:.0f} MB/s")
        if elapsed > 0 and pct > 0:
            remaining = max(0, self._predicted_time - elapsed)
            self._remain_lbl.setText(f"~{remaining:.0f}s remaining")

    def finish(self):
        self._bar.setValue(100)
        self._pct.setText("100%")
        self._status.setText("✅ DONE")


# ---------------------------------------------------------------------------
# Compress Screen
# ---------------------------------------------------------------------------

class CompressScreen(QWidget):
    def _run_compression(self):
        if not self.state.input_path:
            return

        output_dir = self._output_row.get_path()
        self.state.output_dir = output_dir

        self._cta.setEnabled(False)
        self._progress.start(
            self.state.input_path.name,
            self.state.predicted_compress_time,
        )

        self._ticker_worker = ProgressTickerWorker(self.state.predicted_compress_time)
        self._ticker_worker.tick.connect(
            lambda pct: self._progress.set_progress(pct, elapsed=0)
        )
        self._ticker_worker.start()

        self._compress_worker = CompressWorker(
            self.state.input_path,
            self.state.engine,
            self.state.level,
            output_dir,
            self.state.predicted_compress_time,
        )
        self._compress_worker.finished.connect(self._on_compress_done)
        self._compress_worker.error.connect(self._on_compress_error)
        self._compress_worker.start()
    def __init__(self, state: AppState):
        super().__init__()
        self.state           = state
        self._profile_worker = None
        self._compress_worker= None
        self._ticker_worker  = None
        self._result_data    = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # main two-panel area
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

        # progress strip at bottom
        self._progress = ProgressStrip()
        self._progress.cancelled.connect(self._cancel)
        root.addWidget(self._progress)

    # ── Left Panel ──────────────────────────────────────

    def _build_left(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        # Input source
        src_lbl = QLabel("INPUT SOURCE")
        src_lbl.setObjectName("section_label")

        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)

        # Staged payload
        staged_lbl = QLabel("STAGED PAYLOAD")
        staged_lbl.setObjectName("section_label")

        self._file_card = FileCard("📄")

        # Destination
        dest_lbl = QLabel("DESTINATION PATH")
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

    # ── Right Panel ─────────────────────────────────────

    def _build_right(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(16)

        # Parameters
        params_lbl = QLabel("PARAMETERS")
        params_lbl.setObjectName("section_label")

        constraint_lbl = QLabel("CONSTRAINT")
        constraint_lbl.setObjectName("secondary_label")

        self._constraint_combo = QComboBox()
        self._constraint_combo.addItems([
            "⚖  Balanced",
            "🗜  Max Compression",
            "⚡  Fast Compression",
            "📤  Fast Decompress",
            "🔋  Low CPU",
            "💾  Low Memory",
        ])
        self._constraint_combo.currentIndexChanged.connect(self._on_constraint_changed)

        degree_lbl = QLabel("DEGREE")
        degree_lbl.setObjectName("secondary_label")

        self._degree_combo = QComboBox()
        self._degree_combo.addItems(["Normal", "Balanced", "High", "Max"])
        self._degree_combo.setCurrentIndex(1)
        self._degree_combo.currentIndexChanged.connect(self._on_constraint_changed)

        params_frame = QFrame()
        params_frame.setObjectName("panel")
        params_layout = QVBoxLayout(params_frame)
        params_layout.setContentsMargins(16, 16, 16, 16)
        params_layout.setSpacing(10)
        params_layout.addWidget(constraint_lbl)
        params_layout.addWidget(self._constraint_combo)
        params_layout.addWidget(degree_lbl)
        params_layout.addWidget(self._degree_combo)

        # Telemetry
        telem_lbl = QLabel("TELEMETRY & PREDICTION")
        telem_lbl.setObjectName("section_label")

        self._pred_card = PredictionCard()

        # CTA button
        self._cta = QPushButton("▶  INITIALIZE ENGINE")
        self._cta.setObjectName("cta_button")
        self._cta.setEnabled(False)
        self._cta.clicked.connect(self._run_compression)

        layout.addWidget(params_lbl)
        layout.addWidget(params_frame)
        layout.addWidget(telem_lbl)
        layout.addWidget(self._pred_card, stretch=1)
        layout.addWidget(self._cta)

        return layout

    # ── Slots ────────────────────────────────────────────

    def _get_constraint_degree(self):
        constraint_map = {
            0: "balanced",
            1: "max_compression",
            2: "fast_compression",
            3: "fast_decompress",
            4: "low_cpu",
            5: "low_memory",
        }
        degree_map = {
            0: "normal",
            1: "balanced",
            2: "high",
            3: "max",
        }
        c = constraint_map.get(self._constraint_combo.currentIndex(), "balanced")
        d = degree_map.get(self._degree_combo.currentIndex(), "balanced")
        return c, d

    def _on_file_dropped(self, path: Path):
        self.state.input_path = path
        self._file_card.set_file(path)
        self._pred_card.clear()
        self._cta.setEnabled(False)
        self._run_profile()

    def _on_constraint_changed(self):
        if self.state.input_path:
            self._run_profile()

    def _run_profile(self):
        if self._profile_worker and self._profile_worker.isRunning():
            self._profile_worker.finished.disconnect()
            self._profile_worker.error.disconnect()
            self._profile_worker.quit()
            self._profile_worker.wait()
    
        constraint, degree = self._get_constraint_degree()
        self.state.constraint = constraint
        self.state.degree     = degree
    
        self._profile_worker = ProfileWorker(
            self.state.input_path,
            constraint,
            degree,
            self.state.db_path,
        )
        self._profile_worker.finished.connect(self._on_profile_done)
        self._profile_worker.error.connect(self._on_profile_error)
    
        # set priority to low so UI thread stays responsive
        self._profile_worker.start(QThread.Priority.LowPriority)
    
        self._cta.setText("⟳  Analyzing...")
        self._cta.setEnabled(False)
    
    def _on_profile_done(self, data: dict):
        # update state
        self.state.engine                    = data["engine"]
        self.state.level                     = data["level"]
        self.state.predicted_ratio           = data["predicted_ratio"]
        self.state.predicted_compress_speed  = data["predicted_compress_speed"]
        self.state.predicted_compress_time   = data["predicted_compress_time"]
        self.state.predicted_memory_mb       = data["predicted_memory_mb"]
        self.state.confidence                = data["confidence"]
        self.state.estimated_output_mb       = data["estimated_output_mb"]

        # update prediction card
        self._pred_card.update(data, data["file_size_mb"])

        self._cta.setText("▶  INITIALIZE ENGINE")
        self._cta.setEnabled(True)

    def _on_profile_error(self, msg: str):
        self._cta.setText("▶  INITIALIZE ENGINE")
        self._cta.setEnabled(bool(self.state.input_path))

    def _start_compression(self):
        if not self.state.input_path:
            return

        output_dir = self._output_row.get_path()
        self.state.output_dir = output_dir

        self._cta.setEnabled(False)
        self._progress.start(
            self.state.input_path.name,
            self.state.predicted_compress_time,
        )

        # start progress ticker
        self._ticker_worker = ProgressTickerWorker(self.state.predicted_compress_time)
        self._ticker_worker.tick.connect(
            lambda pct: self._progress.set_progress(pct, elapsed=0)
        )
        self._ticker_worker.start()

        # start compression
        self._compress_worker = CompressWorker(
            self.state.input_path,
            self.state.engine,
            self.state.level,
            output_dir,
            self.state.predicted_compress_time,
        )
        self._compress_worker.finished.connect(self._on_compress_done)
        self._compress_worker.error.connect(self._on_compress_error)
        self._compress_worker.start()

    def _on_compress_done(self, data: dict):
        if self._ticker_worker:
            self._ticker_worker.stop()
            self._ticker_worker.wait()

        self._progress.finish()

        # store results in state
        self.state.actual_ratio          = data["ratio"]
        self.state.actual_compress_speed = data["compress_speed"]
        self.state.actual_time           = data["compress_time"]
        self.state.actual_output_mb      = data["output_size_mb"]
        self.state.output_path           = Path(data["output_path"])

        self._result_data = data
        self._show_result()

    def _on_compress_error(self, msg: str):
        if self._ticker_worker:
            self._ticker_worker.stop()
        self._progress.hide()
        self._cta.setEnabled(True)
        self._cta.setText("▶  INITIALIZE ENGINE")

    def _show_result(self):
        """Update the prediction card to show actual vs predicted."""
        if not self._result_data:
            return

        pred_ratio  = self.state.predicted_ratio
        actual_ratio = self.state.actual_ratio
        err = abs(pred_ratio - actual_ratio) / pred_ratio * 100 if pred_ratio > 0 else 0

        # update engine label to show result
        d = self._result_data
        out_mb = d.get("output_size_mb", 0)
        ratio  = d.get("ratio", 0)

        self._pred_card._engine_val.setText(
            f"🔵 {d['engine']} L{d['level']}"
        )
        if out_mb >= 1024:
            self._pred_card._size_val.setText(f"~{out_mb/1024:.2f} GB")
        else:
            self._pred_card._size_val.setText(f"~{out_mb:.2f} MB")

        reduction = (1 - 1/ratio) * 100 if ratio > 1 else 0
        self._pred_card._size_sub.setText(
            f"↓ {reduction:.0f}% reduction  •  {ratio:.2f}x actual"
        )
        self._pred_card._dur_val.setText(f"{d['compress_time']:.1f}s")
        self._pred_card._dur_sub.setText(f"@ {d['compress_speed']:.0f} MB/s actual")
        self._pred_card._conf_val.setText(f"Pred error: {err:.1f}%")

        self._cta.setText("✅  Compress another file")
        self._cta.setEnabled(True)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._reset)

        # show output folder button
        open_btn_exists = hasattr(self, '_open_btn')
        if not open_btn_exists:
            from PySide6.QtWidgets import QApplication
            import subprocess
            self._open_btn = QPushButton("📁  Open output folder")
            self._open_btn.setObjectName("cancel_button")
            self._open_btn.clicked.connect(
                lambda: subprocess.Popen(f'explorer "{self.state.output_dir}"')
                if os.name == "nt"
                else None
            )
            self.layout().itemAt(0).layout().itemAt(2).layout().addWidget(self._open_btn)

    def _reset(self):
        self.state.reset_file()
        self._pred_card.clear()
        self._file_card._name.setText("—")
        self._file_card._meta.setText("—")
        self._progress.hide()
        self._cta.setText("▶  INITIALIZE ENGINE")
        self._cta.setEnabled(False)
        self._cta.clicked.disconnect()
        self._cta.clicked.connect(self._run_compression)
        if hasattr(self, '_open_btn'):
            self._open_btn.hide()

    def _cancel(self):
        if self._compress_worker:
            self._compress_worker.cancel()
        if self._ticker_worker:
            self._ticker_worker.stop()
        self._progress.hide()
        self._cta.setEnabled(True)
