"""
registration.py
Writes/removes HKCU\\Software\\Classes context-menu entries for
"Compress with Anti Matter" / "Extract with Anti Matter". HKCU only — no
admin elevation required.
"""
import sys
import winreg
from pathlib import Path

from paths import get_app_root

APP_NAME = "AntiMatter"
DISPLAY_NAME = "Anti Matter"
SZIP_EXT = ".szip"
SZIP_PROGID = "AntiMatter.szip.1"
CLASSES_ROOT = "Software\\Classes"


def _exe_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None  # dev/unpackaged fallback — see _command_string


def _command_string(flag: str) -> str:
    exe = _exe_path()
    if exe is not None:
        return f'"{exe}" {flag} "%1"'
    main_py = get_app_root() / "main.py"
    return f'"{sys.executable}" "{main_py}" {flag} "%1"'


def _write_flat_entries(hive_subkey: str, entries: list) -> None:
    """entries: [(subkey_name, display_label, command_flag), ...]

    Registers each entry as its own top-level shell\\<subkey_name> verb,
    rather than nesting them under a cascading shell\\AntiMatter\\shell\\...
    SubCommands submenu. Windows 11's classic "Show more options" menu host
    has a known bug where cascading SubCommands submenus from HKCU
    registrations render as a dead ">" arrow with no flyout, even when the
    registry data is fully correct (verified directly against Explorer during
    development). Flat top-level entries are unaffected by that bug.
    """
    exe_str = str(_exe_path() or sys.executable)

    for subkey_name, label, flag in entries:
        item_key = f"{hive_subkey}\\shell\\{APP_NAME}{subkey_name}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, item_key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, label)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, f"{exe_str},0")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{item_key}\\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _command_string(flag))


def _delete_tree(root_subkey: str) -> None:
    """Recursively delete a key and all its subkeys (winreg has no built-in
    recursive delete — must walk children bottom-up)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_subkey) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(f"{root_subkey}\\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root_subkey)
    except FileNotFoundError:
        pass


def register() -> bool:
    try:
        _write_flat_entries(f"{CLASSES_ROOT}\\*", [
            ("Compress", "Compress with Anti Matter", "--context-compress"),
        ])
        _write_flat_entries(f"{CLASSES_ROOT}\\Directory", [
            ("Compress", "Compress with Anti Matter", "--context-compress"),
        ])
        _write_flat_entries(f"{CLASSES_ROOT}\\{SZIP_EXT}", [
            ("Compress", "Compress with Anti Matter", "--context-compress"),
            ("Extract",  "Extract with Anti Matter",  "--context-extract"),
        ])
        # optional polish: give .szip a ProgID/type description
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{CLASSES_ROOT}\\{SZIP_EXT}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, SZIP_PROGID)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{CLASSES_ROOT}\\{SZIP_PROGID}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Anti Matter Archive")
        print("[OK] Registered Anti Matter Explorer context-menu entries (HKCU).")
        return True
    except OSError as e:
        print(f"[ERROR] Registration failed: {e}")
        return False


def unregister() -> bool:
    try:
        _delete_tree(f"{CLASSES_ROOT}\\*\\shell\\{APP_NAME}Compress")
        _delete_tree(f"{CLASSES_ROOT}\\Directory\\shell\\{APP_NAME}Compress")
        _delete_tree(f"{CLASSES_ROOT}\\{SZIP_EXT}\\shell\\{APP_NAME}Compress")
        _delete_tree(f"{CLASSES_ROOT}\\{SZIP_EXT}\\shell\\{APP_NAME}Extract")
        # legacy cleanup: remove any leftover cascading-submenu registration
        # from before the flat-entry fix, in case an older version registered it
        _delete_tree(f"{CLASSES_ROOT}\\*\\shell\\{APP_NAME}")
        _delete_tree(f"{CLASSES_ROOT}\\Directory\\shell\\{APP_NAME}")
        _delete_tree(f"{CLASSES_ROOT}\\{SZIP_EXT}\\shell\\{APP_NAME}")
        _delete_tree(f"{CLASSES_ROOT}\\{SZIP_PROGID}")
        print("[OK] Removed Anti Matter Explorer context-menu entries.")
        return True
    except OSError as e:
        print(f"[ERROR] Unregistration failed: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage Anti Matter Explorer context-menu entries")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register", action="store_true")
    group.add_argument("--unregister", action="store_true")
    args = parser.parse_args()

    ok = register() if args.register else unregister()
    sys.exit(0 if ok else 1)
