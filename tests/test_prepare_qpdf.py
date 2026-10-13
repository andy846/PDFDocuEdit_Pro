"""Native qpdf preparation reuses the pinned source and shared staging contract."""

import json
from pathlib import Path

import pytest


def test_native_preparation_refuses_windows_without_writes(tmp_path, monkeypatch):
    from scripts import prepare_qpdf

    monkeypatch.setattr(prepare_qpdf, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "windows-x64")
    with pytest.raises(RuntimeError, match="native|Windows"):
        prepare_qpdf.prepare_native_qpdf()
    assert list(tmp_path.iterdir()) == []


def test_linux_build_is_pinned_static_qpdf_without_mac_flags(tmp_path, monkeypatch):
    from scripts import prepare_qpdf

    calls = []
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "linux-x64")
    monkeypatch.setattr(prepare_qpdf, "run", lambda args, cwd, env: calls.append([str(x) for x in args]))
    prepare_qpdf.build_qpdf(tmp_path / "source", tmp_path / "install", tmp_path / "work", {})
    assert len(calls) == 3
    assert calls[0][0] == "cmake"
    assert "-DBUILD_SHARED_LIBS=OFF" in calls[0]
    assert "-DREQUIRE_CRYPTO_NATIVE=ON" in calls[0]
    assert not any("OSX" in arg for arg in calls[0])


def test_macos_build_keeps_arm64_and_deployment_target(tmp_path, monkeypatch):
    from scripts import prepare_qpdf

    calls = []
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "macos-arm64")
    monkeypatch.setattr(prepare_qpdf, "run", lambda args, cwd, env: calls.append([str(x) for x in args]))
    prepare_qpdf.build_qpdf(tmp_path / "source", tmp_path / "install", tmp_path / "work", {})
    assert "-DCMAKE_OSX_ARCHITECTURES=arm64" in calls[0]
    assert "-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0" in calls[0]


def test_source_and_binary_version_pins_must_agree(tmp_path, monkeypatch):
    from scripts import prepare_qpdf

    composition = tmp_path / "build_assets/composition"
    composition.mkdir(parents=True)
    (composition / "BUNDLE_INFO.json").write_text(json.dumps({"qpdf_version": "12.4.1", "assets": []}))
    native = tmp_path / "build_assets/macos"
    native.mkdir()
    (native / "SOURCES.json").write_text(json.dumps({"sources": {"qpdf": {"version": "12.4.2"}}}))
    monkeypatch.setattr(prepare_qpdf, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "linux-x64")
    with pytest.raises(RuntimeError, match="version|pin"):
        prepare_qpdf.prepare_native_qpdf()
    assert not (composition / "qpdf").exists()


def test_cross_ci_prepares_the_native_runtime_and_keeps_font_preflight_gate():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    cross = workflow.split("  cross-platform-core:", 1)[1]
    assert "--fonts-only" not in cross
    assert "python -m scripts.prepare_composition_assets" in cross
    assert "tests/test_font_preflight.py" in (root / "scripts/ci_plan.py").read_text()


def test_native_staging_removes_foreign_assets_and_preserves_fonts(tmp_path, monkeypatch):
    import hashlib
    import struct

    from scripts import prepare_qpdf

    root = tmp_path / "build_assets/composition"
    root.mkdir(parents=True)
    font = {"path": "fonts/example.ttf", "sha256": "a" * 64, "source": "https://example.test/font"}
    (root / "BUNDLE_INFO.json").write_text(json.dumps({"schema_version": 1, "qpdf_version": "12.4.2", "platform": "windows-x64", "assets": [font, {"path": "qpdf/qpdf.exe", "sha256": "b" * 64}]}))
    source = tmp_path / "qpdf-built"
    header = bytearray(256)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<H", header, 18, 62)
    source.write_bytes(header)
    notices = tmp_path / "licenses"
    notices.mkdir()
    for name in ("LICENSE.txt", "NOTICE.md"):
        (notices / name).write_text(name)
    pin = {"version": "12.4.2", "url": "https://example.test/pinned.tar.gz", "sha256": "c" * 64, "license": "Apache-2.0"}
    monkeypatch.setattr(prepare_qpdf, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "linux-x64")
    monkeypatch.setattr(prepare_qpdf, "_verify_version", lambda *args: None)
    result = prepare_qpdf.stage_qpdf(source, notices, pin)
    manifest = json.loads((root / "BUNDLE_INFO.json").read_text())
    assert result == root / "qpdf/qpdf"
    assert manifest["platform"] == "linux-x64"
    assert manifest["assets"][0] == font
    assert {e["path"] for e in manifest["assets"] if e["path"].startswith("qpdf/")} == {"qpdf/qpdf", "qpdf/LICENSE.txt", "qpdf/NOTICE.md"}
    assert all(hashlib.sha256((root / e["path"]).read_bytes()).hexdigest() == e["sha256"] for e in manifest["assets"][1:])


def test_source_checksum_failure_stops_before_extraction(tmp_path, monkeypatch):
    from scripts import prepare_macos

    def download(url, output):
        output.write_bytes(b"invalid source")

    monkeypatch.setattr(prepare_macos.urllib.request, "urlretrieve", download)
    with pytest.raises(RuntimeError, match="checksum"):
        prepare_macos.checked_source({"url": "https://example.test/qpdf.tar.gz", "sha256": "0" * 64}, tmp_path)
    assert not (tmp_path / "source").exists()


@pytest.mark.parametrize("failure", [RuntimeError("checksum mismatch"), OSError("missing executable")])
def test_explicit_preparation_rebuilds_invalid_native_cache(tmp_path, monkeypatch, failure):
    from core import pdf_runtime
    from scripts import prepare_qpdf

    composition = tmp_path / "build_assets/composition"
    composition.mkdir(parents=True)
    pin = {"version": "12.4.2", "sha256": "c" * 64}
    (composition / "BUNDLE_INFO.json").write_text(json.dumps({"qpdf_version": "12.4.2", "platform": "linux-x64", "qpdf_source_sha256": pin["sha256"]}))
    native = tmp_path / "build_assets/macos"
    native.mkdir()
    (native / "SOURCES.json").write_text(json.dumps({"sources": {"qpdf": pin}}))
    monkeypatch.setattr(prepare_qpdf, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_qpdf, "runtime_platform", lambda: "linux-x64")
    def reject_cache():
        raise failure
    monkeypatch.setattr(pdf_runtime, "qpdf_executable", reject_cache)
    calls = []
    monkeypatch.setattr(prepare_qpdf, "checked_source", lambda pin, directory: calls.append("checked source") or directory / "source")
    monkeypatch.setattr(prepare_qpdf, "build_qpdf", lambda *args: calls.append("build"))
    monkeypatch.setattr(prepare_qpdf, "stage_qpdf", lambda *args: calls.append("stage") or composition / "qpdf/qpdf")
    assert prepare_qpdf.prepare_native_qpdf() == composition / "qpdf/qpdf"
    assert calls == ["checked source", "build", "stage"]
