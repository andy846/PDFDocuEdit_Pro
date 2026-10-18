"""Customer detection profiles reuse the existing background review workflow."""

import copy

import fitz
import pytest
from PyQt6.QtWidgets import QApplication, QInputDialog

from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from tests.composition.test_multi_rule_detection import profile
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import wait_until


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(app, tmp_path, monkeypatch):
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    path = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for text in ("Other", "continued", "Reminder"):
            pdf.new_page().insert_text((40, 60), text)
        pdf.save(path)
    window = OverlayWindow()
    settings = EnvelopeSettings(pages_per_envelope=1)
    window.apply_spec(EnvelopeSpec(inspect_source(path, settings, uniform=True), settings).to_dict())
    window.show()
    yield window
    for dialog in window.findChildren(MailpieceDialog):
        dialog.reject()
    finish(window)


def test_profile_scan_manual_resolution_undo_and_explicit_accept(overlay, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    original = profile()
    unchanged = copy.deepcopy(original)
    dialog.set_collection_profile(original)
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not dialog.scan_worker)
    assert dialog.report["groups"] == [[1, 2], [3, 3]]
    assert dialog.model.columnCount() == 6
    assert dialog.report["classifications"][0]["classification_status"] == "unknown"
    dialog.acknowledge.setChecked(True)
    assert not dialog.apply_button.isEnabled()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **kw: ("REGULAR", True))
    dialog.confirm_classification()
    dialog.acknowledge.setChecked(True)
    assert dialog.apply_button.isEnabled()
    dialog.restore_boundary_edit(False)
    assert dialog.report["classifications"][0]["classification_status"] == "unknown"
    assert not dialog.apply_button.isEnabled()
    dialog.restore_boundary_edit(True)
    dialog.acknowledge.setChecked(True)
    dialog.apply()
    wait_until(lambda: not overlay.active_worker and overlay.undo.count() == 1)
    assert overlay.spec.overlay_version == 9
    assert overlay.spec.detection_review["accepted"]
    assert original == unchanged
    reopened = MailpieceDialog(overlay)
    reopened.show()
    wait_until(lambda: reopened.report is not None and not reopened.scan_worker)
    assert reopened.customer_profile["profile_id"] == original["profile_id"]
    assert not reopened.acknowledge.isChecked()
    overlay.undo.undo()
    assert not overlay.spec.settings.groups
    reopened.reject()


def test_profile_library_editor_roundtrip(overlay, tmp_path):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog

    manager = ProfileLibraryDialog(overlay, profile()["rule_sets"][0]["config"], root=tmp_path / "library")
    manager.show()
    wait_until(lambda: not manager.busy)
    manager.create_profile()
    manager.name.setText("eMPF")
    manager.add_taught_rule()
    assert len(manager.value["rule_sets"]) == 1
    manager.save_revision()
    wait_until(lambda: not manager.busy and manager.value["revision"] == 1)
    assert manager.use_button.isEnabled()
    manager.name.setText("eMPF revised")
    assert not manager.use_button.isEnabled()
    manager.save_revision()
    wait_until(lambda: not manager.busy and manager.value["revision"] == 2)
    manager.use_profile()
    assert manager.selected_profile["name"] == "eMPF revised"


def test_profile_change_rejects_old_scan_result(overlay):
    from composition.pdf_source.multi_detection import scan_pdf

    dialog = MailpieceDialog(overlay)
    dialog.show()
    chosen = profile()
    dialog.set_collection_profile(chosen)
    result = scan_pdf(overlay.spec.source.path, chosen, cache_path=overlay.directory / "test.sqlite")
    changed = copy.deepcopy(chosen)
    changed["revision"] += 1
    dialog.set_collection_profile(changed)
    dialog.scanned(result)
    assert dialog.report is None
    assert not dialog.apply_button.isEnabled()
    dialog.reject()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_library_narrow_layout_and_close_during_background_read(overlay, app, tmp_path, theme):
    from PyQt6.QtWidgets import QScrollArea

    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from styles.theme import apply_theme, get_theme

    previous = get_theme()
    try:
        apply_theme(app, theme)
        manager = ProfileLibraryDialog(overlay, root=tmp_path / "library")
        manager.resize(760, 540)
        manager.show()
        wait_until(lambda: not manager.busy)
        manager.create_profile()
        app.processEvents()
        assert manager.use_button.isVisible()
        assert all(
            scroll.horizontalScrollBar().maximum() == 0 for scroll in manager.findChildren(QScrollArea)
        )
        manager.refresh()
        manager.reject()
        wait_until(lambda: not overlay.active_worker)
        assert manager.selected_profile is None
    finally:
        apply_theme(app, previous)


def test_split_clears_classification_and_blocks_acceptance(overlay, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.set_collection_profile(profile())
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not dialog.scan_worker)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **kw: (2, True))
    dialog.split()
    assert dialog.report["groups"] == [[1, 1], [2, 2], [3, 3]]
    assert dialog.report["classifications"][1]["classification_status"] == "unknown"
    dialog.acknowledge.setChecked(True)
    assert not dialog.apply_button.isEnabled()
    dialog.reject()
