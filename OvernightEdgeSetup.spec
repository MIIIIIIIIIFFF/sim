# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(".").resolve()
datas = [
    (str(root / "dist" / "OvernightEdge.exe"), "."),
    (str(root / "LICENSE.txt"), "."),
    (str(root / "FOR_THE_BOSS.md"), "."),
]

a = Analysis(
    ["installer/install_gui.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    excludes=["torch", "tensorflow", "sklearn", "matplotlib", "scipy", "pandas", "numpy", "yfinance"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OvernightEdgeSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
