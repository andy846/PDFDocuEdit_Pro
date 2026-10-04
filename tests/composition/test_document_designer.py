from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QApplication

from composition.designer.workspace import CompositionWindow
from composition.engine.fonts import load_font
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_document_designer_layers_arrange_and_type_properties(app):
    window = CompositionWindow()
    window.add_element("text", "First", x=20, y=20)
    window.add_element("text", "Second", x=100, y=70)
    first, second = [e.id for e in window.template.elements]
    assert "Document Designer" in window.windowTitle()
    window.canvas.select_ids([first, second])
    window.arrange_objects("left")
    assert [e.x_mm for e in window.template.elements] == [20, 20]
    window.undo.undo()
    assert [e.x_mm for e in window.template.elements] == [20, 100]
    window.arrange_objects("front")
    assert set(window.canvas.selected_ids()) == {first, second}
    window.canvas.select_ids([first])
    window.arrange_objects("front")
    assert window.template.elements[-1].id == first
    assert window.layers.item(0).data(256) == first
    window.undo.undo()
    assert window.template.elements[0].id == first
    window.add_element("line", x=20, y=120)
    assert window.properties.font_group.isHidden()
    assert window.properties.content_group.isHidden()
    assert not window.properties.appearance_group.isHidden()
    window.object_command("copy")
    assert window.actions["paste"].isEnabled()
    cleanup(window)


@pytest.mark.skipif(os.name != "nt", reason="Windows font choice UI")
def test_searchable_windows_font_style_is_exact_and_can_be_undone(app):
    window = CompositionWindow()
    window.add_element("text", "Windows font")
    wait(lambda: "Arial" in window.properties.catalogue)
    original = window.template.to_dict()
    window.properties.font_family.setCurrentIndex(window.properties.font_family.findText("Arial"))
    wait(lambda: not window.font_requests and bool(window.template.elements[0].font.file))
    assert window.template.elements[0].font.family == "Arial"
    index = window.properties.font_style.findText("Bold")
    assert index >= 0
    window.properties.font_style.setCurrentIndex(index)
    window.properties._style_chosen()
    wait(lambda: not window.font_requests)
    selected = window.template.elements[0].font
    font, _ = load_font(selected)
    assert font.is_bold
    assert not selected.bold, "Actual file face, not simulated bold"
    window.undo.undo()
    window.undo.undo()
    assert window.template.to_dict() == original
    cleanup(window)


def test_font_catalogue_does_not_reset_pending_geometry(app):
    window = CompositionWindow()
    window.add_element("text", "Pending geometry")
    window.properties.numbers["x_mm"].setValue(37.5)
    window.properties.set_catalogue({"faces": []})
    assert window.properties.numbers["x_mm"].value() == 37.5
    window.properties.apply()
    assert window.template.elements[0].x_mm == 37.5
    cleanup(window)
