"""Fail fast when the active application contains Qt5 APIs or missing resources."""

from __future__ import annotations

import sys
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
FORBIDDEN = {
    "PyQt5": "PyQt5 import",
    "exec_": "Qt5 exec_ API",
    "QDesktopWidget": "removed QDesktopWidget API",
    "tempfile.mktemp": "unsafe temporary-file API",
    "QThread.terminate": "unsafe thread termination",
    "os.startfile": "Windows-only shell API",
    "shell=True": "unsafe shell process launch",
    "to be implemented": "unfinished UI path",
}


def python_files():
    for location in ACTIVE:
        if location.is_file():
            yield location
        elif location.is_dir():
            yield from location.rglob("*.py")


def main() -> int:
    errors: list[str] = []
    for path in python_files():
        text = path.read_text(encoding="utf-8")
        for needle, label in FORBIDDEN.items():
            if needle in text:
                errors.append(f"{path.relative_to(ROOT)}: {label}")
    required = [
        ROOT / "main.py",
        ROOT / "splash.png",
        ROOT / "icon.ico",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "App_icon" / "Main_menu.png",
        ROOT / "App_icon" / "Search.png",
        ROOT / "App_icon" / "insert.png",
        ROOT / "App_icon" / "delete.png",
        ROOT / "Ghostscript" / "bin" / "gswin64c.exe",
    ]
    errors.extend(f"Missing resource: {path.relative_to(ROOT)}" for path in required if not path.exists())
    if sys.version_info[:2] < (3, 11) or sys.version_info[:2] > (3, 13):
        errors.append(f"Builds require Python 3.11-3.13; running {sys.version_info.major}.{sys.version_info.minor}")
    if errors:
        print("Source verification failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Source verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
