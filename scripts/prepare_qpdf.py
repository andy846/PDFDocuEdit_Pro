"""Shared qpdf native build/staging from the existing SHA-pinned source.

Linux is a CI/runtime target, not a new distributable application. macOS builds
use this same contract; Windows retains its verified upstream binary bundle.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.pdf_runtime import runtime_platform, verify_binary_architecture
from scripts.prepare_macos import checked_source, digest, run

ROOT = Path(__file__).resolve().parents[1]


def build_qpdf(source, prefix, directory, env):
    target = runtime_platform()
    if target == "windows-x64":
        raise RuntimeError("Native qpdf preparation must not replace the Windows runtime.")
    flags = ["-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_INSTALL_PREFIX={prefix}",
             "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_STATIC_LIBS=ON", "-DUSE_IMPLICIT_CRYPTO=OFF",
             "-DREQUIRE_CRYPTO_NATIVE=ON", "-DBUILD_TESTING=OFF"]
    if target == "macos-arm64":
        flags += ["-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0"]
    build = Path(directory) / "cmake"
    run(["cmake", "-S", source, "-B", build, *flags], source, env)
    run(["cmake", "--build", build, "--parallel", str(min(4, os.cpu_count() or 2))], source, env)
    run(["cmake", "--install", build], source, env)


def _verify_version(executable, version):
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=20, check=True)
    if not result.stdout.splitlines() or result.stdout.splitlines()[0] != f"qpdf version {version}":
        raise RuntimeError("Built qpdf version does not match the source pin.")


def stage_qpdf(executable, licenses, pin):
    target = runtime_platform()
    if target == "windows-x64":
        raise RuntimeError("Native qpdf staging must not replace the Windows runtime.")
    composition = ROOT / "build_assets/composition"
    manifest_path = composition / "BUNDLE_INFO.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["qpdf_version"] != pin["version"]:
        raise RuntimeError("qpdf source and binary version pins disagree.")
    verify_binary_architecture(executable, target)
    _verify_version(executable, pin["version"])
    files = [(Path(executable), "qpdf")]
    for name in ("LICENSE.txt", "NOTICE.md"):
        license_file = Path(licenses) / name
        if not license_file.is_file():
            raise RuntimeError(f"Missing qpdf licence/notice: {name}")
        files.append((license_file, name))
    destination = composition / "qpdf"
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    for source, name in files:
        final = destination / name
        staged = destination / (name + ".download")
        try:
            shutil.copy2(source, staged)
            if name == "qpdf":
                staged.chmod(0o755)
            staged.replace(final)
        finally:
            staged.unlink(missing_ok=True)
        entries.append({"path": f"qpdf/{name}", "sha256": digest(final), "source": pin["url"]})
    manifest["assets"] = [entry for entry in manifest["assets"] if not entry["path"].startswith("qpdf/")] + entries
    manifest.update(platform=target, qpdf_source_sha256=pin["sha256"], qpdf_source_license=pin["license"])
    staged_manifest = manifest_path.with_suffix(".json.download")
    try:
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staged_manifest.replace(manifest_path)
    finally:
        staged_manifest.unlink(missing_ok=True)
    return destination / "qpdf"


def prepare_native_qpdf():
    target = runtime_platform()
    if target == "windows-x64":
        raise RuntimeError("Native qpdf preparation must not run on Windows.")
    composition = ROOT / "build_assets/composition"
    manifest = json.loads((composition / "BUNDLE_INFO.json").read_text(encoding="utf-8"))
    pin = json.loads((ROOT / "build_assets/macos/SOURCES.json").read_text(encoding="utf-8"))["sources"]["qpdf"]
    if manifest["qpdf_version"] != pin["version"]:
        raise RuntimeError("qpdf source and binary version pins disagree.")
    if manifest.get("platform") == target and manifest.get("qpdf_source_sha256") == pin["sha256"]:
        from core.pdf_runtime import qpdf_executable
        try:
            executable = qpdf_executable()
            _verify_version(executable, pin["version"])
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"Rebuilding invalid cached qpdf from pinned source: {exc}")
        else:
            return executable
    env = dict(os.environ)
    if target == "macos-arm64":
        env["MACOSX_DEPLOYMENT_TARGET"] = "13.0"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-qpdf-") as work:
        directory = Path(work)
        source = checked_source(pin, directory)
        prefix = directory / "install"
        build_qpdf(source, prefix, directory, env)
        return stage_qpdf(prefix / "bin/qpdf", source, pin)


if __name__ == "__main__":
    print(prepare_native_qpdf())
