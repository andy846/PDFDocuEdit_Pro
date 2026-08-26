from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import core.viewer as viewer_module
from core.annotations import AnnotationOp
from core.settings import SettingsManager
from ui.pdf_canvas import ToolMode


def make_pdf(path: Path, pages: int = 3) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), f"Annotatable text on page {index + 1}")
        document.save(path)
    return path


def _window(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication(["pdfdocuedit-p3-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    window = viewer_module.PDFViewer()
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    return window, app


def _wait_renders(app, canvas, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while canvas._pending and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def annot_count(window) -> int:
    return len(list(window.engine.document.load_page(0).annots()))


def test_annotation_tool_modes_and_highlight_commit(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "p3.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)

    for key, mode in (
        ("highlight", ToolMode.HIGHLIGHT),
        ("underline", ToolMode.UNDERLINE),
        ("strikeout", ToolMode.STRIKEOUT),
        ("note", ToolMode.NOTE),
        ("ink", ToolMode.INK),
        ("rect", ToolMode.RECT),
        ("redact", ToolMode.REDACT),
        ("stamp", ToolMode.STAMP),
        ("signature", ToolMode.SIGNATURE),
        ("image", ToolMode.IMAGE),
    ):
        window._activate_annotation_tool(key)
        assert window.workspace.canvas.tool_mode == mode, key
        assert window.context_panel.isVisible()

    before = annot_count(window)
    op = AnnotationOp(
        kind="highlight",
        page=0,
        rects=(fitz.Rect(60, 80, 220, 105),),
        color="yellow",
    )
    window._handle_annotation(op)
    app.processEvents()
    assert annot_count(window) == before + 1
    assert window.engine.is_modified
    page = window.engine.document.load_page(0)
    assert "Highlight" in str(list(page.annots())[-1].type)

    window._undo()
    app.processEvents()
    assert annot_count(window) == before
    window.close()


def test_note_and_remove_annotation_flow(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "note.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)

    window._handle_annotation(
        AnnotationOp(kind="note", page=0, points=((200, 300),), text="remember this")
    )
    assert annot_count(window) == 1

    page = window.engine.document.load_page(0)
    xref = int(next(page.annots()).xref)
    window._handle_remove_annotation(xref)
    assert annot_count(window) == 0
    assert window.engine.is_modified

    window._undo()
    assert annot_count(window) == 1
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    window.close()


def test_redact_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "redact.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )
    window._handle_annotation(
        AnnotationOp(kind="redact", page=0, rects=(fitz.Rect(60, 80, 220, 105),))
    )
    assert "Annotatable" in window.engine.document.load_page(0).get_text()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    window._handle_annotation(
        AnnotationOp(kind="redact", page=0, rects=(fitz.Rect(60, 80, 220, 105),))
    )
    assert "Annotatable" not in window.engine.document.load_page(0).get_text()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


def test_context_panel_options_reach_canvas(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "options.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)
    window._activate_annotation_tool("highlight")

    window.context_panel.annotationColorChanged.emit("red")
    window.context_panel.annotationWidthChanged.emit(4)
    window.context_panel.stampKindChanged.emit("Final")
    window.context_panel.stampImageChanged.emit("/tmp/custom-stamp.png")
    window.context_panel.imagePathChanged.emit("/tmp/fake.png")
    options = window.workspace.canvas._annot_options
    assert options["color"] == "red"
    assert options["width"] == 4.0
    assert options["stamp_kind"] == "Final"
    assert options["stamp_image_path"] == "/tmp/custom-stamp.png"
    assert options["image_path"] == "/tmp/fake.png"
    window.close()


def test_custom_stamp_import_persists_selects_and_removes(
    tmp_path: Path, monkeypatch
) -> None:
    from PIL import Image

    window, app = _window(tmp_path, monkeypatch)
    stamp_source = tmp_path / "company-seal.png"
    Image.new("RGBA", (160, 60), (180, 20, 20, 220)).save(stamp_source)
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(stamp_source), "Images (*.png)"),
    )
    monkeypatch.setattr(
        viewer_module.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Company Seal", True),
    )

    window._add_custom_stamp()

    stamps = window.settings.get_custom_stamps()
    assert set(stamps) == {"Company Seal"}
    managed = Path(stamps["Company Seal"])
    assert managed.is_file()
    assert managed.parent == (window.settings.path.parent / "stamps").resolve()
    assert window.context_panel.current_custom_stamp_name() == "Company Seal"

    source = make_pdf(tmp_path / "custom-stamp.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)
    window._activate_annotation_tool("stamp")
    options = window.workspace.canvas._annot_options
    assert options["stamp_kind"] == "Draft"
    assert options["stamp_image_path"] == str(managed)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._remove_custom_stamp("Company Seal")
    assert window.settings.get_custom_stamps() == {}
    assert not managed.exists()
    assert window.context_panel.current_stamp() == ("Draft", "")
    window.close()


def test_custom_text_stamp_is_rendered_and_selected(
    tmp_path: Path, monkeypatch
) -> None:
    window, _app = _window(tmp_path, monkeypatch)
    monkeypatch.setattr(
        viewer_module.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("PAID\n26 AUG 2026", True),
    )
    monkeypatch.setattr(
        viewer_module.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Paid Stamp", True),
    )

    window._add_custom_text_stamp()

    stamps = window.settings.get_custom_stamps()
    assert set(stamps) == {"Paid Stamp"}
    target = Path(stamps["Paid Stamp"])
    image = QImage(str(target))
    assert target.suffix == ".png"
    assert not image.isNull()
    assert image.hasAlphaChannel()
    assert image.width() > image.height()
    assert window.context_panel.current_custom_stamp_name() == "Paid Stamp"
    assert window.context_panel.current_stamp() == ("Draft", str(target))
    window.close()


def test_annotation_commands_registered(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    ids = [command.id for command in window._commands]
    for key in (
        "highlight",
        "underline",
        "strikeout",
        "note",
        "ink",
        "rect",
        "redact",
        "stamp",
        "signature",
        "image",
        "watermark",
    ):
        assert f"annot_{key}" in ids, key
    window.close()


def test_polygon_tool_creates_clicked_triangle_not_drag_rectangle(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "polygon.pdf", pages=1)
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)
    window._activate_annotation_tool("polygon")

    overlay = window.workspace.canvas._page_views[0].overlay
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(260, 100))
    QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(150, 280))
    app.processEvents()

    page = window.engine.document.load_page(0)
    annotations = list(page.annots())
    assert len(annotations) == 1
    polygon = annotations[0]
    assert "Polygon" in str(polygon.type)
    assert polygon.vertices is not None
    assert len(polygon.vertices) == 3
    assert len({(round(point[0]), round(point[1])) for point in polygon.vertices}) == 3
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()
