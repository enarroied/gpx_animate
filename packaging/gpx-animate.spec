# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller spec for the frozen build.

Ships the windowed GUI (the recipient-facing artifact). The console CLI is
built from the same environment so the frozen render path can be exercised end
to end on Linux and on the Windows CI runner, neither of which can drive the
GUI head-first.

ffmpeg is deliberately NOT bundled: ``find_ffmpeg()`` prefers a copy beside the
program (``sys.frozen``), so the release folder carries a static ffmpeg next to
the exe — exactly the portable-folder model the application implements.

``copy_metadata("gpx-animate")`` makes ``gpx_animate.__version__`` resolve from
``importlib.metadata`` inside the frozen app, which is how the manifest version
stays the single source of truth.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

_SPEC_DIR = Path(SPECPATH)
_METADATA = copy_metadata("gpx-animate")
# rasterio loads GDAL data and C extensions (rasterio.serde, ...) by dynamic
# lookup the hooks miss; collect_all() drags in everything including the
# gdal-data directory, so a --tiff render works inside the frozen app.
_RASTERIO_DATAS, _RASTERIO_BINARIES, _RASTERIO_HIDDEN = collect_all("rasterio")

_gui = Analysis(
    [str(_SPEC_DIR / "frozen_gui.py")],
    pathex=[str(_SPEC_DIR.parent / "src")],
    binaries=_RASTERIO_BINARIES,
    datas=_METADATA + _RASTERIO_DATAS,
    hiddenimports=_RASTERIO_HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
_gui_pyz = PYZ(_gui.pure)
gui = EXE(
    _gui_pyz,
    _gui.scripts,
    _gui.binaries,
    _gui.datas,
    [],
    name="gpx-animate-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

_cli = Analysis(
    [str(_SPEC_DIR / "frozen_cli.py")],
    pathex=[str(_SPEC_DIR.parent / "src")],
    binaries=_RASTERIO_BINARIES,
    datas=_METADATA + _RASTERIO_DATAS,
    hiddenimports=_RASTERIO_HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
_cli_pyz = PYZ(_cli.pure)
cli = EXE(
    _cli_pyz,
    _cli.scripts,
    _cli.binaries,
    _cli.datas,
    [],
    name="gpx-animate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
