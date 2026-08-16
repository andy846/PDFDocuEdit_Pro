from __future__ import annotations

from pathlib import Path

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
        violations.extend(f"{path.relative_to(ROOT)} contains {value}" for value in FORBIDDEN if value in text)
    assert not violations, "\n".join(violations)


def test_release_inputs_exist() -> None:
    required = (
        "PDFDocuEdit Pro.spec",
        "installer/PDFDocuEditPro.iss",
        "requirements-base.txt",
        "requirements-windows.txt",
        "requirements-macos.txt",
        "scripts/build.py",
        "THIRD_PARTY_NOTICES.md",
    )
    assert not [value for value in required if not (ROOT / value).exists()]
