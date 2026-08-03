"""
calibration.py

benchmark.db's compress_speed/decompress_speed columns were measured once,
on whichever machine generated the DB. Predicted ratio/size stays accurate
on any machine (it's content-driven), but predicted *time* drifts on a
faster or slower CPU/disk since it's derived from those raw MB/s numbers.

This module benchmarks a small synthetic buffer on the local machine with
the same engine/level used as a DB reference point, and caches the ratio
between local and DB speed as a single scalar `speed_factor`. predictor.py
multiplies predicted speeds by this factor so predicted time tracks the
machine it's actually running on.

Usage (standalone):
    python calibration.py            # run + print the factor
    python calibration.py --force    # ignore cache, recalibrate
"""

import json
import time
import random
import argparse
from pathlib import Path
from typing import Optional

from paths import get_app_root
from selector import get_db_rows, DB_PATH

# Reference engine/level: fast, always present in benchmark.db, and already
# the fixed default for tiny files (archiver.TINY_FILE_ENGINE/LEVEL) — a
# sensible single calibration point since it's cheap to run and representative
# of typical throughput rather than an outlier engine.
REFERENCE_ENGINE = "zstd"
REFERENCE_LEVEL  = 3

# Synthetic calibration buffer: mixed-compressibility content so the local
# run isn't skewed toward a best- or worst-case codec path.
CALIBRATION_SIZE = 8 * 1024 * 1024  # 8 MB

CACHE_PATH = get_app_root() / "calibration_cache.json"


def _make_calibration_buffer(size: int = CALIBRATION_SIZE) -> bytes:
    """Deterministic mixed-content buffer: half repetitive text, half random
    bytes, so calibration reflects a realistic average compress workload
    rather than a single content extreme."""
    rng = random.Random(1234)
    half = size // 2
    repetitive = (b"the quick brown fox jumps over the lazy dog. " * (half // 46 + 1))[:half]
    randomish = bytes(rng.getrandbits(8) for _ in range(size - half))
    return repetitive + randomish


def _reference_db_speed(db_path: Optional[Path] = None) -> Optional[float]:
    """Average compress_speed (MB/s) recorded in benchmark.db for the
    reference engine/level — the baseline the local run is compared against."""
    rows = get_db_rows(db_path or DB_PATH)
    speeds = [
        r["compress_speed"] for r in rows
        if r.get("engine") == REFERENCE_ENGINE
        and r.get("level") == REFERENCE_LEVEL
        and r.get("compress_speed", 0) > 0
    ]
    if not speeds:
        return None
    return sum(speeds) / len(speeds)


def run_calibration(db_path: Optional[Path] = None) -> float:
    """
    Compress a fixed local buffer with the reference engine/level, measure
    actual local throughput, and return local_speed / db_speed. Falls back
    to 1.0 (no adjustment) if the DB has no reference rows, since that means
    there's nothing meaningful to scale against.
    """
    db_speed = _reference_db_speed(db_path)
    if not db_speed:
        return 1.0

    # imported lazily: compressor.py imports predictor.py, which imports
    # calibration.py for get_speed_factor() — a module-level import here
    # would be circular. run_calibration() itself is only ever called
    # standalone (CLI) or from the app-startup background thread, never
    # from inside predict(), so the lazy import costs nothing on the hot path.
    from compressor import COMPRESS_FN

    data = _make_calibration_buffer()
    fn = COMPRESS_FN[REFERENCE_ENGINE]

    t0 = time.perf_counter()
    fn(data, REFERENCE_LEVEL)
    elapsed = time.perf_counter() - t0

    if elapsed <= 0:
        return 1.0

    local_speed_mb_s = (len(data) / 1024 / 1024) / elapsed
    factor = local_speed_mb_s / db_speed

    _save_cached_factor(factor)
    return factor


def _save_cached_factor(factor: float) -> None:
    try:
        CACHE_PATH.write_text(json.dumps({"speed_factor": factor}), encoding="utf-8")
    except OSError:
        pass  # calibration is a nice-to-have; a failed cache write shouldn't break prediction


def get_speed_factor() -> float:
    """
    Load the cached calibration factor, if present. Returns 1.0 (no
    adjustment) if calibration hasn't run yet — callers should not block
    on running calibration synchronously in a hot prediction path.
    """
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        factor = float(cached.get("speed_factor", 1.0))
        if factor > 0:
            return factor
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return 1.0


def main():
    parser = argparse.ArgumentParser(description="Calibrate local compression speed vs benchmark.db")
    parser.add_argument("--force", action="store_true", help="Recalibrate even if a cached factor exists")
    args = parser.parse_args()

    if not args.force:
        cached = get_speed_factor()
        if cached != 1.0:
            print(f"Cached speed_factor: {cached:.3f} (use --force to recalibrate)")
            return

    factor = run_calibration()
    print(f"speed_factor: {factor:.3f}  (>1 = this machine is faster than the benchmark.db reference)")


if __name__ == "__main__":
    main()
