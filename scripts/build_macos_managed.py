"""Build a fixed Mac shell and platform/channel-bound update assets; no publish."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.distribution_safety import assert_public_distribution
from scripts.prepare_macos import require_arm64
from updates.macos import validate_app
from updates.macos_archive import write_bundle
from updates.protocol import LAUNCHER_VERSION, PRODUCT, Manifest, UpdateError, digest_file
from updates.target import UpdateTarget

ROOT = Path(__file__).resolve().parents[1]


def create_update(app, output, app_version, target, *, key=None, public_key=None):
    validate_app(app.parent, app_version, target)
    assert_public_distribution(app, allow_bundle_links=True)
    output.mkdir(parents=True, exist_ok=True)
    package = output / target.asset(app_version)
    expanded = write_bundle(app, package)
    metadata = {"schema": 2, "product": PRODUCT, **asdict(target), "version": app_version,
                "min_launcher_version": LAUNCHER_VERSION, "asset": package.name,
                "size": package.stat().st_size, "expanded_size": expanded, "sha256": digest_file(package)}
    raw = json.dumps(metadata, sort_keys=True, indent=2).encode()
    if key is not None:
        if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw().hex() != public_key:
            raise UpdateError("Mac signing key does not match the installed trust anchor.")
        signature = key.sign(raw)
        Manifest.verify(raw, signature, public_key, target=target).verify_archive(package)
        (output / (target.metadata + ".json")).write_bytes(raw)
        (output / (target.metadata + ".sig")).write_bytes(signature)
    else:
        # An internal candidate cannot masquerade as a signed downloadable update.
        (output / ("candidate-" + target.metadata + ".json")).write_bytes(raw)
    (package.with_suffix(".zip.sha256")).write_text(f"{digest_file(package)}  {package.name}\n")
    return package


def build_shell(app, target, app_version):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir", "--windowed",
                    "--name", "PDFDocuEdit Pro", "--icon", str(ROOT / "build_assets/icon.icns"),
                    "--copy-metadata", "cryptography", "--copy-metadata", "cffi", "--copy-metadata", "pycparser",
                    "--distpath", str(ROOT / "dist-mac-shell"), "--specpath", str(ROOT / "build/mac-shell-spec"),
                    str(ROOT / "mac_launcher.py")], cwd=ROOT, check=True)
    shell = ROOT / "dist-mac-shell/PDFDocuEdit Pro.app"
    resources = shell / "Contents/Resources"
    shutil.copytree(app, resources / "Initial.app", symlinks=True)
    (resources / "bootstrap.json").write_text(json.dumps({"version": app_version, "target": asdict(target)}), encoding="utf-8")
    path = shell / "Contents/Info.plist"
    with path.open("rb") as stream:
        info = plistlib.load(stream)
    info.update(CFBundleIdentifier=f"com.pdfdocuedit.pro.launcher.{target.channel}",
                CFBundleDisplayName="PDFDocuEdit Pro", CFBundleShortVersionString=app_version,
                CFBundleVersion=app_version, LSMinimumSystemVersion="13.0", NSHighResolutionCapable=True,
                LSUIElement=True)
    with (app / "Contents/Info.plist").open("rb") as stream:
        info["CFBundleDocumentTypes"] = plistlib.load(stream).get("CFBundleDocumentTypes", [])
    with path.open("wb") as stream:
        plistlib.dump(info, stream)
    identity = os.environ.get("PDFDOCUEDIT_CODESIGN_IDENTITY") or "-"
    command = ["/usr/bin/codesign", "--force", "--sign", identity]
    if identity != "-":
        command += ["--options", "runtime", "--timestamp"]
    subprocess.run([*command, str(shell)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(shell)], check=True)
    return shell


def main():
    require_arm64()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=ROOT / "dist/PDFDocuEdit Pro.app")
    parser.add_argument("--key", type=Path, help="Optional external Ed25519 signing key; never copied into the app")
    args = parser.parse_args()
    app = args.app.resolve()
    with (app / "Contents/Info.plist").open("rb") as stream:
        app_version = plistlib.load(stream)["CFBundleShortVersionString"]
    target = UpdateTarget(**json.loads((app / "Contents/Resources/update-target.json").read_text()))
    key = None
    if args.key:
        value = args.key.read_bytes()
        try:
            key = serialization.load_pem_private_key(value, password=None)
        except TypeError:
            key = serialization.load_pem_private_key(value, password=getpass.getpass("Signing-key password: ").encode())
    from updates.trust import PUBLIC_KEY_HEX
    output = ROOT / "release"
    package = create_update(app, output, app_version, target, key=key, public_key=PUBLIC_KEY_HEX)
    shell = build_shell(app, target, app_version)
    suffix = "-Private" if target.channel == "private" else ""
    dmg = output / f"PDFDocuEdit-Pro-v{app_version}-Managed-macOS-arm64{suffix}.dmg"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-managed-dmg-") as temporary:
        stage = Path(temporary)
        shutil.copytree(shell, stage / shell.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        subprocess.run(["hdiutil", "create", "-volname", "PDFDocuEdit Pro", "-srcfolder", str(stage),
                        "-ov", "-format", "UDZO", str(dmg)], check=True)
    profile = os.environ.get("PDFDOCUEDIT_NOTARY_PROFILE")
    if profile:
        subprocess.run(["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile", profile, "--wait"], check=True)
        subprocess.run(["xcrun", "stapler", "staple", str(dmg)], check=True)
    dmg.with_suffix(".dmg.sha256").write_text(f"{digest_file(dmg)}  {dmg.name}\n")
    print(package)
    print(dmg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
