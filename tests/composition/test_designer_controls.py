from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.data_dialog import DataDialog
from composition.designer.workspace import CompositionWindow
from composition.engine.assets import asset_root

pytestmark = pytest.mark.skipif(
    not (asset_root() / "fonts" / "NotoSans-Regular.ttf").exists(), reason="Prepared font runtime required."
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(predicate):
    end = time.monotonic()+20
    while not predicate() and time.monotonic() < end:
        QApplication.processEvents()
        QTest.qWait(10)
    assert predicate()


def cleanup(window):
    window.undo.setClean()
    window.close()
    wait(lambda: not window.workers)


def test_multiselection_keyboard_and_pending_text(app):
    window = CompositionWindow()
    window.add_element("text", "First", x=20)
    window.add_element("text", "Second", x=100)
    ids = [e.id for e in window.template.elements]
    window.canvas.set_template(window.template, ids)
    QTest.keyClick(window.canvas, Qt.Key.Key_Right)
    QTest.keyClick(window.canvas, Qt.Key.Key_Right)
    assert [e.x_mm for e in window.template.elements] == [21, 101]
    assert set(window.canvas.selected_ids()) == set(ids)
    window.object_command("copy")
    window.object_command("paste")
    assert len(window.template.elements) == 4
    window.undo.undo()
    assert len(window.template.elements) == 2
    window.canvas.set_template(window.template, ids[0])
    window._selection(ids[0])
    window.properties.content.setPlainText("Latest value")
    assert window.template.elements[0].value == "Latest value"
    window._selection(ids[1])
    assert window.template.elements[0].value == "Latest value"
    cleanup(window)


def test_import_dialog_original_names_and_mapping(app, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text(" Customer Name \tBalance\nLee\t10\n", encoding="utf-8")
    dialog = DataDialog(str(source), tmp_path)
    wait(lambda: dialog.mapping.rowCount() == 2)
    assert dialog.mapping.item(0, 0).text() == " Customer Name "
    assert dialog.mapping.item(0, 1).text() == "Customer_Name"
    dialog.mapping.item(0, 1).setText("Name")
    assert dialog.config().mapping[" Customer Name "] == "Name"
    dialog.reject()
    wait(lambda: not dialog.workers)


def test_mouse_drag_commits_one_undoable_geometry_edit(app):
    from PyQt6.QtCore import QPointF
    window = CompositionWindow()
    window.show()
    window.add_element("text", "Drag me")
    QTest.qWait(30)
    window.canvas.fit_page()
    item = window.canvas.element_items[0]
    start = window.canvas.mapFromScene(item.pos()+QPointF(15, 5))
    end = window.canvas.mapFromScene(item.pos()+QPointF(25, 15))
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), end, 50)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    QApplication.processEvents()
    assert window.template.elements[0].x_mm > 25
    moved = window.template.elements[0].x_mm
    window.undo.undo()
    assert window.template.elements[0].x_mm == 20
    window.undo.redo()
    assert window.template.elements[0].x_mm == moved
    cleanup(window)


def test_resize_and_properties_do_not_dirty_unchanged_geometry(app):
    from PyQt6.QtCore import QPointF
    window = CompositionWindow()
    window.show()
    window.add_element("text", "Resize me")
    QTest.qWait(30)
    window.canvas.fit_page()
    item = window.canvas.element_items[0]
    start = window.canvas.mapFromScene(item.pos()+item.rect().bottomRight()-QPointF(.5, .5))
    end = window.canvas.mapFromScene(item.pos()+item.rect().bottomRight()+QPointF(10, 5))
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), end, 50)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert window.template.elements[0].width_mm > 75
    window.undo.undo()
    assert window.template.elements[0].width_mm == 70
    before, after = window.template.to_dict(), window.template.to_dict()
    after["elements"][0]["x_mm"] = 20.123456
    window._commit(before, after, "Imported precision", after["elements"][0]["id"])
    window.undo.setClean()
    window.properties.apply()
    assert window.undo.isClean()
    assert window.template.elements[0].x_mm == 20.123456
    cleanup(window)
