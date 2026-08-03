"""
selector.py

Takes a user file + constraints → returns the best engine and level.

Steps:
    1. Profile the incoming file
    2. Query benchmark.db for similar chunks (k-NN)
    3. Predict metrics per engine/level via weighted interpolation
    4. Translate user constraints into a weight vector
    5. Score every engine/level combo
    6. Return best recommendation + alternatives

Does NOT run compression. Does NOT store anything.
compressor.py takes the recommendation and runs the actual engine.

Usage (standalone test):
    python selector.py path/to/file.xlsx
    python selector.py path/to/file.xml --constraint max_compression --degree high
    python selector.py path/to/file.bin --constraint fast_decompress --degree max
    python selector.py path/to/file.sql --constraint max_compression --degree high --constraint low_memory --degree normal
"""

import math
import sqlite3
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .profiler import profile_file, FileProfile
from .runner import ENGINE_LEVELS
from .paths import DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = DEFAULT_DB_PATH

# How many nearest neighbors to use for interpolation
K_NEIGHBORS = 20

# Feature dimensions used for k-NN distance calculation.
# Must match column names in benchmark.db.
FEATURE_COLS = [
    "entropy",
    "repetitiveness",
    "numeric_density",
    "ascii_ratio",
    "compression_hint",
    "unique_byte_ratio",
]

# Feature weights for distance calculation —
# entropy and compression_hint are the strongest predictors so get more weight.
FEATURE_WEIGHTS = {
    "entropy":           2.0,
    "repetitiveness":    1.5,
    "numeric_density":   1.0,
    "ascii_ratio":       1.0,
    "compression_hint":  2.0,
    "unique_byte_ratio": 1.0,
}

# ---------------------------------------------------------------------------
# Constraints
# Each row: [ratio_weight, compress_speed_weight, decompress_speed_weight, memory_weight]
# Weights sum to 1.0
# ---------------------------------------------------------------------------
CONSTRAINT_WEIGHTS = {
    #                     ratio  cmp_spd  dcmp_spd  memory
    "max_compression":  [0.90,   0.05,    0.03,    0.02],  # unchanged — already optimal
    "balanced":         [0.30,   0.40,    0.20,    0.10],  # ratio weight down from 0.50 — was still ~2x cmp-speed weight even after log-scale speed normalization, causing balanced to collapse onto max_compression's pick
    "fast_compression": [0.10,   0.80,    0.05,    0.05],  # unchanged — already optimal
    "fast_decompress":  [0.10,   0.05,    0.80,    0.05],  # unchanged — already optimal
    "low_cpu":          [0.15,   0.65,    0.15,    0.05],  # unchanged — already optimal
    "low_memory":       [0.10,   0.05,    0.05,    0.80],  # memory weight up from 0.60
}

VALID_CONSTRAINTS = list(CONSTRAINT_WEIGHTS.keys())

# Degree multipliers — scales how strongly a constraint pulls
DEGREE_MULTIPLIERS = {
    "normal":   0.50,
    "balanced": 0.70,
    "high":     0.90,
    "max":      1.00,
}

VALID_DEGREES = list(DEGREE_MULTIPLIERS.keys())

# Plain English reasons shown to the user per winning constraint
CONSTRAINT_REASONS = {
    "max_compression":  "highest compression ratio for this file type",
    "balanced":         "best balance of ratio and speed for this file type",
    "fast_compression": "fastest compression speed within acceptable ratio",
    "fast_decompress":  "fastest decompression speed for quick file access",
    "low_cpu":          "lowest CPU usage during compression",
    "low_memory":       "lowest memory footprint during compression",
}

# Incompressible threshold — if predicted ratio is this low,
# warn the user rather than wasting time compressing
INCOMPRESSIBLE_THRESHOLD = 1.05


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EngineScore:
    engine:                   str
    level:                    int
    predicted_ratio:          float
    predicted_compress_speed: float
    predicted_decompress_speed: float
    predicted_memory_mb:      float
    cost:                     float   # lower = better

    def summary(self) -> str:
        return (
            f"  {self.engine:<10} L{self.level:<4} "
            f"ratio={self.predicted_ratio:.2f}x  "
            f"cmp={self.predicted_compress_speed:.1f}MB/s  "
            f"dcmp={self.predicted_decompress_speed:.1f}MB/s  "
            f"mem={self.predicted_memory_mb:.1f}MB  "
            f"cost={self.cost:.4f}"
        )


@dataclass
class Recommendation:
    engine:                     str
    level:                      int
    predicted_ratio:            float
    predicted_compress_speed:   float
    predicted_decompress_speed: float
    predicted_memory_mb:        float
    reason:                     str
    warning:                    Optional[str]
    alternatives:               list   # list of EngineScore

    def summary(self) -> str:
        lines = [
            f"\n  Recommended   : {self.engine} level {self.level}",
            f"  Predicted     : {self.predicted_ratio:.2f}x ratio  "
            f"{self.predicted_compress_speed:.1f}MB/s compress  "
            f"{self.predicted_decompress_speed:.1f}MB/s decompress  "
            f"{self.predicted_memory_mb:.1f}MB memory",
            f"  Reason        : {self.reason}",
        ]
        if self.warning:
            lines.append(f"  ⚠ Warning     : {self.warning}")
        if self.alternatives:
            lines.append("\n  Alternatives:")
            for alt in self.alternatives:
                lines.append(alt.summary())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_db_rows(db_path: Path) -> list:
    """
    Load all successful rows from benchmark.db into memory as dicts.
    For 12k rows this is ~5MB — fine to hold in memory.
    Cached on first call.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"benchmark.db not found at {db_path}\n"
            "Run pipeline.py first to populate the database."
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            entropy, repetitiveness, numeric_density,
            ascii_ratio, compression_hint, unique_byte_ratio,
            file_size, category,
            engine, level,
            ratio, compress_speed, decompress_speed, peak_memory_mb
        FROM results
        WHERE success = 1
    """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# Module-level cache so we only hit the DB once per process
_DB_CACHE: Optional[list] = None

def get_db_rows(db_path: Path = DB_PATH) -> list:
    global _DB_CACHE
    if _DB_CACHE is None:
        _DB_CACHE = _load_db_rows(db_path)
    return _DB_CACHE


# ---------------------------------------------------------------------------
# Vectorized feature matrix — built once per db_rows identity, reused across
# every file in a batch (folder preview/compress) instead of re-scanning the
# ~12k-row list in a pure-Python loop per file. Keyed by id(db_rows) since
# get_db_rows() already caches the list itself per process.
# ---------------------------------------------------------------------------
_FEATURE_WEIGHTS_ARR = np.array([FEATURE_WEIGHTS[c] for c in FEATURE_COLS])

_FEATURE_MATRIX_CACHE: dict = {}   # id(db_rows) -> (raw_matrix, engine_arr, level_arr)

def _get_feature_matrix(db_rows: list):
    key = id(db_rows)
    cached = _FEATURE_MATRIX_CACHE.get(key)
    if cached is not None:
        return cached

    raw = np.array([[row[c] for c in FEATURE_COLS] for row in db_rows], dtype=np.float64)
    engine_arr = np.array([row["engine"] for row in db_rows])
    level_arr = np.array([row["level"] for row in db_rows])

    result = (raw, engine_arr, level_arr)
    _FEATURE_MATRIX_CACHE.clear()   # only ever one db_rows identity per process in practice
    _FEATURE_MATRIX_CACHE[key] = result
    return result


def _vectorized_distances(profile: FileProfile, raw_matrix: np.ndarray) -> np.ndarray:
    """
    Weighted euclidean distance from profile to every row in raw_matrix,
    computed as a single vectorized pass instead of a per-row Python loop.
    Matches _euclidean_distance()'s formula exactly: sum(w * (p-r)^2) per row.
    """
    profile_vec = np.array([getattr(profile, c) for c in FEATURE_COLS])
    diff = profile_vec - raw_matrix
    return np.sqrt(np.sum(_FEATURE_WEIGHTS_ARR * diff * diff, axis=1))


# ---------------------------------------------------------------------------
# k-NN + interpolation
# ---------------------------------------------------------------------------

def _euclidean_distance(profile: FileProfile, row: dict) -> float:
    """
    Weighted euclidean distance between a file profile and a DB row.
    File size is excluded — we want to match on content characteristics,
    not size, since behavior scales linearly with size.
    """
    total = 0.0
    for col in FEATURE_COLS:
        w     = FEATURE_WEIGHTS[col]
        p_val = getattr(profile, col)
        r_val = row[col]
        total += w * (p_val - r_val) ** 2
    return math.sqrt(total)


def _predict_for_engine_level(
    neighbors: list,   # list of (distance, row) tuples, pre-sorted
    engine: str,
    level: int,
    k: int = K_NEIGHBORS,
) -> Optional[EngineScore]:
    """
    From the k nearest neighbors, find those matching engine+level
    and compute inverse-distance-weighted averages of metrics.
    Returns None if no matching rows found.
    """
    matching = [
        (dist, row) for dist, row in neighbors
        if row["engine"] == engine and row["level"] == level
    ]

    if not matching:
        return None

    # use up to k matches
    matching = matching[:k]

    # inverse distance weighting — closer rows contribute more
    # add small epsilon to avoid division by zero for perfect matches
    weights = [1.0 / (dist + 1e-9) for dist, _ in matching]
    total_w = sum(weights)

    def wavg(key):
        return sum(w * row[key] for w, (_, row) in zip(weights, matching)) / total_w

    predicted_ratio  = wavg("ratio")
    predicted_cmp    = wavg("compress_speed")
    predicted_dcmp   = wavg("decompress_speed")
    predicted_memory = wavg("peak_memory_mb")

    return EngineScore(
        engine                    = engine,
        level                     = level,
        predicted_ratio           = predicted_ratio,
        predicted_compress_speed  = predicted_cmp,
        predicted_decompress_speed= predicted_dcmp,
        predicted_memory_mb       = predicted_memory,
        cost                      = 0.0,   # filled in during scoring
    )


def find_neighbors(profile: FileProfile, db_rows: list, k: int = K_NEIGHBORS * 5) -> list:
    """
    Find the k*5 nearest neighbors across ALL engine/level combos.
    We use a larger pool here so each engine/level has enough candidates.
    Returns list of (distance, row) sorted by distance ascending.
    """
    raw_matrix, _, _ = _get_feature_matrix(db_rows)
    distances = _vectorized_distances(profile, raw_matrix)

    k = min(k, len(db_rows))
    nearest_idx = np.argpartition(distances, k - 1)[:k]
    nearest_idx = nearest_idx[np.argsort(distances[nearest_idx])]

    return [(float(distances[i]), db_rows[i]) for i in nearest_idx]


# ---------------------------------------------------------------------------
# Constraint → weight vector
# ---------------------------------------------------------------------------
def build_weight_vector(constraints: list) -> list:
    if not constraints:
        constraints = [("balanced", "balanced")]

    # neutral baseline — equal weight to all metrics
    NEUTRAL = [0.25, 0.25, 0.25, 0.25]

    final = [0.0, 0.0, 0.0, 0.0]

    for constraint, degree in constraints:
        if constraint not in CONSTRAINT_WEIGHTS:
            raise ValueError(f"Unknown constraint '{constraint}'.")
        if degree not in DEGREE_MULTIPLIERS:
            raise ValueError(f"Unknown degree '{degree}'.")

        t    = DEGREE_MULTIPLIERS[degree]          # 0.5 / 0.7 / 0.9 / 1.0
        base = CONSTRAINT_WEIGHTS[constraint]

        # lerp between neutral and full constraint weight
        blended = [
            NEUTRAL[i] * (1 - t) + base[i] * t
            for i in range(4)
        ]

        for i in range(4):
            final[i] += blended[i]

    # normalize
    total = sum(final)
    if total > 0:
        final = [w / total for w in final]

    return final
# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _normalize_scores(candidates: list) -> list:
    """
    Normalize each metric across all candidates to [0, 1] range.
    Returns candidates with normalized values attached.
    """
    if not candidates:
        return candidates

    # collect min/max for each metric
    ratios  = [c.predicted_ratio           for c in candidates]
    cmps    = [c.predicted_compress_speed  for c in candidates]
    dcmps   = [c.predicted_decompress_speed for c in candidates]
    mems    = [c.predicted_memory_mb       for c in candidates]

    def norm(val, lo, hi):
        if hi == lo:
            return 0.5
        return (val - lo) / (hi - lo)

    def norm_log(val, lo, hi):
        """
        Log-scale min-max. compress/decompress speed across engines spans
        multiple orders of magnitude (e.g. ~1.6 MB/s brotli11 to ~1500 MB/s
        lz4-1) — plain linear norm() crushes everything except the single
        fastest candidate down to ~0, making the speed term in
        score_candidates() unable to distinguish the rest of the field.
        Log-scaling first spreads that range out evenly before min-maxing.
        """
        if hi <= 0 or lo <= 0 or hi == lo:
            return 0.5
        val = max(val, 1e-9)
        return (math.log(val) - math.log(lo)) / (math.log(hi) - math.log(lo))

    normalized = []
    for c in candidates:
        normalized.append({
            "candidate":   c,
            "norm_ratio":  norm(c.predicted_ratio,            min(ratios),  max(ratios)),
            "norm_cmp":    norm_log(c.predicted_compress_speed,   min(cmps),  max(cmps)),
            "norm_dcmp":   norm_log(c.predicted_decompress_speed, min(dcmps), max(dcmps)),
            "norm_mem":    norm(c.predicted_memory_mb,        min(mems),    max(mems)),
        })

    return normalized


def score_candidates(candidates: list, weights: list) -> list:
    """
    Score all candidates using the weight vector.
    Cost formula (lower = better):
        cost = w[0] * (1 - norm_ratio)      ← higher ratio = lower cost
             + w[1] * (1 - norm_cmp_speed)  ← higher speed = lower cost
             + w[2] * (1 - norm_dcmp_speed) ← higher speed = lower cost
             + w[3] * norm_memory           ← higher memory = higher cost

    Returns candidates sorted by cost ascending (best first).
    """
    normalized = _normalize_scores(candidates)

    for entry in normalized:
        c = entry["candidate"]
        c.cost = (
            weights[0] * (1.0 - entry["norm_ratio"])  +
            weights[1] * (1.0 - entry["norm_cmp"])    +
            weights[2] * (1.0 - entry["norm_dcmp"])   +
            weights[3] * entry["norm_mem"]
        )

    candidates.sort(key=lambda c: c.cost)
    return candidates


# ---------------------------------------------------------------------------
# Reason builder
# ---------------------------------------------------------------------------

def _build_reason(winner: EngineScore, constraints: list) -> str:
    """Build a plain English reason string for the recommendation."""
    if not constraints:
        primary = "balanced"
    else:
        primary = constraints[0][0]

    base   = CONSTRAINT_REASONS.get(primary, "best overall fit for this file type")
    engine = winner.engine
    level  = winner.level

    # add engine-specific context
    engine_notes = {
        "zstd":   "Zstandard offers excellent speed with strong compression",
        "lzma":   "LZMA achieves maximum ratio at the cost of speed",
        "brotli": "Brotli excels on text and structured content",
        "lz4":    "LZ4 is the fastest option with acceptable ratio",
        "gzip":   "gzip provides universal compatibility",
    }
    note = engine_notes.get(engine, "")

    return f"{note} — selected for {base} (level {level})"


# ---------------------------------------------------------------------------
# Main selector entry point
# ---------------------------------------------------------------------------

def select(
    file_path: Path,
    constraints: list = None, # type: ignore
    db_path: Path = DB_PATH,
    n_alternatives: int = 3,
    profile: Optional[FileProfile] = None,
) -> Recommendation:
    """
    Main entry point. Called by compressor.py and the UI.

    Args:
        file_path:      path to the user's file
        constraints:    list of (constraint_name, degree) tuples
                        e.g. [("max_compression", "high")]
                        defaults to [("balanced", "balanced")] if empty
        db_path:        path to benchmark.db
        n_alternatives: how many alternatives to include
        profile:        pre-computed FileProfile, if the caller already has
                        one (e.g. batch folder previews) — avoids re-reading
                        and re-profiling the file from disk

    Returns:
        Recommendation with best engine/level + alternatives
    """
    if constraints is None:
        constraints = []

    # --- step 1: profile the file (skip if caller already has one) ---
    if profile is None:
        profile = profile_file(file_path)

    # --- step 2: load DB + find neighbors ---
    db_rows   = get_db_rows(db_path)
    neighbors = find_neighbors(profile, db_rows)

    # --- step 3: predict metrics for every engine/level ---
    candidates = []
    for engine, levels in ENGINE_LEVELS.items():
        for level in levels:
            score = _predict_for_engine_level(neighbors, engine, level)
            if score is not None:
                candidates.append(score)

    if not candidates:
        raise RuntimeError(
            "No predictions could be made — benchmark.db may be empty or corrupted."
        )

    # --- step 4: build weight vector from constraints ---
    weights = build_weight_vector(constraints)

    # --- step 5: score and rank ---
    ranked = score_candidates(candidates, weights)

    winner       = ranked[0]
    alternatives = ranked[1: n_alternatives + 1]

    # --- step 6: build recommendation ---
    reason  = _build_reason(winner, constraints)
    warning = None

    if winner.predicted_ratio < INCOMPRESSIBLE_THRESHOLD:
        warning = (
            f"This file has very high entropy (entropy={profile.entropy:.2f}) "
            f"and is unlikely to compress meaningfully. "
            f"Best predicted ratio is only {winner.predicted_ratio:.2f}x."
        )

    return Recommendation(
        engine                     = winner.engine,
        level                      = winner.level,
        predicted_ratio            = winner.predicted_ratio,
        predicted_compress_speed   = winner.predicted_compress_speed,
        predicted_decompress_speed = winner.predicted_decompress_speed,
        predicted_memory_mb        = winner.predicted_memory_mb,
        reason                     = reason,
        warning                    = warning,
        alternatives               = alternatives,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Select best compression engine for a file"
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to file to compress"
    )
    parser.add_argument(
        "--constraint",
        action="append",
        dest="constraints",
        default=[],
        metavar="NAME",
        help=f"Constraint to apply. Valid: {VALID_CONSTRAINTS}. Can be used multiple times."
    )
    parser.add_argument(
        "--degree",
        action="append",
        dest="degrees",
        default=[],
        metavar="LEVEL",
        help=f"Degree for each constraint. Valid: {VALID_DEGREES}. Must match --constraint count."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Path to benchmark.db (default: {DB_PATH})"
    )
    args = parser.parse_args()

    path = args.path.resolve()
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    # pair up constraints and degrees
    constraints = args.constraints
    degrees     = args.degrees

    if len(degrees) == 0:
        degrees = ["balanced"] * len(constraints)
    elif len(degrees) != len(constraints):
        print(f"[ERROR] Number of --degree values must match number of --constraint values")
        return

    constraint_pairs = list(zip(constraints, degrees))

    # --- run selector ---
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"\nFile       : {path.name}  ({size_mb:.2f} MB)")

    if constraint_pairs:
        print(f"Constraints: {constraint_pairs}")
    else:
        print(f"Constraints: none — using balanced defaults")

    print(f"\nProfiling file...")
    profile = profile_file(path)
    print(f"  entropy={profile.entropy:.3f}  "
          f"repetitiveness={profile.repetitiveness:.3f}  "
          f"ascii_ratio={profile.ascii_ratio:.3f}  "
          f"compression_hint={profile.compression_hint:.2f}x")

    print(f"\nQuerying benchmark.db and scoring engines...")
    rec = select(path, constraint_pairs, args.db)

    print(rec.summary())


if __name__ == "__main__":
    main()