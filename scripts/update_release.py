"""Build signed update/deployment ZIPs and a managed Inno Setup installer.

Run from the repository root with Python 3.12. Private keys never enter dist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    UpdateError,
    archive_members,
    atomic_json,
    digest_file,
    version,
)
from updates.target import DEFAULT_TARGET  # noqa: E402


def source_fingerprint() -> str:
    sources = [ROOT / "main.py", ROOT / "launcher.py", ROOT / "PDFDocuEdit Pro.spec", ROOT / "requirements-base.txt"]
    for extra in ("requirements-auth-windows.lock", "build_assets/auth/PROJECT.json"):
        if (ROOT / extra).is_file():
            sources.append(ROOT / extra)
    for name in ("auth", "core", "ui", "dialogs", "styles", "updates", "composition", "workflow", "scripts"):
        sources.extend((ROOT / name).rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(sources):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        # Native Windows/Mac checkouts can use CRLF/LF for the same Git blob.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
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


def build_launcher(*, target=None) -> Path:
    extra = []
    if target is not None:
        from dataclasses import asdict
        folder = ROOT / "build/launcher-target"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pdfdocuedit_update_build.py").write_text("TARGET = " + repr(asdict(target)) + "\n", encoding="utf-8")
        atomic_json(folder / "update-target.json", asdict(target))
        extra = ["--paths", str(folder), "--hidden-import", "pdfdocuedit_update_build",
                 "--add-data", str(folder / "update-target.json") + ";."]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "Launcher", "--contents-directory", "launcher_runtime", "--icon", str(ROOT / "icon.ico"),
        "--copy-metadata", "cryptography", "--copy-metadata", "cffi", "--copy-metadata", "pycparser",
        "--specpath", str(ROOT / "build" / "launcher-spec"), *extra, str(ROOT / "launcher.py"),
    ], cwd=ROOT, check=True)
    from scripts.build import _sign_windows_file, _windows_signing_settings

    signing = _windows_signing_settings()
    if signing:
        _sign_windows_file(ROOT / "dist" / "Launcher" / "Launcher.exe", signing)
    return ROOT / "dist" / "Launcher"


def create_packages(dist: Path, launcher: Path, release: Path, app_version: str, key: Ed25519PrivateKey | None, *, target=DEFAULT_TARGET) -> list[Path]:
    from scripts.build import _clean_portable_tree

    for path in dist.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise UpdateError("Distribution must not contain links.")
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-update-package-") as temporary:
        clean = Path(temporary) / "application"
        shutil.copytree(dist, clean, symlinks=True)
        _clean_portable_tree(clean)
        return _create_packages(clean, launcher, release, app_version, key, target=target)


def _create_packages(dist: Path, launcher: Path, release: Path, app_version: str, key: Ed25519PrivateKey, *, target=DEFAULT_TARGET) -> list[Path]:
    version(app_version)
    from updates.trust import PUBLIC_KEY_HEX

    if key is not None and key.public_key().public_bytes_raw().hex() != PUBLIC_KEY_HEX:
        raise UpdateError("Signing key does not match the embedded trust anchor.")
    if not (dist / EXECUTABLE).is_file() or not (launcher / "Launcher.exe").is_file():
        raise UpdateError("Build the editor and launcher before packaging.")
    from dataclasses import asdict
    if target.platform != "windows-x64":
        raise UpdateError("Use the Mac packager for Mac applications.")
    identity = dist / "_internal/update-target.json"
    if target.legacy:
        if identity.exists() and json.loads(identity.read_text()) != asdict(target):
            raise UpdateError("Cannot publish a private application as a public update.")
    else:
        for path in (identity, launcher / "launcher_runtime/update-target.json"):
            if not path.is_file() or json.loads(path.read_text()) != asdict(target):
                raise UpdateError("Application and launcher must match the private update identity.")
    release.mkdir(parents=True, exist_ok=True)
    zip_path = release / target.asset(app_version)
    files = []
    from scripts.distribution_safety import assert_public_distribution
    try:
        assert_public_distribution(dist)
    except ValueError as error:
        raise UpdateError(str(error)) from None
    for path in sorted(dist.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise UpdateError("Distribution must not contain links.")
        if path.is_file():
            files.append(path)
    expanded = sum(path.stat().st_size for path in files)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(dist).as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        archive_members(archive, expanded)
    metadata = {
        "schema": 1 if target.legacy else 2, "product": PRODUCT, "platform": "windows-x64", "version": app_version,
        "min_launcher_version": LAUNCHER_VERSION, "asset": zip_path.name,
        "size": zip_path.stat().st_size, "expanded_size": expanded, "sha256": digest_file(zip_path),
    }
    if not target.legacy:
        metadata.update(channel=target.channel, auth_project=target.auth_project)
    from scripts.release_signing import write_update_metadata
    manifest_path, signature_path = write_update_metadata(release, metadata, key)
    suffix = "-Private" if target.channel == "private" else ""
    deployment = release / f"PDFDocuEdit-Pro-v{app_version}-Managed-Portable-Windows-x64{suffix}.zip"
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


def create_legacy_auth_bridge(release, app_version, target, key=None):
    """Explicit schema-1 compatibility publication of the SAME private payload."""
    from dataclasses import asdict

    from scripts.release_signing import write_update_metadata
    if target.platform != "windows-x64" or target.channel != "private":
        raise UpdateError("Only account-enabled Windows releases may create a legacy bridge.")
    prefix = "" if key is not None else "candidate-"
    release = Path(release)
    data = json.loads((release / (prefix + target.metadata + ".json")).read_text(encoding="utf-8"))
    if (data.get("platform"), data.get("channel"), data.get("auth_project"), data.get("version")) != (
        target.platform, target.channel, target.auth_project, app_version
    ):
        raise UpdateError("Canonical account manifest identity differs.")
    original = release / target.asset(app_version)
    if original.stat().st_size != data["size"] or digest_file(original) != data["sha256"]:
        raise UpdateError("Canonical account payload differs from its manifest.")
    data.update(schema=1, asset=DEFAULT_TARGET.asset(app_version), application_target=asdict(target))
    data.pop("channel")
    data.pop("auth_project")
    alias = release / data["asset"]
    shutil.copyfile(original, alias)
    manifest, signature = write_update_metadata(release, data, key)
    checksum = alias.with_suffix(".zip.sha256")
    checksum.write_text(f"{data['sha256']}  {alias.name}\n", encoding="utf-8")
    return [alias, manifest, signature, checksum]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("keygen", "build"))
    parser.add_argument("--key", type=Path, default=ROOT / ".update-keys" / "signing.pem")
    parser.add_argument("--skip-build", action="store_true", help="Reuse a matching, already built application; rebuild launcher")
    parser.add_argument("--run-tests", action="store_true", help="Explicitly repeat the full suite locally")
    parser.add_argument("--private-auth", action="store_true", help="Build account-gated private updates; never a public installer")
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.key)
        return 0
    if args.skip_build and args.run_tests:
        parser.error("--run-tests requires a new build")
    from composition.enabled import is_enabled
    from core.resources import APP_VERSION
    from updates.trust import PUBLIC_KEY_HEX

    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise UpdateError("Release builds require Windows x64 and Python 3.12.")
    target = DEFAULT_TARGET
    if args.private_auth:
        from updates.target import UpdateTarget
        project = json.loads((ROOT / "build_assets/auth/PROJECT.json").read_text())
        target = UpdateTarget("windows-x64", "private", project["project_ref"])
        os.environ["PDFDOCUEDIT_BUILD_AUTH"] = "1"
    elif os.environ.get("PDFDOCUEDIT_BUILD_AUTH") == "1":
        raise UpdateError("Private builds require --private-auth; public packaging is blocked.")
    if int(APP_VERSION.split(".",1)[0])>=3 and not is_enabled():
        raise UpdateError("V3 release packages must enable Document Designer.")
    from scripts.release_signing import load_signing_key
    key = load_signing_key(args.key)
    if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw().hex() != PUBLIC_KEY_HEX:
        raise UpdateError("Private key does not match the embedded update public key.")
    fingerprint = source_fingerprint()
    # Persist exact release provenance alongside the source fingerprint. Only
    # build committed, reviewable trees; generated/ignored QA output is allowed.
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise UpdateError("Commit release source changes before building signed packages.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    build_info = {"version": APP_VERSION, "source_fingerprint": fingerprint,
                  "source_commit": commit, "composition_enabled": is_enabled()}
    dist = ROOT / "dist" / "PDFDocuEdit Pro"
    if not args.skip_build:
        atomic_json(ROOT / "build_assets" / "update_build.json", build_info)
        command = [sys.executable, "scripts/build.py", "--portable-only"]
        if args.run_tests:
            command.append("--run-tests")
        subprocess.run(command, cwd=ROOT, check=True)
    info_path = dist / "_internal" / "update_build.json"
    if not info_path.is_file() or json.loads(info_path.read_text(encoding="utf-8")) != build_info:
        raise UpdateError("Packaged application does not match this source tree. Build without --skip-build.")
    launcher = build_launcher(target=target if not target.legacy else None)
    outputs = create_packages(dist, launcher, ROOT / "release", APP_VERSION, key, target=target)
    if args.private_auth:
        outputs.extend(create_legacy_auth_bridge(ROOT / "release", APP_VERSION, target, key))
    from scripts.build_managed_installer import build_installer

    if target.legacy:
        installer = build_installer(outputs[3], APP_VERSION)
        outputs.extend((installer, installer.with_suffix(installer.suffix + ".sha256")))
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
