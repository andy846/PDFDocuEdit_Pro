"""Shell-open projects must reach Designer instead of the PDF opener."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_shell_arguments_keep_project_paths_and_order(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(main.sys, "platform", platform)
    paths = [tmp_path / name for name in ("letter template.PDCX", "route.PDFLOW", "print.PDF", "note.txt")]
    assert main.pdf_arguments([str(p) for p in paths]) == [p.resolve() for p in paths[:3]]


@pytest.mark.parametrize("managed", [False, True])
def test_windows_mixed_open_dispatches_projects_and_pdfs_separately(monkeypatch, managed):
    monkeypatch.setattr(main.sys, "platform", "win32")
    host = Mock()
    controller = Mock()
    controller.exit_approved = False
    controller.ensure_host.return_value = host
    manager = Mock() if managed else None
    viewer = SimpleNamespace(_mode_controller=controller, document_windows=manager, queue_open_files=Mock())
    pdf_viewer = manager.active_window.return_value if manager else viewer
    main.route_open_files(viewer, ["letter.PDCX", "print.pdf", "route.pdflow"])
    assert [call.args[0] for call in host.open_project.call_args_list] == ["letter.PDCX", "route.pdflow"]
    assert controller.ensure_host.call_count == 2
    assert all(call.kwargs == {"create_default": False} for call in controller.ensure_host.call_args_list)
    assert [call.args for call in controller.request_mode.call_args_list] == [("designer",), ("designer",)]
    pdf_viewer.queue_open_files.assert_called_once_with(["print.pdf"])
    if manager:
        manager.focus.assert_called_with(viewer)


def test_failed_project_open_keeps_current_workspace(monkeypatch):
    monkeypatch.setattr(main.sys, "platform", "win32")
    controller = Mock()
    controller.exit_approved = False
    controller.ensure_host.return_value.open_project.return_value = None
    viewer = SimpleNamespace(_mode_controller=controller, document_windows=None, queue_open_files=Mock())
    main.route_open_files(viewer, ["invalid.pdcx"])
    controller.request_mode.assert_not_called()
    viewer.queue_open_files.assert_not_called()


@pytest.mark.parametrize("installer", ["PDFDocuEditPro.iss", "PDFDocuEditProManaged.iss"])
def test_windows_installer_offers_projects_without_overriding_defaults(installer):
    text = (Path(__file__).resolve().parents[1] / "installer" / installer).read_text(encoding="utf-8")
    registry = text.split("[Registry]", 1)[1].split("[Run]", 1)[0]
    entries = [line for line in registry.splitlines() if line.startswith("Root:")]
    for extension in (".pdcx", ".pdflow"):
        offered = [line for line in entries if f"Classes\\{extension}\\OpenWithProgids" in line]
        assert len(offered) == 1
        assert 'ValueName: "{#MyAppProgId}"' in offered[0]
        capabilities = [line for line in entries if "Capabilities\\FileAssociations" in line
                        and f'ValueName: "{extension}"' in line]
        assert len(capabilities) == 1 and 'ValueData: "{#MyAppProgId}"' in capabilities[0]
        assert not any(f'Subkey: "Software\\Classes\\{extension}";' in line for line in entries)


def test_shell_open_during_approved_exit_does_not_create_project(monkeypatch):
    monkeypatch.setattr(main.sys, "platform", "win32")
    controller = Mock()
    controller.exit_approved = True
    viewer = SimpleNamespace(_mode_controller=controller, document_windows=None, queue_open_files=Mock())
    main.route_open_files(viewer, ["late.pdcx"])
    controller.ensure_host.assert_not_called()
    controller.request_mode.assert_not_called()
    viewer.queue_open_files.assert_not_called()
