"""Reproducible platform-native build and installer entry point."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "PDFDocuEdit Pro"
VERSION = "1.1"


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env=env)


def sha256(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def build_macos() -> Path:
    run(sys.executable, "scripts/make_icns.py")
    run(sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "PDFDocuEdit Pro.spec")
    app = ROOT / "dist" / f"{APP_NAME}.app"
    if not app.exists():
        raise FileNotFoundError(app)
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    arch = platform.machine()
    dmg = release / f"PDFDocuEdit-Pro-{VERSION}-macOS-{arch}.dmg"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-dmg-") as value:
        staging = Path(value)
        shutil.copytree(app, staging / app.name, symlinks=True)
        os.symlink("/Applications", staging / "Applications")
        run("hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging), "-ov", "-format", "UDZO", str(dmg))
    notary_profile = os.environ.get("PDFDOCUEDIT_NOTARY_PROFILE")
    if notary_profile:
        run("xcrun", "notarytool", "submit", str(dmg), "--keychain-profile", notary_profile, "--wait")
        run("xcrun", "stapler", "staple", str(dmg))
    sha256(dmg)
    return dmg


def build_windows() -> Path:
    run(sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "PDFDocuEdit Pro.spec")
    compiler = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not compiler:
        raise RuntimeError("Inno Setup 6 (ISCC.exe) is required to build the installer.")
    run(compiler, "installer/PDFDocuEditPro.iss")
    output = ROOT / "release" / f"PDFDocuEdit-Pro-{VERSION}-Windows-x64-Setup.exe"
    signtool = os.environ.get("PDFDOCUEDIT_SIGNTOOL")
    certificate = os.environ.get("PDFDOCUEDIT_CERT_SHA1")
    if signtool and certificate:
        run(
            signtool,
            "sign",
            "/sha1",
            certificate,
            "/fd",
            "SHA256",
            "/tr",
            os.environ.get("PDFDOCUEDIT_TIMESTAMP_URL", "http://timestamp.digicert.com"),
            "/td",
            "SHA256",
            str(output),
        )
    sha256(output)
    return output


def main() -> int:
    if sys.version_info[:2] < (3, 11) or sys.version_info[:2] > (3, 13):
        raise RuntimeError("Builds must run with Python 3.11-3.13.")
    run(sys.executable, "scripts/verify_source.py")
    run(
        sys.executable,
        "-m",
        "ruff",
        "check",
        "main.py",
        "PDFdocuEdit_Pro.py",
        "core",
        "dialogs",
        "ui",
        "styles",
        "tests",
        "scripts",
    )
    test_environment = os.environ.copy()
    test_environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    run(sys.executable, "-m", "pytest", env=test_environment)
    system = platform.system()
    if system == "Darwin":
        output = build_macos()
    elif system == "Windows":
        output = build_windows()
    else:
        raise RuntimeError("Release builds are supported only on Windows and macOS.")
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
