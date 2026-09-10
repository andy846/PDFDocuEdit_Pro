import sys

import fitz
import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from core.page_plan import POINTS_PER_MM
from dialogs.document_dialogs import VisualOrganizerDialog
from dialogs.organizer_tools import BlankPagesDialog


@pytest.mark.parametrize("paper,landscape,expected", [
    (0, False, (300, 500)), (0, True, (300, 500)),
    (1, False, (210 * POINTS_PER_MM, 297 * POINTS_PER_MM)),
    (1, True, (297 * POINTS_PER_MM, 210 * POINTS_PER_MM)),
    (2, False, (215.9 * POINTS_PER_MM, 279.4 * POINTS_PER_MM)),
    (3, True, (140 * POINTS_PER_MM, 100 * POINTS_PER_MM)),
])
def test_blank_dialog_shows_and_changes_dimensions(monkeypatch, paper, landscape, expected):
    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    dialog = BlankPagesDialog((300, 500))
    try:
        dialog.show()
        app.processEvents()
        assert not errors, errors
        assert callable(dialog.width) and callable(dialog.height)
        assert dialog.width() > 0 and dialog.height() > 0
        dialog.paper.setCurrentIndex(paper)
        if paper == 3:
            dialog.width_mm.setValue(100)
            dialog.height_mm.setValue(140)
        dialog.orientation.setCurrentIndex(int(landscape))
        assert dialog.page_size() == pytest.approx(expected)
    finally:
        dialog.close()


@pytest.mark.parametrize("accept", [False, True])
def test_blank_button_opens_real_dialog_and_cancel_or_insert(monkeypatch, accept):
    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    with fitz.open() as doc:
        doc.new_page(width=300, height=500)
        organizer = VisualOrganizerDialog(doc)
        organizer.show()
        app.processEvents()
        organizer._select_expression("1")
        before = organizer.pages.page_plan()

        def finish():
            dialog = app.activeModalWidget()
            try:
                assert isinstance(dialog, BlankPagesDialog)
                assert dialog.isVisible()
                dialog.count.setValue(2)
                controls = dialog.findChild(QDialogButtonBox)
                role = QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel
                QTest.mouseClick(controls.button(role), Qt.MouseButton.LeftButton)
            except Exception as exc:
                errors.append(exc)
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(30, finish)
        button = next(b for b in organizer.findChildren(QPushButton) if b.text() == "Blank pages")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert not errors, errors
        if accept:
            assert organizer.pages.count() == 3
            assert [p.page_size for p in organizer.pages.page_plan()[1:]] == [(300, 500), (300, 500)]
            organizer._undo()
            assert organizer.pages.page_plan() == before
            organizer._redo()
            assert organizer.pages.count() == 3
        else:
            assert organizer.pages.page_plan() == before
        assert doc.page_count == 1
        organizer.reject()
