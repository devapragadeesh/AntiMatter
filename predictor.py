"""
predictor.py

Predicts compression metrics (ratio, speed, memory) for a given file
and engine/level combination BEFORE actually running compression.

Uses k-NN regression over benchmark.db:
    1. Profile the file → feature vector
    2. Find k nearest neighbors in DB for the given engine/level
    3. Inverse-distance weighted average of their results
    4. Compute confidence from neighbor distance + result variance
    5. Return prediction with range and confidence

Does NOT run compression. Does NOT store anything.
Called by compressor.py to show estimates before the user confirms.

Usage (standalone):
    python predictor.py path/to/file.xlsx
    python predictor.py path/to/file.sql --engine zstd --level 9
    python predictor.py path/to/file.bin --engine lz4 --level 1 --all_engines
"""

import math
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from profiler import profile_file, FileProfile
from selector import get_db_rows, FEATURE_COLS, FEATURE_WEIGHTS
from runner import ENGINE_LEVELS


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Number of nearest neighbors to use for prediction
K = 20

# Distance thresholds for confidence scoring
CONFIDENCE_DISTANCE_HIGH   = 0.25
CONFIDENCE_DISTANCE_MEDIUM = 0.50
CONFIDENCE_VARIANCE_HIGH   = 0.50
CONFIDENCE_VARIANCE_MEDIUM = 1.00

# Incompressible threshold — ratio below this triggers a warning
INCOMPRESSIBLE_RATIO = 1.05


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Prediction:
    engine:              str
    level:               int

    # point estimates
    predicted_ratio:          float
    predicted_compress_speed: float   # MB/s
    predicted_decompress_speed: float # MB/s
    predicted_memory_mb:      float

    # estimated time based on file size + predicted speed
    predicted_compress_time:    float  # seconds
    predicted_decompress_time:  float  # seconds

    # prediction range (from neighbor min/max)
    ratio_low:   float
    ratio_high:  float

    # confidence
    confidence:       str     # "high" / "medium" / "low"
    avg_distance:     float   # how far the nearest neighbors were
    ratio_variance:   float   # std dev of neighbor ratios
    n_neighbors_used: int     # actual neighbors found (may be < K)

    # file info
    file_size_mb: float
    estimated_output_mb: float

    # warnings
    warning: Optional[str]

    def summary(self) -> str:
        conf_emoji = {"high": "✅", "medium": "⚠️ ", "low": "❌"}
        emoji = conf_emoji.get(self.confidence, "  ")

        lines = [
            f"\n  ┌─ Prediction: {self.engine} level {self.level} {'─'*30}┐",
            f"  │  Ratio      : {self.predicted_ratio:.2f}x"
            f"  ({self.file_size_mb:.1f} MB → ~{self.estimated_output_mb:.1f} MB)"
            f"{'':>10}│",
            f"  │  Range      : {self.ratio_low:.2f}x – {self.ratio_high:.2f}x"
            f"{'':>30}│",
            f"  │  Cmp time   : ~{self.predicted_compress_time:.1f}s"
            f"  ({self.predicted_compress_speed:.0f} MB/s)"
            f"{'':>20}│",
            f"  │  Dcmp time  : ~{self.predicted_decompress_time:.1f}s"
            f"  ({self.predicted_decompress_speed:.0f} MB/s)"
            f"{'':>19}│",
            f"  │  Memory     : ~{self.predicted_memory_mb:.0f} MB"
            f"{'':>40}│",
            f"  │  Confidence : {emoji} {self.confidence:<10}"
            f"  (based on {self.n_neighbors_used} neighbors)"
            f"{'':>10}│",
            f"  └{'─'*56}┘",
        ]

        if self.warning:
            lines.append(f"\n  ⚠️  {self.warning}")

        return "\n".join(lines)


@dataclass
class PredictionComparison:
    """Actual vs predicted — filled in after compression runs."""
    engine:             str
    level:              int
    predicted_ratio:    float
    actual_ratio:       float
    ratio_error_pct:    float
    predicted_speed:    float
    actual_speed:       float
    speed_error_pct:    float

    def summary(self) -> str:
        ratio_ok = "✅" if self.ratio_error_pct < 15 else "⚠️ " if self.ratio_error_pct < 30 else "❌"
        return (
            f"\n  Prediction vs Actual:"
            f"\n    Ratio  predicted={self.predicted_ratio:.2f}x  "
            f"actual={self.actual_ratio:.2f}x  "
            f"{ratio_ok} {self.ratio_error_pct:.1f}% error"
            f"\n    Speed  predicted={self.predicted_speed:.0f}MB/s  "
            f"actual={self.actual_speed:.0f}MB/s  "
            f"{self.speed_error_pct:.1f}% error"
        )


# ---------------------------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------------------------

def _euclidean_distance(profile: FileProfile, row: dict) -> float:
    """
    Weighted euclidean distance between a file profile and a DB row.
    File size excluded — we match on content characteristics only.
    """
    total = 0.0
    for col in FEATURE_COLS:
        w     = FEATURE_WEIGHTS[col]
        p_val = getattr(profile, col)
        r_val = row[col]
        total += w * (p_val - r_val) ** 2
    return math.sqrt(total)


# ---------------------------------------------------------------------------
# k-NN core
# ---------------------------------------------------------------------------

def _find_neighbors_for_engine(
    profile:  FileProfile,
    db_rows:  list,
    engine:   str,
    level:    int,
    k:        int = K,
) -> list:
    """
    Find k nearest neighbors in db_rows that match engine+level.
    Returns list of (distance, row) sorted by distance ascending.
    """
    candidates = [
        row for row in db_rows
        if row["engine"] == engine
        and row["level"] == level
        and row.get("success", 1) == 1
        and row.get("ratio", 0) > 0
    ]

    if not candidates:
        return []

    distances = [
        (_euclidean_distance(profile, row), row)
        for row in candidates
    ]
    distances.sort(key=lambda x: x[0])
    return distances[:k]


def _weighted_average(neighbors: list, key: str) -> float:
    """
    Compute inverse-distance weighted average of a metric across neighbors.
    Closer neighbors contribute more to the prediction.
    """
    epsilon = 1e-9
    weights = [1.0 / (dist + epsilon) for dist, _ in neighbors]
    total_w = sum(weights)

    if total_w == 0:
        return 0.0

    return sum(
        w * row[key]
        for w, (_, row) in zip(weights, neighbors)
        if key in row and row[key] is not None
    ) / total_w


def _std_dev(values: list) -> float:
    """Standard deviation of a list of values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _compute_confidence(
    neighbors:    list,
    avg_distance: float,
    ratio_values: list,
) -> tuple:
    """
    Compute confidence level from:
        1. Average neighbor distance (how similar are the neighbors)
        2. Variance in neighbor ratios (how consistent are the results)

    Returns (confidence_str, ratio_variance)
    """
    ratio_variance = _std_dev(ratio_values)

    # both signals must be good for high confidence
    dist_ok     = avg_distance  < CONFIDENCE_DISTANCE_HIGH
    variance_ok = ratio_variance < CONFIDENCE_VARIANCE_HIGH

    dist_med     = avg_distance  < CONFIDENCE_DISTANCE_MEDIUM
    variance_med = ratio_variance < CONFIDENCE_VARIANCE_MEDIUM

    if dist_ok and variance_ok:
        confidence = "high"
    elif dist_med and variance_med:
        confidence = "medium"
    else:
        confidence = "low"

    return confidence, ratio_variance


# ---------------------------------------------------------------------------
# Main prediction entry point
# ---------------------------------------------------------------------------

def predict(
    file_path: Path,
    engine:    str,
    level:     int,
    db_path:   Optional[Path] = None,
    k:         int = K,
) -> Optional[Prediction]:
    """
    Predict compression metrics for file_path using engine at level.

    Args:
        file_path : path to the user's file
        engine    : compression engine name
        level     : compression level
        db_path   : optional custom path to benchmark.db
        k         : number of neighbors to use

    Returns:
        Prediction dataclass, or None if no neighbors found in DB.
    """
    # --- validate ---
    if engine not in ENGINE_LEVELS:
        raise ValueError(f"Unknown engine '{engine}'. Valid: {list(ENGINE_LEVELS.keys())}")
    if level not in ENGINE_LEVELS[engine]:
        raise ValueError(f"Level {level} not valid for {engine}. Valid: {ENGINE_LEVELS[engine]}")

    # --- profile file ---
    profile = profile_file(file_path)

    # --- load DB ---
    from selector import get_db_rows, DB_PATH
    actual_db_path = db_path or DB_PATH
    db_rows = get_db_rows(actual_db_path)

    # --- find neighbors ---
    neighbors = _find_neighbors_for_engine(profile, db_rows, engine, level, k)

    if not neighbors:
        return None

    # --- compute predictions ---
    predicted_ratio  = _weighted_average(neighbors, "ratio")
    predicted_cmp    = _weighted_average(neighbors, "compress_speed")
    predicted_dcmp   = _weighted_average(neighbors, "decompress_speed")
    predicted_memory = _weighted_average(neighbors, "peak_memory_mb")

    # --- prediction range ---
    ratios    = [row["ratio"] for _, row in neighbors]
    ratio_low  = min(ratios)
    ratio_high = max(ratios)

    # --- confidence ---
    avg_distance          = sum(d for d, _ in neighbors) / len(neighbors)
    confidence, ratio_var = _compute_confidence(neighbors, avg_distance, ratios)

    # --- estimated times ---
    file_size_mb = profile.file_size / 1024 / 1024
    cmp_time     = file_size_mb / predicted_cmp  if predicted_cmp  > 0 else 0.0
    dcmp_time    = file_size_mb / predicted_dcmp if predicted_dcmp > 0 else 0.0

    # --- estimated output size ---
    est_output_mb = file_size_mb / predicted_ratio if predicted_ratio > 0 else file_size_mb

    # --- warning ---
    warning = None
    if predicted_ratio < INCOMPRESSIBLE_RATIO:
        warning = (
            f"File has high entropy ({profile.entropy:.2f}) — "
            f"unlikely to compress meaningfully. "
            f"Predicted ratio is only {predicted_ratio:.2f}x."
        )
    elif confidence == "low":
        warning = (
            f"Low confidence prediction — this file type is underrepresented "
            f"in the benchmark DB. Actual results may differ significantly."
        )

    return Prediction(
        engine                    = engine,
        level                     = level,
        predicted_ratio           = predicted_ratio,
        predicted_compress_speed  = predicted_cmp,
        predicted_decompress_speed= predicted_dcmp,
        predicted_memory_mb       = predicted_memory,
        predicted_compress_time   = cmp_time,
        predicted_decompress_time = dcmp_time,
        ratio_low                 = ratio_low,
        ratio_high                = ratio_high,
        confidence                = confidence,
        avg_distance              = avg_distance,
        ratio_variance            = ratio_var,
        n_neighbors_used          = len(neighbors),
        file_size_mb              = file_size_mb,
        estimated_output_mb       = est_output_mb,
        warning                   = warning,
    )


def predict_all_engines(
    file_path: Path,
    db_path:   Optional[Path] = None,
    k:         int = K,
) -> dict:
    """
    Predict metrics for every engine/level combination.
    Returns dict keyed by (engine, level) → Prediction.
    Useful for the selector and for showing a full comparison table.
    """
    results = {}
    for engine, levels in ENGINE_LEVELS.items():
        for level in levels:
            pred = predict(file_path, engine, level, db_path, k)
            if pred is not None:
                results[(engine, level)] = pred
    return results


# ---------------------------------------------------------------------------
# Comparison: prediction vs actual (called after compression finishes)
# ---------------------------------------------------------------------------

def compare(
    prediction:      Prediction,
    actual_ratio:    float,
    actual_speed:    float,
) -> PredictionComparison:
    """
    Compare a prediction against actual compression results.
    Call this after compressor.py runs to measure prediction accuracy.
    """
    ratio_err = (
        abs(prediction.predicted_ratio - actual_ratio) / actual_ratio * 100
        if actual_ratio > 0 else 0.0
    )
    speed_err = (
        abs(prediction.predicted_compress_speed - actual_speed) / actual_speed * 100
        if actual_speed > 0 else 0.0
    )

    return PredictionComparison(
        engine           = prediction.engine,
        level            = prediction.level,
        predicted_ratio  = prediction.predicted_ratio,
        actual_ratio     = actual_ratio,
        ratio_error_pct  = ratio_err,
        predicted_speed  = prediction.predicted_compress_speed,
        actual_speed     = actual_speed,
        speed_error_pct  = speed_err,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Predict compression metrics for a file before compressing"
    )
    parser.add_argument(
        "path", type=Path,
        help="File to predict for"
    )
    parser.add_argument(
        "--engine", type=str, default=None,
        help=f"Engine to predict for. Valid: {list(ENGINE_LEVELS.keys())}"
    )
    parser.add_argument(
        "--level", type=int, default=None,
        help="Compression level"
    )
    parser.add_argument(
        "--all_engines", action="store_true",
        help="Predict for every engine/level combo and show comparison table"
    )
    parser.add_argument(
        "--k", type=int, default=K,
        help=f"Number of neighbors (default: {K})"
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help="Path to benchmark.db"
    )

    args = parser.parse_args()

    path = args.path.resolve()
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    size_mb = path.stat().st_size / 1024 / 1024
    print(f"\nFile : {path.name}  ({size_mb:.2f} MB)")
    print(f"Profiling...")

    from profiler import profile_file
    profile = profile_file(path)
    print(
        f"  entropy={profile.entropy:.3f}  "
        f"repetitiveness={profile.repetitiveness:.3f}  "
        f"compression_hint={profile.compression_hint:.2f}x"
    )

    if args.all_engines:
        print(f"\nPredicting all engine/level combos (k={args.k})...\n")
        predictions = predict_all_engines(path, args.db, args.k)

        if not predictions:
            print("[ERROR] No predictions — benchmark.db may be empty.")
            return

        print(
            f"  {'Engine':<10} {'L':<5} {'Ratio':>7} {'Range':>14} "
            f"{'CmpSpd':>9} {'DcmpSpd':>9} {'Mem':>7} {'CmpTime':>9} {'Conf':<8}"
        )
        print(f"  {'-'*85}")

        for (engine, level), pred in sorted(predictions.items()):
            conf_marker = {"high": "✅", "medium": "⚠️ ", "low": "❌ "}.get(pred.confidence, "  ")
            print(
                f"  {engine:<10} {level:<5} "
                f"{pred.predicted_ratio:>6.2f}x  "
                f"{pred.ratio_low:.1f}x-{pred.ratio_high:.1f}x  "
                f"{pred.predicted_compress_speed:>7.0f}MB/s  "
                f"{pred.predicted_decompress_speed:>7.0f}MB/s  "
                f"{pred.predicted_memory_mb:>5.0f}MB  "
                f"~{pred.predicted_compress_time:>6.1f}s  "
                f"{conf_marker} {pred.confidence}"
            )
        return

    # single engine/level prediction
    if args.engine is None:
        # default to zstd level 3 as a quick demo
        engine, level = "zstd", 3
        print(f"\nNo engine specified — defaulting to zstd level 3")
    else:
        engine = args.engine.lower()
        if engine not in ENGINE_LEVELS:
            print(f"[ERROR] Unknown engine '{engine}'")
            return
        level = args.level if args.level is not None else ENGINE_LEVELS[engine][2]

    print(f"\nPredicting for {engine} level {level}  (k={args.k})...")

    pred = predict(path, engine, level, args.db, args.k)

    if pred is None:
        print(f"[ERROR] No neighbors found in DB for {engine} level {level}.")
        print("  Run pipeline.py first to populate benchmark.db.")
        return

    print(pred.summary())
    print(
        f"\n  Debug:"
        f"\n    Avg neighbor distance : {pred.avg_distance:.4f}"
        f"\n    Ratio std dev         : {pred.ratio_variance:.4f}"
        f"\n    Neighbors used        : {pred.n_neighbors_used}"
    )


if __name__ == "__main__":
    main()