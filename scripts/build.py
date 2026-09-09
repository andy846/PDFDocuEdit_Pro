"""Reproducible platform-native build and installer entry point."""

from __future__ import annotations

import argparse
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
VERSION = "2.5.5"
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
    print("OCR is not bundled in the macOS build.")
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
    purge_suffixes = {".pyc", ".pyo", ".log", ".tmp", ".bak"}
    for dirpath, dirnames, filenames in os.walk(tree, topdown=False):
        for name in filenames:
            full = Path(dirpath) / name
            if full.suffix.casefold() in purge_suffixes:
                full.unlink(missing_ok=True)
        for name in list(dirnames):
            if name in purge_dirs:
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


def _find_inno_setup_compiler() -> str | None:
    """Locate Inno Setup even when its standard install folder is not on PATH."""
    compiler = shutil.which("ISCC.exe") or shutil.which("iscc")
    if compiler:
        return compiler
    program_roots = (
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
    )
    for root in program_roots:
        if not root:
            continue
        candidate = Path(root) / "Inno Setup 6" / "ISCC.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _windows_signing_settings() -> tuple[str, str, str] | None:
    """Return Authenticode settings, failing fast on partial configuration."""
    signtool = os.environ.get("PDFDOCUEDIT_SIGNTOOL")
    certificate = os.environ.get("PDFDOCUEDIT_CERT_SHA1")
    if bool(signtool) != bool(certificate):
        raise RuntimeError(
            "Set both PDFDOCUEDIT_SIGNTOOL and PDFDOCUEDIT_CERT_SHA1, "
            "or leave both unset."
        )
    if not signtool or not certificate:
        return None
    timestamp_url = os.environ.get(
        "PDFDOCUEDIT_TIMESTAMP_URL", "http://timestamp.digicert.com"
    )
    return signtool, certificate, timestamp_url


def _sign_windows_file(path: Path, settings: tuple[str, str, str]) -> None:
    signtool, certificate, timestamp_url = settings
    run(
        signtool,
        "sign",
        "/sha1",
        certificate,
        "/fd",
        "SHA256",
        "/tr",
        timestamp_url,
        "/td",
        "SHA256",
        "/d",
        APP_NAME,
        str(path),
    )


def _inno_signing_args(settings: tuple[str, str, str] | None) -> list[str]:
    """Configure ISCC to sign Setup and its embedded uninstaller."""
    if settings is None:
        return []
    signtool, certificate, timestamp_url = settings
    name = "pdfdocuedit_authenticode"
    command = (
        f"$q{signtool}$q sign /sha1 {certificate} /fd SHA256 "
        f"/tr {timestamp_url} /td SHA256 /d $q{APP_NAME}$q $f"
    )
    return [f"/S{name}={command}", f"/DMySignTool={name}"]


def build_windows(*, portable_only: bool = False) -> tuple[Path | None, Path]:
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
    signing = _windows_signing_settings()
    executable = ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
    if signing:
        _sign_windows_file(executable, signing)
    portable = build_portable_zip()
    if portable_only:
        return None, portable
    compiler = _find_inno_setup_compiler()
    if not compiler:
        raise RuntimeError(
            "Inno Setup 6 (ISCC.exe) is required to build the installer."
        )
    run(compiler, *_inno_signing_args(signing), "installer/PDFDocuEditPro.iss")
    output = ROOT / "release" / f"PDFDocuEdit-Pro-v{VERSION}-Setup-Windows-x64.exe"
    sha256(output)
    return output, portable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-only", action="store_true", help="Build Windows ZIP without Inno Setup")
    args = parser.parse_args(argv or [])
    if sys.version_info[:2] != (3, 12):
        current = ".".join(map(str, sys.version_info[:3]))
        raise RuntimeError(
            "PDFDocuEdit Pro build requires Python 3.12.x. "
            f"Current interpreter: {current}"
        )
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
        "updates",
        "launcher.py",
    )
    test_environment = os.environ.copy()
    test_environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    run(sys.executable, "-m", "pytest", env=test_environment)
    system = platform.system()
    if system == "Darwin":
        output = build_macos()
        print(f"Created {output}")
    elif system == "Windows":
        setup_exe, portable_zip = build_windows(portable_only=True) if args.portable_only else build_windows()
        if setup_exe is not None:
            print(f"Created {setup_exe}")
        print(f"Created {portable_zip}")
    else:
        raise RuntimeError("Release builds are supported only on Windows and macOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
