"""
main.py
Entry point for ANTI MATTER.

Preferred (from the src/ folder):
    python -m antimatter --context-compress "C:\\path\\to\\file_or_folder"
    python -m antimatter --context-extract "C:\\path\\to\\archive.szip"
    python -m antimatter --register      (writes HKCU context-menu registry keys)
    python -m antimatter --unregister    (removes them)

Also runnable directly (e.g. an IDE's Run button on this file) — the
bootstrap block below re-execs it as `antimatter.main` so the package's
relative imports still resolve.
"""

if __name__ == "__main__" and __package__ in (None, ""):
    import sys
    from pathlib import Path
    src_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(src_dir))
    import antimatter.main
    antimatter.main.main()
    sys.exit()

import sys
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .ui.main_window import MainWindow
from .ui.styles import DARK_THEME


def parse_args(argv):
    parser = argparse.ArgumentParser(add_help=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--context-compress", type=Path, default=None, metavar="PATH",
        help="Launch GUI with PATH pre-staged on the Compress tab "
             "(used by the Explorer 'Compress with Anti Matter' entry)"
    )
    group.add_argument(
        "--context-extract", type=Path, default=None, metavar="PATH",
        help="Launch GUI with PATH pre-staged on the Decompress tab "
             "(used by the Explorer 'Extract with Anti Matter' entry)"
    )
    group.add_argument(
        "--register", action="store_true",
        help="Write Explorer context-menu registry entries (HKCU) and exit"
    )
    group.add_argument(
        "--unregister", action="store_true",
        help="Remove Explorer context-menu registry entries and exit"
    )
    # parse_known_args (not parse_args): don't fight Qt's own recognized flags
    return parser.parse_known_args(argv)[0]


def main():
    args = parse_args(sys.argv[1:])

    if args.register or args.unregister:
        from .registration import register, unregister
        ok = register() if args.register else unregister()
        sys.exit(0 if ok else 1)

    # enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Anti Matter")
    app.setOrganizationName("AntiMatter")

    # apply dark theme
    app.setStyleSheet(DARK_THEME)

    # default font
    font = QFont()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)

    initial_path = args.context_compress or args.context_extract
    initial_mode = "extract" if args.context_extract else ("compress" if args.context_compress else None)

    window = MainWindow(initial_path=initial_path, initial_mode=initial_mode)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
