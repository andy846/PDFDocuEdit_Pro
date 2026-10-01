from __future__ import annotations

from dataclasses import asdict

import pytest
from PyQt6.QtWidgets import QApplication

from composition.designer.glyph_dialog import GlyphRepairDialog
from composition.designer.workspace import CompositionWindow
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_configure_repair_in_designer_preserves_primary_and_has_undo(app):
    window = CompositionWindow()
    window.add_element("text", "Client standard Latin text")
    original = asdict(window.template.elements[0].font)
    object_id = window.template.elements[0].id
    window._record_font_error(f"Font preflight: Record 346, object {object_id}: U+7530")
    assert window.failed_record == 346 and window.failed_codepoint == "U+7530"
    assert not window.repair_error_button.isHidden()
    dialog = GlyphRepairDialog(window.template.elements[0], {}, window.failed_codepoint, window)
    dialog.family.setCurrentText("Noto Sans CJK HK")
    dialog._apply()
    assert dialog.choice["codepoint"] == "U+7530"
    window._request_font(dialog.choice)
    wait(lambda: not window.font_requests)
    updated = window.template.elements[0]
    assert asdict(updated.font) == original
    assert updated.glyph_repairs["U+7530"].family == "Noto Sans CJK HK"
    assert "U+7530" in window.properties.repair_status.text()
    window.properties.content.setPlainText("Still uses the client standard face")
    assert window.template.elements[0].glyph_repairs
    window.undo.undo()  # content
    window.undo.undo()  # repair
    assert not window.template.elements[0].glyph_repairs
    window.undo.redo()
    window.remove_glyph_repair(object_id, "U+7530")
    assert not window.template.elements[0].glyph_repairs
    assert asdict(window.template.elements[0].font) == original
    window.undo.undo()
    assert window.template.elements[0].glyph_repairs
    cleanup(window)


def test_incompatible_repair_face_keeps_entire_template_unchanged(app):
    window = CompositionWindow()
    window.add_element("text", "No silent substitution")
    before = window.template.to_dict()
    window._request_font({"element_id": window.template.elements[0].id,
                          "codepoint": "U+7530", "spec": {"family": "Noto Sans"}})
    wait(lambda: not window.font_requests)
    assert window.template.to_dict() == before
    assert "cannot render U+7530" in window.message.text()
    cleanup(window)
