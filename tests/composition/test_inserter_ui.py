"""Focused preset drafts, page placement, Undo and responsive layout checks."""
import copy
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QDialogButtonBox

from composition.designer.barcode_operations import apply_template_profile
from composition.designer.barcode_setup import BarcodeSetupDialog
from composition.engine.barcode_profiles import INSERTER_I25, BarcodeProfile
from composition.template.model import CompositionError, Element, PageSpec, Template


@pytest.fixture(autouse=True)
def readable_offscreen_fonts(qt_application):
    # The offscreen Windows platform lacks native font enumeration. Register
    # the actual UI face so DPI/layout checks use letters rather than tofu boxes.
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    if path.exists():
        from PyQt6.QtGui import QFont, QFontDatabase
        QFontDatabase.addApplicationFont(str(path))
        old = qt_application.font()
        qt_application.setFont(QFont("Segoe UI", 9))
        yield
        qt_application.setFont(old)
    else:
        yield


def source(pages=4):
    return Template(pages=[PageSpec(id=f"p{i}", elements=[Element(type="code128", width_mm=100, height_mm=14)]
                                   if i == 0 else []) for i in range(pages)])


def test_same_position_fronts_preserve_original_and_check_conflicts():
    model = source()
    before = model.to_dict()
    changed, summary = apply_template_profile(before, model.pages[0].id, model.elements[0].id,
                                             BarcodeProfile.inserter(), True, True)
    assert before == model.to_dict()
    assert [len(page["elements"]) for page in changed["pages"]] == [1, 0, 1, 0]
    first, third = changed["pages"][0]["elements"][0], changed["pages"][2]["elements"][0]
    assert first["id"] != third["id"]
    assert all(first[key] == third[key] for key in ("x_mm", "y_mm", "width_mm", "height_mm", "rotation_deg"))
    assert "1, 3" in summary and changed["media"]["duplex"]
    changed["pages"][2]["elements"].append({**copy.deepcopy(third), "id": "duplicate"})
    with pytest.raises(CompositionError, match="multiple inserter"):
        apply_template_profile(changed, model.pages[0].id, first["id"], BarcodeProfile.inserter(), True, True)
    changed["pages"][0]["elements"].append({**copy.deepcopy(first), "id": "duplicate_source"})
    with pytest.raises(CompositionError, match="already has another"):
        apply_template_profile(changed, model.pages[0].id, first["id"], BarcodeProfile.inserter(), True, True)


def test_all_copy_bounds_are_checked_atomically():
    model = source(2)
    model.pages[1].width_mm = 60
    before = model.to_dict()
    with pytest.raises(CompositionError, match="outside the page"):
        apply_template_profile(before, model.pages[0].id, model.elements[0].id, BarcodeProfile.inserter(), False, True)
    assert model.to_dict() == before


def test_invalid_insert_and_customer_drafts_stay_editable(qt_application):
    dialog = BarcodeSetupDialog(BarcodeProfile.inserter(),
        {"EnvelopeIndex": "1", "SheetNo": "1", "SheetCount": "2", "JobSheetNo": "1", "Customer": "000000123"}, symbology="i25")
    try:
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert dialog.start.text() == "00"
        assert ok.isEnabled() and "000000000000000000" in dialog.payload.text()
        dialog.insert_modes[0].setCurrentIndex(2)
        assert not ok.isEnabled() and dialog.insert_modes[0].currentData() == "conditional"
        dialog.insert_modes[0].setCurrentIndex(1)
        dialog.customer.setCurrentIndex(dialog.customer.findData("Customer"))
        assert ok.isEnabled() and dialog.candidate().inserter_parts(dialog.fields)["customer"] == "000000123"
        dialog.fields["Customer"] = "123"
        dialog.refresh()
        assert not ok.isEnabled() and "nine ASCII digits" in dialog.status.text()
        assert dialog.customer.currentData() == "Customer"
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_narrow_dialog_fixed_footer_and_full_combo_popup(qt_application, theme):
    from styles.theme import apply_theme
    apply_theme(qt_application, theme)
    dialog = BarcodeSetupDialog(BarcodeProfile.inserter(),
        {"EnvelopeIndex": "1", "SheetNo": "1", "SheetCount": "2", "JobSheetNo": "1"}, symbology="i25", template=True)
    try:
        dialog.resize(460, 360)
        dialog.show()
        qt_application.processEvents()
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            qt_application.processEvents()
            ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
            bottom = ok.mapTo(dialog, QPoint(ok.width(), ok.height()))
            assert ok.isVisible() and bottom.y() <= dialog.height() and bottom.x() <= dialog.width()
        dialog.printing.showPopup()
        assert dialog.body.width() <= dialog.scroll.viewport().width()
        assert dialog.printing.view().minimumWidth() >= min(dialog.printing.width(), dialog.screen().availableGeometry().width()-24)
        assert dialog.printing.view().maximumWidth() <= dialog.screen().availableGeometry().width()
        dialog.printing.hidePopup()
    finally:
        dialog.close()
        dialog.deleteLater()
        apply_theme(qt_application, "system")


def test_designer_apply_is_one_undo_and_cancel_restores_selector(qt_application, monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    import sys
    import traceback
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append("".join(traceback.format_exception(*args))))
    window = CompositionWindow()
    try:
        model = source()
        window._apply_template(model.to_dict(), model.elements[0].id)
        def apply(dialog):
            dialog.printing.setCurrentIndex(1)
            dialog.accept()
            return dialog.result()
        monkeypatch.setattr(BarcodeSetupDialog, "exec", apply)
        before = window.template.to_dict()
        window.properties.barcode_preset.setCurrentIndex(1)
        assert not errors, errors
        assert window.template.pages[0].elements[0].barcode_profile["preset"] == INSERTER_I25
        assert len(window.template.pages[2].elements) == 1
        window.undo.undo()
        assert window.template.to_dict() == before
        monkeypatch.setattr(BarcodeSetupDialog, "exec", lambda self: 0)
        window.properties.barcode_preset.setCurrentIndex(1)
        assert window.template.to_dict() == before
        assert window.properties.barcode_preset.currentData() == "generic"
    finally:
        close_window(window)


def test_overlay_preset_updates_required_read_scope_and_printing(qt_application, monkeypatch, tmp_path):
    from composition.designer.overlay_workspace import OverlayWindow
    from tests.composition.test_pdf_overlay_models import sample_spec
    from tests.composition.test_pdf_overlay_ui import finish
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    window = OverlayWindow()
    try:
        model = sample_spec(tmp_path)
        window.apply_spec(model.to_dict())
        window.canvas.select_ids([model.objects[1].element.id])
        def apply(dialog):
            dialog.printing.setCurrentIndex(1)
            dialog.accept()
            assert dialog.result() == dialog.DialogCode.Accepted, dialog.status.text()
            return dialog.result()
        monkeypatch.setattr(BarcodeSetupDialog, "exec", apply)
        before = window.spec.to_dict()
        window.properties.barcode_preset.setCurrentIndex(1)
        barcode = window.spec.objects[1]
        assert barcode.profile.preset == INSERTER_I25
        assert barcode.scope == window.spec.required_scope == "front" and barcode.control
        assert barcode.element.type == "i25" and window.spec.settings.duplex
        assert not window.properties.barcode_format.isEnabled()
        window.undo.undo()
        assert window.spec.to_dict() == before
    finally:
        finish(window)


def test_production_printing_is_visible_changes_counts_and_undo(qt_application, monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_inserter_production import template_for
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    window = CompositionWindow()
    try:
        model = template_for(pages=2, count=200, duplex=False)
        model.pages[1].elements.clear()
        window._apply_template(model.to_dict())
        window.tabs.setCurrentIndex(3)
        window.show()
        window.resize(960, 640)
        qt_application.processEvents()
        assert window.production_printing.isVisible() and window.production_printing.isEnabled()
        assert "Physical sheets: 400" in window.production_plan.text()
        assert "pages without an I25 control barcode: 2" in window.production_plan.text()
        before = window.template.to_dict()
        window.production_printing.setCurrentIndex(1)
        assert window.template.media["duplex"]
        assert "Physical sheets: 200" in window.production_plan.text()
        assert "Required control barcodes: 200" in window.production_plan.text()
        assert "pages without" not in window.production_plan.text()
        window.undo.undo()
        assert window.template.to_dict() == before and window.production_printing.currentData() is False
        window.undo.redo()
        assert window.production_printing.currentData() is True
    finally:
        close_window(window)


def test_migration_cancel_update_and_undo_preserve_project(qt_application, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from composition.designer.production_settings import confirm_i25_update
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_inserter_production import template_for
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    model = template_for(pages=2)
    for e in model.all_elements():
        e.barcode_profile.update(version=2, sheet_sequence_scope="envelope", group_start=7)
    window = CompositionWindow()
    try:
        window._apply_template(model.to_dict())
        before = window.template.to_dict()
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
        assert not confirm_i25_update(window, before)
        assert window.template.to_dict() == before and not window.undo.canUndo()
        calls = []
        def confirm(*args, **kwargs):
            calls.append(args)
            return QMessageBox.StandardButton.Yes
        monkeypatch.setattr(QMessageBox, "question", confirm)
        assert confirm_i25_update(window, before)
        assert len(calls) == 1
        assert all(e.barcode_profile["sheet_sequence_scope"] == "job" and e.barcode_profile["group_start"] == 0
                   for e in window.template.all_elements())
        assert confirm_i25_update(window, window.template.to_dict()) and len(calls) == 1
        window.undo.undo()
        assert window.template.to_dict() == before
    finally:
        close_window(window)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_production_review_duplex_and_footer_fit(qt_application, theme):
    from composition.designer.production_settings import ProductionReviewDialog
    from styles.theme import apply_theme
    from tests.composition.test_inserter_production import template_for
    apply_theme(qt_application, theme)
    model = template_for(pages=2, count=200, duplex=False)
    model.pages[1].elements.clear()
    before = model.to_dict()
    dialog = ProductionReviewDialog(model, 200)
    try:
        dialog.resize(460, 320)
        dialog.show()
        qt_application.processEvents()
        assert "Physical sheets: 400" in dialog.summary.text()
        dialog.printing.setCurrentIndex(1)
        assert "Physical sheets: 200" in dialog.summary.text() and "pages without" not in dialog.summary.text()
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        qt_application.processEvents()
        corner = ok.mapTo(dialog, QPoint(ok.width(), ok.height()))
        assert ok.isVisible() and corner.x() <= dialog.width() and corner.y() <= dialog.height()
        dialog.reject()
        assert model.to_dict() == before
    finally:
        dialog.close()
        dialog.deleteLater()
        apply_theme(qt_application, "system")


def test_production_placement_is_atomic_and_conflicts_do_not_change_project(qt_application, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_inserter_production import template_for
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][0], True))
    window = CompositionWindow()
    try:
        model = template_for(pages=2, duplex=False)
        model.pages[1].elements.clear()
        window._apply_template(model.to_dict())
        before = window.template.to_dict()
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
        window.place_inserter_fronts()
        assert window.template.to_dict() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        window.place_inserter_fronts()
        assert len(window.template.pages[1].elements) == 1
        assert window.template.pages[0].elements[0].x_mm == window.template.pages[1].elements[0].x_mm
        window.undo.undo()
        assert window.template.to_dict() == before
        model.pages[1].elements = [copy.deepcopy(model.elements[0]), copy.deepcopy(model.elements[0])]
        model.pages[1].elements[0].id = "duplicate1"
        model.pages[1].elements[1].id = "duplicate2"
        window._apply_template(model.to_dict())
        before = window.template.to_dict()
        errors = []
        monkeypatch.setattr(window, "_error", errors.append)
        window.place_inserter_fronts()
        assert errors and "multiple inserter" in errors[0] and window.template.to_dict() == before
    finally:
        close_window(window)


def test_active_media_printing_cannot_be_overridden(qt_application, monkeypatch):
    from composition.designer.production_settings import ProductionReviewDialog
    from tests.composition.test_media_duplex_sheets import four_page_template
    model = four_page_template()
    model.pages[0].elements.append(Element(type="i25", width_mm=100, barcode_profile=BarcodeProfile.inserter().to_dict()))
    dialog = ProductionReviewDialog(model, 2)
    try:
        assert not dialog.printing.isEnabled() and dialog.printing.currentData() is True
        assert "Printing follows Print Media" in dialog.summary.text()
    finally:
        dialog.deleteLater()


def test_configure_legacy_profile_requires_confirmation(qt_application, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    legacy = BarcodeProfile(version=2, preset=INSERTER_I25, group_start=9, validation="user_verified", machine="Test inserter")
    before = legacy.to_dict()
    dialog = BarcodeSetupDialog(legacy, {"EnvelopeIndex": "2", "SheetNo": "1", "SheetCount": "1", "JobSheetNo": "4"}, symbology="i25")
    try:
        assert dialog.start.text() == "00" and not dialog.start.isEnabled()
        assert dialog.candidate().inserter_parts(dialog.fields)["sheet"] == "03"
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Rejected and dialog.profile.to_dict() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Accepted
        assert dialog.profile.sheet_sequence_scope == "job" and dialog.profile.validation == "pending"
        assert legacy.to_dict() == before
    finally:
        dialog.close()
        dialog.deleteLater()


def test_production_review_cancel_does_not_start_worker_or_change_printing(qt_application, monkeypatch, tmp_path):
    from composition.designer.production_settings import ProductionReviewDialog
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_inserter_production import template_for
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    window = CompositionWindow()
    try:
        model = template_for(pages=2, duplex=False)
        model.pages[1].elements.clear()
        window._apply_template(model.to_dict())
        before = window.template.to_dict()
        def reject(dialog):
            dialog.printing.setCurrentIndex(1)
            dialog.reject()
            return dialog.result()
        monkeypatch.setattr(ProductionReviewDialog, "exec", reject)
        window.start_production(str(tmp_path / "not-created"))
        assert window.production_worker is None and window.template.to_dict() == before
        assert not (tmp_path / "not-created").exists()
    finally:
        close_window(window)
