# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

ROOT = Path(SPECPATH)
APP_NAME = "PDFDocuEdit Pro"
MAC_ICON = ROOT / "build_assets" / "icon.icns"
_win_icon_alt = ROOT / "icon_2.ico"
WIN_ICON = _win_icon_alt if _win_icon_alt.exists() else ROOT / "icon.ico"
WIN_VERSION = ROOT / "installer" / "PDFDocuEditPro.version.txt"

datas = [
    (str(ROOT / "splash.png"), "."),
    (str(ROOT / "icon.ico"), "."),
    (str(ROOT / "icon.png"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
if _win_icon_alt.exists():
    datas.append((str(_win_icon_alt), "."))
datas.extend(
    (str(path), "App_icon")
    for path in sorted(ROOT.joinpath("App_icon").iterdir())
    if path.suffix.casefold() in {".png", ".svg"}
)

# Bundle the complete Ghostscript distribution (Windows binaries ship in the
# repository) so PostScript conversion works on machines without Ghostscript.
_GS_ROOT = ROOT / "Ghostscript"
for _rel in ("bin", "lib", "Resource", "iccprofiles"):
    _src = _GS_ROOT / _rel
    if _src.is_dir():
        for _file in _src.rglob("*"):
            if _file.is_file() and _file.suffix.casefold() != ".lib":
                # Destination must be the parent directory: PyInstaller treats
                # file-shaped destinations as directories and nests the file
                # inside a same-named folder (observed with 6.14.2 on Windows).
                datas.append((str(_file), f"ghostscript/{_file.relative_to(_GS_ROOT).parent}"))

# OCR is a Windows x64 bundled-only capability. Release builds must contain
# the pinned Tesseract 5.5.3 runtime, both language files, the PDF config, and
# its dependent DLLs. Missing assets are a build error rather than a runtime
# fallback to an arbitrary system installation.
_TESS_ROOT = ROOT / "Tesseract"
if sys.platform == "win32":
    _tess_required = (
        _TESS_ROOT / "tesseract.exe",
        _TESS_ROOT / "tessdata" / "eng.traineddata",
        _TESS_ROOT / "tessdata" / "chi_tra.traineddata",
        _TESS_ROOT / "tessdata" / "configs" / "pdf",
        _TESS_ROOT / "BUNDLE_INFO.json",
    )
    _tess_missing = [str(path.relative_to(ROOT)) for path in _tess_required if not path.is_file()]
    if not list(_TESS_ROOT.glob("*.dll")):
        _tess_missing.append("Tesseract/*.dll")
    if _tess_missing:
        raise RuntimeError(
            "Bundled Tesseract 5.5.3 assets are incomplete: "
            + ", ".join(_tess_missing)
        )
    for _file in _TESS_ROOT.rglob("*"):
        if _file.is_file():
            datas.append(
                (str(_file), f"tesseract/{_file.relative_to(_TESS_ROOT).parent}")
            )

# PDF/A and PDF/UA validation is fully offline. Both supported platforms ship
# the pinned veraPDF Greenfield distribution and its private Temurin JRE.
_VERA_ROOT = ROOT / "VeraPDF"
_vera_windows = sys.platform == "win32"
_vera_required = (
    _VERA_ROOT / ("verapdf.bat" if _vera_windows else "verapdf"),
    _VERA_ROOT / "jre" / "bin" / ("java.exe" if _vera_windows else "java"),
    _VERA_ROOT / "BUNDLE_INFO.json",
)
_vera_missing = [
    str(path.relative_to(ROOT)) for path in _vera_required if not path.is_file()
]
if _vera_missing:
    raise RuntimeError(
        "Bundled veraPDF/Temurin assets are incomplete: "
        + ", ".join(_vera_missing)
    )
for _file in _VERA_ROOT.rglob("*"):
    if _file.is_file():
        datas.append((str(_file), f"verapdf/{_file.relative_to(_VERA_ROOT).parent}"))

# pyzbar ships the zbar native library as DLLs inside its package on Windows.
binaries = []
try:
    import pyzbar as _pyzbar

    _pkg = Path(_pyzbar.__file__).resolve().parent
    binaries.extend((str(path), "pyzbar") for path in _pkg.glob("*.dll"))
except Exception:
    pass

_hiddenimports = [
    "PyQt6.QtSvg",
    "PyQt6.QtPrintSupport",
    "fitz",
    "pdf2docx",
    "openpyxl",
    "xlrd",
    "PIL",
    "pyzbar.pyzbar",
    "docx",
    "lxml",
    "cv2",
    "numpy",
    "fontTools",
]
if sys.platform == "win32":
    # Microsoft Office COM backend for Office-to-PDF conversion.
    _hiddenimports += ["comtypes", "comtypes.client"]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep builds deterministic even when they run in a broad Conda environment.
    # None of these optional pandas/test/notebook integrations are used by the app.
    excludes=[
        "PyQt5",
        "tkinter",
        "pandas",
        "pandas.tests",
        "pandas._testing",
        "pandas.testing",
        "pandas.plotting",
        "pytest",
        "IPython",
        "matplotlib",
        "scipy",
        "torch",
        "sympy",
        "sphinx",
        "docutils",
        "jedi",
        "notebook",
        "jupyterlab",
        "nbformat",
        "black",
        "pyarrow",
        "fsspec",
        "tables",
        "panel",
        "plotly",
        "skimage",
        "statsmodels",
        "patsy",
        "intake",
        "sklearn",
        "tensorflow",
        "distributed",
        "dask",
        "numba",
        "llvmlite",
        "xarray",
        "boto3",
        "botocore",
        "bokeh",
        "sqlalchemy",
        "pygame",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",
    target_arch=None,
    codesign_identity=os.environ.get("PDFDOCUEDIT_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
    icon=str(WIN_ICON) if sys.platform == "win32" and WIN_ICON.exists() else None,
    version=(
        str(WIN_VERSION)
        if sys.platform == "win32" and WIN_VERSION.exists()
        else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(MAC_ICON) if MAC_ICON.exists() else None,
        bundle_identifier="com.pdfdocuedit.pro",
        version="2.1.0",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "2.1",
            "CFBundleVersion": "210",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "PDF document",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["com.adobe.pdf"],
                    "CFBundleTypeExtensions": ["pdf"],
                },
                {
                    "CFBundleTypeName": "PostScript document",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["com.adobe.postscript"],
                    "CFBundleTypeExtensions": ["ps", "eps"],
                },
            ],
        },
    )
