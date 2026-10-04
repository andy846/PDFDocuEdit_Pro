from __future__ import annotations

import copy
from dataclasses import asdict

import pytest
from PyQt6.QtWidgets import QApplication

from composition.designer.workspace import CompositionWindow
from composition.engine.fonts import load_font
from composition.template.model import (
    ConditionGroup,
    Element,
    ElementRules,
    FontSpec,
    RuleCondition,
    Template,
)
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="session")
def app():
    # Qt permits one application per process; keep it alive across later GUI modules.
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w = CompositionWindow()
    items = [
        Element(value="First {{Account}}", font=FontSpec(size_pt=9), height_mm=20,
                glyph_repairs={"U+7530": FontSpec(family="Noto Sans CJK HK")}),
        Element(value="Second", y_mm=55, height_mm=20,
                font=FontSpec(family="Noto Sans CJK HK", bold=True, size_pt=17),
                colour="#000080", line_spacing=1.8, align="right",
                rules=ElementRules(ConditionGroup("all", [RuleCondition("Scheme_Code", value="GS")]))),
        Element(value="Unselected", y_mm=95, height_mm=20),
        Element(type="rectangle", y_mm=125, height_mm=20),
        Element(type="code128", value="000123", y_mm=155, height_mm=25, width_mm=100,
                show_barcode_text=True, font=FontSpec(size_pt=11)),
        Element(type="qr", value="000123", y_mm=200, height_mm=35, width_mm=35),
    ]
    w._apply_template(Template(elements=items).to_dict())
    w.undo.clear()
    w.show()
    w.canvas.select_ids([items[0].id, items[1].id])
    yield w
    w.production_worker = w.import_worker = None
    w.font_requests.clear()
    w.content_invalid = False
    w.batch_editor.revert()
    cleanup(w)


def snapshots(window):
    return [asdict(e) for e in window.page.elements]


def test_mixed_size_changes_only_size_and_one_undo(window):
    before = snapshots(window)
    assert len(window.properties.bulk_ids) == 2
    assert "Mixed fonts, sizes" in window.properties.empty.text()
    assert not window.properties.content_group.isVisible()
    assert window.properties.geometry.isVisible()
    control = window.properties.numbers["font_size"]
    control.setValue(14)
    control.editingFinished.emit()
    assert snapshots(window) == before
    assert window.batch_editor.apply()
    after = snapshots(window)
    expected = copy.deepcopy(before)
    for e in expected[:2]:
        e["font"]["size_pt"] = 14
    assert after == expected
    assert window.undo.count() == 1 and len(window.canvas.selected_ids()) == 2
    window.undo.undo()
    assert snapshots(window) == before
    window.undo.redo()
    assert snapshots(window) == expected


@pytest.mark.parametrize("key,value", [("align", "center"), ("vertical_align", "bottom"),
                                       ("line_spacing", 2.1), ("colour", "#ff8800")])
def test_bulk_layout_colour_preserves_other_properties(window, key, value):
    before = snapshots(window)
    p = window.properties
    if key == "align":
        p.alignment.setCurrentText(value)
    elif key == "vertical_align":
        p.vertical.setCurrentText(value)
    elif key == "line_spacing":
        p.numbers[key].setValue(value)
        p.numbers[key].editingFinished.emit()
    else:
        p.colour.setText(value)
        p.colour.editingFinished.emit()
    assert window.batch_editor.apply()
    expected = copy.deepcopy(before)
    for e in expected[:2]:
        e[key] = value
    assert snapshots(window) == expected
    window.undo.undo()
    assert snapshots(window) == before


def test_toolbar_size_formats_text_and_human_barcode_only(window):
    ids = [e.id for e in window.page.elements]
    window.canvas.select_ids([ids[0], ids[3], ids[4], ids[5]])
    assert len(window.properties.bulk_ids) == 1
    window.properties.include_barcode.setChecked(True)
    assert len(window.properties.bulk_ids) == 2
    before = snapshots(window)
    window.font_size_tool.setValue(15)
    window.font_size_tool.editingFinished.emit()
    assert window.batch_editor.apply()
    expected = copy.deepcopy(before)
    for index in [0, 4]:
        expected[index]["font"]["size_pt"] = 15
    assert snapshots(window) == expected
    assert window.undo.count() == 1


def test_same_family_explicit_selection_applies_to_mixed_fonts_only(window):
    before = snapshots(window)
    p = window.properties
    p.font_family.setCurrentText("Noto Sans")
    p.font_family.activated.emit(p.font_family.currentIndex())
    assert window.batch_editor.apply()
    expected = copy.deepcopy(before)
    for e in expected[:2]:
        e["font"].update(family="Noto Sans", file="", bold=False, italic=False)
    assert snapshots(window) == expected
    assert window.undo.count() == 1
    window.undo.undo()
    assert snapshots(window) == before


def test_bundled_bold_style_applies_without_changing_individual_sizes(window):
    before = snapshots(window)
    p = window.properties
    p.font_family.setCurrentText("Noto Sans")
    p._set_styles("Noto Sans")
    p.font_style.setCurrentIndex(p.font_style.findText("Bold"))
    p.font_style.activated.emit(p.font_style.currentIndex())
    assert window.batch_editor.apply()
    expected = copy.deepcopy(before)
    for e in expected[:2]:
        e["font"].update(family="Noto Sans", file="", bold=True, italic=False)
    assert snapshots(window) == expected


def test_passive_apply_and_font_focus_do_not_overwrite_mixed_values(window):
    before = snapshots(window)
    window.properties.apply()
    window.properties._typed_family()
    window.properties.numbers["font_size"].editingFinished.emit()
    window.properties.numbers["line_spacing"].editingFinished.emit()
    window.properties.colour.editingFinished.emit()
    window.font_size_tool.editingFinished.emit()
    assert snapshots(window) == before and window.undo.count() == 0


def test_non_text_selection_has_no_typography_controls(window):
    ids = [e.id for e in window.page.elements]
    window.canvas.select_ids([ids[3], ids[5]])
    before = snapshots(window)
    assert window.properties.element is not None and not window.font_size_tool.isEnabled()
    assert not window.properties.bulk_ids
    assert window.properties.font_group.isHidden()
    assert window.properties.text_layout_group.isHidden()
    window.properties.apply_field("font_size")
    assert snapshots(window) == before


@pytest.mark.parametrize("mode", ["preview", "production", "import", "font_pending", "invalid"])
def test_busy_or_preview_blocks_bulk_mutation(window, mode):
    before = snapshots(window)
    if mode == "preview":
        window.tabs.setCurrentIndex(2)
    elif mode == "production":
        window.production_worker = object()
    elif mode == "import":
        window.import_worker = object()
    elif mode == "font_pending":
        window.font_requests["other"] = "token"
    else:
        window.content_invalid = True
    window.properties.numbers["font_size"].setValue(22)
    window.properties.apply_field("font_size")
    assert snapshots(window) == before


def test_windows_exact_face_prepared_once_and_applied_atomically(window):
    wait(lambda: bool(window.properties.catalogue))
    assert any(f["usable"] and f["style"] == "Bold" for f in window.properties.catalogue["Arial"])
    before = snapshots(window)
    calls = []
    original = window._worker

    def worker(request, *args, **kwargs):
        calls.append(request["task"])
        return original(request, *args, **kwargs)

    window._worker = worker
    p = window.properties
    p.loading = True
    p.font_family.setCurrentText("Arial")
    p._set_styles("Arial")
    p.font_style.setCurrentIndex(p.font_style.findText("Bold"))
    p.loading = False
    p.font_style.activated.emit(p.font_style.currentIndex())
    assert not calls
    assert window.batch_editor.apply(wait=True)
    assert calls.count("font_export") == 1
    assert window.undo.count() == 1
    after = snapshots(window)
    for old, new in zip(before[:2], after[:2], strict=True):
        assert new["font"]["size_pt"] == old["font"]["size_pt"]
        assert new["glyph_repairs"] == old["glyph_repairs"] and new["rules"] == old["rules"]
        assert new["font"]["family"] == "Arial" and new["font"]["file"]
    assert load_font(window.page.elements[0].font)[0].is_bold
    assert after[0]["font"]["file"] == after[1]["font"]["file"] and after[2:] == before[2:]
    window.undo.undo()
    assert snapshots(window) == before
    window.undo.redo()
    assert snapshots(window) == after


def hold_request(window):
    callbacks = []
    original = window._worker

    def hold(request, success, failure=None):
        if request["task"] == "font_export":
            callbacks.append((success, failure))
            return object()
        return original(request, success, failure)

    window._worker = hold
    ids = list(window.properties.bulk_ids)
    window._request_font({"element_id": ids[0], "element_ids": ids, "face": {"fake": True}})
    assert len(callbacks) == 1
    return callbacks[0], ids


def test_failed_face_keeps_all_fonts_and_reports_error(window):
    before = snapshots(window)
    (ready, failed), ids = hold_request(window)
    failed("Font unavailable")
    assert not window.font_requests and snapshots(window) == before
    assert "Font unavailable" in window.message.text()


def test_stale_font_completion_after_undo_cannot_override_new_sizes(window):
    (ready, failed), ids = hold_request(window)
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][0]["elements"][0]["font"]["size_pt"] = 23
    window._commit(before, after, "Other change", window.canvas.selected_ids())
    expected = snapshots(window)
    ready({"file": "", "family": "Noto Sans", "style": "Regular"})
    assert snapshots(window) == expected and not window.font_requests
    assert "No batch font change applied" in window.message.text()


def test_async_face_targets_original_selection_not_later_selection(window):
    before = snapshots(window)
    (ready, failed), ids = hold_request(window)
    third = window.page.elements[2].id
    window.canvas.select_ids([third])
    ready({"file": "", "family": "Noto Sans", "style": "Regular"})
    assert window.page.elements[1].font.family == "Noto Sans"
    assert snapshots(window)[2:] == before[2:]
    assert window.canvas.selected_ids() == [third] and not window.font_requests

def test_typing_first_size_explicitly_can_unify_mixed_sizes(window):
    from PyQt6.QtTest import QTest
    control = window.properties.numbers["font_size"]
    control.setFocus()
    control.lineEdit().selectAll()
    QTest.keyClicks(control.lineEdit(), "9")
    control.editingFinished.emit()
    assert window.batch_editor.apply()
    assert [e.font.size_pt for e in window.page.elements[:2]] == [9, 9]
    assert window.undo.count() == 1

def test_late_error_after_cancel_does_not_replace_current_message(window):
    (ready, failed), ids = hold_request(window)
    window._request_font({"cancel": True, "element_id": ids[0], "element_ids": ids})
    window.message.setText("Current project")
    failed("Stale missing font error")
    assert not window.font_requests and window.message.text() == "Current project"

def test_toolbar_draft_survives_real_background_preview_refresh(window):
    window.font_size_tool.setValue(12)
    window._schedule_preview()
    wait(lambda: window.canvas.preview_item is not None)
    assert window.font_size_tool.value() == 12 and window.toolbar_size_dirty
    window.font_size_tool.editingFinished.emit()
    assert window.batch_editor.apply()
    assert [e.font.size_pt for e in window.page.elements[:2]] == [12, 12]


def test_toolbar_draft_does_not_apply_to_a_later_selection(window):
    before = snapshots(window)
    window.font_size_tool.setValue(12)
    window.canvas.select_ids([window.page.elements[2].id])
    assert not window.toolbar_size_dirty and window.font_size_tool.value() == 10
    window.font_size_tool.editingFinished.emit()
    assert snapshots(window) == before
