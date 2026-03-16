"""
compressor.py

The main entry point for the smart compression tool.
Wires together profiler → selector → compression engine.

What it does:
    1. Takes a user file + optional constraints
    2. Profiles the file
    3. Calls selector to get best engine/level recommendation
    4. Shows prediction to user before running
    5. Runs the actual compression
    6. Reports final results

Usage:
    python compressor.py path/to/file.xlsx
    python compressor.py path/to/file.sql --constraint max_compression --degree high
    python compressor.py path/to/file.xml --constraint fast_decompress --degree max
    python compressor.py path/to/file.bin --output path/to/output/folder
    python compressor.py path/to/file.xlsx --constraint max_compression --degree high --constraint low_memory --degree normal

Decompress:
    python compressor.py path/to/file.zst --decompress
    python compressor.py path/to/file.lzma --decompress
"""

import gzip
import lzma
import time
import argparse
import tracemalloc
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import lz4.frame
import zstandard as zstd
import brotli

from profiler import profile_file
from selector import select, VALID_CONSTRAINTS, VALID_DEGREES, Recommendation
from runner import ENGINE_LEVELS

# ---------------------------------------------------------------------------
# Output file extensions per engine
# ---------------------------------------------------------------------------
ENGINE_EXTENSIONS = {
    "zstd":   ".zst",
    "lz4":    ".lz4",
    "gzip":   ".gz",
    "lzma":   ".lzma",
    "brotli": ".br",
}

# Reverse map for decompression — extension → engine
EXTENSION_ENGINE_MAP = {v: k for k, v in ENGINE_EXTENSIONS.items()}

# ---------------------------------------------------------------------------
# Compression result
# ---------------------------------------------------------------------------

@dataclass
class CompressionResult:
    input_path:        Path
    output_path:       Path
    engine:            str
    level:             int
    input_size:        int       # bytes
    output_size:       int       # bytes
    ratio:             float
    compress_time:     float     # seconds
    compress_speed:    float     # MB/s
    peak_memory_mb:    float
    success:           bool
    error:             Optional[str]

    def summary(self) -> str:
        if not self.success:
            return f"\n  ❌ Compression failed: {self.error}"

        saved    = self.input_size - self.output_size
        saved_mb = saved / 1024 / 1024

        return (
            f"\n  ✅ Done"
            f"\n  {'Input':<20} {self.input_size  / 1024 / 1024:.2f} MB  ({self.input_path.name})"
            f"\n  {'Compressed':<20} {self.output_size / 1024 / 1024:.2f} MB  ({self.output_path.name})"
            f"\n  {'Ratio':<20} {self.ratio:.2f}x"
            f"\n  {'Space saved':<20} {saved_mb:.2f} MB"
            f"\n  {'Time':<20} {self.compress_time:.2f}s"
            f"\n  {'Speed':<20} {self.compress_speed:.1f} MB/s"
            f"\n  {'Peak memory':<20} {self.peak_memory_mb:.1f} MB"
            f"\n  {'Engine':<20} {self.engine} level {self.level}"
        )


@dataclass
class DecompressionResult:
    input_path:       Path
    output_path:      Path
    engine:           str
    input_size:       int
    output_size:      int
    decompress_time:  float
    decompress_speed: float
    success:          bool
    error:            Optional[str]

    def summary(self) -> str:
        if not self.success:
            return f"\n  ❌ Decompression failed: {self.error}"
        return (
            f"\n  ✅ Done"
            f"\n  {'Compressed':<20} {self.input_size  / 1024 / 1024:.2f} MB"
            f"\n  {'Restored':<20} {self.output_size / 1024 / 1024:.2f} MB  ({self.output_path.name})"
            f"\n  {'Time':<20} {self.decompress_time:.2f}s"
            f"\n  {'Speed':<20} {self.decompress_speed:.1f} MB/s"
        )


# ---------------------------------------------------------------------------
# Engine compress / decompress implementations
# ---------------------------------------------------------------------------

def _compress_zstd(data: bytes, level: int) -> bytes:
    return zstd.ZstdCompressor(level=level).compress(data)

def _decompress_zstd(data: bytes) -> bytes:
    return zstd.ZstdDecompressor().decompress(data)


def _compress_lz4(data: bytes, level: int) -> bytes:
    return lz4.frame.compress(data, compression_level=level)

def _decompress_lz4(data: bytes) -> bytes:
    return lz4.frame.decompress(data)


def _compress_gzip(data: bytes, level: int) -> bytes:
    return gzip.compress(data, compresslevel=level)

def _decompress_gzip(data: bytes) -> bytes:
    return gzip.decompress(data)


def _compress_lzma(data: bytes, level: int) -> bytes:
    return lzma.compress(data, preset=level)

def _decompress_lzma(data: bytes) -> bytes:
    return lzma.decompress(data)


def _compress_brotli(data: bytes, level: int) -> bytes:
    return brotli.compress(data, quality=level)

def _decompress_brotli(data: bytes) -> bytes:
    return brotli.decompress(data)


COMPRESS_FN = {
    "zstd":   _compress_zstd,
    "lz4":    _compress_lz4,
    "gzip":   _compress_gzip,
    "lzma":   _compress_lzma,
    "brotli": _compress_brotli,
}

DECOMPRESS_FN = {
    "zstd":   _decompress_zstd,
    "lz4":    _decompress_lz4,
    "gzip":   _decompress_gzip,
    "lzma":   _decompress_lzma,
    "brotli": _decompress_brotli,
}


# ---------------------------------------------------------------------------
# Core compress / decompress functions
# ---------------------------------------------------------------------------

def compress(
    input_path:   Path,
    engine:       str,
    level:        int,
    output_path:  Optional[Path] = None,
) -> CompressionResult:
    """
    Compress input_path using engine at level.
    Writes output to output_path (defaults to same folder as input).
    Returns CompressionResult with all measured metrics.
    """
    input_path = input_path.resolve()

    if not input_path.exists():
        return CompressionResult(
            input_path=input_path, output_path=Path(""),
            engine=engine, level=level, input_size=0, output_size=0,
            ratio=0.0, compress_time=0.0, compress_speed=0.0,
            peak_memory_mb=0.0, success=False,
            error=f"Input file not found: {input_path}"
        )

    # determine output path
    ext = ENGINE_EXTENSIONS.get(engine, ".compressed")
    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + ext)
    elif output_path.is_dir():
        output_path = output_path / (input_path.name + ext)

    # read input
    try:
        data = input_path.read_bytes()
    except Exception as e:
        return CompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, level=level, input_size=0, output_size=0,
            ratio=0.0, compress_time=0.0, compress_speed=0.0,
            peak_memory_mb=0.0, success=False,
            error=f"Could not read input file: {e}"
        )

    input_size = len(data)

    # compress with memory + time tracking
    fn = COMPRESS_FN.get(engine)
    if fn is None:
        return CompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, level=level, input_size=input_size, output_size=0,
            ratio=0.0, compress_time=0.0, compress_speed=0.0,
            peak_memory_mb=0.0, success=False,
            error=f"Unknown engine: {engine}"
        )

    try:
        tracemalloc.start()
        t0         = time.perf_counter()
        compressed = fn(data, level)
        elapsed    = time.perf_counter() - t0
        _, peak    = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    except Exception as e:
        tracemalloc.stop()
        return CompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, level=level, input_size=input_size, output_size=0,
            ratio=0.0, compress_time=0.0, compress_speed=0.0,
            peak_memory_mb=0.0, success=False,
            error=f"Compression failed: {e}"
        )

    output_size    = len(compressed)
    ratio          = input_size / output_size if output_size > 0 else 0.0
    compress_speed = (input_size / 1024 / 1024) / elapsed if elapsed > 0 else 0.0
    peak_memory_mb = peak / 1024 / 1024

    # write output
    try:
        output_path.write_bytes(compressed)
    except Exception as e:
        return CompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, level=level, input_size=input_size,
            output_size=output_size, ratio=ratio,
            compress_time=elapsed, compress_speed=compress_speed,
            peak_memory_mb=peak_memory_mb, success=False,
            error=f"Could not write output file: {e}"
        )

    return CompressionResult(
        input_path     = input_path,
        output_path    = output_path,
        engine         = engine,
        level          = level,
        input_size     = input_size,
        output_size    = output_size,
        ratio          = ratio,
        compress_time  = elapsed,
        compress_speed = compress_speed,
        peak_memory_mb = peak_memory_mb,
        success        = True,
        error          = None,
    )


def decompress(
    input_path:  Path,
    output_path: Optional[Path] = None,
    engine:      Optional[str]  = None,
) -> DecompressionResult:
    """
    Decompress input_path.
    Engine is auto-detected from file extension if not specified.
    """
    input_path = input_path.resolve()

    if not input_path.exists():
        return DecompressionResult(
            input_path=input_path, output_path=Path(""),
            engine=engine or "unknown", input_size=0, output_size=0,
            decompress_time=0.0, decompress_speed=0.0,
            success=False, error=f"File not found: {input_path}"
        )

    # auto-detect engine from extension
    if engine is None:
        ext    = input_path.suffix.lower()
        engine = EXTENSION_ENGINE_MAP.get(ext)
        if engine is None:
            return DecompressionResult(
                input_path=input_path, output_path=Path(""),
                engine="unknown", input_size=0, output_size=0,
                decompress_time=0.0, decompress_speed=0.0,
                success=False,
                error=(
                    f"Cannot detect engine from extension '{ext}'. "
                    f"Known extensions: {list(EXTENSION_ENGINE_MAP.keys())}"
                )
            )

    # determine output path — strip the compressed extension
    if output_path is None:
        output_path = input_path.with_suffix("")   # removes .zst / .gz etc
    elif output_path.is_dir():
        output_path = output_path / input_path.stem

    # read compressed data
    try:
        data = input_path.read_bytes()
    except Exception as e:
        return DecompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, input_size=0, output_size=0,
            decompress_time=0.0, decompress_speed=0.0,
            success=False, error=f"Could not read file: {e}"
        )

    input_size = len(data)

    fn = DECOMPRESS_FN.get(engine)
    if fn is None:
        return DecompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, input_size=input_size, output_size=0,
            decompress_time=0.0, decompress_speed=0.0,
            success=False, error=f"Unknown engine: {engine}"
        )

    try:
        t0             = time.perf_counter()
        decompressed   = fn(data)
        elapsed        = time.perf_counter() - t0
    except Exception as e:
        return DecompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, input_size=input_size, output_size=0,
            decompress_time=0.0, decompress_speed=0.0,
            success=False, error=f"Decompression failed: {e}"
        )

    output_size      = len(decompressed)
    decompress_speed = (input_size / 1024 / 1024) / elapsed if elapsed > 0 else 0.0

    try:
        output_path.write_bytes(decompressed)
    except Exception as e:
        return DecompressionResult(
            input_path=input_path, output_path=output_path,
            engine=engine, input_size=input_size, output_size=output_size,
            decompress_time=elapsed, decompress_speed=decompress_speed,
            success=False, error=f"Could not write output: {e}"
        )

    return DecompressionResult(
        input_path       = input_path,
        output_path      = output_path,
        engine           = engine,
        input_size       = input_size,
        output_size      = output_size,
        decompress_time  = elapsed,
        decompress_speed = decompress_speed,
        success          = True,
        error            = None,
    )


# ---------------------------------------------------------------------------
# Smart compress — profiles + selects + compresses in one call
# This is the main function the UI / FastAPI layer will call
# ---------------------------------------------------------------------------

def smart_compress(
    input_path:    Path,
    constraints:   list         = None, # type: ignore
    output_path:   Optional[Path] = None,
    db_path:       Optional[Path] = None,
    confirm:       bool         = True,
) -> tuple:
    """
    Full pipeline: profile → select → compress.

    Args:
        input_path:  file to compress
        constraints: list of (constraint_name, degree) tuples
        output_path: where to write output (defaults to same folder)
        db_path:     path to benchmark.db
        confirm:     if True, print recommendation and ask user to confirm
                     before compressing. Set False for programmatic use.

    Returns:
        (Recommendation, CompressionResult)
    """
    if constraints is None:
        constraints = []

    input_path = input_path.resolve()

    # --- profile + select ---
    kwargs = {}
    if db_path:
        kwargs["db_path"] = db_path

    print(f"\nAnalyzing {input_path.name}...")
    rec = select(input_path, constraints, **kwargs)

    # --- show recommendation ---
    _print_recommendation(rec, input_path)

    # --- incompressible warning ---
    if rec.warning:
        print(f"\n  ⚠  {rec.warning}")
        if confirm:
            ans = input("\n  Compress anyway? [y/N]: ").strip().lower()
            if ans != "y":
                print("  Cancelled.")
                return rec, None

    # --- confirm before running ---
    if confirm:
        ans = input("\n  Compress with these settings? [Y/n]: ").strip().lower()
        if ans == "n":
            print("  Cancelled.")
            return rec, None

    # --- compress ---
    print(f"\n  Compressing...")
    result = compress(input_path, rec.engine, rec.level, output_path)

    # --- print result ---
    print(result.summary())

    # --- compare prediction vs actual ---
    if result.success:
        _print_prediction_vs_actual(rec, result)

    return rec, result


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_recommendation(rec: Recommendation, input_path: Path) -> None:
    size_mb     = input_path.stat().st_size / 1024 / 1024
    est_size_mb = size_mb / rec.predicted_ratio
    est_time_s  = size_mb / rec.predicted_compress_speed if rec.predicted_compress_speed > 0 else 0

    W = 56  # inner width
    def row(label, value):
        content = f"  {label:<14}: {value}"
        print(f"  │{content:<{W}}│")

    print(f"\n  ┌{'─' * W}┐")
    row("Engine",      f"{rec.engine} level {rec.level}")
    row("Est. ratio",  f"{rec.predicted_ratio:.2f}x  ({size_mb:.1f} MB → ~{est_size_mb:.1f} MB)")
    row("Est. time",   f"~{est_time_s:.1f}s")
    row("Est. memory", f"~{rec.predicted_memory_mb:.0f} MB")
    row("Reason",      rec.reason[:40])
    print(f"  └{'─' * W}┘")

    if rec.alternatives:
        print(f"\n  Alternatives:")
        for alt in rec.alternatives:
            print(
                f"    {alt.engine:<10} L{alt.level:<4} "
                f"ratio={alt.predicted_ratio:.2f}x  "
                f"cmp={alt.predicted_compress_speed:.0f}MB/s  "
                f"dcmp={alt.predicted_decompress_speed:.0f}MB/s"
            )


def _print_prediction_vs_actual(rec: Recommendation, result: CompressionResult) -> None:
    ratio_diff = abs(rec.predicted_ratio - result.ratio)
    ratio_pct  = (ratio_diff / rec.predicted_ratio * 100) if rec.predicted_ratio > 0 else 0

    print(f"\n  Prediction accuracy:")
    print(f"    Ratio   predicted={rec.predicted_ratio:.2f}x  "
          f"actual={result.ratio:.2f}x  "
          f"(off by {ratio_pct:.1f}%)")
    print(f"    Speed   predicted={rec.predicted_compress_speed:.0f}MB/s  "
          f"actual={result.compress_speed:.0f}MB/s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Smart compression tool — automatically selects best engine and level"
    )
    parser.add_argument(
        "path",
        type=Path,
        help="File to compress (or decompress with --decompress)"
    )
    parser.add_argument(
        "--constraint",
        action="append",
        dest="constraints",
        default=[],
        metavar="NAME",
        help=f"Constraint: {VALID_CONSTRAINTS}. Can be repeated."
    )
    parser.add_argument(
        "--degree",
        action="append",
        dest="degrees",
        default=[],
        metavar="LEVEL",
        help=f"Degree for each constraint: {VALID_DEGREES}"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output file or folder (default: same folder as input)"
    )
    parser.add_argument(
        "--decompress", "-d",
        action="store_true",
        help="Decompress the file instead of compressing"
    )
    parser.add_argument(
        "--engine",
        type=str,
        default=None,
        help="Force a specific engine (skips selector)"
    )
    parser.add_argument(
        "--level",
        type=int,
        default=None,
        help="Force a specific level (requires --engine)"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to benchmark.db"
    )

    args = parser.parse_args()
    path = args.path.resolve()

    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    # --- decompress mode ---
    if args.decompress:
        print(f"\nDecompressing {path.name}...")
        result = decompress(path, args.output, args.engine)
        print(result.summary())
        return

    # --- force engine mode (bypass selector) ---
    if args.engine:
        if args.level is None:
            print(f"[ERROR] --level is required when using --engine")
            return
        print(f"\nForced mode: {args.engine} level {args.level}")
        result = compress(path, args.engine, args.level, args.output)
        print(result.summary())
        return

    # --- smart compress mode ---
    constraints = args.constraints
    degrees     = args.degrees

    if len(degrees) == 0:
        degrees = ["balanced"] * len(constraints)
    elif len(degrees) != len(constraints):
        print("[ERROR] Number of --degree values must match --constraint count")
        return

    constraint_pairs = list(zip(constraints, degrees))

    db_kwargs = {"db_path": args.db} if args.db else {}

    smart_compress(
        input_path  = path,
        constraints = constraint_pairs,
        output_path = args.output,
        confirm     = not args.yes,
        **db_kwargs,
    )


if __name__ == "__main__":
    main()