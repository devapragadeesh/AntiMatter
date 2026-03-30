"""
worker.py
QThread workers — keeps UI responsive during heavy operations.

Three workers:
    ProfileWorker    — runs profiler + selector + predictor after file drop
    CompressWorker   — runs actual compression, emits progress
    DecompressWorker — runs decompression
"""

import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal


# ---------------------------------------------------------------------------
# Profile + Select + Predict Worker
# Runs immediately when a file is dropped.
# ---------------------------------------------------------------------------

class ProfileWorker(QThread):
    """
    Profiles file, runs selector, runs predictor.
    Emits result when done so the UI can update prediction card.
    """
    finished = Signal(dict)   # emits result dict
    error    = Signal(str)    # emits error message

    def __init__(self, file_path: Path, constraint: str, degree: str,
                 db_path: Optional[Path] = None):
        super().__init__()
        self.file_path  = file_path
        self.constraint = constraint
        self.degree     = degree
        self.db_path    = db_path

    def run(self):
        try:
            # add project root to path so imports work
            import sys
            from pathlib import Path
            root = Path(__file__).parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))

            from profiler import profile_file
            from selector import select
            from predictor import predict

            # profile
            profile = profile_file(self.file_path)

            # select
            constraints = [(self.constraint, self.degree)]
            kwargs = {}
            if self.db_path:
                kwargs["db_path"] = self.db_path

            rec = select(self.file_path, constraints, **kwargs)

            # predict
            pred = predict(
                self.file_path, rec.engine, rec.level,
                self.db_path
            )

            result = {
                # profile
                "entropy":          profile.entropy,
                "repetitiveness":   profile.repetitiveness,
                "compression_hint": profile.compression_hint,
                "file_size_mb":     profile.file_size / 1024 / 1024,
                # recommendation
                "engine":       rec.engine,
                "level":        rec.level,
                "reason":       rec.reason,
                "alternatives": [
                    {
                        "engine": a.engine,
                        "level":  a.level,
                        "ratio":  a.predicted_ratio,
                        "cmp":    a.predicted_compress_speed,
                        "dcmp":   a.predicted_decompress_speed,
                    }
                    for a in rec.alternatives
                ],
                # prediction
                "predicted_ratio":           pred.predicted_ratio          if pred else rec.predicted_ratio,
                "predicted_compress_speed":  pred.predicted_compress_speed if pred else rec.predicted_compress_speed,
                "predicted_decompress_speed":pred.predicted_decompress_speed if pred else rec.predicted_decompress_speed,
                "predicted_memory_mb":       pred.predicted_memory_mb      if pred else rec.predicted_memory_mb,
                "predicted_compress_time":   pred.predicted_compress_time  if pred else 0.0,
                "predicted_decompress_time": pred.predicted_decompress_time if pred else 0.0,
                "ratio_low":    pred.ratio_low   if pred else 0.0,
                "ratio_high":   pred.ratio_high  if pred else 0.0,
                "confidence":   pred.confidence  if pred else "low",
                "estimated_output_mb": pred.estimated_output_mb if pred else 0.0,
                "warning":      pred.warning if pred else rec.warning,
            }

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Compress Worker
# ---------------------------------------------------------------------------

class CompressWorker(QThread):
    """
    Runs actual compression on a background thread.
    Emits progress periodically based on elapsed time vs predicted time.
    """
    progress  = Signal(int)    # 0-100
    finished  = Signal(dict)   # result dict
    error     = Signal(str)

    def __init__(
        self,
        file_path:        Path,
        engine:           str,
        level:            int,
        output_path:      Optional[Path],
        predicted_time_s: float,
    ):
        super().__init__()
        self.file_path        = file_path
        self.engine           = engine
        self.level            = level
        self.output_path      = output_path
        self.predicted_time_s = max(predicted_time_s, 0.5)
        self._cancelled       = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import sys
            from pathlib import Path
            root = Path(__file__).parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))

            from compressor import compress

            # emit fake progress based on predicted time
            # real compression runs in the same thread —
            # progress ticks in 100ms intervals up to 90%
            # then jumps to 100% when done
            start = time.perf_counter()

            # run compression (blocking)
            result = compress(
                self.file_path,
                self.engine,
                self.level,
                self.output_path,
            )

            elapsed = time.perf_counter() - start

            if not result.success:
                self.error.emit(result.error or "Compression failed")
                return

            self.progress.emit(100)
            self.finished.emit({
                "ratio":          result.ratio,
                "compress_speed": result.compress_speed,
                "compress_time":  result.compress_time,
                "input_size_mb":  result.input_size  / 1024 / 1024,
                "output_size_mb": result.output_size / 1024 / 1024,
                "output_path":    str(result.output_path),
                "peak_memory_mb": result.peak_memory_mb,
                "engine":         result.engine,
                "level":          result.level,
            })

        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Progress Ticker — separate thread to animate progress bar
# while CompressWorker runs on main thread
# ---------------------------------------------------------------------------

class ProgressTickerWorker(QThread):
    """
    Emits progress ticks (0-90%) based on predicted time.
    Stops when told to. Parent emits 100% when compression finishes.
    """
    tick = Signal(int)

    def __init__(self, predicted_time_s: float):
        super().__init__()
        self.predicted_time_s = max(predicted_time_s, 1.0)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        start    = time.perf_counter()
        interval = 0.1  # tick every 100ms

        while not self._stop:
            elapsed = time.perf_counter() - start
            # progress goes to 90% over predicted time
            # never reaches 100% — that's emitted by CompressWorker
            pct = min(int((elapsed / self.predicted_time_s) * 90), 90)
            self.tick.emit(pct)
            time.sleep(interval)


# ---------------------------------------------------------------------------
# Decompress Worker
# ---------------------------------------------------------------------------

class DecompressWorker(QThread):
    progress = Signal(int)
    finished = Signal(dict)
    error    = Signal(str)

    def __init__(
        self,
        file_path:   Path,
        output_path: Optional[Path],
        engine:      Optional[str] = None,
    ):
        super().__init__()
        self.file_path   = file_path
        self.output_path = output_path
        self.engine      = engine

    def run(self):
        try:
            import sys
            from pathlib import Path
            root = Path(__file__).parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))

            from compressor import decompress

            self.progress.emit(50)
            result = decompress(self.file_path, self.output_path, self.engine)
            self.progress.emit(100)

            if not result.success:
                self.error.emit(result.error or "Decompression failed")
                return

            self.finished.emit({
                "input_size_mb":   result.input_size  / 1024 / 1024,
                "output_size_mb":  result.output_size / 1024 / 1024,
                "decompress_time": result.decompress_time,
                "decompress_speed":result.decompress_speed,
                "output_path":     str(result.output_path),
                "engine":          result.engine,
            })

        except Exception as e:
            self.error.emit(str(e))
