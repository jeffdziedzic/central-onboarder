# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller onedir spec for the Central Onboarder GUI on Windows.
# Onedir (not onefile), mirroring the sibling AOS8-to-AOS10 Conversion
# Tool project's own spec-review decision (2026-08-18): no code-signing
# budget for field/partner laptop distribution, so a plain unzip-and-run
# folder + an expected AV-exception heads-up is the accepted tradeoff
# over building real installer/signing infrastructure.
#
# Build (from the repo root, with this project's venv active):
#   pip install ".[gui,windows-build]"
#   pyinstaller central_onboarder/gui/packaging/central-onboarder-gui-windows.spec
#
# Produces dist/Central Onboarder/Central Onboarder.exe.

from pathlib import Path

_PROJECT_ROOT = Path(SPECPATH).resolve().parents[2]  # central_onboarder/gui/packaging -> project root
_STATIC_DIR = _PROJECT_ROOT / "central_onboarder" / "gui" / "static"
_ASSETS_DIR = _PROJECT_ROOT / "central_onboarder" / "assets"

# Destination is relative to the frozen bundle's root (_MEIPASS in
# onedir mode - see app.py's _static_dir() for the matching read-side
# path math, and assets/__init__.py's importlib.resources helpers for
# the .xlsx/.md files) and preserves the central_onboarder/gui/static /
# central_onboarder/assets prefixes exactly, same reasoning as the
# sibling project's own spec.
datas = [
    (str(_STATIC_DIR), "central_onboarder/gui/static"),
    (str(_ASSETS_DIR / "device_list_template.xlsx"), "central_onboarder/assets"),
    (str(_ASSETS_DIR / "USER_GUIDE.md"), "central_onboarder/assets"),
    (str(_ASSETS_DIR / "CHANGELOG.md"), "central_onboarder/assets"),
]

a = Analysis(
    [str(_PROJECT_ROOT / "central_onboarder" / "gui" / "packaging" / "run_gui_windows.py")],
    pathex=[str(_PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    # pywebview's Windows backends are dynamically imported by name at
    # runtime (webview/guilib.py's initialize()) based on what's
    # actually installed - listed explicitly here so PyInstaller's
    # static analysis can't miss one the way it might miss a purely
    # dynamic import, same defensive reasoning as the sibling project's
    # own spec.
    hiddenimports=[
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "webview.platforms.mshtml",
        "clr_loader",
        "pythonnet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "PIL", "pygments.lexers"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Central Onboarder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Central Onboarder",
)
