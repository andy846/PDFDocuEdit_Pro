"""Provision the pinned offline veraPDF and private Java release bundle."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "build_assets" / "verapdf"
MANIFEST = ASSETS / "BUNDLE_INFO.json"
TEMPLATE = ASSETS / "auto-install.xml"
TARGET = ROOT / "VeraPDF"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, expected: str) -> None:
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, destination)
    actual = _sha256(destination)
    if actual.casefold() != expected.casefold():
        raise RuntimeError(
            f"Checksum mismatch for {destination.name}: {actual} != {expected}"
        )


def _platform_key() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows-x64"
    if system == "Darwin":
        machine = platform.machine().casefold()
        return "macos-arm64" if machine in {"arm64", "aarch64"} else "macos-x64"
    raise RuntimeError("veraPDF release bundles are supported only on Windows/macOS.")


def _locate_java(root: Path) -> Path:
    name = "java.exe" if platform.system() == "Windows" else "java"
    matches = sorted(root.glob(f"**/bin/{name}"))
    if not matches:
        raise FileNotFoundError(f"{name} was not found in the verified JRE archive.")
    return matches[0]


def _smoke_test(target: Path, expected_version: str) -> None:
    windows = platform.system() == "Windows"
    launcher = target / ("verapdf.bat" if windows else "verapdf")
    java_home = target / "jre"
    environment = os.environ.copy()
    environment["JAVA_HOME"] = str(java_home)
    environment["PATH"] = (
        str(java_home / "bin") + os.pathsep + environment.get("PATH", "")
    )
    command = (
        ["cmd.exe", "/d", "/s", "/c", str(launcher), "--version"]
        if windows
        else [str(launcher), "--version"]
    )
    result = subprocess.run(
        command,
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode or expected_version not in output:
        raise RuntimeError(
            f"veraPDF offline smoke test failed ({result.returncode}): {output}"
        )


def provision() -> Path:
    if TARGET.exists():
        raise RuntimeError(
            f"Refusing to overwrite existing bundle: {TARGET}. "
            "Move it aside explicitly before reprovisioning."
        )
    metadata = json.loads(MANIFEST.read_text(encoding="utf-8"))
    runtime = metadata["java_runtimes"][_platform_key()]
    installer = metadata["verapdf_installer"]

    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-verapdf-") as folder:
        work = Path(folder)
        installer_archive = work / "verapdf-installer.zip"
        java_suffix = ".zip" if runtime["url"].endswith(".zip") else ".tar.gz"
        java_archive = work / f"temurin-jre{java_suffix}"
        _download(installer["url"], installer_archive, installer["sha256"])
        _download(runtime["url"], java_archive, runtime["sha256"])

        installer_dir = work / "installer"
        java_dir = work / "java"
        shutil.unpack_archive(installer_archive, installer_dir)
        shutil.unpack_archive(java_archive, java_dir)
        java = _locate_java(java_dir)
        jars = sorted(installer_dir.glob("**/verapdf-izpack-installer-*.jar"))
        if len(jars) != 1:
            raise RuntimeError("Expected exactly one veraPDF IzPack installer.")
        response = work / "auto-install.xml"
        response.write_text(
            TEMPLATE.read_text(encoding="utf-8").replace(
                "@INSTALL_PATH@", html.escape(str(TARGET))
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [str(java), "-jar", str(jars[0]), str(response)],
            cwd=ROOT,
            check=True,
            timeout=300,
        )
        java_home = java.parent.parent
        shutil.copytree(java_home, TARGET / "jre")
        shutil.copy2(MANIFEST, TARGET / "BUNDLE_INFO.json")

    _smoke_test(TARGET, metadata["verapdf_version"])
    print(f"Provisioned verified offline bundle: {TARGET}")
    return TARGET


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision the pinned offline veraPDF + Temurin bundle."
    )
    parser.parse_args()
    provision()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
