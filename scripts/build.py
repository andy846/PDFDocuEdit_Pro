"""Reproducible platform-native build and installer entry point."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "PDFDocuEdit Pro"
VERSION = "2.0"
VERAPDF_VERSION = "1.30.2"
VERAPDF_INSTALLER_SHA256 = (
    "6cc6341cb1af644044054b81f00a6590a7918abb18f762243de115258bcad838"
)


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env=env)


def sha256(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def build_macos() -> Path:
    validate_verapdf_bundle()
    run(sys.executable, "scripts/make_icns.py")
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "PDFDocuEdit Pro.spec",
    )
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
        run(
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(dmg),
        )
    notary_profile = os.environ.get("PDFDOCUEDIT_NOTARY_PROFILE")
    if notary_profile:
        run(
            "xcrun",
            "notarytool",
            "submit",
            str(dmg),
            "--keychain-profile",
            notary_profile,
            "--wait",
        )
        run("xcrun", "stapler", "staple", str(dmg))
    sha256(dmg)
    return dmg


def validate_tesseract_bundle() -> None:
    root = ROOT / "Tesseract"
    required = (
        root / "tesseract.exe",
        root / "tessdata" / "eng.traineddata",
        root / "tessdata" / "chi_tra.traineddata",
        root / "tessdata" / "configs" / "pdf",
        root / "BUNDLE_INFO.json",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if not list(root.glob("*.dll")):
        missing.append("Tesseract/*.dll")
    if missing:
        raise RuntimeError(
            "Bundled Tesseract 5.5.3 assets are incomplete: " + ", ".join(missing)
        )
    metadata = json.loads((root / "BUNDLE_INFO.json").read_text(encoding="utf-8"))
    if metadata.get("tesseract_version") != "5.5.3.20260724":
        raise RuntimeError(
            "Bundled Tesseract metadata is not pinned to 5.5.3.20260724."
        )
    version = subprocess.run(
        [str(root / "tesseract.exe"), "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    if not version or not version[0].startswith("tesseract v5.5.3"):
        raise RuntimeError("Bundled tesseract.exe is not version 5.5.3.")


def _verapdf_platform_key() -> str:
    if platform.system() == "Windows":
        return "windows-x64"
    machine = platform.machine().casefold()
    return "macos-arm64" if machine in {"arm64", "aarch64"} else "macos-x64"


def validate_verapdf_bundle() -> None:
    root = ROOT / "VeraPDF"
    windows = platform.system() == "Windows"
    launcher = root / ("verapdf.bat" if windows else "verapdf")
    java = root / "jre" / "bin" / ("java.exe" if windows else "java")
    metadata_path = root / "BUNDLE_INFO.json"
    required = (launcher, java, metadata_path)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(
            "Bundled veraPDF/Temurin assets are incomplete: " + ", ".join(missing)
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("verapdf_version") != VERAPDF_VERSION:
        raise RuntimeError(f"Bundled veraPDF must be pinned to {VERAPDF_VERSION}.")
    installer = metadata.get("verapdf_installer", {})
    if installer.get("sha256", "").casefold() != VERAPDF_INSTALLER_SHA256:
        raise RuntimeError("Bundled veraPDF installer checksum metadata is invalid.")
    runtime = metadata.get("java_runtimes", {}).get(_verapdf_platform_key(), {})
    if not runtime.get("version") or len(runtime.get("sha256", "")) != 64:
        raise RuntimeError("Bundled Temurin runtime metadata is incomplete.")
    environment = os.environ.copy()
    environment["JAVA_HOME"] = str(root / "jre")
    environment["PATH"] = (
        str(root / "jre" / "bin") + os.pathsep + environment.get("PATH", "")
    )
    command = (
        ["cmd.exe", "/d", "/s", "/c", str(launcher), "--version"]
        if windows
        else [str(launcher), "--version"]
    )
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    version_output = result.stdout + result.stderr
    if result.returncode or VERAPDF_VERSION not in version_output:
        raise RuntimeError(
            f"Bundled veraPDF {VERAPDF_VERSION} offline smoke test failed."
        )


def _clean_portable_tree(tree: Path) -> None:
    """Remove cache/temp/debug artefacts from a portable distribution tree."""
    purge_dirs = {"__pycache__", ".pytest_cache", ".ruff_cache", "tests", "test"}
    purge_suffixes = {".pyc", ".pyo", ".pyd", ".log", ".tmp", ".bak"}
    for dirpath, dirnames, filenames in os.walk(tree, topdown=False):
        for name in filenames:
            full = Path(dirpath) / name
            if full.suffix.casefold() in purge_suffixes:
                full.unlink(missing_ok=True)
        for name in list(dirnames):
            if name in purge_dirs or name.startswith("."):
                shutil.rmtree(Path(dirpath) / name, ignore_errors=True)


def build_portable_zip() -> Path:
    """Create the Portable ZIP from the PyInstaller ``dist`` folder."""
    dist_dir = ROOT / "dist" / APP_NAME
    if not dist_dir.is_dir():
        raise FileNotFoundError(
            f"PyInstaller output not found at {dist_dir}. Run PyInstaller first."
        )
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-portable-") as value:
        staging = Path(value) / APP_NAME
        shutil.copytree(dist_dir, staging)
        _clean_portable_tree(staging)
        release = ROOT / "release"
        release.mkdir(exist_ok=True)
        zip_path = release / f"PDFDocuEdit-Pro-v{VERSION}-Portable-Windows-x64.zip"
        shutil.make_archive(
            str(zip_path.with_suffix("")),
            "zip",
            root_dir=str(Path(value)),
            base_dir=APP_NAME,
        )
    sha256(zip_path)
    return zip_path


def build_windows() -> tuple[Path, Path]:
    validate_tesseract_bundle()
    validate_verapdf_bundle()
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "PDFDocuEdit Pro.spec",
    )
    portable = build_portable_zip()
    compiler = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not compiler:
        raise RuntimeError(
            "Inno Setup 6 (ISCC.exe) is required to build the installer."
        )
    run(compiler, "installer/PDFDocuEditPro.iss")
    output = ROOT / "release" / f"PDFDocuEdit-Pro-v{VERSION}-Setup-Windows-x64.exe"
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
            os.environ.get(
                "PDFDOCUEDIT_TIMESTAMP_URL", "http://timestamp.digicert.com"
            ),
            "/td",
            "SHA256",
            str(output),
        )
    sha256(output)
    return output, portable


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
        print(f"Created {output}")
    elif system == "Windows":
        setup_exe, portable_zip = build_windows()
        print(f"Created {setup_exe}")
        print(f"Created {portable_zip}")
    else:
        raise RuntimeError("Release builds are supported only on Windows and macOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
