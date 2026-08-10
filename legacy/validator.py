"""
validator.py

Verifies that the selector is making optimal choices by:
    1. Running selector on a file → gets recommendation
    2. Actually compressing the file with EVERY engine × level combo
    3. Measuring both compress AND decompress speed
    4. Scoring all results using the same weight vector the selector used
    5. Ranking them and checking where the selector's pick lands
    6. Comparing predicted metrics vs actual measured metrics

Usage:
    # validate with no constraints (balanced)
    python validator.py path/to/file.xlsx

    # validate with constraints
    python validator.py path/to/file.sql --constraint max_compression --degree high

    # validate across all constraint types
    python validator.py path/to/file.xlsx --all_constraints

    # validate across all degrees for one constraint
    python validator.py path/to/file.xlsx --constraint max_compression --all_degrees

    # save results to CSV
    python validator.py path/to/file.xlsx --constraint balanced --degree high --csv results.csv
"""

import csv
import time
import argparse
import tracemalloc
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import lz4.frame
import zstandard as zstd
import brotli
import gzip
import lzma

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "src"))

from antimatter.profiler import profile_file
from antimatter.runner import ENGINE_LEVELS
from antimatter.selector import (
    select, build_weight_vector,
    get_db_rows, find_neighbors, _predict_for_engine_level,
    VALID_CONSTRAINTS, VALID_DEGREES,
)


# ---------------------------------------------------------------------------
# Compress + decompress with full measurement
# ---------------------------------------------------------------------------

def _timed(fn) -> tuple:
    """Run fn(), return (result, elapsed_seconds, peak_memory_mb)."""
    tracemalloc.start()
    t0      = time.perf_counter()
    result  = fn()
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak / 1024 / 1024


def _compress_and_decompress(data: bytes, engine: str, level: int) -> tuple:
    """
    Compress then decompress data with engine at level.
    Measures compress time, peak memory, and decompress speed.

    Returns:
        (compressed_bytes, compress_time_s, peak_memory_mb, decompress_speed_mbs)
        Returns (None, 0, 0, 0) on any failure.
    """
    size_mb = len(data) / 1024 / 1024

    try:
        if engine == "zstd":
            cctx = zstd.ZstdCompressor(level=level)
            dctx = zstd.ZstdDecompressor()
            compressed, c_time, peak = _timed(lambda: cctx.compress(data))
            _,          d_time, _    = _timed(lambda: dctx.decompress(compressed))

        elif engine == "lz4":
            compressed, c_time, peak = _timed(
                lambda: lz4.frame.compress(data, compression_level=level)
            )
            _, d_time, _ = _timed(lambda: lz4.frame.decompress(compressed))

        elif engine == "gzip":
            compressed, c_time, peak = _timed(
                lambda: gzip.compress(data, compresslevel=level)
            )
            _, d_time, _ = _timed(lambda: gzip.decompress(compressed))

        elif engine == "lzma":
            compressed, c_time, peak = _timed(
                lambda: lzma.compress(data, preset=level)
            )
            _, d_time, _ = _timed(lambda: lzma.decompress(compressed))

        elif engine == "brotli":
            compressed, c_time, peak = _timed(
                lambda: brotli.compress(data, quality=level)
            )
            _, d_time, _ = _timed(lambda: brotli.decompress(compressed))

        else:
            return None, 0.0, 0.0, 0.0

        decompress_speed = size_mb / d_time if d_time > 0 else 0.0
        return compressed, c_time, peak, decompress_speed

    except Exception:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        return None, 0.0, 0.0, 0.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EngineResult:
    engine:             str
    level:              int
    ratio:              float
    compress_speed:     float
    decompress_speed:   float
    peak_memory_mb:     float
    compress_time:      float
    score:              float
    rank:               int
    predicted_ratio:    float
    prediction_error:   float
    success:            bool
    error:              Optional[str]


# ---------------------------------------------------------------------------
# Run every engine × level
# ---------------------------------------------------------------------------

def run_all_engines(data: bytes, input_size: int) -> list:
    """
    Compress + decompress data with every engine × level combo.
    Returns list of result dicts with all measured metrics.
    """
    results = []
    total   = sum(len(v) for v in ENGINE_LEVELS.values())
    done    = 0

    for engine, levels in ENGINE_LEVELS.items():
        for level in levels:
            done += 1
            print(
                f"    [{done:>2}/{total}] {engine:<10} L{level:<4}",
                end=" ", flush=True
            )

            compressed, c_time, peak_mb, dcmp_speed = _compress_and_decompress(
                data, engine, level
            )

            if compressed is None:
                print("FAILED")
                results.append({
                    "engine": engine, "level": level,
                    "success": False, "error": "compression failed",
                    "ratio": 0.0, "compress_speed": 0.0,
                    "decompress_speed": 0.0, "peak_memory_mb": 0.0,
                    "compress_time": 0.0,
                })
                continue

            output_size    = len(compressed)
            ratio          = input_size / output_size if output_size > 0 else 0.0
            compress_speed = (input_size / 1024 / 1024) / c_time if c_time > 0 else 0.0

            print(
                f"ratio={ratio:.2f}x  "
                f"cmp={compress_speed:.0f}MB/s  "
                f"dcmp={dcmp_speed:.0f}MB/s"
            )

            results.append({
                "engine":           engine,
                "level":            level,
                "success":          True,
                "error":            None,
                "ratio":            ratio,
                "compress_speed":   compress_speed,
                "decompress_speed": dcmp_speed,
                "peak_memory_mb":   peak_mb,
                "compress_time":    c_time,
            })

    return results


# ---------------------------------------------------------------------------
# Predictions from DB
# ---------------------------------------------------------------------------

def get_predictions(profile, db_rows: list) -> dict:
    """
    Get predicted metrics for every engine/level from the benchmark DB.
    Returns dict keyed by (engine, level).
    """
    neighbors   = find_neighbors(profile, db_rows)
    predictions = {}

    for engine, levels in ENGINE_LEVELS.items():
        for level in levels:
            score = _predict_for_engine_level(neighbors, engine, level)
            if score:
                predictions[(engine, level)] = score

    return predictions


# ---------------------------------------------------------------------------
# Scoring actual results with same weight vector as selector
# ---------------------------------------------------------------------------

def score_actual_results(actual_results: list, weights: list) -> list:
    """
    Score all successful results using the weight vector.
    weights = [ratio_w, compress_speed_w, decompress_speed_w, memory_w]

    Cost formula (lower = better):
        cost = w[0] * (1 - norm_ratio)
             + w[1] * (1 - norm_cmp_speed)
             + w[2] * (1 - norm_dcmp_speed)
             + w[3] * norm_memory

    Returns results sorted by cost ascending (best first).
    """
    successful = [r for r in actual_results if r["success"]]
    if not successful:
        return []

    ratios = [r["ratio"]             for r in successful]
    cmps   = [r["compress_speed"]    for r in successful]
    dcmps  = [r["decompress_speed"]  for r in successful]
    mems   = [r["peak_memory_mb"]    for r in successful]

    def norm(val, lo, hi):
        if hi == lo:
            return 0.5
        return (val - lo) / (hi - lo)

    for r in successful:
        nr = norm(r["ratio"],            min(ratios), max(ratios))
        nc = norm(r["compress_speed"],   min(cmps),   max(cmps))
        nd = norm(r["decompress_speed"], min(dcmps),  max(dcmps))
        nm = norm(r["peak_memory_mb"],   min(mems),   max(mems))

        r["score"] = (
            weights[0] * (1.0 - nr) +
            weights[1] * (1.0 - nc) +
            weights[2] * (1.0 - nd) +
            weights[3] * nm
        )

    successful.sort(key=lambda x: x["score"])
    return successful


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

RANK_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}


def print_report(
    file_path:   Path,
    constraint:  str,
    degree:      str,
    rec_engine:  str,
    rec_level:   int,
    ranked:      list,
    predictions: dict,
    weights:     list,
) -> list:
    """Print validation report. Returns list of EngineResult for CSV export."""
    size_mb = file_path.stat().st_size / 1024 / 1024
    total   = len(ranked)

    selector_rank = None
    for i, r in enumerate(ranked, 1):
        if r["engine"] == rec_engine and r["level"] == rec_level:
            selector_rank = i
            break

    print(f"\n{'='*82}")
    print(f"  FILE       : {file_path.name}  ({size_mb:.2f} MB)")
    print(f"  CONSTRAINT : {constraint} / {degree}")
    print(f"  WEIGHTS    : ratio={weights[0]:.2f}  cmp={weights[1]:.2f}  "
          f"dcmp={weights[2]:.2f}  mem={weights[3]:.2f}")
    print(f"{'='*82}")

    if selector_rank is None:
        verdict = "❓ UNKNOWN — selector pick not found in results"
    elif selector_rank == 1:
        verdict = "✅ OPTIMAL — selector picked the best engine"
    elif selector_rank <= 3:
        verdict = f"✅ GOOD — selector picked rank {selector_rank}/{total} (top 3)"
    elif selector_rank <= 5:
        verdict = f"⚠️  ACCEPTABLE — selector picked rank {selector_rank}/{total} (top 5)"
    else:
        verdict = f"❌ POOR — selector picked rank {selector_rank}/{total}"

    print(f"\n  {verdict}")
    print(f"  Selector recommended: {rec_engine} level {rec_level}")

    print(
        f"\n  {'Rank':<6} {'Engine':<10} {'L':<5} "
        f"{'Ratio':>7} {'CmpSpd':>10} {'DcmpSpd':>10} "
        f"{'Mem':>7} {'Score':>8}  {'Pred':>7}  {'PredErr':>8}"
    )
    print(f"  {'-'*87}")

    engine_results = []
    for i, r in enumerate(ranked, 1):
        is_rec   = r["engine"] == rec_engine and r["level"] == rec_level
        pred     = predictions.get((r["engine"], r["level"]))
        pred_r   = pred.predicted_ratio if pred else 0.0
        pred_err = (
            abs(pred_r - r["ratio"]) / r["ratio"] * 100
            if r["ratio"] > 0 else 0.0
        )
        emoji  = RANK_EMOJI.get(i, "  ")
        marker = "  ◄ SELECTOR" if is_rec else ""

        print(
            f"  {emoji} {i:<3}  {r['engine']:<10} {r['level']:<5} "
            f"{r['ratio']:>6.2f}x  "
            f"{r['compress_speed']:>8.0f}MB/s  "
            f"{r['decompress_speed']:>8.0f}MB/s  "
            f"{r['peak_memory_mb']:>5.0f}MB  "
            f"{r['score']:>8.4f}  "
            f"{pred_r:>6.2f}x  "
            f"{pred_err:>6.1f}%"
            f"{marker}"
        )

        engine_results.append(EngineResult(
            engine           = r["engine"],
            level            = r["level"],
            ratio            = r["ratio"],
            compress_speed   = r["compress_speed"],
            decompress_speed = r["decompress_speed"],
            peak_memory_mb   = r["peak_memory_mb"],
            compress_time    = r.get("compress_time", 0.0),
            score            = r["score"],
            rank             = i,
            predicted_ratio  = pred_r,
            prediction_error = pred_err,
            success          = r["success"],
            error            = r.get("error"),
        ))

    # prediction accuracy summary
    preds_ok = [e for e in engine_results if e.success and e.predicted_ratio > 0]
    if preds_ok:
        avg_err = sum(e.prediction_error for e in preds_ok) / len(preds_ok)
        max_err = max(e.prediction_error for e in preds_ok)
        print(f"\n  Prediction accuracy:")
        print(f"    Avg error : {avg_err:.1f}%")
        print(f"    Max error : {max_err:.1f}%")
        if avg_err < 10:
            print(f"    ✅ Predictions are accurate")
        elif avg_err < 25:
            print(f"    ⚠️  Moderate error — DB may need more coverage for this file type")
        else:
            print(f"    ❌ Inaccurate — k-NN neighbors not similar enough to this file")

    print(f"{'='*82}\n")
    return engine_results


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def save_csv(
    results:    list,
    file_path:  Path,
    constraint: str,
    degree:     str,
    csv_path:   Path,
) -> None:
    write_header = not csv_path.exists()

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "file", "constraint", "degree", "rank",
            "engine", "level",
            "ratio", "compress_speed", "decompress_speed",
            "peak_memory_mb", "score",
            "predicted_ratio", "prediction_error",
        ])
        if write_header:
            writer.writeheader()

        for r in results:
            writer.writerow({
                "file":             file_path.name,
                "constraint":       constraint,
                "degree":           degree,
                "rank":             r.rank,
                "engine":           r.engine,
                "level":            r.level,
                "ratio":            round(r.ratio, 4),
                "compress_speed":   round(r.compress_speed, 2),
                "decompress_speed": round(r.decompress_speed, 2),
                "peak_memory_mb":   round(r.peak_memory_mb, 2),
                "score":            round(r.score, 6),
                "predicted_ratio":  round(r.predicted_ratio, 4),
                "prediction_error": round(r.prediction_error, 2),
            })

    print(f"  Results appended to: {csv_path}")


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate(
    file_path:  Path,
    constraint: str = "balanced",
    degree:     str = "balanced",
    csv_path:   Optional[Path] = None,
) -> int:
    """
    Run full validation for one (file, constraint, degree) combination.
    Returns selector rank (1 = optimal).
    """
    file_path = file_path.resolve()

    print(f"\nValidating: {file_path.name}")
    print(f"Constraint: {constraint} / {degree}")

    print(f"\n  Profiling file...")
    profile = profile_file(file_path)
    print(
        f"  entropy={profile.entropy:.3f}  "
        f"repetitiveness={profile.repetitiveness:.3f}  "
        f"compression_hint={profile.compression_hint:.2f}x"
    )

    if profile.entropy > 0.95:
        print(f"\n  ⚠️  High entropy — file unlikely to compress meaningfully")

    print(f"\n  Getting selector recommendation...")
    rec = select(file_path, [(constraint, degree)])
    print(
        f"  Selector recommends: {rec.engine} level {rec.level}  "
        f"(predicted ratio={rec.predicted_ratio:.2f}x)"
    )

    db_rows     = get_db_rows()
    predictions = get_predictions(profile, db_rows)
    weights     = build_weight_vector([(constraint, degree)])

    data = file_path.read_bytes()
    n    = sum(len(v) for v in ENGINE_LEVELS.values())
    print(f"\n  Running all {n} engine/level combos...")
    print(f"  (measuring both compress and decompress speed)\n")

    actual_results = run_all_engines(data, len(data))
    ranked         = score_actual_results(actual_results, weights)

    engine_results = print_report(
        file_path, constraint, degree,
        rec.engine, rec.level,
        ranked, predictions, weights,
    )

    if csv_path:
        save_csv(engine_results, file_path, constraint, degree, csv_path)

    for r in engine_results:
        if r.engine == rec.engine and r.level == rec.level:
            return r.rank

    return -1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate selector choices against actual compression results"
    )
    parser.add_argument(
        "path", type=Path,
        help="File to validate on"
    )
    parser.add_argument(
        "--constraint", type=str, default="balanced",
        help=f"Constraint to test. Valid: {VALID_CONSTRAINTS}"
    )
    parser.add_argument(
        "--degree", type=str, default="balanced",
        help=f"Degree to test. Valid: {VALID_DEGREES}"
    )
    parser.add_argument(
        "--all_constraints", action="store_true",
        help="Run validation for every constraint type"
    )
    parser.add_argument(
        "--all_degrees", action="store_true",
        help="Run validation across all degrees for the given constraint"
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="Append results to this CSV file"
    )

    args = parser.parse_args()
    path = args.path.resolve()

    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    pairs = []
    if args.all_constraints:
        for c in VALID_CONSTRAINTS:
            pairs.append((c, args.degree))
    elif args.all_degrees:
        for d in VALID_DEGREES:
            pairs.append((args.constraint, d))
    else:
        pairs.append((args.constraint, args.degree))

    ranks = []
    for constraint, degree in pairs:
        rank = validate(path, constraint, degree, args.csv)
        ranks.append((constraint, degree, rank))

    if len(ranks) > 1:
        print(f"\n{'='*58}")
        print(f"  SUMMARY")
        print(f"{'='*58}")
        print(f"  {'Constraint':<22} {'Degree':<12} Result")
        print(f"  {'-'*54}")

        for constraint, degree, rank in ranks:
            if rank == 1:
                emoji = "✅"
                label = f"rank {rank}/26  OPTIMAL"
            elif rank <= 3:
                emoji = "✅"
                label = f"rank {rank}/26  GOOD"
            elif rank <= 5:
                emoji = "⚠️ "
                label = f"rank {rank}/26  ACCEPTABLE"
            else:
                emoji = "❌"
                label = f"rank {rank}/26  POOR"
            print(f"  {emoji}  {constraint:<20} {degree:<12} {label}")

        optimal = sum(1 for _, _, r in ranks if r == 1)
        good    = sum(1 for _, _, r in ranks if 1 < r <= 3)
        poor    = sum(1 for _, _, r in ranks if r > 5)

        print(f"\n  Optimal  (rank 1)   : {optimal}/{len(ranks)}")
        print(f"  Good     (rank 2-3) : {good}/{len(ranks)}")
        print(f"  Poor     (rank 6+)  : {poor}/{len(ranks)}")
        print(f"{'='*58}")


if __name__ == "__main__":
    main()