"""
paths.py
Resolves paths relative to the application's real location, whether running
from source or as a PyInstaller-frozen onedir executable.
"""
import sys
from pathlib import Path
from typing import Optional


def get_app_root() -> Path:
    """The exe's own install directory — used for locating the exe itself
    (e.g. registry command strings), NOT for bundled data files."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_data_root() -> Path:
    """Where bundled datas= files actually live at runtime. PyInstaller sets
    sys._MEIPASS for both onedir and onefile builds — for onedir (used here)
    it points at the app's _internal/ folder, which is where datas= entries
    are collected by default, NOT next to the exe itself."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", get_app_root()))
    # dev/source mode: repo root, three levels up from src/antimatter/paths.py
    return Path(__file__).parent.parent.parent


APP_ROOT = get_app_root()
DATA_DIR = get_data_root() / "data"
DEFAULT_DB_PATH = DATA_DIR / "benchmark.db"
ASSETS_DIR = get_data_root() / "packaging" / "assets"


def resolve_output_path(output_path: Optional[Path], default_path: Path) -> Path:
    """
    Resolve a user-supplied --output path against the tool's own default
    (default_path — already the correct full filename, e.g. input+ext).

    - None                      -> default_path
    - an existing directory     -> default_path.name written inside it
    - a path with no suffix     -> treated as a directory-to-be-created
                                    (even though it doesn't exist yet), with
                                    default_path.name written inside it
    - anything else             -> used verbatim as the destination file

    Without the no-suffix case, a --output folder that hasn't been created
    yet falls through as a literal file path, silently dropping the
    extension and overwriting itself on every call — that used to happen
    silently instead of creating the folder.
    """
    if output_path is None:
        resolved = default_path
    else:
        output_path = Path(output_path)
        treat_as_dir = output_path.is_dir() or output_path.suffix == ""
        if treat_as_dir:
            output_path.mkdir(parents=True, exist_ok=True)
            resolved = output_path / default_path.name
        else:
            resolved = output_path

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
