"""Bundle a clean copy of the project for the Windows build machine.

Produces ``release/PDFDocuEdit_Pro-Windows-build-kit.zip`` containing exactly
what scripts/build_windows.bat needs — and nothing else. macOS-only artifacts
(venv, builds, backups, Ghostscript docs) are excluded so the archive stays
small and copies quickly.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "release" / "PDFDocuEdit_Pro-Windows-build-kit.zip"

EXCLUDED_DIRS = {
    ".venv-pyqt6",
    ".venv",
    ".venv-build",
    "wheels",
    "build",
    "dist",
    "build_pyi_cache",
    "release",
    "backup",
    "PDFdocuEdit_Pro_backup",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    "staging_tmp",
    "node_modules",
}
EXCLUDED_FILES = {".DS_Store", "Thumbs.db", "VC_config.json"}
# The spec only bundles Ghostscript's runtime files; docs/examples stay out.
GHOSTSCRIPT_SKIP = {"doc", "examples", "App", "Other"}


def _included(relative: Path) -> bool:
    parts = relative.parts
    for part in parts:
        if part in EXCLUDED_DIRS:
            return False
    if relative.name in EXCLUDED_FILES:
        return False
    if "Ghostscript" in parts:
        index = parts.index("Ghostscript")
        if index + 1 < len(parts) and parts[index + 1] in GHOSTSCRIPT_SKIP:
            return False
        if relative.suffix.casefold() == ".lib":
            return False
    return True


def main() -> int:
    OUTPUT.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if not _included(relative):
                continue
            archive.write(path, relative)
            count += 1
    print(f"Packed {count} files -> {OUTPUT} ({OUTPUT.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
