from __future__ import annotations

import copy
from dataclasses import asdict

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from composition.designer.repeat_objects import RepeatObjectsDialog, repeat_selection
from composition.designer.workspace import CompositionWindow
from composition.engine.renderer import render_preview
from composition.template.model import (
    CompositionError,
    Element,
    FontSpec,
    PageSpec,
    Template,
)
from composition.template.serializer import load_project, save_project
from tests.composition.test_workspace import close_window


def sample():
    return Template(pages=[
        PageSpec(id="first", name="Letter", elements=[
            Element(id="seq", value="{{Seq}}", x_mm=25.5, y_mm=270, width_mm=40, height_mm=8,
                    font=FontSpec(size_pt=12), glyph_repairs={"U+7530": FontSpec()}),
            Element(id="ref", value="Reference: {{Ref}}", x_mm=80, y_mm=270, width_mm=80, height_mm=8),
            Element(id="barcode", type="code128", value="{{Ref}}", x_mm=25.5, y_mm=250, width_mm=50, height_mm=12),
        ]),
        PageSpec(id="second", name="Terms", elements=[Element(value="Terms")]),
        PageSpec(id="third", name="Appendix"),
    ])


def test_exact_repeat_preserves_group_payload_backgrounds_and_unique_ids():
    raw = sample().to_dict()
    raw["pages"][1]["background"] = "existing-background.pdf"
    before = copy.deepcopy(raw)
    after = repeat_selection(raw, "first", ["seq", "ref", "barcode"], ["second", "third"])
    assert raw == before
    assert after["pages"][0] == before["pages"][0]
    assert after["pages"][1]["background"] == "existing-background.pdf"
    assert after["pages"][1]["elements"][0] == before["pages"][1]["elements"][0]
    for page in after["pages"][1:]:
        for source, copied in zip(before["pages"][0]["elements"], page["elements"][-3:], strict=True):
            assert {k: v for k, v in source.items() if k != "id"} == {
                k: v for k, v in copied.items() if k != "id"}
    ids = [e["id"] for p in after["pages"] for e in p["elements"]]
    assert len(ids) == len(set(ids))
    # No link: later edits to a copied field do not propagate to other pages.
    after["pages"][1]["elements"][-3]["font"]["size_pt"] = 18
    assert after["pages"][0]["elements"][0]["font"]["size_pt"] == 12
    assert after["pages"][2]["elements"][0]["font"]["size_pt"] == 12


def test_bottom_distance_moves_whole_group_and_validates_rotated_bounds():
    raw = sample().to_dict()
    raw["pages"][1]["height_mm"] = 210
    raw["pages"][0]["elements"][0]["rotation_deg"] = 10
    after = repeat_selection(raw, "first", ["seq", "ref"], ["second"], "bottom")
    assert [e["y_mm"] for e in after["pages"][1]["elements"][-2:]] == [183, 183]
    assert after["pages"][1]["elements"][-2]["rotation_deg"] == 10
    with pytest.raises(CompositionError, match="outside the page"):
        repeat_selection(raw, "first", ["seq", "ref"], ["second"], "position")
    # The unrotated 40 mm box fits, but its rotated extent exceeds this page.
    raw["pages"][2]["width_mm"] = 65.6
    with pytest.raises(CompositionError, match="outside the page"):
        repeat_selection(raw, "first", ["seq"], ["third"])


@pytest.mark.parametrize("targets,selected,anchor", [
    ([], ["seq"], "position"), (["first"], ["seq"], "position"),
    (["missing"], ["seq"], "position"), (["third"], [], "position"),
    (["third"], ["missing"], "position"), (["third"], ["seq"], "unknown"),
])
def test_invalid_requests_do_not_change_source(targets, selected, anchor):
    raw = sample().to_dict()
    before = copy.deepcopy(raw)
    with pytest.raises(CompositionError):
        repeat_selection(raw, "first", selected, targets, anchor)
    assert raw == before


def test_failure_on_later_page_is_atomic():
    raw = sample().to_dict()
    raw["pages"][2]["width_mm"] = 50
    before = copy.deepcopy(raw)
    with pytest.raises(CompositionError, match="Appendix"):
        repeat_selection(raw, "first", ["seq", "ref"], ["second", "third"])
    assert raw == before


def test_saved_three_page_template_renders_fields_at_identical_pdf_coordinates(tmp_path):
    model = sample()
    # Text-only render isolates exact footer placement from barcode symbology tests.
    model.pages[0].elements = model.pages[0].elements[:2]
    model.pages[0].elements[0].glyph_repairs = {}
    repeated = Template.from_dict(repeat_selection(model.to_dict(), "first", ["seq", "ref"], ["second", "third"]))
    loaded = load_project(save_project(repeated, tmp_path / "footer.pdcx"))
    with fitz.open(stream=render_preview(loaded, {"Seq": "000123", "Ref": "A987"}), filetype="pdf") as pdf:
        assert len(pdf) == 3
        for text in ("000123", "Reference: A987"):
            rects = [page.search_for(text)[0] for page in pdf]
            assert all(tuple(rect) == pytest.approx(tuple(rects[0]), abs=.001) for rect in rects[1:])


@pytest.fixture
def window(qt_application, monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    value = CompositionWindow()
    value._apply_template(sample().to_dict(), ["seq", "ref"], page_id="first")
    value.undo.clear()
    yield value
    close_window(value)


def test_repeat_dialog_validation_and_page_bottom_option(qt_application):
    raw = sample().to_dict()
    raw["pages"][1]["height_mm"] = 210
    dialog = RepeatObjectsDialog(raw, "first", ["seq", "ref"])
    try:
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not ok.isEnabled()
        dialog.anchor.setCurrentIndex(1)
        assert ok.isEnabled() and "sizes differ" in dialog.status.text()
        dialog.check_all(False)
        assert not ok.isEnabled()
        dialog.pages.item(0).setCheckState(Qt.CheckState.Checked)
        assert dialog.target_ids() == ["second"] and ok.isEnabled()
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.result_value["pages"][1]["elements"][-1]["y_mm"] == 183
    finally:
        dialog.close()


def test_repeat_single_undo_preserves_current_page_selection_zoom(window, monkeypatch):
    original = window.template.to_dict()
    window.canvas.set_zoom(1.4)
    monkeypatch.setattr(RepeatObjectsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.actions["repeat_pages"].trigger()
    assert window.undo.count() == 1
    assert window.active_page_id == "first" and set(window.canvas.selected_ids()) == {"seq", "ref"}
    assert window.canvas.transform().m11() == pytest.approx(1.4 * 96/25.4)
    assert len(window.template.pages[1].elements) == 3 and len(window.template.pages[2].elements) == 2
    repeated = window.template.to_dict()
    window.undo.undo()
    assert window.template.to_dict() == original
    window.undo.redo()
    assert window.template.to_dict() == repeated


def test_paste_in_place_shortcut_keeps_exact_position_and_normal_paste_offset(window):
    window.object_command("copy")
    window.select_template_page(2)
    window.tabs.setCurrentIndex(1)
    window.show()
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert len(window.page.elements) == 2
    assert [(e.x_mm, e.y_mm) for e in window.page.elements] == [(25.5, 270), (80, 270)]
    assert set(window.canvas.selected_ids()) == {e.id for e in window.page.elements}
    window.undo.undo()
    assert window.page.elements == []
    window.object_command("paste")
    assert [(e.x_mm, e.y_mm) for e in window.page.elements] == [(28.5, 273), (83, 273)]


def test_paste_rejected_without_partial_changes_and_repeat_cancel(window, monkeypatch):
    window.object_command("copy")
    raw = window.template.to_dict()
    raw["pages"][2]["width_mm"] = 100
    window._apply_template(raw, [], page_id="third")
    before = window.template.to_dict()
    count = window.undo.count()
    window.object_command("paste_in_place")
    assert window.template.to_dict() == before and window.undo.count() == count
    assert "outside the page" in window.message.text()
    window.select_template_page(0)
    window.canvas.select_ids(["seq", "ref"])
    monkeypatch.setattr(RepeatObjectsDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.actions["repeat_pages"].trigger()
    assert window.template.to_dict() == before and window.undo.count() == count


def test_actions_lock_in_preview_and_busy_and_single_page(window):
    window.object_command("copy")
    assert window.actions["repeat_pages"].isEnabled() and window.actions["paste_in_place"].isEnabled()
    window.canvas.mode_preview = True
    window._update_actions()
    assert not window.actions["repeat_pages"].isEnabled() and not window.actions["paste_in_place"].isEnabled()
    window.canvas.mode_preview = False
    window.batch_pending = True
    window._update_actions()
    assert not window.actions["repeat_pages"].isEnabled()
    window.batch_pending = False
    window._apply_template(Template(elements=[Element(id="one")]).to_dict(), ["one"])
    assert not window.actions["repeat_pages"].isEnabled()


def test_duplicate_targets_are_not_copied_twice():
    after = repeat_selection(sample().to_dict(), "first", ["seq"], ["third", "third"])
    assert len(after["pages"][2]["elements"]) == 1
    assert after["pages"][2]["elements"][0]["font"] == asdict(FontSpec(size_pt=12))
