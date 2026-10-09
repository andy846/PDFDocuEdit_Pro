"""Platform adapters must leave the Windows release contracts untouched."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import macos_runtime
from scripts import prepare_macos

ROOT = Path(__file__).resolve().parents[1]


def test_native_preparation_rejects_windows_without_writes(monkeypatch):
    monkeypatch.setattr(prepare_macos.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="Apple Silicon"):
        prepare_macos.prepare()


def test_windows_bootstrap_is_noop(monkeypatch):
    monkeypatch.setattr(macos_runtime.sys, "platform", "win32")
    monkeypatch.setattr(macos_runtime.sys, "frozen", True, raising=False)
    loader = Mock()
    monkeypatch.setattr(macos_runtime.ctypes, "CDLL", loader)
    before = dict(macos_runtime.os.environ)
    macos_runtime.bootstrap()
    assert dict(macos_runtime.os.environ) == before
    loader.assert_not_called()


def test_source_pins_and_windows_asset_manifest():
    pins = json.loads((ROOT / "build_assets/macos/SOURCES.json").read_text())
    assert pins["platform"] == "macos-arm64"
    assert set(pins["sources"]) == {"qpdf", "zbar", "ghostscript"}
    for entry in pins["sources"].values():
        assert len(entry["sha256"]) == 64 and entry["url"].startswith("https://") and entry["license"]
    manifest = json.loads((ROOT / "build_assets/composition/BUNDLE_INFO.json").read_text())
    executable = "qpdf/qpdf" if prepare_macos.platform.system() == "Darwin" else "qpdf/qpdf.exe"
    assert any(e["path"] == executable for e in manifest["assets"])


def test_mac_font_inventory_reuses_shared_files(monkeypatch, tmp_path):
    import composition.engine.system_fonts as fonts
    import core.system_fonts as shared
    path = tmp_path / "example.ttc"
    monkeypatch.setattr(fonts.sys, "platform", "darwin")
    monkeypatch.setattr(shared, "_font_files", lambda: (path,))
    assert fonts.installed_font_files() == [path]


def test_finder_routes_projects_to_existing_host(monkeypatch):
    import main
    monkeypatch.setattr(main.sys, "platform", "darwin")
    viewer = Mock()
    main.route_open_files(viewer, ["letter.pdcx", "route.pdflow", "sample.pdf"])
    host = viewer._mode_controller.ensure_host.return_value
    assert [c.args[0] for c in host.open_project.call_args_list] == ["letter.pdcx", "route.pdflow"]
    viewer.queue_open_files.assert_called_once_with(["sample.pdf"])
    assert len(main.pdf_arguments(["letter.pdcx", "route.pdflow", "sample.pdf", "--print-worker"])) == 3


def test_windows_file_routing_unchanged(monkeypatch):
    import main
    monkeypatch.setattr(main.sys, "platform", "win32")
    viewer = Mock()
    paths = ["sample.pdf", "sample.ps"]
    main.route_open_files(viewer, paths)
    viewer.queue_open_files.assert_called_once_with(paths)
    viewer._mode_controller.ensure_host.assert_not_called()
    assert len(main.pdf_arguments(["letter.pdcx", "sample.pdf"])) == 1


def test_mac_library_uses_owned_bundle_and_windows_labels_remain(monkeypatch, tmp_path):
    import pyzbar.zbar_library as zbar

    from core.system_fonts import font_platform_label
    original = zbar.load
    monkeypatch.setattr(zbar, "load", original)
    monkeypatch.setattr(macos_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(macos_runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(macos_runtime.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(macos_runtime.sys, "argv", ["application"])
    # bootstrap sets only the Mac child environment. Restore it after the test.
    monkeypatch.setenv("GS_LIB", "before")
    monkeypatch.setenv("GS_FONTPATH", "before")
    assert font_platform_label() == "macOS"
    with pytest.raises(RuntimeError, match="barcode decoder"):
        macos_runtime.bootstrap()
    library = tmp_path / "pyzbar/libzbar.dylib"
    library.parent.mkdir()
    library.touch()
    loaded = Mock()
    loader = Mock(return_value=loaded)
    monkeypatch.setattr(macos_runtime.ctypes, "CDLL", loader)
    macos_runtime.bootstrap()
    assert zbar.load() == (loaded, [])
    loader.assert_called_once_with(str(library))


def test_mac_update_ui_never_starts_windows_update(qt_application, monkeypatch):
    from PyQt6.QtWidgets import QWidget

    import ui.update_dialog as module
    monkeypatch.setattr(module.sys, "platform", "darwin")
    start = Mock()
    monkeypatch.setattr(module.UpdateWorker, "start", start)
    owner = QWidget()
    dialog = module.UpdateDialog(owner)
    assert dialog.action.text() == "Open download page"
    assert "DMG" in dialog.status.text() and dialog.worker is None
    start.assert_not_called()
    dialog.close()
    owner.close()
