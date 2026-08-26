from __future__ import annotations

from pathlib import Path

from core.resources import APP_VERSION, COPYRIGHT_NOTICE

ROOT = Path(__file__).resolve().parent.parent
ACTIVE = [
    ROOT / "main.py",
    ROOT / "PDFdocuEdit_Pro.py",
    ROOT / "core",
    ROOT / "dialogs",
    ROOT / "ui",
    ROOT / "styles",
]
FORBIDDEN = (
    "PyQt5",
    "exec_",
    "QDesktopWidget",
    "tempfile.mktemp",
    "QThread.terminate",
    "os.startfile",
    "shell=True",
    "to be implemented",
)


def active_python_files():
    for location in ACTIVE:
        if location.is_file():
            yield location
        else:
            yield from location.rglob("*.py")


def test_active_source_uses_only_qt6_apis() -> None:
    violations = []
    for path in active_python_files():
        text = path.read_text(encoding="utf-8")
        violations.extend(
            f"{path.relative_to(ROOT)} contains {value}"
            for value in FORBIDDEN
            if value in text
        )
    assert not violations, "\n".join(violations)


def test_release_inputs_exist() -> None:
    required = (
        "PDFDocuEdit Pro.spec",
        "installer/PDFDocuEditPro.iss",
        "installer/PDFDocuEditPro.version.txt",
        "requirements-base.txt",
        "requirements-windows.txt",
        "requirements-macos.txt",
        "scripts/build.py",
        "scripts/prepare_verapdf.py",
        "build_assets/verapdf/BUNDLE_INFO.json",
        "build_assets/verapdf/auto-install.xml",
        "THIRD_PARTY_NOTICES.md",
    )
    assert not [value for value in required if not (ROOT / value).exists()]


def test_release_metadata_is_v2_1b() -> None:
    assert APP_VERSION == "2.1B"
    assert "Copyright © 2026 Andy Leung" in COPYRIGHT_NOTICE
    assert 'version = "2.1b0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '#define MyAppVersion "2.1B"' in (
        ROOT / "installer/PDFDocuEditPro.iss"
    ).read_text(encoding="utf-8")
    assert 'VERSION = "2.1B"' in (ROOT / "scripts/build.py").read_text(encoding="utf-8")
    assert "filevers=(2, 1, 0, 1)" in (
        ROOT / "installer/PDFDocuEditPro.version.txt"
    ).read_text(encoding="utf-8")


def test_windows_icon_uses_high_dpi_master_sizes() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "GetDpiForWindow" in source
    assert "round(32 * dpi / 96)" in source
    assert "128, 256" in source
