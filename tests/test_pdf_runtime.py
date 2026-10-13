"""Pinned qpdf runtime must fail closed on every supported platform."""

import hashlib
import json
import struct

import pytest

from core import pdf_runtime


def native_bytes(target):
    data = bytearray(256)
    if target == "windows-x64":
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 60, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<H", data, 132, 0x8664)
    elif target == "macos-arm64":
        struct.pack_into("<II", data, 0, 0xFEEDFACF, 0x100000C)
    else:
        data[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<H", data, 18, 62)
    return bytes(data)


def runtime(tmp_path, monkeypatch, target, *, actual=None):
    root = tmp_path / "composition"
    exe = root / "qpdf" / ("qpdf.exe" if target == "windows-x64" else "qpdf")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(native_bytes(actual or target))
    exe.chmod(0o755)
    manifest = {"schema_version": 1, "qpdf_version": "12.4.2", "platform": target,
                "assets": [{"path": exe.relative_to(root).as_posix(),
                            "sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}]}
    (root / "BUNDLE_INFO.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(pdf_runtime, "asset_root", lambda: root)
    monkeypatch.setattr(pdf_runtime.sys, "platform", {"windows-x64": "win32", "macos-arm64": "darwin", "linux-x64": "linux"}[target])
    # Host architecture is explicit; the tests run on Windows as well.
    monkeypatch.setattr("platform.machine", lambda: "arm64" if target == "macos-arm64" else "AMD64")
    return root, exe, manifest


@pytest.mark.parametrize("target", ["windows-x64", "macos-arm64", "linux-x64"])
def test_valid_native_qpdf_returns_verified_executable(tmp_path, monkeypatch, target):
    _, exe, _ = runtime(tmp_path, monkeypatch, target)
    assert pdf_runtime.qpdf_executable() == exe


@pytest.mark.parametrize("target,actual", [("macos-arm64", "linux-x64"), ("linux-x64", "macos-arm64"), ("windows-x64", "macos-arm64")])
def test_wrong_platform_header_is_rejected_even_when_hash_matches(tmp_path, monkeypatch, target, actual):
    runtime(tmp_path, monkeypatch, target, actual=actual)
    with pytest.raises(RuntimeError, match="architecture|platform"):
        pdf_runtime.qpdf_executable()


def test_manifest_platform_mismatch_is_rejected(tmp_path, monkeypatch):
    root, _, manifest = runtime(tmp_path, monkeypatch, "macos-arm64")
    manifest["platform"] = "windows-x64"
    (root / "BUNDLE_INFO.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="platform"):
        pdf_runtime.qpdf_executable()


def test_tampered_runtime_is_rejected(tmp_path, monkeypatch):
    _, exe, _ = runtime(tmp_path, monkeypatch, "windows-x64")
    exe.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="integrity"):
        pdf_runtime.qpdf_executable()


def test_native_permission_failure_is_actionable(tmp_path, monkeypatch):
    runtime(tmp_path, monkeypatch, "linux-x64")
    monkeypatch.setattr("os.access", lambda *args: False)
    with pytest.raises(RuntimeError, match="permission|executable"):
        pdf_runtime.qpdf_executable()


def test_manifest_path_traversal_is_rejected(tmp_path, monkeypatch):
    root, _, manifest = runtime(tmp_path, monkeypatch, "windows-x64")
    leaked = root.parent / "outside"
    leaked.write_bytes(b"outside")
    manifest["assets"].append({"path": "qpdf/../../outside", "sha256": hashlib.sha256(leaked.read_bytes()).hexdigest()})
    (root / "BUNDLE_INFO.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="path|outside"):
        pdf_runtime.qpdf_executable()


def test_malformed_manifest_is_actionable(tmp_path, monkeypatch):
    root, _, _ = runtime(tmp_path, monkeypatch, "windows-x64")
    (root / "BUNDLE_INFO.json").write_text("{")
    with pytest.raises(RuntimeError, match="manifest"):
        pdf_runtime.qpdf_executable()
