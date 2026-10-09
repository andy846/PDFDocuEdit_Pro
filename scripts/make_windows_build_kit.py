"""Allowlisted Windows source/build runtime kit. Never enumerate local user state."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "release" / "PDFDocuEdit_Pro-Windows-build-kit.zip"

PRIVATE_PARTS = {"secret", ".update-keys", ".git", ".idea", "node_modules", "__pycache__",
                 "build", "dist", "release", ".pytest_cache", ".ruff_cache"}
PRIVATE_NAMES = {"config.json", "vc_config.json", "settings.json", "recent_files.json"}
RUNTIMES = ("Ghostscript/bin", "Ghostscript/lib", "Ghostscript/Resource", "Ghostscript/iccprofiles",
            "Tesseract", "VeraPDF", "build_assets/composition/fonts", "build_assets/composition/qpdf")


def _included(relative: Path) -> bool:
    return not (any(p.casefold() in PRIVATE_PARTS or p.casefold().startswith((".venv", ".env"))
                    for p in relative.parts) or
                relative.name.casefold() in PRIVATE_NAMES or
                relative.suffix.casefold() in {".pem", ".key", ".log", ".pyc", ".lib"} or
                relative.name.casefold().startswith(("launch_log", "launch_err")))


def allowed_files(root=ROOT, *, tracked=None):
    root = root.resolve()
    if tracked is None:
        raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        tracked = [Path(p.decode("utf-8")) for p in raw.split(b"\0") if p]
    candidates = {root / p for p in tracked}
    candidates.add(root / "Ghostscript/doc/COPYING")
    for relative in RUNTIMES:
        directory = root / relative
        if directory.is_symlink() or directory.is_junction():
            raise ValueError("Build runtime must not be a link.")
        if directory.exists():
            candidates.update(directory.rglob("*"))
    files = []
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if not _included(relative):
            continue
        if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents) if parent.is_relative_to(root)):
            raise ValueError("Build kit must not contain links.")
        if not path.resolve().is_relative_to(root):
            raise ValueError("Build kit path escaped the repository.")
        if path.is_file():
            files.append(path)
    return files


def main() -> int:
    files = allowed_files()
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    print(f"Packed {len(files)} allowlisted files -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
