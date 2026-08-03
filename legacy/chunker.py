"""
chunker.py

Splits large source files into varied-size chunks at varied offsets.
Each chunk becomes one row in the benchmark DB later.

Folder structure expected:
    data/
        raw/
            numeric/    (.xlsx etc)
            random/     (.bin etc)
            repetitive/ (.html, .txt etc)
            structured/ (.sql etc)
            text/       (.xml etc)
        chunks/         <- generated here
            numeric/
            random/
            ...

Usage:
    python chunker.py
    python chunker.py --raw_dir path/to/raw --chunks_dir path/to/chunks
"""

import argparse
import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Chunk size buckets (bytes) — gives size as a real variable in the DB
# ---------------------------------------------------------------------------
CHUNK_SIZES = [
    512  * 1024,        #  512 KB  — lots of rows, fast to run
    1    * 1024 ** 2,   #    1 MB
    5    * 1024 ** 2,   #    5 MB
    10   * 1024 ** 2,   #   10 MB
    50   * 1024 ** 2,   #   50 MB
    100  * 1024 ** 2,   #  100 MB  — medium scale behavior
    250  * 1024 ** 2,   #  250 MB  — large scale, fewer chunks
]

# Chunks per size bucket — smaller buckets get more chunks for DB row density,
# larger buckets get fewer since they're slow to run through every engine/level.
CHUNKS_PER_SIZE_BY_BUCKET = {
    512  * 1024:      15,
    1    * 1024 ** 2: 15,
    5    * 1024 ** 2: 10,
    10   * 1024 ** 2: 10,
    50   * 1024 ** 2:  6,
    100  * 1024 ** 2:  4,
    250  * 1024 ** 2:  2,   # just start + middle of file
}

# Fallback if a size somehow isn't in the dict above
CHUNKS_PER_SIZE_DEFAULT = 10

# Minimum bytes a chunk must have to be saved (avoids tiny tail chunks)
MIN_CHUNK_BYTES = 256 * 1024   # 256 KB

# Categories and which file extensions belong to each.
# Used only for a sanity-check warning — chunking itself is extension-agnostic.
CATEGORY_EXTENSIONS = {
    "numeric":    {".xlsx", ".xls", ".csv"},
    "random":     {".bin"},
    "repetitive": {".html", ".htm", ".txt"},
    "structured": {".sql"},
    "text":       {".xml"},
}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def iter_source_files(raw_dir: Path, category: str):
    """Yield every file inside raw_dir/category, recursively."""
    cat_dir = raw_dir / category
    if not cat_dir.exists():
        print(f"  [WARN] category folder not found: {cat_dir}")
        return
    for path in sorted(cat_dir.rglob("*")):
        if path.is_file():
            yield path


def compute_offsets(file_size: int, chunk_size: int, n: int) -> list:
    """
    Return n evenly-spaced byte offsets so chunks cover the whole file.
    Spread from byte 0 to the last valid start position so we always
    sample from the beginning, middle, and end — not just the first bytes.
    """
    if file_size <= chunk_size:
        return [0]

    max_start = file_size - chunk_size
    if n == 1:
        return [0]

    step = max_start / (n - 1)
    offsets = [int(i * step) for i in range(n)]

    # deduplicate in case file is small relative to n
    seen = set()
    unique = []
    for o in offsets:
        if o not in seen:
            seen.add(o)
            unique.append(o)
    return unique


def short_hash(data: bytes, length: int = 6) -> str:
    """Short content hash — makes chunk filenames unique even across runs."""
    return hashlib.md5(data[:4096]).hexdigest()[:length]


def _human(n: int) -> str:
    """Return a human-readable size label used in chunk filenames."""
    if n >= 1024 ** 2:
        return f"{n // (1024 ** 2)}mb"
    return f"{n // 1024}kb"


def chunk_file(
    src: Path,
    out_dir: Path,
    category: str,
    chunk_sizes: list = None, 
    chunks_per_size_by_bucket: dict = None,
    min_bytes: int = MIN_CHUNK_BYTES,
) -> int:
    """
    Read src, write chunks into out_dir.
    Original file is never modified — only read.
    Returns the number of chunks written.
    """
    if chunk_sizes is None:
        chunk_sizes = CHUNK_SIZES
    if chunks_per_size_by_bucket is None:
        chunks_per_size_by_bucket = CHUNKS_PER_SIZE_BY_BUCKET

    file_size = src.stat().st_size
    if file_size < min_bytes:
        print(f"  [SKIP] {src.name} is only {file_size / 1024:.0f} KB — too small")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    with open(src, "rb") as fh:
        for chunk_size in chunk_sizes:
            n_chunks = chunks_per_size_by_bucket.get(chunk_size, CHUNKS_PER_SIZE_DEFAULT)

            if chunk_size > file_size:
                # File is smaller than this bucket.
                # Take the whole file as one chunk rather than skipping —
                # still gives a useful DB row for this size range.
                offsets        = [0]
                effective_size = file_size
            else:
                offsets        = compute_offsets(file_size, chunk_size, n_chunks)
                effective_size = chunk_size

            size_label = _human(effective_size)

            for offset in offsets:
                fh.seek(offset)
                data = fh.read(effective_size)

                if len(data) < min_bytes:
                    continue

                # Filename encodes all metadata so no separate manifest is needed.
                # Pattern: {category}__{stem}__{size_label}__off{offset}__{hash}.bin
                stem  = src.stem[:40]       # truncate very long filenames
                h     = short_hash(data)
                fname = f"{category}__{stem}__{size_label}__off{offset}__{h}.bin"
                dest  = out_dir / fname

                if dest.exists():
                    written += 1            # already done — safe to re-run
                    continue

                dest.write_bytes(data)
                written += 1

    return written


# ---------------------------------------------------------------------------
# Summary + plan printers
# ---------------------------------------------------------------------------

def print_bucket_plan() -> None:
    """Show the chunk plan before running so the user knows what to expect."""
    print("Chunk size plan:")
    print(f"  {'Bucket':<12} {'Chunks per file':>16}")
    print(f"  {'-'*28}")
    for size, n in CHUNKS_PER_SIZE_BY_BUCKET.items():
        print(f"  {_human(size):<12} {n:>16}")
    print()


def print_summary(results: dict) -> None:
    print("\n" + "=" * 52)
    print(f"{'CATEGORY':<20} {'CHUNKS WRITTEN':>15}")
    print("=" * 52)
    total = 0
    for cat, count in sorted(results.items()):
        print(f"  {cat:<18} {count:>15,}")
        total += count
    print("-" * 52)
    print(f"  {'TOTAL':<18} {total:>15,}")
    print("=" * 52)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Chunk large source files into the benchmark dataset"
    )
    parser.add_argument(
        "--raw_dir",
        type=Path,
        default=Path("data/raw"),
        help="Root folder containing category sub-folders (default: data/raw)",
    )
    parser.add_argument(
        "--chunks_dir",
        type=Path,
        default=Path("data/chunks"),
        help="Output root for chunks (default: data/chunks)",
    )
    args = parser.parse_args()

    raw_dir    = args.raw_dir.resolve()
    chunks_dir = args.chunks_dir.resolve()

    if not raw_dir.exists():
        print(f"[ERROR] raw_dir does not exist: {raw_dir}")
        print("  Create it and place your category folders inside, e.g.:")
        print("    data/raw/numeric/   data/raw/random/   ...")
        return

    categories = sorted([d.name for d in raw_dir.iterdir() if d.is_dir()])
    if not categories:
        print(f"[ERROR] No sub-folders found in {raw_dir}")
        return

    print(f"Source     : {raw_dir}")
    print(f"Output     : {chunks_dir}")
    print(f"Categories : {categories}\n")
    print_bucket_plan()

    results = {}

    for category in categories:
        print(f"── {category.upper()} ──")
        out_dir   = chunks_dir / category
        cat_total = 0

        for src_file in iter_source_files(raw_dir, category):
            ext      = src_file.suffix.lower()
            expected = CATEGORY_EXTENSIONS.get(category, set())
            if expected and ext not in expected:
                print(f"  [NOTE] unexpected extension '{ext}' in {category}/ — chunking anyway")

            size_mb = src_file.stat().st_size / 1024 ** 2
            print(f"  {src_file.name}  ({size_mb:.1f} MB) ...", end=" ", flush=True)

            n = chunk_file(src_file, out_dir, category)
            print(f"{n} chunks")
            cat_total += n

        results[category] = cat_total
        print()

    print_summary(results)
    print(f"\nChunks saved to : {chunks_dir}")
    print("Next step       : run profiler.py on the chunks/ directory")


if __name__ == "__main__":
    main()