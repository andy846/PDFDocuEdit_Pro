"""Build signed update/deployment ZIPs without Inno Setup or administrator rights.

Run from the repository root with Python 3.12. Private keys never enter dist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from updates.protocol import (  # noqa: E402
    EXECUTABLE,
    LAUNCHER_VERSION,
    PRODUCT,
    Manifest,
    UpdateError,
    archive_members,
    atomic_json,
    digest_file,
    version,
)


def source_fingerprint() -> str:
    sources = [ROOT / "main.py", ROOT / "launcher.py", ROOT / "PDFDocuEdit Pro.spec", ROOT / "requirements-base.txt"]
    for name in ("core", "ui", "dialogs", "styles", "updates"):
        sources.extend((ROOT / name).rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(sources):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def keygen(path: Path) -> None:
    from updates.trust import PUBLIC_KEY_HEX

    if PUBLIC_KEY_HEX:
        raise UpdateError("A trust anchor already exists. Preserve its private key; do not rotate it implicitly.")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    with path.open("xb") as output:
        output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = key.public_key().public_bytes_raw().hex()
    trust = ROOT / "updates" / "trust.py"
    text = trust.read_text(encoding="utf-8")
    if 'PUBLIC_KEY_HEX = ""' not in text:
        raise UpdateError("Trust configuration is not empty.")
    trust.write_text(text.replace('PUBLIC_KEY_HEX = ""', f'PUBLIC_KEY_HEX = "{public}"'), encoding="utf-8")
    print(f"Created signing key at {path}. Back it up privately; only the public trust anchor belongs in Git.")


def build_launcher() -> Path:
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "Launcher", "--contents-directory", "launcher_runtime", "--icon", str(ROOT / "icon.ico"),
        "--copy-metadata", "cryptography", "--copy-metadata", "cffi", "--copy-metadata", "pycparser",
        "--specpath", str(ROOT / "build" / "launcher-spec"), str(ROOT / "launcher.py"),
    ], cwd=ROOT, check=True)
    from scripts.build import _sign_windows_file, _windows_signing_settings

    signing = _windows_signing_settings()
    if signing:
        _sign_windows_file(ROOT / "dist" / "Launcher" / "Launcher.exe", signing)
    return ROOT / "dist" / "Launcher"


def create_packages(dist: Path, launcher: Path, release: Path, app_version: str, key: Ed25519PrivateKey) -> list[Path]:
    from scripts.build import _clean_portable_tree

    for path in dist.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise UpdateError("Distribution must not contain links.")
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-update-package-") as temporary:
        clean = Path(temporary) / "application"
        shutil.copytree(dist, clean, symlinks=True)
        _clean_portable_tree(clean)
        return _create_packages(clean, launcher, release, app_version, key)


def _create_packages(dist: Path, launcher: Path, release: Path, app_version: str, key: Ed25519PrivateKey) -> list[Path]:
    version(app_version)
    from updates.trust import PUBLIC_KEY_HEX

    if key.public_key().public_bytes_raw().hex() != PUBLIC_KEY_HEX:
        raise UpdateError("Signing key does not match the embedded trust anchor.")
    if not (dist / EXECUTABLE).is_file() or not (launcher / "Launcher.exe").is_file():
        raise UpdateError("Build the editor and launcher before packaging.")
    release.mkdir(parents=True, exist_ok=True)
    zip_path = release / f"PDFDocuEdit-Pro-v{app_version}-Update-Windows-x64.zip"
    files = []
    forbidden_names = {"secret", "config.json", "vc_config.json", "settings.json"}
    for path in sorted(dist.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise UpdateError("Distribution must not contain links.")
        if path.is_file():
            if path.name.casefold() in forbidden_names or path.suffix.casefold() in {".pem", ".key", ".log"}:
                raise UpdateError(f"Private/local file found in distribution: {path.relative_to(dist)}")
            files.append(path)
    expanded = sum(path.stat().st_size for path in files)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(dist).as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        archive_members(archive, expanded)
    metadata = {
        "schema": 1, "product": PRODUCT, "platform": "windows-x64", "version": app_version,
        "min_launcher_version": LAUNCHER_VERSION, "asset": zip_path.name,
        "size": zip_path.stat().st_size, "expanded_size": expanded, "sha256": digest_file(zip_path),
    }
    raw = json.dumps(metadata, sort_keys=True, indent=2).encode("utf-8")
    signature = key.sign(raw)
    Manifest.verify(raw, signature, PUBLIC_KEY_HEX).verify_archive(zip_path)
    manifest_path, signature_path = release / "update.json", release / "update.sig"
    manifest_path.write_bytes(raw)
    signature_path.write_bytes(signature)
    deployment = release / f"PDFDocuEdit-Pro-v{app_version}-Managed-Portable-Windows-x64.zip"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-deployment-") as temporary:
        folder = Path(temporary) / PRODUCT
        shutil.copytree(launcher, folder)
        shutil.copytree(dist, folder / "versions" / app_version)
        (folder / "versions" / app_version / ".managed-update").write_text(app_version, encoding="utf-8")
        atomic_json(folder / "state.json", {"current": app_version, "previous": None, "phase": "stable"})
        (folder / "START-HERE.txt").write_text(
            "Extract this entire folder to %LOCALAPPDATA% or another approved writable location.\n"
            "Open Launcher.exe and create a desktop shortcut to it. Do not open a versioned EXE.\n"
            "Help > Check for Updates downloads signed updates without an installer.\n"
            "Never extract a deployment ZIP over an existing managed installation.\n", encoding="utf-8",
        )
        shutil.make_archive(str(deployment.with_suffix("")), "zip", temporary, PRODUCT)
    outputs = [zip_path, manifest_path, signature_path, deployment]
    for path in (zip_path, deployment):
        checksum = path.with_suffix(path.suffix + ".sha256")
        checksum.write_text(f"{digest_file(path)}  {path.name}\n", encoding="utf-8")
        outputs.append(checksum)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("keygen", "build"))
    parser.add_argument("--key", type=Path, default=ROOT / ".update-keys" / "signing.pem")
    parser.add_argument("--skip-build", action="store_true", help="Reuse a matching, already built application; rebuild launcher")
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.key)
        return 0
    from core.resources import APP_VERSION
    from updates.trust import PUBLIC_KEY_HEX

    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise UpdateError("Release builds require Windows x64 and Python 3.12.")
    key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw().hex() != PUBLIC_KEY_HEX:
        raise UpdateError("Private key does not match the embedded update public key.")
    fingerprint = source_fingerprint()
    build_info = {"version": APP_VERSION, "source_fingerprint": fingerprint}
    dist = ROOT / "dist" / "PDFDocuEdit Pro"
    if not args.skip_build:
        atomic_json(ROOT / "build_assets" / "update_build.json", build_info)
        subprocess.run([sys.executable, "scripts/build.py", "--portable-only"], cwd=ROOT, check=True)
    info_path = dist / "_internal" / "update_build.json"
    if not info_path.is_file() or json.loads(info_path.read_text(encoding="utf-8")) != build_info:
        raise UpdateError("Packaged application does not match this source tree. Build without --skip-build.")
    launcher = build_launcher()
    outputs = create_packages(dist, launcher, ROOT / "release", APP_VERSION, key)
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
