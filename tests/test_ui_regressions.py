from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTabBar, QToolButton, QWidget

from dialogs.barcode_dialogs import BARCODE_TYPES, BarcodeScanDialog
from dialogs.batch_tools import PdfFileTable
from dialogs.conversion_dialogs import BatchFileTable
from ui.icons import brand_pixmap, clear_icon_cache
from ui.workspace import DocumentWorkspace

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


def test_conversion_tables_accept_drag_move_and_drop(tmp_path: Path) -> None:
    _app()
    for suffix in (".txt", ".ps", ".eps", ".pdf"):
        source = tmp_path / f"dragged{suffix}"
        source.write_bytes(b"test")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        table = BatchFileTable({suffix})
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
        assert enter.isAccepted(), suffix

        move = QDragMoveEvent(
            QPoint(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        table.dragMoveEvent(move)
        assert move.isAccepted(), suffix

        drop = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        table.dropEvent(drop)
        assert drop.isAccepted(), suffix
        assert len(dropped) == 1 and len(dropped[0]) == 1
        assert Path(dropped[0][0]) == source


def test_barcode_scan_dialog_requires_and_returns_selected_types(tmp_path: Path) -> None:
    _app()
    source = tmp_path / "codes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    dialog = BarcodeScanDialog(source)

    assert dialog.barcode_types.count() == len(BARCODE_TYPES)
    assert all(
        dialog.barcode_types.item(index).isSelected()
        for index in range(dialog.barcode_types.count())
    )

    dialog._select_all_types(False)
    dialog._validate()
    assert dialog.details is None
    assert "at least one barcode type" in dialog._validation.text().casefold()

    qr_index = BARCODE_TYPES.index("QRCODE")
    dialog.barcode_types.item(qr_index).setSelected(True)
    dialog._validate()
    assert dialog.details is not None
    assert dialog.details["barcode_types"] == ["QRCODE"]
    dialog.close()


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


class _FakeSession:
    """Minimal stand-in for DocumentSession when only the tab shell is needed."""

    def __init__(self, title: str):
        self.tab_widget = QWidget()
        self.tab_title = title
        self.display_path: Path | None = None
        self.document_name = title


def _workspace_with_two_tabs() -> DocumentWorkspace:
    workspace = DocumentWorkspace(recent_files=[])
    for title in ("first.pdf", "second.pdf"):
        workspace.create_tab(_FakeSession(title))  # type: ignore[arg-type]
    return workspace


def _drift_click(button, inside: QPoint, outside: QPoint) -> None:
    """Press inside the button, drift outside it, then release.

    A real human click on an 18-24 px tab target nearly always moves the
    cursor a few pixels between press and release; QToolButton's default
    behaviour cancels the click when that drift leaves the widget rect.
    """
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=inside)
    QTest.mouseMove(button, pos=outside)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=outside)


def test_visible_tab_close_button_responds_to_left_click() -> None:
    """Regression: the visible X must emit the tab close request."""
    _app()
    workspace = _workspace_with_two_tabs()
    workspace.show()
    _app().processEvents()

    bar = workspace._tabs.tabBar()
    button = bar.tabButton(1, QTabBar.ButtonPosition.RightSide)
    assert button is not None
    assert button.objectName() == "tabCloseButton"
    assert not button.icon().isNull()

    closed: list[object] = []
    workspace.tabCloseRequested.connect(closed.append)

    w, h = button.width(), button.height()
    assert w > 0 and h > 0
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    _app().processEvents()
    assert len(closed) == 1


def test_tab_close_press_survives_release_captured_by_tab_drag() -> None:
    """The close request is queued from press even if release moves away."""
    _app()
    workspace = _workspace_with_two_tabs()
    workspace.show()
    _app().processEvents()

    bar = workspace._tabs.tabBar()
    button = bar.tabButton(1, QTabBar.ButtonPosition.RightSide)
    assert button is not None

    closed: list[object] = []
    workspace.tabCloseRequested.connect(closed.append)

    w, h = button.width(), button.height()
    _drift_click(
        button,
        inside=QPoint(w - 1, h // 2),
        outside=QPoint(w + 40, h // 2),
    )
    _app().processEvents()
    assert len(closed) == 1


def test_many_tabs_have_scroll_buttons_and_all_documents_menu() -> None:
    """Overflow tabs remain reachable without widening the window."""
    _app()
    workspace = DocumentWorkspace(recent_files=[])
    workspace.resize(560, 320)
    for index in range(18):
        workspace.create_tab(_FakeSession(f"long-document-name-{index:02d}.pdf"))  # type: ignore[arg-type]

    workspace.show()
    _app().processEvents()

    bar = workspace._tabs.tabBar()
    assert bar.usesScrollButtons()
    assert not bar.expanding()
    assert bar.elideMode() == Qt.TextElideMode.ElideMiddle

    left = bar.findChild(QToolButton, "ScrollLeftButton")
    right = bar.findChild(QToolButton, "ScrollRightButton")
    assert left is not None and left.isVisible()
    assert right is not None and right.isVisible()
    assert not left.icon().isNull()
    assert not right.icon().isNull()

    assert workspace._tab_list_button.isVisible()
    workspace._rebuild_tab_list_menu()
    actions = workspace._tab_list_menu.actions()
    assert len(actions) == 18
    assert actions[-1].isChecked()

    actions[0].trigger()
    _app().processEvents()
    assert workspace._tabs.currentIndex() == 0
    assert bar.tabRect(0).intersects(bar.rect())
