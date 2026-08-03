"""
paths.py
Resolves paths relative to the application's real location, whether running
from source (`python main.py`) or as a PyInstaller-frozen onedir executable.
Stdlib-only — must be importable before any project-internal sys.path setup.
"""
import sys
from pathlib import Path


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
    return Path(__file__).parent


def ensure_on_path() -> None:
    root_str = str(APP_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


APP_ROOT = get_app_root()
DATA_DIR = get_data_root() / "data"
DEFAULT_DB_PATH = DATA_DIR / "benchmark.db"
ASSETS_DIR = get_data_root() / "assets"
