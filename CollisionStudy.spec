# -*- mode: python ; coding: utf-8 -*-
#
# Fresh spec for the color-thresholding branch's CV pipeline (no YOLO --
# no .pt weights, no Puck_Training*/runs* data to bundle, unlike the old
# spec this replaces). Mirrors the known-working invocation recorded in
# the repo's old Notes.txt (since removed):
#
#   pyinstaller --name CollisionStudy --onedir --noconfirm --clean \
#     --console --collect-all PyQt6 --collect-binaries cv2 \
#     --add-data "gui.ui;." --add-data "Images;Images" initializer.py
#
# Build with: pyinstaller CollisionStudy.spec

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = [("gui.ui", "."), ("Images", "Images")]
binaries = collect_dynamic_libs("cv2")
hiddenimports = []

pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all("PyQt6")
datas += pyqt6_datas
binaries += pyqt6_binaries
hiddenimports += pyqt6_hiddenimports

a = Analysis(
    ["initializer.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CollisionStudy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CollisionStudy",
)
