"""Customer detection profiles reuse the existing background review workflow."""

import copy

import pytest
from PyQt6.QtWidgets import QApplication, QInputDialog

from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from core.pdf_backend import fitz
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


def test_template_scope_canvas_and_customer_profile_actions(overlay, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    from tests.composition.test_template_overlay_routing import sample

    spec = sample(tmp_path)
    overlay.apply_spec(spec.to_dict())
    overlay.envelope.setValue(2)
    overlay.refresh_canvas()
    expected = spec.objects[1].element.id
    assert expected in {e.id for e in overlay.canvas.template.elements}
    assert spec.objects[0].element.id not in {e.id for e in overlay.canvas.template.elements}
    overlay.canvas.select_ids([expected])
    overlay.selection_changed()
    assert overlay.template_scope.currentData() == ["REMINDER"]
    overlay.template_scope.setCurrentIndex(overlay.template_scope.findData([]))
    assert next(o for o in overlay.spec.objects if o.element.id == expected).template_ids == []
    overlay.undo.undo()
    assert next(o for o in overlay.spec.objects if o.element.id == expected).template_ids == ["REMINDER"]
    target = tmp_path / "customer.pdpp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(target), ""))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("eMPF production", True))
    overlay.save_customer_profile()
    wait_until(lambda: target.exists() and not overlay.active_worker)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(target), ""))
    overlay.open_customer_profile()
    wait_until(lambda: not overlay.active_worker and overlay.spec.needs_detection_review)
    assert not overlay.spec.settings.groups and not overlay.actions["generate"].isEnabled()
    dialog = MailpieceDialog(overlay)
    dialog.show()
    assert dialog.customer_profile["name"] == spec.detection_review["profile_name"]
    assert dialog.report is None
    dialog.reject()


def test_layer_selection_navigates_to_applicable_template(overlay, tmp_path):
    from tests.composition.test_template_overlay_routing import sample

    spec = sample(tmp_path)
    overlay.apply_spec(spec.to_dict())
    overlay.envelope.setValue(2)
    overlay.select_layer_objects([spec.objects[0].element.id])
    assert overlay.envelope.value() == 1
    assert overlay.canvas.selected_ids() == [spec.objects[0].element.id]


def test_export_draft_index_preserves_unknown_and_does_not_accept(overlay, tmp_path, monkeypatch):
    import csv

    from PyQt6.QtWidgets import QFileDialog

    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.set_collection_profile(profile())
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not dialog.scan_worker)
    path = tmp_path / "index.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), ""))
    dialog.export_index()
    wait_until(lambda: path.exists() and not overlay.active_worker)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2 and rows[0]["TemplateID"] == "" and rows[0]["ReviewStatus"] == "unknown"
    assert dialog.report["accepted"] is False and not overlay.spec.detection_review
    assert not dialog.apply_button.isEnabled()
    dialog.reject()


def test_profile_rule_required_signals_editable_without_reteaching(overlay, tmp_path):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog

    config = profile()["rule_sets"][0]["config"]
    config["rules"].append({"kind": "page_number", "pattern": "Page {CURRENT} of {TOTAL}"})
    manager = ProfileLibraryDialog(overlay, config, root=tmp_path / "library")
    manager.show()
    wait_until(lambda: not manager.busy)
    manager.create_profile()
    manager.add_taught_rule()
    manager.combination.setCurrentIndex(manager.combination.findData("all"))
    manager.primary.setCurrentIndex(manager.primary.findData("page_number"))
    assert manager.value["rule_sets"][0]["config"]["combine"] == "all"
    assert manager.value["rule_sets"][0]["primary"] == "page_number"
    manager.save_revision()
    wait_until(lambda: not manager.busy)
    assert manager.use_button.isEnabled()
    manager.reject()


def test_review_history_budget_retains_latest_edit(overlay):
    dialog = MailpieceDialog(overlay)
    latest = ({"groups": [[1, 1]] * 1000, "findings": [], "edits": []}, 7)
    history = [copy.deepcopy(latest) for _ in range(20)]
    dialog.trim_review_history(history)
    assert 1 <= len(history) <= 8 and history[-1] == latest
    dialog.reject()


def test_reinspect_new_source_keeps_rules_and_layouts_but_revokes_acceptance(overlay, tmp_path):
    from tests.composition.test_template_overlay_routing import sample

    spec = sample(tmp_path)
    overlay.apply_spec(spec.to_dict())
    other = tmp_path / "new-source.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 60), "Regular new month")
        pdf.new_page().insert_text((40, 60), "Reminder new month")
        pdf.save(other)
    overlay.inspect_source(other, EnvelopeSettings(pages_per_envelope=1, duplex=True), preserve=True)
    wait_until(lambda: not overlay.active_worker)
    assert overlay.spec.source.sha256 != spec.source.sha256
    assert overlay.spec.needs_detection_review and not overlay.spec.settings.groups
    assert overlay.spec.detection_review["profile"]["profile_id"] == spec.detection_review["profile_id"]
    assert overlay.spec.objects[0].template_ids == ["REGULAR"]
    assert not overlay.actions["generate"].isEnabled()


def test_workflow_changed_boundaries_can_reopen_detection_without_old_acceptance(app, tmp_path):
    from dataclasses import asdict

    from composition.designer.mailpiece_workflow import WorkflowDetectionHost
    from tests.composition.test_template_overlay_routing import sample
    from workflow.model import WorkflowRun
    from workflow.workspace import WorkflowWindow

    spec = sample(tmp_path)
    owner = WorkflowWindow()
    owner.show()
    owner.spec.node("group").params = {
        "method": "reviewed_detection",
        "detection_review": spec.detection_review,
    }
    owner.run = WorkflowRun(
        source=spec.source.path, database=str(tmp_path / "unused.sqlite"), groups=[[1, 2], [3, 4]]
    )
    dialog = None
    try:
        host = WorkflowDetectionHost(owner, asdict(spec.source))
        dialog = MailpieceDialog(host)
        dialog.show()
        wait_until(lambda: dialog.customer_profile is not None and not dialog.scan_worker)
        assert dialog.report is None and not dialog.apply_button.isEnabled()
        assert dialog.customer_profile["profile_id"] == spec.detection_review["profile_id"]
    finally:
        if dialog:
            dialog.reject()
        owner.undo.setClean()
        owner.close()
        wait_until(lambda: not owner.workers)


def test_library_displays_recognition_rules_as_operator_text(overlay, tmp_path):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog

    manager = ProfileLibraryDialog(overlay, profile()["rule_sets"][0]["config"], root=tmp_path / "library")
    manager.show()
    wait_until(lambda: not manager.busy)
    manager.create_profile()
    manager.add_taught_rule()
    detail = manager.rule_detail.toPlainText()
    assert "Regular" in detail and "Whole page" in detail
    assert "'kind':" not in detail
    assert manager.value["rule_sets"][0]["template_id"] == "TYPE_01"
    manager.reject()



def test_library_imports_existing_region_file_and_refreshes_entries(overlay, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from composition.pdf_source.detection import DetectionConfig
    from composition.pdf_source.profiles import load_profile, save_profile

    source = save_profile(tmp_path / "existing.pdmp", DetectionConfig(
        rules=[{"kind": "region_present"}], region_mm=[8, 19, 70, 8], profile_name="Existing letters"))
    manager = ProfileLibraryDialog(overlay, root=tmp_path / "library")
    manager.show()
    wait_until(lambda: not manager.busy)
    assert not manager.records
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (source, ""))
    manager.import_profile()
    wait_until(lambda: not manager.busy and len(manager.records) == 1)
    assert manager.use_button.isEnabled()
    assert "Text present" in manager.rule_detail.toPlainText()
    assert manager.value["config"]["region_mm"] == [8, 19, 70, 8]
    manager.name.setText("Renamed letters")
    assert not manager.use_button.isEnabled()
    manager.save_revision()
    wait_until(lambda: not manager.busy and manager.saved["revision"] == 2)
    target = tmp_path / "exported.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    manager.export_profile()
    wait_until(lambda: not manager.busy)
    assert load_profile(target)["profile_name"] == "Renamed letters"
    manager.use_profile()
    assert manager.selected_profile["kind"] == "single_mailpiece_detection"
    assert manager.selected_profile["revision"] == 2


def test_create_region_library_profile_requires_manual_save(overlay, tmp_path):
    from dataclasses import asdict

    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from composition.pdf_source.detection import DetectionConfig
    from composition.pdf_source.profile_library import ProfileLibrary

    root = tmp_path / "library"
    config = asdict(DetectionConfig(rules=[{"kind": "region_present"}], region_mm=[8, 19, 70, 8]))
    manager = ProfileLibraryDialog(overlay, config, root=root)
    manager.show()
    wait_until(lambda: not manager.busy)
    manager.create_profile()
    assert manager.value["kind"] == "single_mailpiece_detection"
    assert not manager.use_button.isEnabled()
    assert not ProfileLibrary(root).list()["entries"]
    manager.name.setText("Manually created")
    manager.save_revision()
    wait_until(lambda: not manager.busy and len(manager.records) == 1)
    assert manager.use_button.isEnabled()
    manager.reject()



def test_selected_single_profile_shows_ready_without_collection_only_fields(overlay, tmp_path):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from composition.pdf_source.profile_library import ProfileLibrary
    from tests.composition.test_detection_profile_library import region_config

    root = tmp_path / "library"
    ProfileLibrary(root).add_single(region_config())
    manager = ProfileLibraryDialog(overlay, root=root)
    manager.show()
    try:
        wait_until(lambda: not manager.busy and len(manager.records) == 1)
        manager.entries.setCurrentRow(0)
        wait_until(lambda: not manager.busy and manager.saved is not None)
        assert manager.status.text() != "Working…"
        assert not manager.description.isVisible()
        assert not manager.primary.isVisible() and not manager.combination.isVisible()
        assert manager.use_button.isEnabled()
        assert "Text present in selected region" in manager.rule_detail.toPlainText()
    finally:
        manager.reject()


def test_old_duplicate_names_are_distinguishable_and_rename_failure_keeps_selection(overlay, tmp_path):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from tests.composition.test_detection_profile_library import legacy_duplicate_library

    root = tmp_path / "library"
    library = legacy_duplicate_library(root)
    manager = ProfileLibraryDialog(overlay, root=root)
    manager.show()
    try:
        wait_until(lambda: not manager.busy and len(manager.records) == 2)
        labels = [manager.entries.item(i).text() for i in range(2)]
        assert labels[0] != labels[1] and all("duplicate" in label.lower() for label in labels)
        manager.entries.setCurrentRow(1)
        wait_until(lambda: not manager.busy and manager.saved is not None)
        assert manager.saved["profile_id"] == "old_b"
        manager.name.setText("Different layout")
        manager.save_revision()
        wait_until(lambda: not manager.busy and manager.saved["revision"] == 2)
        manager.name.setText(" REGION LETTERS ")
        manager.save_revision()
        wait_until(lambda: not manager.busy and "name already exists" in manager.status.text())
        assert manager.saved["profile_id"] == "old_b" and manager.saved["revision"] == 2
        assert manager.name.text() == " REGION LETTERS " and not manager.use_button.isEnabled()
        assert library.read("old_a")["revision"] == 1
        assert library.read("old_b")["name"] == "Different layout"
    finally:
        manager.reject()
