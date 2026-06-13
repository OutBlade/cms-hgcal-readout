# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for HGCAL Lab.
# Run from the repo root:  pyinstaller app/hgcal_lab.spec

from pathlib import Path
import customtkinter as _ctk

SPEC_DIR  = Path(SPECPATH)        # app/
ROOT_DIR  = SPEC_DIR.parent       # repo root
CTK_PATH  = Path(_ctk.__file__).parent

a = Analysis(
    [str(SPEC_DIR / "hgcal_lab.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=[
        # customtkinter needs its entire package tree (themes, assets)
        (str(CTK_PATH), "customtkinter"),
        # Bundle analysis + data modules so the app runs without a checkout
        (str(ROOT_DIR / "analysis"), "analysis"),
        (str(ROOT_DIR / "data"),     "data"),
    ],
    hiddenimports=[
        # scipy sub-modules that PyInstaller misses
        "scipy.special._ufuncs",
        "scipy.special._ufuncs_cxx",
        "scipy.optimize._minpack2",
        "scipy._lib.messagestream",
        # matplotlib tk backend
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends._backend_tk",
        # PIL/Pillow tk glue
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "notebook", "jupyterlab"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="hgcal-lab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can trigger AV false positives; keep off
    console=False,      # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,   # native arch of the build host
    icon=None,
)
