"""Build verified arm64 native dependencies; never runs on Windows.

Homebrew is a CI build-tool provider only. The resulting application has no
Homebrew runtime dependency. Runtime sources/versions are pinned separately.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "build_assets" / "macos"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def checked_source(entry, directory):
    archive = directory / ("source.tar.xz" if entry["url"].endswith(".xz") else "source.tar.gz")
    urllib.request.urlretrieve(entry["url"], archive)
    if digest(archive) != entry["sha256"]:
        raise RuntimeError("Native source checksum mismatch.")
    destination = directory / "source"
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise RuntimeError("Unexpected source archive layout.")
    return children[0]


def run(args, cwd, env):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)


def require_arm64():
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        raise RuntimeError("Mac native preparation requires an Apple Silicon macOS builder.")


def prepare():
    require_arm64()
    sources = json.loads((NATIVE / "SOURCES.json").read_text())
    env = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": "13.0"}
    env["PATH"] = "/opt/homebrew/opt/gettext/bin:" + env.get("PATH", "")
    jobs = str(min(4, os.cpu_count() or 2))
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-native-") as work:
        work = Path(work)
        for name, entry in sources["sources"].items():
            folder = work / name
            folder.mkdir()
            source = checked_source(entry, folder)
            prefix = NATIVE / name
            if prefix.exists():
                raise RuntimeError(f"Refusing to overwrite existing native runtime: {prefix}")
            if name == "qpdf":
                run(["cmake", "-S", source, "-B", folder / "cmake", "-DCMAKE_BUILD_TYPE=Release",
                     "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0",
                     f"-DCMAKE_INSTALL_PREFIX={prefix}", "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_STATIC_LIBS=ON",
                     "-DUSE_IMPLICIT_CRYPTO=OFF", "-DREQUIRE_CRYPTO_NATIVE=ON", "-DBUILD_TESTING=OFF"], source, env)
                run(["cmake", "--build", folder / "cmake", "--parallel", jobs], source, env)
                run(["cmake", "--install", folder / "cmake"], source, env)
            else:
                if name == "zbar":
                    env = {**env, "LIBS": "-liconv"}
                    run(["autoreconf", "-fi"], source, env)
                    flags = ["--disable-nls", "--disable-doc", "--disable-video", "--without-x", "--without-jpeg", "--without-imagemagick",
                             "--without-gtk", "--without-qt", "--without-python", "--without-dbus"]
                else:
                    flags = ["--without-x", "--disable-cups", "--without-tesseract", "--disable-dbus", "--disable-fontconfig"]
                # GS's libtiff configure prepends cwd; an absolute configure
                # argv[0] incorrectly duplicates the path in its subconfigure.
                run(["./configure", f"--prefix={prefix}", *flags], source, env)
                run(["make", "-j" + jobs], source, env)
                run(["make", "install"], source, env)
                env.pop("LIBS", None)
            license_dir = NATIVE / "licenses" / name
            license_dir.mkdir(parents=True, exist_ok=True)
            for pattern in ("COPYING*", "LICENSE*", "doc/COPYING*"):
                for license_file in source.glob(pattern):
                    if license_file.is_file():
                        shutil.copy2(license_file, license_dir / license_file.name)

    composition = ROOT / "build_assets" / "composition"
    manifest = json.loads((composition / "BUNDLE_INFO.json").read_text())
    manifest["assets"] = [e for e in manifest["assets"] if e["path"].startswith("fonts/")]
    target = composition / "qpdf"
    target.mkdir(exist_ok=True)
    shutil.copy2(NATIVE / "qpdf" / "bin" / "qpdf", target / "qpdf")
    manifest["platform"] = "macos-arm64"
    manifest["assets"].append({"path": "qpdf/qpdf", "sha256": digest(target / "qpdf"),
                              "source": sources["sources"]["qpdf"]["url"]})
    (composition / "BUNDLE_INFO.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    from scripts.prepare_composition_assets import prepare as prepare_fonts
    prepare_fonts(fonts_only=True)
    for executable in (target / "qpdf", NATIVE / "ghostscript/bin/gs"):
        run([executable, "--version"], ROOT, env)


if __name__ == "__main__":
    prepare()
