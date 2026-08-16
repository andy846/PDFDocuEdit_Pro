from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication

from dialogs.batch_tools import PdfFileTable
from ui.icons import brand_pixmap, clear_icon_cache

_app_instance: QApplication | None = None


def _app() -> QApplication:
    global _app_instance
    if _app_instance is None:
        _app_instance = QApplication.instance() or QApplication(
            ["pdfdocuedit-ui-regression-test"]
        )
    return _app_instance


def test_pdf_table_accepts_drag_move_and_drop(tmp_path: Path) -> None:
    _app()
    source = tmp_path / "dragged.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    table = PdfFileTable()
    dropped: list[list[str]] = []
    table.filesDropped.connect(dropped.append)

    enter = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert table.property("dragActive") is True

    move = QDragMoveEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dragMoveEvent(move)
    assert move.isAccepted()

    drop = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    table.dropEvent(drop)
    assert drop.isAccepted()
    assert len(dropped) == 1 and len(dropped[0]) == 1
    assert Path(dropped[0][0]) == source
    assert table.property("dragActive") is False


def test_brand_pixmap_keeps_red_application_colour() -> None:
    _app()
    clear_icon_cache()
    pixmap = brand_pixmap(32)
    assert not pixmap.isNull()
    colours = [
        pixmap.toImage().pixelColor(x, y)
        for y in range(pixmap.height())
        for x in range(pixmap.width())
    ]
    assert any(
        colour.alpha() > 0
        and colour.red() > colour.green() + 30
        and colour.red() > colour.blue() + 30
        for colour in colours
    )
