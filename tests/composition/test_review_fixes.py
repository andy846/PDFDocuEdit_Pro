"""Regressions for preserved production intent and Designer review findings."""
import copy
from dataclasses import asdict
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QInputDialog, QTableWidgetItem

from composition.designer.media_dialog import MediaDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.media.model import default_media
from composition.media.planner import build_print_plan
from composition.overlay.generator import generate
from composition.overlay.model import OverlayJob
from composition.overlay.serializer import load_project, save_project
from composition.pdf_source.model import EnvelopeSettings
from composition.template.geometry import element_bounds
from composition.template.model import Element, PageSpec, Template
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window, wait_until
from workflow.workspace import WorkflowWindow


@pytest.fixture(scope="module")
def app(qt_application):
    return qt_application


@pytest.fixture(autouse=True)
def bounded_preview(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)


@pytest.mark.parametrize("pages", [2, 6])
def test_regroup_keeps_print_media_and_rechecks_compatibility(app, tmp_path, pages):
    window = OverlayWindow()
    spec = sample_spec(tmp_path)
    spec.name = "Customer letters"
    spec.media = default_media()
    window.apply_spec(spec.to_dict())
    try:
        window.inspect_source(spec.source.path, EnvelopeSettings(pages_per_envelope=pages), preserve=True)
        wait_until(lambda: window.active_worker is None)
        assert window.spec.settings.pages_per_envelope == pages
        assert window.spec.media == spec.media and window.spec.name == spec.name
        if pages == 6:
            assert "no assigned Stock" in window.media_error
            assert not window.actions["generate"].isEnabled()
        else:
            assert not window.media_error
            result = generate(OverlayJob(window.spec.to_dict(), str(tmp_path / "output")))
            assert result.status == "completed", result.error
            assert result.generated_pages == 6
            assert Path(result.report_dir, "default_ticket.jdf").is_file()
            assert result.media_summary["stock_sheets"] == {"LH_A": 3, "LH_B": 3}
        window.undo.undo()
        assert window.spec.settings.pages_per_envelope == 3 and window.spec.media == spec.media
        window.undo.redo()
        assert window.spec.settings.pages_per_envelope == pages and window.spec.media == spec.media
    finally:
        finish(window)


def test_regroup_preserves_workflow_fields_on_save_and_reopen(app, tmp_path):
    window = OverlayWindow()
    spec = sample_spec(tmp_path)
    spec.external_fields = ["Customer"]
    spec.objects[0].element.value = "{{Customer}}"
    spec.name = "Workflow letter"
    spec.media = default_media()
    window.apply_spec(spec.to_dict())
    try:
        window.inspect_source(spec.source.path, EnvelopeSettings(pages_per_envelope=2), preserve=True)
        wait_until(lambda: window.active_worker is None)
        saved = save_project(window.spec, tmp_path / "regrouped.pdcx")
        loaded = load_project(saved)
        assert loaded.external_fields == ["Customer"]
        assert loaded.name == spec.name and loaded.media == spec.media
        assert loaded.objects[0].element.value == "{{Customer}}"
    finally:
        finish(window)


def test_regroup_printing_change_updates_retained_media_and_undo(app, tmp_path):
    window = OverlayWindow()
    spec = sample_spec(tmp_path)
    spec.media = default_media()
    window.apply_spec(spec.to_dict())
    try:
        window.inspect_source(spec.source.path, EnvelopeSettings(pages_per_envelope=3, duplex=True), preserve=True)
        wait_until(lambda: window.active_worker is None)
        assert window.spec.settings.duplex and window.spec.media["duplex"]
        assert window.spec.media["assignments"] == spec.media["assignments"]
        window.undo.undo()
        assert not window.spec.settings.duplex and not window.spec.media["duplex"]
    finally:
        finish(window)


def test_four_page_template_add_rule_targets_real_page_and_restores_deleted_rule(app):
    model = Template(pages=[PageSpec(name=f"Page {i+1}") for i in range(4)])
    # New templates deliberately do not guess paper assignments. This test
    # starts with three explicitly configured pages, then repairs page four.
    media = default_media()
    media.update(mode="template", assignments={page.id: stock for page, stock in
                 zip(model.pages[:3], ("LH_A", "LH_B", "LH_C"), strict=True)})
    dialog = MediaDialog(media, {"kind": "template", "project": model.to_dict(), "records": 2})
    try:
        dialog.add_rule()
        assert "Page 4" in dialog.assignments.item(3, 0).text()
        assert not dialog.assignments.item(3, 0).flags() & Qt.ItemFlag.ItemIsEditable
        dialog.assignments.setItem(3, 1, QTableWidgetItem("LH_A"))
        model.media = dialog.value()
        plan = build_print_plan(model, 2)
        assert plan.output_pages == 8 and plan.output_page(4).stock == "LH_A"
        # Row count must not become the key after a rule is removed.
        dialog.assignments.clearSelection()
        dialog.assignments.selectRow(1)
        dialog.remove_rows(dialog.assignments)
        dialog.add_rule()
        dialog.assignments.setItem(3, 1, QTableWidgetItem("LH_B"))
        model.media = dialog.value()
        assert build_print_plan(model, 2).output_page(2).stock == "LH_B"
    finally:
        dialog.reject()


def test_rule_modes_keep_separate_drafts_and_profile_load_replaces_them(app, monkeypatch):
    model = Template(pages=[PageSpec() for _ in range(3)])
    media = default_media()
    media.update(mode="template", assignments={page.id: stock for page, stock in
                 zip(model.pages, ("LH_A", "LH_B", "LH_C"), strict=True)})
    dialog = MediaDialog(media, {"kind": "template", "project": model.to_dict(), "records": 1})
    try:
        original = dialog.value()["assignments"]
        dialog.mode.setCurrentIndex(dialog.mode.findData("page"))
        assert dialog.value()["assignments"] == {"1": "LH_A", "2": "LH_B", "3": "LH_C"}
        dialog.assignments.setItem(0, 1, QTableWidgetItem("LH_C"))
        page_draft = dialog.value()["assignments"]
        dialog.mode.setCurrentIndex(dialog.mode.findData("role"))
        dialog.assignments.setItem(0, 1, QTableWidgetItem("LH_B"))
        role_draft = dialog.value()["assignments"]
        for mode, expected in (("template", original), ("page", page_draft), ("role", role_draft)):
            dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
            assert dialog.value()["assignments"] == expected
        dialog.assignments.removeRow(0)
        dialog.add_rule()
        dialog.assignments.setItem(3, 1, QTableWidgetItem("LH_C"))
        assert dialog.value()["assignments"]["SINGLE"] == "LH_C"
        # Loading a different profile must not resurrect the previous profile's draft.
        replacement = default_media()
        replacement["assignments"] = {"1": "LH_B"}
        dialog.fill(replacement)
        dialog.mode.setCurrentIndex(dialog.mode.findData("role"))
        assert dialog.value()["assignments"] == {}
        dialog.mode.setCurrentIndex(dialog.mode.findData("page"))
        assert dialog.value()["assignments"] == {"1": "LH_B"}
        monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][-1], True))
        dialog.mode.setCurrentIndex(dialog.mode.findData("template"))
        # Blank page rows are now visible for repair. Remove them to exercise
        # the explicit Add rule chooser rather than treating them as absent.
        for row in range(dialog.assignments.rowCount()-1, 0, -1):
            dialog.assignments.removeRow(row)
        dialog.add_rule()
        assert dialog.assignments.item(1, 0).data(Qt.ItemDataRole.UserRole) == model.pages[2].id
        dialog.assignments.removeRow(1)
        monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("", False))
        count = dialog.assignments.rowCount()
        dialog.add_rule()
        assert dialog.assignments.rowCount() == count
    finally:
        dialog.reject()


@pytest.mark.parametrize("command", ["duplicate", "paste"])
def test_rotated_copy_at_page_edge_is_clamped_and_undoable(app, command):
    window = CompositionWindow()
    element = Element(value="Rotated {{Name}}", x_mm=165, y_mm=100, width_mm=20, height_mm=70, rotation_deg=90)
    window._apply_template(Template(elements=[element]).to_dict(), element.id)
    window.undo.clear()
    try:
        original = asdict(window.page.elements[0])
        if command == "paste":
            window.object_command("copy")
        window.object_command(command)
        assert len(window.page.elements) == 2
        copied = window.page.elements[1]
        assert copied.id != element.id and copied.value == element.value and copied.rotation_deg == 90
        assert copied.font == element.font
        x0, y0, x1, y1 = element_bounds(copied)
        assert 0 <= x0 <= x1 <= 210 and 0 <= y0 <= y1 <= 297
        assert asdict(window.page.elements[0]) == original
        assert window.undo.count() == 1
        window.undo.undo()
        assert [asdict(e) for e in window.page.elements] == [original]
    finally:
        close_window(window)


def test_font_details_toggle_preserves_selection_and_unapplied_batch(app):
    window = CompositionWindow()
    window._apply_template(Template(elements=[Element(value="One"), Element(value="Two", y_mm=50)]).to_dict())
    try:
        window.show()
        window.canvas.select_ids([e.id for e in window.page.elements])
        window.properties.numbers["font_size"].setValue(18)
        snapshot = copy.deepcopy(window.template.to_dict())
        ids = window.canvas.selected_ids()
        for expanded in (True, False, True):
            window.properties.font_details_toggle.setChecked(expanded)
            assert window.properties.has_batch_draft()
            assert window.canvas.selected_ids() == ids
            assert window.template.to_dict() == snapshot
        assert window.batch_editor.apply()
        assert all(e.font.size_pt == 18 for e in window.page.elements)
    finally:
        window.batch_editor.revert()
        close_window(window)


def test_workflow_save_is_visible_and_saves_current_project(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    window = WorkflowWindow()
    try:
        window.show()
        target = tmp_path / "workflow.pdflow"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
        button = window.layout_toolbar.widgetForAction(window.actions["save"])
        assert button.isVisible()
        button.click()
        wait_until(lambda: window.active_worker is None)
        assert target.is_file() and window.project_path == target
        for index in (1, 2, 0):
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            assert button.isVisible()
    finally:
        window.undo.setClean()
        window.close()
        wait_until(lambda: not window.workers)
