"""
pipeline.py

Orchestrates the full benchmark run:
    - Scans data/chunks/ for every .bin chunk file
    - Profiles each chunk (entropy, repetitiveness etc)
    - Runs every engine × level combination
    - Writes one row per (chunk, engine, level) to benchmark.db

Resume capability:
    Already-completed (chunk, engine, level) combinations are skipped.
    Safe to ctrl+c and re-run — nothing is duplicated.

DB schema (benchmark.db):
    One table: results
    Left side  — profiler output (file features)
    Right side — runner output  (compression metrics)

Usage:
    python pipeline.py
    python pipeline.py --chunks_dir data/chunks --db data/benchmark.db
    python pipeline.py --workers 4       # parallel chunk processing
    python pipeline.py --dry_run         # shows what would run, no execution
"""

import sqlite3
import argparse
import traceback
import concurrent.futures
from pathlib import Path
from datetime import datetime

from profiler import profile_file
from runner import run_all, ENGINE_LEVELS, RunResult


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CHUNKS_DIR = Path("data/chunks")
DEFAULT_DB_PATH    = Path("data/benchmark.db")
DEFAULT_WORKERS    = 1      # set >1 to parallelize across chunks
                            # keep at 1 for LZMA — it already pegs one core


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    -- identity
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_file        TEXT    NOT NULL,
    category          TEXT    NOT NULL,
    run_at            TEXT    NOT NULL,

    -- profiler output (file features)
    entropy           REAL,
    repetitiveness    REAL,
    numeric_density   REAL,
    ascii_ratio       REAL,
    compression_hint  REAL,
    unique_byte_ratio REAL,
    file_size         INTEGER,

    -- runner config
    engine            TEXT    NOT NULL,
    level             INTEGER NOT NULL,

    -- runner output (compression metrics)
    input_size        INTEGER,
    output_size       INTEGER,
    ratio             REAL,
    compress_time     REAL,
    decompress_time   REAL,
    compress_speed    REAL,
    decompress_speed  REAL,
    peak_memory_mb    REAL,
    success           INTEGER,   -- 1 = True, 0 = False
    error             TEXT,

    -- uniqueness constraint — enables resume
    UNIQUE(chunk_file, engine, level)
);

CREATE INDEX IF NOT EXISTS idx_engine_level
    ON results (engine, level);

CREATE INDEX IF NOT EXISTS idx_category
    ON results (category);

CREATE INDEX IF NOT EXISTS idx_features
    ON results (entropy, repetitiveness, file_size);
"""

INSERT_SQL = """
INSERT OR IGNORE INTO results (
    chunk_file, category, run_at,
    entropy, repetitiveness, numeric_density, ascii_ratio,
    compression_hint, unique_byte_ratio, file_size,
    engine, level,
    input_size, output_size, ratio,
    compress_time, decompress_time,
    compress_speed, decompress_speed,
    peak_memory_mb, success, error
) VALUES (
    :chunk_file, :category, :run_at,
    :entropy, :repetitiveness, :numeric_density, :ascii_ratio,
    :compression_hint, :unique_byte_ratio, :file_size,
    :engine, :level,
    :input_size, :output_size, :ratio,
    :compress_time, :decompress_time,
    :compress_speed, :decompress_speed,
    :peak_memory_mb, :success, :error
)
"""

ALREADY_DONE_SQL = """
SELECT engine, level FROM results
WHERE chunk_file = :chunk_file AND success = 1
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(DB_SCHEMA)
    conn.commit()
    return conn


def get_completed(conn: sqlite3.Connection, chunk_file: str) -> set:
    """Return set of (engine, level) pairs already successfully run for this chunk."""
    rows = conn.execute(ALREADY_DONE_SQL, {"chunk_file": chunk_file}).fetchall()
    return {(row[0], row[1]) for row in rows}


def write_rows(conn: sqlite3.Connection, rows: list) -> int:
    """Write a batch of row dicts. Returns number inserted (ignores duplicates)."""
    cursor = conn.executemany(INSERT_SQL, rows)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Chunk discovery
# ---------------------------------------------------------------------------

def find_chunks(chunks_dir: Path) -> list:
    """
    Recursively find all .bin chunk files under chunks_dir.
    Returns sorted list of Path objects.
    """
    return sorted(chunks_dir.rglob("*.bin"))


def parse_category(chunk_path: Path) -> str:
    """
    Extract category from chunk filename.
    Filename pattern: {category}__{stem}__{size}__off{n}__{hash}.bin
    Falls back to parent folder name if pattern doesn't match.
    """
    parts = chunk_path.stem.split("__")
    if len(parts) >= 1:
        return parts[0]
    return chunk_path.parent.name


# ---------------------------------------------------------------------------
# Per-chunk processing
# ---------------------------------------------------------------------------

def process_chunk(chunk_path: Path, conn: sqlite3.Connection) -> dict:
    """
    Profile a chunk, run all engines, write results to DB.
    Returns a stats dict for progress reporting.
    """
    chunk_file = chunk_path.name
    category   = parse_category(chunk_path)
    run_at     = datetime.utcnow().isoformat()

    stats = {
        "chunk":    chunk_file,
        "ran":      0,
        "skipped":  0,
        "failed":   0,
    }

    # --- profile ---
    try:
        profile = profile_file(chunk_path)
    except Exception as e:
        print(f"  [ERROR] profiling failed for {chunk_file}: {e}")
        return stats

    profile_dict = profile.to_dict()

    # --- check what's already done (resume) ---
    completed = get_completed(conn, chunk_file)

    total_configs = sum(len(lvls) for lvls in ENGINE_LEVELS.values())
    if len(completed) == total_configs:
        stats["skipped"] = total_configs
        return stats   # entire chunk already done

    # --- run engines ---
    results: list[RunResult] = run_all(chunk_path)

    rows = []
    for result in results:
        key = (result.engine, result.level)

        if key in completed:
            stats["skipped"] += 1
            continue

        row = {
            "chunk_file":        chunk_file,
            "category":          category,
            "run_at":            run_at,
            # profiler fields
            "entropy":           profile_dict["entropy"],
            "repetitiveness":    profile_dict["repetitiveness"],
            "numeric_density":   profile_dict["numeric_density"],
            "ascii_ratio":       profile_dict["ascii_ratio"],
            "compression_hint":  profile_dict["compression_hint"],
            "unique_byte_ratio": profile_dict["unique_byte_ratio"],
            "file_size":         profile_dict["file_size"],
            # runner config
            "engine":            result.engine,
            "level":             result.level,
            # runner results
            "input_size":        result.input_size,
            "output_size":       result.output_size,
            "ratio":             result.ratio,
            "compress_time":     result.compress_time,
            "decompress_time":   result.decompress_time,
            "compress_speed":    result.compress_speed,
            "decompress_speed":  result.decompress_speed,
            "peak_memory_mb":    result.peak_memory_mb,
            "success":           1 if result.success else 0,
            "error":             result.error,
        }
        rows.append(row)

        if result.success:
            stats["ran"] += 1
        else:
            stats["failed"] += 1

    if rows:
        write_rows(conn, rows)

    return stats


# ---------------------------------------------------------------------------
# Progress printer
# ---------------------------------------------------------------------------

def print_progress(
    done: int,
    total: int,
    stats: dict,
    start_time: float,
) -> None:
    import time
    elapsed   = time.perf_counter() - start_time
    pct       = (done / total * 100) if total > 0 else 0
    rate      = done / elapsed if elapsed > 0 else 0
    remaining = (total - done) / rate if rate > 0 else 0

    print(
        f"  [{done:>5}/{total}]  {pct:>5.1f}%  "
        f"ran={stats['ran']}  skip={stats['skipped']}  fail={stats['failed']}  "
        f"elapsed={elapsed:.0f}s  eta={remaining:.0f}s  "
        f"— {stats['chunk']}"
    )


def print_summary(total_chunks: int, total_ran: int, total_skipped: int,
                  total_failed: int, elapsed: float, db_path: Path) -> None:
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Chunks processed : {total_chunks:,}")
    print(f"  Rows inserted    : {total_ran:,}")
    print(f"  Rows skipped     : {total_skipped:,}  (already in DB)")
    print(f"  Failures         : {total_failed:,}")
    print(f"  Total time       : {elapsed:.1f}s  ({elapsed/60:.1f} min)")
    print(f"  Database         : {db_path}")
    print("=" * 60)
    print("Next step: run train.py to build regression models")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import time

    parser = argparse.ArgumentParser(
        description="Run full benchmark pipeline and populate benchmark.db"
    )
    parser.add_argument(
        "--chunks_dir", type=Path, default=DEFAULT_CHUNKS_DIR,
        help=f"Chunks directory (default: {DEFAULT_CHUNKS_DIR})"
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help="Parallel workers for chunk processing (default: 1)"
    )
    parser.add_argument(
        "--dry_run", action="store_true",
        help="Show what would run without executing anything"
    )
    args = parser.parse_args()

    chunks_dir = args.chunks_dir.resolve()
    db_path    = args.db.resolve()

    # --- validate ---
    if not chunks_dir.exists():
        print(f"[ERROR] chunks_dir not found: {chunks_dir}")
        print("  Run chunker.py first to generate chunks.")
        return

    chunks = find_chunks(chunks_dir)
    if not chunks:
        print(f"[ERROR] No .bin files found in {chunks_dir}")
        return

    # --- count total configs ---
    total_configs = sum(len(lvls) for lvls in ENGINE_LEVELS.items())
    total_runs    = len(chunks) * sum(len(v) for v in ENGINE_LEVELS.values())

    print(f"Chunks dir  : {chunks_dir}")
    print(f"Database    : {db_path}")
    print(f"Chunks found: {len(chunks):,}")
    print(f"Engines     : {list(ENGINE_LEVELS.keys())}")
    print(f"Total runs  : {total_runs:,}  (chunks × engine/level combos)")
    print(f"Workers     : {args.workers}")

    if args.dry_run:
        print("\n[DRY RUN] No compression executed.")
        for c in chunks[:10]:
            print(f"  would process: {c.name}")
        if len(chunks) > 10:
            print(f"  ... and {len(chunks) - 10} more")
        return

    # --- init DB ---
    conn = init_db(db_path)
    print(f"\nDatabase initialized. Starting pipeline...\n")

    # --- run ---
    start_time    = time.perf_counter()
    total_ran     = 0
    total_skipped = 0
    total_failed  = 0

    if args.workers == 1:
        # single-threaded — simpler, easier to debug
        for i, chunk_path in enumerate(chunks, 1):
            try:
                stats = process_chunk(chunk_path, conn)
            except Exception as e:
                print(f"  [CRASH] {chunk_path.name}: {e}")
                traceback.print_exc()
                stats = {"chunk": chunk_path.name, "ran": 0,
                         "skipped": 0, "failed": 1}

            total_ran     += stats["ran"]
            total_skipped += stats["skipped"]
            total_failed  += stats["failed"]
            print_progress(i, len(chunks), stats, start_time)

    else:
        # multi-threaded — faster for lz4/gzip, be careful with LZMA
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {
                ex.submit(process_chunk, cp, conn): cp
                for cp in chunks
            }
            done = 0
            for future in concurrent.futures.as_completed(futures):
                done += 1
                chunk_path = futures[future]
                try:
                    stats = future.result()
                except Exception as e:
                    print(f"  [CRASH] {chunk_path.name}: {e}")
                    stats = {"chunk": chunk_path.name, "ran": 0,
                             "skipped": 0, "failed": 1}

                total_ran     += stats["ran"]
                total_skipped += stats["skipped"]
                total_failed  += stats["failed"]
                print_progress(done, len(chunks), stats, start_time)

    conn.close()
    elapsed = time.perf_counter() - start_time
    print_summary(len(chunks), total_ran, total_skipped,
                  total_failed, elapsed, db_path)


if __name__ == "__main__":
    main()