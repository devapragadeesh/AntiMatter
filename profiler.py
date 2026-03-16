"""
profiler.py

Analyzes raw bytes of a chunk and returns a feature vector.
This is pure computation — no file storage happens here.
Storage is handled by pipeline.py which combines profiler + runner output.

Feature vector produced:
    entropy          — Shannon entropy (0=fully repetitive, 1=fully random)
    repetitiveness   — LZ77-style match ratio (how much content repeats)
    numeric_density  — proportion of bytes that look like numeric/structured data
    ascii_ratio      — proportion of printable ASCII bytes
    compression_hint — fast lz4 ratio as a cheap compressibility proxy
    unique_byte_ratio— how many distinct byte values appear (256 max)
    file_size        — size of the chunk in bytes

Usage (standalone, for testing):
    python profiler.py path/to/chunk.bin
    python profiler.py data/chunks/text/text__sample__5mb__off0__a1b2c3.bin
"""

import math
import zlib
import struct
import argparse
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, asdict


# ---------------------------------------------------------------------------
# How many bytes to sample for profiling.
# Reading the full chunk is slow for 250MB files — sampling gives the same
# signal for entropy/repetitiveness at a fraction of the cost.
# ---------------------------------------------------------------------------
SAMPLE_SIZE   = 2 * 1024 * 1024    # 2 MB sample from the chunk
SAMPLE_POINTS = 4                   # take samples at 4 spread-out offsets


@dataclass
class FileProfile:
    entropy:           float   # 0.0 – 1.0
    repetitiveness:    float   # 0.0 – 1.0
    numeric_density:   float   # 0.0 – 1.0
    ascii_ratio:       float   # 0.0 – 1.0
    compression_hint:  float   # compression ratio via zlib fast (>1 = compressible)
    unique_byte_ratio: float   # 0.0 – 1.0  (1.0 = all 256 byte values present)
    file_size:         int     # bytes

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        lines = [
            f"  entropy           : {self.entropy:.4f}   (0=repetitive, 1=random)",
            f"  repetitiveness    : {self.repetitiveness:.4f}   (1=highly repetitive)",
            f"  numeric_density   : {self.numeric_density:.4f}",
            f"  ascii_ratio       : {self.ascii_ratio:.4f}",
            f"  compression_hint  : {self.compression_hint:.2f}x  (zlib fast ratio)",
            f"  unique_byte_ratio : {self.unique_byte_ratio:.4f}",
            f"  file_size         : {self.file_size / 1024 / 1024:.2f} MB",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _read_sample(data: bytes, sample_size: int, n_points: int) -> bytes:
    """
    Pull n_points evenly-spaced windows from data and concatenate.
    Each window is sample_size // n_points bytes.
    For small data just returns all of it.
    """
    total = len(data)
    window = sample_size // n_points

    if total <= sample_size:
        return data

    chunks = []
    for i in range(n_points):
        offset = int(i * (total - window) / (n_points - 1)) if n_points > 1 else 0
        chunks.append(data[offset: offset + window])
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------

def compute_entropy(data: bytes) -> float:
    """
    Shannon entropy normalized to [0, 1].
    0 = all bytes identical (e.g. all zeros)
    1 = perfectly uniform distribution (random bytes)
    """
    if not data:
        return 0.0

    counts = Counter(data)
    total  = len(data)
    entropy = 0.0

    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    # normalize: max entropy for byte data is log2(256) = 8 bits
    return entropy / 8.0


def compute_repetitiveness(data: bytes) -> float:
    """
    Estimates how repetitive the data is using a sliding window approach.
    Measures what fraction of 8-byte sequences have been seen before
    in the preceding 32KB window — a rough LZ77 match ratio proxy.

    Returns 0.0 (no repetition) to 1.0 (fully repetitive).
    """
    if len(data) < 16:
        return 0.0

    step        = 8       # stride between probes (faster than every byte)
    window_size = 32768   # 32KB lookback window
    matches     = 0
    probes      = 0

    i = window_size
    while i < len(data) - 8:
        needle  = data[i: i + 8]
        window  = data[max(0, i - window_size): i]
        if needle in window:
            matches += 1
        probes  += 1
        i       += step

    return matches / probes if probes > 0 else 0.0


def compute_numeric_density(data: bytes) -> float:
    """
    Proportion of bytes that fall in ASCII digit range (0x30–0x39)
    plus common numeric punctuation (., -, +, e, E).
    Higher values suggest CSV/SQL/structured numeric content.
    """
    numeric_bytes = set(b"0123456789.,-+eE")
    count = sum(1 for b in data if b in numeric_bytes)
    return count / len(data) if data else 0.0


def compute_ascii_ratio(data: bytes) -> float:
    """
    Proportion of bytes that are printable ASCII (0x20–0x7E) or common
    whitespace (tab, newline, carriage return).
    High ratio → text-like content (XML, SQL, HTML, logs).
    Low ratio  → binary content.
    """
    printable = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}
    count = sum(1 for b in data if b in printable)
    return count / len(data) if data else 0.0


def compute_compression_hint(data: bytes) -> float:
    """
    Compress a sample with zlib level 1 (fastest) and return the ratio.
    input_size / compressed_size  →  >1 means compressible, ~1 means random.
    Using level 1 keeps this fast — it's just a proxy, not a real benchmark.
    """
    if not data:
        return 1.0
    try:
        compressed = zlib.compress(data, level=1)
        return len(data) / len(compressed)
    except Exception:
        return 1.0


def compute_unique_byte_ratio(data: bytes) -> float:
    """
    Fraction of all 256 possible byte values that actually appear.
    0.0 = only 1 unique byte value (e.g. all zeros)
    1.0 = all 256 byte values present (typical of random/encrypted data)
    """
    return len(set(data)) / 256.0


# ---------------------------------------------------------------------------
# Main profiler entry point
# ---------------------------------------------------------------------------

def profile_bytes(data: bytes) -> FileProfile:
    """
    Compute the full feature vector from raw bytes.
    This is what pipeline.py calls for every chunk.
    """
    sample = _read_sample(data, SAMPLE_SIZE, SAMPLE_POINTS)

    return FileProfile(
        entropy           = compute_entropy(sample),
        repetitiveness    = compute_repetitiveness(sample),
        numeric_density   = compute_numeric_density(sample),
        ascii_ratio       = compute_ascii_ratio(sample),
        compression_hint  = compute_compression_hint(sample),
        unique_byte_ratio = compute_unique_byte_ratio(sample),
        file_size         = len(data),
    )


def profile_file(path: Path) -> FileProfile:
    """
    Read a file from disk and profile it.
    For large files (>SAMPLE_SIZE) only a sample is read into memory.
    """
    size = path.stat().st_size

    if size <= SAMPLE_SIZE:
        data = path.read_bytes()
        return profile_bytes(data)

    # For large files: read windows at spread-out offsets directly
    # so we never load the whole file into memory
    window  = SAMPLE_SIZE // SAMPLE_POINTS
    offsets = [
        int(i * (size - window) / (SAMPLE_POINTS - 1))
        for i in range(SAMPLE_POINTS)
    ]

    chunks = []
    with open(path, "rb") as fh:
        for offset in offsets:
            fh.seek(offset)
            chunks.append(fh.read(window))

    sample_data = b"".join(chunks)

    # profile_bytes uses len(data) for file_size — override with real size
    profile          = profile_bytes(sample_data)
    profile.file_size = size
    return profile


# ---------------------------------------------------------------------------
# CLI — for quick inspection of any chunk
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Profile a file chunk")
    parser.add_argument("path", type=Path, help="Path to chunk file")
    args = parser.parse_args()

    path = args.path.resolve()
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    print(f"Profiling: {path.name}  ({path.stat().st_size / 1024 / 1024:.2f} MB)")
    print()

    profile = profile_file(path)
    print(profile.summary())
    print()

    # Quick interpretation hint
    e = profile.entropy
    r = profile.repetitiveness
    if e < 0.3 and r > 0.7:
        hint = "highly repetitive — zstd/brotli with dictionary will shine"
    elif e > 0.85:
        hint = "high entropy / near-random — compression unlikely to help much"
    elif profile.ascii_ratio > 0.85:
        hint = "text-like — brotli/zstd with text dictionary are good candidates"
    elif profile.numeric_density > 0.3:
        hint = "numeric/structured — zstd or lzma with structured data settings"
    else:
        hint = "moderately compressible — zstd balanced mode is a safe default"

    print(f"  Hint: {hint}")


if __name__ == "__main__":
    main()