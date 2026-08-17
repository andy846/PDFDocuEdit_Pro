from __future__ import annotations

import time
from pathlib import Path

import fitz
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
        viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json")
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


def test_annotation_tool_modes_and_highlight_commit(tmp_path: Path, monkeypatch) -> None:
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

    window._handle_remove_annotation(0)
    assert annot_count(window) == 0
    assert window.engine.is_modified

    window._undo()
    assert annot_count(window) == 1
    window.close()


def test_redact_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "redact.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.No
        ),
    )
    window._handle_annotation(
        AnnotationOp(kind="redact", page=0, rects=(fitz.Rect(60, 80, 220, 105),))
    )
    assert "Annotatable" in window.engine.document.load_page(0).get_text()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        ),
    )
    window._handle_annotation(
        AnnotationOp(kind="redact", page=0, rects=(fitz.Rect(60, 80, 220, 105),))
    )
    assert "Annotatable" not in window.engine.document.load_page(0).get_text()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard
        ),
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
    window.context_panel.imagePathChanged.emit("/tmp/fake.png")
    options = window.workspace.canvas._annot_options
    assert options["color"] == "red"
    assert options["width"] == 4.0
    assert options["stamp_kind"] == "Final"
    assert options["image_path"] == "/tmp/fake.png"
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
