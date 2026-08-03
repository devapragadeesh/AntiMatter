# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Anti Matter — onedir build.
Onedir (not onefile): a context-menu launch needs to feel instant, and
onefile re-extracts the whole bundle to a temp dir on every single launch.

Run from the repo root: pyinstaller packaging/AntiMatter.spec
"""
import os

REPO_ROOT = os.path.dirname(SPECPATH)  # packaging/ -> repo root

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, 'packaging', 'entrypoint.py')],
    pathex=[os.path.join(REPO_ROOT, 'src')],
    binaries=[],
    datas=[
        (os.path.join(REPO_ROOT, 'data', 'benchmark.db'), 'data'),
        (os.path.join(REPO_ROOT, 'packaging', 'assets', 'bg_loop.gif'), 'assets'),
    ],
    hiddenimports=['zstandard', 'lz4.frame', 'brotli', 'rarfile'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AntiMatter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, 'packaging', 'assets', 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AntiMatter',
)
