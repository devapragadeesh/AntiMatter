"""
standard_formats.py

Interop with archive formats other tools already understand: zip, tar
(.tar/.tar.gz/.tar.bz2/.tar.xz), and rar (extract only — RAR's compressor is
proprietary, so no open-source library can create .rar files).

Unlike archiver.py's .szip, these formats don't go through the
profiler -> selector -> predictor pipeline: they use one fixed, well-known
algorithm for the whole archive, so there's nothing to profile or predict.
This module is the "compatibility" counterpart to archiver.py's "smart" one,
sharing its ArchiveResult return type so callers don't need per-format
branches.

Usage (standalone):
    python standard_formats.py path/to/folder --format zip
    python standard_formats.py path/to/archive.zip --decompress
"""

import os
import time
import zipfile
import tarfile
import argparse
from pathlib import Path
from typing import Optional, Callable

from .archiver import ArchiveResult, iter_folder_entries

try:
    import rarfile
except ImportError:
    rarfile = None


ZIP_COMPRESSION_METHODS = {
    "stored":  zipfile.ZIP_STORED,
    "deflate": zipfile.ZIP_DEFLATED,
    "bzip2":   zipfile.ZIP_BZIP2,
    "lzma":    zipfile.ZIP_LZMA,
}

TAR_MODES = {
    "gz":  "gz",
    "bz2": "bz2",
    "xz":  "xz",
}

TAR_SUFFIXES = {
    "gz":  ".tar.gz",
    "bz2": ".tar.bz2",
    "xz":  ".tar.xz",
}

# Magic bytes for sniffing, checked before falling back to extension.
_ZIP_MAGIC = b"PK\x03\x04"
_RAR_MAGIC = b"Rar!\x1a\x07"


class UnsupportedFormatError(Exception):
    pass


# ---------------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------------

def compress_to_zip(
    input_path:  Path,
    output_path: Optional[Path] = None,
    compression: str = "deflate",
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> ArchiveResult:
    """Compress a file or folder into a standard .zip archive."""
    input_path = input_path.resolve()
    t0 = time.perf_counter()

    if not input_path.exists():
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=f"Path not found: {input_path}",
        )

    method = ZIP_COMPRESSION_METHODS.get(compression)
    if method is None:
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False,
            error=f"Unknown zip compression '{compression}', expected one of {list(ZIP_COMPRESSION_METHODS)}",
        )

    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + ".zip") if input_path.is_file() \
            else input_path.with_suffix(".zip")
    elif output_path.is_dir():
        output_path = output_path / (input_path.name + ".zip")

    if input_path.is_dir():
        entries = [(a, r, d) for a, r, d, is_symlink in iter_folder_entries(input_path) if not is_symlink]
        file_entries = [e for e in entries if not e[2]]
        dir_entries = [e for e in entries if e[2]]
    else:
        file_entries = [(input_path, input_path.name, False)]
        dir_entries = []

    total_files = len(file_entries)
    total_input_size = 0
    skipped = []

    try:
        with zipfile.ZipFile(output_path, "w", compression=method) as zf:
            for _, rel, _ in dir_entries:
                zf.writestr(rel.rstrip("/") + "/", b"")

            for i, (abs_path, rel, _) in enumerate(file_entries):
                try:
                    zf.write(abs_path, arcname=rel)
                    total_input_size += abs_path.stat().st_size
                except Exception as e:
                    skipped.append((rel, f"write error: {e}"))
                if progress_cb:
                    progress_cb(i + 1, total_files, rel)
    except Exception as e:
        return ArchiveResult(
            input_path=input_path, output_path=output_path,
            success=False, error=f"Failed to write zip: {e}",
        )

    total_output_size = output_path.stat().st_size
    elapsed = time.perf_counter() - t0
    ratio = total_input_size / total_output_size if total_output_size > 0 else 0.0

    return ArchiveResult(
        input_path=input_path,
        output_path=output_path,
        file_count=len(file_entries),
        dir_count=len(dir_entries),
        skipped=skipped,
        total_input_size=total_input_size,
        total_output_size=total_output_size,
        ratio=ratio,
        elapsed=elapsed,
        success=True,
        error=None,
    )


# ---------------------------------------------------------------------------
# Tar (.tar.gz / .tar.bz2 / .tar.xz)
# ---------------------------------------------------------------------------

def compress_to_tar(
    input_path:  Path,
    output_path: Optional[Path] = None,
    compression: str = "gz",
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> ArchiveResult:
    """Compress a file or folder into a .tar.{gz,bz2,xz} archive."""
    input_path = input_path.resolve()
    t0 = time.perf_counter()

    if not input_path.exists():
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=f"Path not found: {input_path}",
        )

    mode = TAR_MODES.get(compression)
    if mode is None:
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False,
            error=f"Unknown tar compression '{compression}', expected one of {list(TAR_MODES)}",
        )

    suffix = TAR_SUFFIXES[compression]
    if output_path is None:
        base = input_path.name
        output_path = input_path.parent / (base + suffix)
    elif output_path.is_dir():
        output_path = output_path / (input_path.name + suffix)

    if input_path.is_dir():
        entries = [(a, r, d) for a, r, d, is_symlink in iter_folder_entries(input_path) if not is_symlink]
        file_entries = [e for e in entries if not e[2]]
        dir_entries = [e for e in entries if e[2]]
    else:
        file_entries = [(input_path, input_path.name, False)]
        dir_entries = []

    total_files = len(file_entries)
    total_input_size = 0
    skipped = []

    try:
        with tarfile.open(output_path, mode=f"w:{mode}") as tf:
            for _, rel, _ in dir_entries:
                info = tarfile.TarInfo(name=rel)
                info.type = tarfile.DIRTYPE
                tf.addfile(info)

            for i, (abs_path, rel, _) in enumerate(file_entries):
                try:
                    tf.add(abs_path, arcname=rel, recursive=False)
                    total_input_size += abs_path.stat().st_size
                except Exception as e:
                    skipped.append((rel, f"write error: {e}"))
                if progress_cb:
                    progress_cb(i + 1, total_files, rel)
    except Exception as e:
        return ArchiveResult(
            input_path=input_path, output_path=output_path,
            success=False, error=f"Failed to write tar archive: {e}",
        )

    total_output_size = output_path.stat().st_size
    elapsed = time.perf_counter() - t0
    ratio = total_input_size / total_output_size if total_output_size > 0 else 0.0

    return ArchiveResult(
        input_path=input_path,
        output_path=output_path,
        file_count=len(file_entries),
        dir_count=len(dir_entries),
        skipped=skipped,
        total_input_size=total_input_size,
        total_output_size=total_output_size,
        ratio=ratio,
        elapsed=elapsed,
        success=True,
        error=None,
    )


# ---------------------------------------------------------------------------
# Format sniffing
# ---------------------------------------------------------------------------

def _sniff_format(input_path: Path) -> str:
    """
    Identify an archive by magic bytes first, extension as fallback, so a
    renamed file still extracts correctly. Returns one of "zip", "rar", "tar".
    """
    try:
        with open(input_path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        head = b""

    if head.startswith(_ZIP_MAGIC):
        return "zip"
    if head.startswith(_RAR_MAGIC):
        return "rar"
    if tarfile.is_tarfile(input_path):
        return "tar"

    ext = input_path.suffix.lower()
    name = input_path.name.lower()
    if ext == ".zip":
        return "zip"
    if ext == ".rar":
        return "rar"
    if name.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")) or ext == ".tar":
        return "tar"

    raise UnsupportedFormatError(f"Could not identify archive format for: {input_path}")


# ---------------------------------------------------------------------------
# Extract (zip / tar / rar)
# ---------------------------------------------------------------------------

def list_archive_contents(input_path: Path) -> list:
    """Cheap peek at an archive's entries (name, size, is_dir) without extracting."""
    input_path = input_path.resolve()
    fmt = _sniff_format(input_path)

    entries = []
    if fmt == "zip":
        with zipfile.ZipFile(input_path) as zf:
            for info in zf.infolist():
                entries.append({
                    "path": info.filename,
                    "size": info.file_size,
                    "is_dir": info.is_dir(),
                })
    elif fmt == "tar":
        with tarfile.open(input_path) as tf:
            for member in tf.getmembers():
                entries.append({
                    "path": member.name,
                    "size": member.size,
                    "is_dir": member.isdir(),
                })
    elif fmt == "rar":
        _require_rarfile()
        with rarfile.RarFile(input_path) as rf:
            for info in rf.infolist():
                entries.append({
                    "path": info.filename,
                    "size": info.file_size,
                    "is_dir": info.is_dir(),
                })

    return entries


def _require_rarfile():
    """
    Raises UnsupportedFormatError if RAR extraction isn't actually usable.
    rarfile.RarFile() can open and even list a .rar's metadata without a
    working unrar/unar/bsdtar tool present (it only shells out to one when
    extracting file contents), so checking tool_setup() up front is the only
    way to catch a missing tool before extraction silently no-ops.
    """
    if rarfile is None:
        raise UnsupportedFormatError(
            "RAR support requires the 'rarfile' package (pip install rarfile) "
            "plus an unrar/unar/bsdtar tool available on PATH."
        )
    try:
        rarfile.tool_setup()
    except rarfile.RarCannotExec as e:
        raise UnsupportedFormatError(
            f"RAR extraction requires unrar, unar, or bsdtar on PATH: {e}"
        )


def extract_archive(
    input_path:  Path,
    output_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> ArchiveResult:
    """
    Extract a .zip, .tar(.gz/.bz2/.xz), or .rar archive to output_path
    (a directory; created if it doesn't exist). Format is sniffed from magic
    bytes, falling back to extension for edge cases sniffing can't resolve.
    """
    input_path = input_path.resolve()
    t0 = time.perf_counter()

    if not input_path.exists():
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=f"File not found: {input_path}",
        )

    try:
        fmt = _sniff_format(input_path)
    except UnsupportedFormatError as e:
        return ArchiveResult(
            input_path=input_path, output_path=Path(""),
            success=False, error=str(e),
        )

    if output_path is None:
        name = input_path.name
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if name.lower().endswith(suffix):
                name = name[: -len(suffix)]
                break
        else:
            name = input_path.stem
        output_path = input_path.parent / name
    elif output_path.is_dir() and any(output_path.iterdir()):
        output_path = output_path / input_path.stem

    output_path.mkdir(parents=True, exist_ok=True)

    total_input_size = input_path.stat().st_size
    file_count = 0
    dir_count = 0
    total_output_size = 0

    try:
        if fmt == "zip":
            with zipfile.ZipFile(input_path) as zf:
                members = zf.infolist()
                for i, info in enumerate(members):
                    zf.extract(info, path=output_path)
                    if info.is_dir():
                        dir_count += 1
                    else:
                        file_count += 1
                        total_output_size += info.file_size
                    if progress_cb:
                        progress_cb(i + 1, len(members), info.filename)

        elif fmt == "tar":
            with tarfile.open(input_path) as tf:
                members = tf.getmembers()
                tf.extractall(path=output_path, members=members, filter="data")
                for i, member in enumerate(members):
                    if member.isdir():
                        dir_count += 1
                    elif member.isfile():
                        file_count += 1
                        total_output_size += member.size
                    if progress_cb:
                        progress_cb(i + 1, len(members), member.name)

        elif fmt == "rar":
            _require_rarfile()
            with rarfile.RarFile(input_path) as rf:
                members = rf.infolist()
                for i, info in enumerate(members):
                    rf.extract(info, path=output_path)
                    if info.is_dir():
                        dir_count += 1
                    else:
                        file_count += 1
                        total_output_size += info.file_size
                    if progress_cb:
                        progress_cb(i + 1, len(members), info.filename)

    except Exception as e:
        return ArchiveResult(
            input_path=input_path, output_path=output_path,
            success=False, error=f"Failed to extract {fmt} archive: {e}",
        )

    elapsed = time.perf_counter() - t0
    ratio = total_output_size / total_input_size if total_input_size > 0 else 0.0

    return ArchiveResult(
        input_path=input_path,
        output_path=output_path,
        file_count=file_count,
        dir_count=dir_count,
        skipped=[],
        total_input_size=total_input_size,
        total_output_size=total_output_size,
        ratio=ratio,
        elapsed=elapsed,
        success=True,
        error=None,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Standard-format archiving — zip / tar.gz / tar.bz2 / tar.xz / rar (extract only)"
    )
    parser.add_argument("path", type=Path, help="File/folder to compress, or archive to extract")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output path")
    parser.add_argument("--decompress", "-d", action="store_true", help="Extract an archive")
    parser.add_argument(
        "--format", type=str, default="zip",
        choices=["zip", "tar.gz", "tar.bz2", "tar.xz"],
        help="Archive format to create (default: zip). Not used with --decompress.",
    )

    args = parser.parse_args()
    path = args.path.resolve()

    if not path.exists():
        print(f"[ERROR] Path not found: {path}")
        return

    if args.decompress:
        print(f"\nExtracting {path.name}...")
        result = extract_archive(path, args.output)
        print(result.summary())
        return

    print(f"\nCompressing {path} as {args.format}...")
    if args.format == "zip":
        result = compress_to_zip(path, args.output)
    else:
        compression = args.format.split(".", 1)[1]
        result = compress_to_tar(path, args.output, compression=compression)
    print(result.summary())


if __name__ == "__main__":
    main()
