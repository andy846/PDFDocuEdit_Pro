from __future__ import annotations

import copy
from dataclasses import asdict

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from composition.designer.workspace import CompositionWindow
from composition.template.model import DataConfig, FontSpec
from composition.template.serializer import load_project
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_page_duplicate_order_delete_undo_and_fonts(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Client face", font=FontSpec(family="Arial", size_pt=12))
        before, after = window.template.to_dict(), window.template.to_dict()
        after["pages"][0]["elements"][0]["glyph_repairs"]["U+E473"] = asdict(FontSpec(family="MingLiU_HKSCS"))
        window._commit(before, after, "Repair config")
        original = copy.deepcopy(window.page)
        window.actions["page_duplicate"].trigger()
        assert len(window.template.pages) == 2 and window.page_index == 1
        duplicate_id = window.active_page_id
        assert window.page.id != original.id and window.page.elements[0].id != original.elements[0].id
        assert window.page.elements[0].font == original.elements[0].font
        assert window.page.elements[0].glyph_repairs == original.elements[0].glyph_repairs
        window.actions["page_up"].trigger()
        assert window.page_index == 0 and window.active_page_id == duplicate_id
        window.undo.undo()
        assert window.page_index == 1 and window.active_page_id == duplicate_id
        window.actions["page_delete"].trigger()
        assert len(window.template.pages) == 1
        window.undo.undo()
        assert len(window.template.pages) == 2 and window.page_index == 1
        window.undo.redo()
        assert len(window.template.pages) == 1
        assert not window.actions["page_delete"].isEnabled()
        window.delete_template_page()
        assert len(window.template.pages) == 1
    finally:
        cleanup(window)


def test_active_page_canvas_keyboard_copy_and_switch_preserve_edits(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Page one")
        first = window.page.elements[0].id
        window.object_command("copy")
        window.add_template_page()
        second_page = window.active_page_id
        window.object_command("paste")
        assert window.page.elements[0].id != first
        window.canvas.setFocus()
        window.canvas.select_ids([window.page.elements[0].id])
        QTest.keyClick(window.canvas, Qt.Key.Key_Right)
        assert window.page.elements[0].x_mm == 23.5
        assert window.template.pages[0].elements[0].x_mm == 20
        window.properties.content.setPlainText("Page two edited")
        window.page_combo.setCurrentIndex(0)
        assert window.template.pages[1].elements[0].value == "Page two edited"
        window.undo.undo()
        assert window.active_page_id == second_page and window.page.elements[0].value == "Page one"
        window.undo.redo()
        assert window.page.elements[0].value == "Page two edited"
        window.failed_object = window.template.pages[0].elements[0].id
        window.review_failed_object()
        assert window.page_index == 0 and window.properties.element.id == first
    finally:
        cleanup(window)


def test_background_response_targets_requested_page_not_current_page(app, tmp_path, monkeypatch):
    window = CompositionWindow()
    try:
        requests = []
        monkeypatch.setattr(window, "_worker", lambda request, callback, *a: requests.append((request, callback)))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("background.pdf", ""))
        from PyQt6.QtWidgets import QInputDialog
        monkeypatch.setattr(QInputDialog, "getInt", lambda *a: (1, True))
        window.add_background()
        window.add_template_page()
        result = {"background": str(tmp_path/"snapshot.pdf"), "width_mm": 148, "height_mm": 210}
        requests[0][1](result)
        assert window.template.pages[0].background == result["background"]
        assert window.page_index == 1 and window.page.background == ""
        assert window.template.pages[0].width_mm == 148
    finally:
        cleanup(window)


def test_multipage_ui_save_preview_and_production(app, tmp_path, monkeypatch):
    window = CompositionWindow()
    try:
        window.show()
        window.resize(960, 640)
        window.add_element("text", "Front {{Name}}")
        window.add_template_page()
        window.add_element("text", "Back {{Name}}")
        source = tmp_path/"data.csv"
        source.write_text("Name\nAlice\nBob\n", encoding="utf-8")
        window._start_import(DataConfig(path=str(source)))
        wait(lambda: window.import_worker is None)
        assert "4 expected pages" in window.production_heading.text()
        window.tabs.setCurrentIndex(2)
        window.record.setValue(2)
        wait(lambda: window.canvas.preview_item is not None)
        target = tmp_path/"pages.pdcx"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
        assert window.save_project()
        assert len(load_project(target).pages) == 2 and window.page_index == 1
        window.start_production(str(tmp_path/"output"))
        wait(lambda: window.production_worker is None)
        assert window.last_output, window.production_summary.toPlainText()
        with fitz.open(window.last_output) as doc:
            assert [page.get_text().strip() for page in doc] == ["Front Alice", "Back Alice", "Front Bob", "Back Bob"]
        assert "Expected pages: 4" in window.production_summary.toPlainText()
    finally:
        cleanup(window)
