"""
archiver.py

Per-file-optimized folder archiving for .szip.

Each file in a folder is independently profiled, selected, and compressed
with its own best-fit engine/level — NOT one engine for the whole folder.
Reuses the existing profiler -> selector -> predictor -> compressor pipeline
once per entry instead of tarring the folder into a single blob.

.szip binary layout:
    [MAGIC: b"SZIP"]                       4 bytes
    [FORMAT_VERSION: uint16 LE]            2 bytes
    --- archive body ---
    entry 0 compressed bytes
    entry 1 compressed bytes
    ...
    --- manifest ---
    manifest JSON bytes (UTF-8)
    --- trailer (always the last 16 bytes of the file) ---
    [manifest_offset: uint64 LE]           8 bytes
    [manifest_length: uint64 LE]           8 bytes

The manifest is a footer, not a header, because entry offsets/sizes are only
known once every file has been compressed — a header would need a full
buffering/two-pass write. This mirrors how ZIP's own central directory works.

Usage (standalone):
    python archiver.py path/to/folder
    python archiver.py path/to/archive.szip --decompress
"""

import os
import json
import time
import struct
import hashlib
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, Iterator

from profiler import profile_file
from selector import select, DB_PATH as SELECTOR_DB_PATH
from predictor import predict
from compressor import COMPRESS_FN, DECOMPRESS_FN

MAGIC = b"SZIP"
FORMAT_VERSION = 1
HEADER_SIZE = 6      # MAGIC (4) + version (2)
TRAILER_SIZE = 16    # manifest_offset (8) + manifest_length (8)

ARCHIVE_EXTENSION = ".szip"

# Below this size, skip full k-NN selection (not worth the overhead) and use
# a fast, safe default engine/level instead.
TINY_FILE_THRESHOLD = 4 * 1024  # 4 KB
TINY_FILE_ENGINE = "zstd"
TINY_FILE_LEVEL = 3

STORE_ENGINE = "store"  # sentinel: bytes stored raw, no compression applied

# Extensions for formats that are already compressed (archives, media codecs,
# fonts). Re-compressing these wastes CPU for near-zero size benefit, so they
# skip straight to STORE_ENGINE without going through select()/predict().
PRECOMPRESSED_EXTENSIONS = {
    # archives / containers
    ".zip", ".7z", ".rar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".lz4",
    ".szip", ".jar", ".war", ".apk", ".cab",
    # images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif",
    # audio / video
    ".mp3", ".aac", ".ogg", ".opus", ".flac", ".m4a",
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v",
    # documents with internal compression
    ".pdf", ".docx", ".xlsx", ".pptx", ".epub",
    # fonts
    ".woff", ".woff2",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ArchiveEntryResult:
    rel_path:        str
    entry_type:       str               # "file" | "dir"
    engine:           Optional[str]
    level:            Optional[int]
    original_size:    int
    compressed_size:  int
    offset:           int
    sha256:           Optional[str]
    mtime:            Optional[float]


@dataclass
class ArchiveResult:
    input_path:        Path
    output_path:        Path
    file_count:          int = 0
    dir_count:            int = 0
    skipped:             list = field(default_factory=list)   # [(path, reason)]
    stored_count:         int = 0   # entries written raw (precompressed or no benefit)
    total_input_size:    int = 0
    total_output_size:   int = 0
    ratio:                float = 0.0
    elapsed:              float = 0.0
    success:              bool = True
    error:                Optional[str] = None

    def summary(self) -> str:
        if not self.success:
            return f"\n  ❌ Archive failed: {self.error}"

        saved_mb = (self.total_input_size - self.total_output_size) / 1024 / 1024
        return (
            f"\n  ✅ Done"
            f"\n  {'Files':<20} {self.file_count} ({self.dir_count} empty dirs)"
            f"\n  {'Input':<20} {self.total_input_size  / 1024 / 1024:.2f} MB"
            f"\n  {'Output':<20} {self.total_output_size / 1024 / 1024:.2f} MB  ({self.output_path.name})"
            f"\n  {'Ratio':<20} {self.ratio:.2f}x"
            f"\n  {'Space saved':<20} {saved_mb:.2f} MB"
            f"\n  {'Time':<20} {self.elapsed:.2f}s"
            f"\n  {'Stored raw':<20} {self.stored_count} (already compressed / no benefit)"
            f"\n  {'Skipped':<20} {len(self.skipped)}"
        )


# ---------------------------------------------------------------------------
# Folder walk
# ---------------------------------------------------------------------------

def iter_folder_entries(root: Path) -> Iterator[tuple]:
    """
    Walk root yielding (absolute_path, relative_posix_path, is_dir, is_symlink)
    for every file, plus a dir entry ONLY for directories that are genuinely
    empty (no files and no non-empty subdirectories anywhere underneath) —
    those need a manifest placeholder so extraction recreates them; non-empty
    directories are implied by their files' paths and don't need one.
    Does not follow symlinks (os.walk default).
    """
    root = root.resolve()
    entries = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)

        if current != root and not dirnames and not filenames:
            rel = current.relative_to(root).as_posix()
            entries.append((current, rel, True, current.is_symlink()))

        for name in filenames:
            abs_path = current / name
            rel = abs_path.relative_to(root).as_posix()
            entries.append((abs_path, rel, False, abs_path.is_symlink()))

    entries.sort(key=lambda e: e[1])
    yield from entries


# ---------------------------------------------------------------------------
# Per-entry engine selection
# ---------------------------------------------------------------------------

def _is_precompressed(abs_path: Path) -> bool:
    """Extension-based check for formats that are already compressed."""
    return abs_path.suffix.lower() in PRECOMPRESSED_EXTENSIONS


def _select_for_entry(abs_path: Path, size: int, constraints: list, db_path) -> tuple:
    """
    Returns (engine, level) for one file.
    Known-precompressed formats (by extension) and tiny files skip full k-NN
    selection — precompressed content won't shrink further (re-running the
    codec just burns CPU), and tiny files' fixed k-NN cost dominates runtime
    at that size — everything else goes through the normal selector.
    """
    if _is_precompressed(abs_path):
        return STORE_ENGINE, None

    if size < TINY_FILE_THRESHOLD:
        return TINY_FILE_ENGINE, TINY_FILE_LEVEL

    kwargs = {}
    if db_path:
        kwargs["db_path"] = db_path
    rec = select(abs_path, constraints, **kwargs)
    return rec.engine, rec.level


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def compress_folder(
    input_path:  Path,
    output_path: Optional[Path] = None,
    constraints: list = None,          # type: ignore
    db_path:     Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> ArchiveResult:
    """
    Walk input_path (a directory), profile + select + compress each file
    independently, and write a .szip archive to output_path.

    progress_cb, if given, is called as progress_cb(files_done, files_total,
    current_rel_path) after each file finishes.
    """
    if constraints is None:
        constraints = []

    input_path = input_path.resolve()
    t0 = time.perf_counter()

    if not input_path.is_dir():
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=f"Not a directory: {input_path}",
        )

    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + ARCHIVE_EXTENSION)
    elif output_path.is_dir():
        output_path = output_path / (input_path.name + ARCHIVE_EXTENSION)

    all_entries = list(iter_folder_entries(input_path))
    skipped = []
    work_entries = []
    for abs_path, rel, is_dir, is_symlink in all_entries:
        if is_symlink:
            skipped.append((rel, "symlink (not followed)"))
            continue
        work_entries.append((abs_path, rel, is_dir))

    file_entries = [e for e in work_entries if not e[2]]
    dir_entries = [e for e in work_entries if e[2]]
    total_files = len(file_entries)

    manifest_entries = []
    total_input_size = 0
    total_output_size = 0
    stored_count = 0

    try:
        with open(output_path, "wb") as out:
            out.write(MAGIC)
            out.write(struct.pack("<H", FORMAT_VERSION))
            offset = HEADER_SIZE

            for _, rel, _ in dir_entries:
                manifest_entries.append({
                    "path": rel, "type": "dir",
                })

            for i, (abs_path, rel, _) in enumerate(file_entries):
                try:
                    size = abs_path.stat().st_size
                    data = abs_path.read_bytes()
                except Exception as e:
                    skipped.append((rel, f"read error: {e}"))
                    continue

                sha256_hex = hashlib.sha256(data).hexdigest()
                engine, level = _select_for_entry(abs_path, size, constraints, db_path)

                if engine == STORE_ENGINE:
                    compressed = data
                else:
                    compressed = COMPRESS_FN[engine](data, level)
                    # store-if-larger guard: never let an entry balloon past
                    # its original size (already-compressed / random content).
                    if len(compressed) >= size:
                        compressed = data
                        engine = STORE_ENGINE
                        level = None

                out.write(compressed)

                if engine == STORE_ENGINE:
                    stored_count += 1

                manifest_entries.append({
                    "path": rel,
                    "type": "file",
                    "engine": engine,
                    "level": level,
                    "original_size": size,
                    "compressed_size": len(compressed),
                    "offset": offset,
                    "sha256": sha256_hex,
                    "mtime": abs_path.stat().st_mtime,
                })

                offset += len(compressed)
                total_input_size += size
                total_output_size += len(compressed)

                if progress_cb:
                    progress_cb(i + 1, total_files, rel)

            manifest = {
                "format_version": FORMAT_VERSION,
                "root_name": input_path.name,
                "entries": manifest_entries,
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            manifest_offset = offset
            out.write(manifest_bytes)
            out.write(struct.pack("<QQ", manifest_offset, len(manifest_bytes)))

    except Exception as e:
        return ArchiveResult(
            input_path=input_path, output_path=output_path,
            success=False, error=f"Failed to write archive: {e}",
        )

    elapsed = time.perf_counter() - t0
    ratio = total_input_size / total_output_size if total_output_size > 0 else 0.0

    return ArchiveResult(
        input_path=input_path,
        output_path=output_path,
        file_count=len(file_entries),
        dir_count=len(dir_entries),
        skipped=skipped,
        stored_count=stored_count,
        total_input_size=total_input_size,
        total_output_size=total_output_size,
        ratio=ratio,
        elapsed=elapsed,
        success=True,
        error=None,
    )


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def _read_manifest(fh) -> dict:
    """Seek to the trailer, parse offset/length, read + json.loads the manifest."""
    fh.seek(0, os.SEEK_END)
    file_size = fh.tell()
    if file_size < HEADER_SIZE + TRAILER_SIZE:
        raise ValueError("File too small to be a valid .szip archive")

    fh.seek(file_size - TRAILER_SIZE)
    trailer = fh.read(TRAILER_SIZE)
    manifest_offset, manifest_length = struct.unpack("<QQ", trailer)

    fh.seek(manifest_offset)
    manifest_bytes = fh.read(manifest_length)
    return json.loads(manifest_bytes.decode("utf-8"))


def decompress_folder(
    input_path:  Path,
    output_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    verify_checksums: bool = True,
) -> ArchiveResult:
    """
    Parse a .szip manifest, recreate the directory structure, decompress each
    entry with DECOMPRESS_FN[entry.engine], and verify its sha256.
    """
    input_path = input_path.resolve()
    t0 = time.perf_counter()

    if not input_path.exists():
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=f"File not found: {input_path}",
        )

    try:
        with open(input_path, "rb") as fh:
            magic = fh.read(4)
            if magic != MAGIC:
                return ArchiveResult(
                    input_path=input_path, output_path=Path(""),
                    success=False,
                    error="Not a valid .szip file (bad magic bytes)",
                )
            (version,) = struct.unpack("<H", fh.read(2))
            if version != FORMAT_VERSION:
                return ArchiveResult(
                    input_path=input_path, output_path=Path(""),
                    success=False,
                    error=f"Unsupported .szip format version: {version}",
                )

            manifest = _read_manifest(fh)
            entries = manifest.get("entries", [])
            root_name = manifest.get("root_name", input_path.stem)

            if output_path is None:
                output_path = input_path.parent / root_name
            elif output_path.is_dir():
                # Given an existing directory to extract "into" (matching
                # compressor.decompress()'s convention for a dir output_path)
                # -> nest under a subfolder named after the archive root,
                # rather than dumping contents flatly into it.
                output_path = output_path / root_name

            dest_conflict = (
                output_path.is_dir() and any(output_path.iterdir())
            ) or (output_path.exists() and not output_path.is_dir())
            if dest_conflict:
                return ArchiveResult(
                    input_path=input_path, output_path=output_path,
                    success=False,
                    error=f"Destination already exists: {output_path}",
                )

            output_path.mkdir(parents=True, exist_ok=True)

            file_entries = [e for e in entries if e["type"] == "file"]
            total_files = len(file_entries)
            file_count = 0
            dir_count = 0
            skipped = []
            total_input_size = 0
            total_output_size = 0

            for entry in entries:
                dest = output_path / entry["path"]

                if entry["type"] == "dir":
                    dest.mkdir(parents=True, exist_ok=True)
                    dir_count += 1
                    continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                fh.seek(entry["offset"])
                raw = fh.read(entry["compressed_size"])

                if entry["engine"] == STORE_ENGINE:
                    data = raw
                else:
                    data = DECOMPRESS_FN[entry["engine"]](raw)

                if verify_checksums:
                    actual_hash = hashlib.sha256(data).hexdigest()
                    if actual_hash != entry["sha256"]:
                        return ArchiveResult(
                            input_path=input_path, output_path=output_path,
                            success=False,
                            error=f"Checksum mismatch for '{entry['path']}' — archive may be corrupted",
                        )

                dest.write_bytes(data)
                if entry.get("mtime"):
                    try:
                        os.utime(dest, (entry["mtime"], entry["mtime"]))
                    except OSError:
                        pass

                file_count += 1
                total_input_size += entry["original_size"]
                total_output_size += len(data)

                if progress_cb:
                    progress_cb(file_count, total_files, entry["path"])

    except Exception as e:
        return ArchiveResult(
            input_path=input_path, output_path=output_path or Path(""),
            success=False, error=f"Failed to read archive: {e}",
        )

    elapsed = time.perf_counter() - t0
    ratio = total_input_size / total_output_size if total_output_size > 0 else 0.0

    return ArchiveResult(
        input_path=input_path,
        output_path=output_path,
        file_count=file_count,
        dir_count=dir_count,
        skipped=skipped,
        total_input_size=total_input_size,
        total_output_size=total_output_size,
        ratio=ratio,
        elapsed=elapsed,
        success=True,
        error=None,
    )


# ---------------------------------------------------------------------------
# Dry-run preview (profile + select + predict, no compression)
# ---------------------------------------------------------------------------

def preview_folder(
    input_path:  Path,
    constraints: list = None,          # type: ignore
    db_path:     Optional[Path] = None,
) -> dict:
    """
    Walk + profile + select + predict per file WITHOUT compressing.
    Returns an aggregated dict for UI display before the user commits.
    """
    if constraints is None:
        constraints = []

    input_path = input_path.resolve()
    entries = list(iter_folder_entries(input_path))

    file_count = 0
    dir_count = 0
    skipped = []
    total_input_size = 0
    total_predicted_output = 0
    total_predicted_time = 0.0
    confidence_scores = []
    confidence_weights = []
    engine_breakdown = {}

    CONF_SCORE = {"high": 2, "medium": 1, "low": 0}
    CONF_LABEL = {2: "high", 1: "medium", 0: "low"}

    for abs_path, rel, is_dir, is_symlink in entries:
        if is_symlink:
            skipped.append((rel, "symlink (not followed)"))
            continue
        if is_dir:
            dir_count += 1
            continue

        try:
            size = abs_path.stat().st_size
        except OSError as e:
            skipped.append((rel, f"stat error: {e}"))
            continue

        file_count += 1
        total_input_size += size

        engine, level = _select_for_entry(abs_path, size, constraints, db_path)
        engine_breakdown[engine] = engine_breakdown.get(engine, 0) + 1

        pred = predict(abs_path, engine, level, db_path) if engine != STORE_ENGINE else None
        if pred:
            predicted_output = size / pred.predicted_ratio if pred.predicted_ratio > 0 else size
            total_predicted_output += predicted_output
            total_predicted_time += pred.predicted_compress_time
            score = CONF_SCORE.get(pred.confidence, 0)
        else:
            total_predicted_output += size
            score = CONF_SCORE["low"]

        confidence_scores.append(score)
        confidence_weights.append(size)

    if confidence_weights and sum(confidence_weights) > 0:
        weighted_score = sum(s * w for s, w in zip(confidence_scores, confidence_weights)) / sum(confidence_weights)
        aggregate_confidence = CONF_LABEL[round(weighted_score)]
    else:
        aggregate_confidence = "low"

    aggregate_ratio = (
        total_input_size / total_predicted_output if total_predicted_output > 0 else 0.0
    )

    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "skipped": skipped,
        "total_input_size": total_input_size,
        "predicted_output_size": total_predicted_output,
        "predicted_ratio": aggregate_ratio,
        "predicted_compress_time": total_predicted_time,
        "confidence": aggregate_confidence,
        "engine_breakdown": engine_breakdown,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Smart folder archiving — .szip with per-file engine selection"
    )
    parser.add_argument("path", type=Path, help="Folder to compress, or .szip file to extract")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output path")
    parser.add_argument("--decompress", "-d", action="store_true", help="Extract a .szip archive")
    parser.add_argument("--db", type=Path, default=None, help="Path to benchmark.db")

    args = parser.parse_args()
    path = args.path.resolve()

    if not path.exists():
        print(f"[ERROR] Path not found: {path}")
        return

    if args.decompress:
        print(f"\nExtracting {path.name}...")
        result = decompress_folder(path, args.output)
        print(result.summary())
        return

    print(f"\nArchiving {path}...")
    result = compress_folder(path, args.output, db_path=args.db)
    print(result.summary())


if __name__ == "__main__":
    main()
