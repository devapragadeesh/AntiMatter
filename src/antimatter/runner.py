"""
runner.py

Compresses and decompresses a chunk using a given engine + level,
measures the results, and returns them. Does NOT store anything —
pipeline.py handles writing to benchmark.db.

What it measures per run:
    - compression ratio     (input_size / output_size)
    - compression speed     (MB/s)
    - decompression speed   (MB/s)
    - peak memory           (MB, tracked via tracemalloc)
    - wall time for both    (seconds)

Engines + levels (stage 1):
    zstd:   1, 3, 6, 9, 12, 15, 19
    lz4:    1, 3, 6, 9, 12
    gzip:   1, 3, 6, 9
    lzma:   1, 3, 5, 7, 9
    brotli: 1, 4, 7, 9, 11

Usage (standalone test):
    python runner.py path/to/chunk.bin zstd 3
    python runner.py path/to/chunk.bin brotli 9
    python runner.py path/to/chunk.bin gzip 6
"""

import gzip
import lzma
import time
import argparse
import tracemalloc
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

import lz4.frame
import zstandard as zstd
import brotli

# ---------------------------------------------------------------------------
# Stage 1 level sweep per engine
# ---------------------------------------------------------------------------
ENGINE_LEVELS = {
    "zstd":   [1, 3, 6, 9, 12, 15, 19],
    "lz4":    [1, 3, 6, 9, 12],
    "gzip":   [1, 3, 6, 9],
    "lzma":   [1, 3, 5, 7, 9],
    "brotli": [1, 4, 7, 9, 11],
}

ALL_ENGINES = list(ENGINE_LEVELS.keys())


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    engine:           str
    level:            int
    input_size:       int       # bytes
    output_size:      int       # bytes
    ratio:            float     # input / output  (>1.0 = got smaller)
    compress_time:    float     # seconds
    decompress_time:  float     # seconds
    compress_speed:   float     # MB/s
    decompress_speed: float     # MB/s
    peak_memory_mb:   float     # MB during compression
    success:          bool
    error:            Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if not self.success:
            return (
                f"  [{self.engine:<8} L{self.level:<3}]  "
                f"FAILED: {self.error}"
            )
        return (
            f"  [{self.engine:<8} L{self.level:<3}]  "
            f"ratio={self.ratio:.2f}x  "
            f"cmp={self.compress_speed:>8.1f} MB/s  "
            f"dcmp={self.decompress_speed:>8.1f} MB/s  "
            f"mem={self.peak_memory_mb:.1f} MB"
        )


def _failed(
    engine: str,
    level: int,
    input_size: int,
    error: str,
) -> RunResult:
    return RunResult(
        engine=engine, level=level, input_size=input_size,
        output_size=0, ratio=0.0, compress_time=0.0,
        decompress_time=0.0, compress_speed=0.0,
        decompress_speed=0.0, peak_memory_mb=0.0,
        success=False, error=error,
    )


# ---------------------------------------------------------------------------
# Memory + timing helpers
# ---------------------------------------------------------------------------

def _compress_tracked(fn, data: bytes) -> tuple:
    """
    Run fn(data) → compressed bytes while tracking:
        - wall time (seconds)
        - peak memory delta (MB)

    Returns (compressed_bytes, elapsed_seconds, peak_memory_mb)
    """
    tracemalloc.start()
    t0 = time.perf_counter()

    compressed = fn(data)

    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()   # peak in bytes
    tracemalloc.stop()

    return compressed, elapsed, peak / 1024 / 1024


def _decompress_timed(fn, data: bytes) -> tuple:
    """
    Run fn(data) → decompressed bytes and measure wall time only.
    Returns (decompressed_bytes, elapsed_seconds)
    """
    t0 = time.perf_counter()
    decompressed = fn(data)
    elapsed = time.perf_counter() - t0
    return decompressed, elapsed


def _speed_mbs(n_bytes: int, seconds: float) -> float:
    """Convert byte count + seconds into MB/s. Avoids division by zero."""
    if seconds <= 0:
        return 0.0
    return (n_bytes / 1024 / 1024) / seconds


# ---------------------------------------------------------------------------
# Per-engine compress / decompress functions
# Each returns raw bytes so the runner can measure sizes uniformly.
# ---------------------------------------------------------------------------

def _run_zstd(data: bytes, level: int) -> tuple:
    cctx = zstd.ZstdCompressor(level=level)
    dctx = zstd.ZstdDecompressor()
    compress_fn   = lambda d: cctx.compress(d)
    decompress_fn = lambda d: dctx.decompress(d)
    return compress_fn, decompress_fn


def _run_lz4(data: bytes, level: int) -> tuple:
    # lz4 level 1 uses fast mode; levels 3-12 use HC mode — same API
    compress_fn   = lambda d: lz4.frame.compress(d, compression_level=level)
    decompress_fn = lambda d: lz4.frame.decompress(d)
    return compress_fn, decompress_fn


def _run_gzip(data: bytes, level: int) -> tuple:
    compress_fn   = lambda d: gzip.compress(d, compresslevel=level)
    decompress_fn = lambda d: gzip.decompress(d)
    return compress_fn, decompress_fn


def _run_lzma(data: bytes, level: int) -> tuple:
    compress_fn   = lambda d: lzma.compress(d, preset=level)
    decompress_fn = lambda d: lzma.decompress(d)
    return compress_fn, decompress_fn


def _run_brotli(data: bytes, level: int) -> tuple:
    compress_fn   = lambda d: brotli.compress(d, quality=level)
    decompress_fn = lambda d: brotli.decompress(d)
    return compress_fn, decompress_fn


ENGINE_FN_MAP = {
    "zstd":   _run_zstd,
    "lz4":    _run_lz4,
    "gzip":   _run_gzip,
    "lzma":   _run_lzma,
    "brotli": _run_brotli,
}


# ---------------------------------------------------------------------------
# Main entry point — this is what pipeline.py calls
# ---------------------------------------------------------------------------

def run(chunk_path: Path, engine: str, level: int) -> RunResult:
    """
    Compress and decompress chunk_path with the given engine + level.
    Returns a RunResult with all measured metrics.
    """
    if engine not in ENGINE_FN_MAP:
        return _failed(engine, level, 0, f"unknown engine '{engine}'")

    valid_levels = ENGINE_LEVELS.get(engine, [])
    if level not in valid_levels:
        return _failed(
            engine, level, 0,
            f"level {level} not in stage-1 sweep for {engine}: {valid_levels}"
        )

    # --- read chunk ---
    try:
        data = chunk_path.read_bytes()
    except Exception as e:
        return _failed(engine, level, 0, f"could not read chunk: {e}")

    input_size = len(data)

    # --- get compress/decompress functions ---
    try:
        compress_fn, decompress_fn = ENGINE_FN_MAP[engine](data, level)
    except Exception as e:
        return _failed(engine, level, input_size, f"engine init failed: {e}")

    # --- compress ---
    try:
        compressed, compress_time, peak_memory_mb = _compress_tracked(
            compress_fn, data
        )
    except Exception as e:
        return _failed(engine, level, input_size, f"compression failed: {e}")

    output_size = len(compressed)

    if output_size == 0:
        return _failed(engine, level, input_size, "compression produced empty output")

    # --- decompress ---
    try:
        _, decompress_time = _decompress_timed(decompress_fn, compressed)
    except Exception as e:
        return _failed(engine, level, input_size, f"decompression failed: {e}")

    # --- metrics ---
    ratio            = input_size / output_size
    compress_speed   = _speed_mbs(input_size, compress_time)
    decompress_speed = _speed_mbs(input_size, decompress_time)

    return RunResult(
        engine           = engine,
        level            = level,
        input_size       = input_size,
        output_size      = output_size,
        ratio            = ratio,
        compress_time    = compress_time,
        decompress_time  = decompress_time,
        compress_speed   = compress_speed,
        decompress_speed = decompress_speed,
        peak_memory_mb   = peak_memory_mb,
        success          = True,
        error            = None,
    )


def run_all(chunk_path: Path) -> list:
    """
    Run every engine × level combination on a single chunk.
    Returns a list of RunResult — one per (engine, level) pair.
    This is a convenience wrapper for pipeline.py.
    """
    results = []
    for engine, levels in ENGINE_LEVELS.items():
        for level in levels:
            result = run(chunk_path, engine, level)
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# CLI — for quick testing of a single chunk
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run a single engine+level on a chunk file"
    )
    parser.add_argument("path",   type=Path, help="Path to chunk file")
    parser.add_argument("engine", type=str,  help=f"Engine: {ALL_ENGINES}")
    parser.add_argument("level",  type=int,  nargs="?", default=None,
                        help="Compression level (see ENGINE_LEVELS)")
    args = parser.parse_args()

    path = args.path.resolve()
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    engine = args.engine.lower()
    if engine not in ENGINE_FN_MAP:
        print(f"[ERROR] Unknown engine '{engine}'. Choose from: {ALL_ENGINES}")
        return

    # if no level given, run all levels for that engine
    levels = [args.level] if args.level is not None else ENGINE_LEVELS[engine]

    size_mb = path.stat().st_size / 1024 / 1024
    print(f"Chunk  : {path.name}  ({size_mb:.2f} MB)")
    print(f"Engine : {engine}")
    print()

    for level in levels:
        result = run(path, engine, level)
        print(result.summary())

    print()
    print("Done.")


if __name__ == "__main__":
    main()