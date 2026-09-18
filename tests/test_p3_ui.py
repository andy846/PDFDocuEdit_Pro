from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QFontDatabase, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import core.viewer as viewer_module
from core.annotations import (
    AnnotationOp,
    AnnotationStyle,
    freetext_visual_metrics,
)
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
    app.setQuitOnLastWindowClosed(False)
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
    window._load_file_sync(str(source))
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
    window._load_file_sync(str(source))
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


def test_redact_marks_require_separate_confirmation_to_apply(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "redact.pdf")
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)

    window._handle_annotation(
        AnnotationOp(kind="redact", page=0, rects=(fitz.Rect(60, 80, 220, 105),))
    )
    page = window.engine.document.load_page(0)
    assert "Annotatable" in page.get_text()
    assert any("Redact" in str(annot.type) for annot in page.annots())

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )
    window._apply_redactions()
    assert "Annotatable" in window.engine.document.load_page(0).get_text()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    window._apply_redactions()
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
    window._load_file_sync(str(source))
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
    window._load_file_sync(str(source))
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
    annotation_commands = [
        command for command in window._commands if command.section == "Annotate"
    ]
    assert {command.id for command in annotation_commands} == {
        "font_inspect", "highlight", "underline", "strikeout", "squiggly",
        "note", "ink",
        "rect", "line", "arrow", "ellipse", "polygon",
        "freetext_typewriter", "freetext_box", "freetext_callout", "redact",
        "stamp", "signature", "image", "watermark",
    }
    assert all(command.shortcut for command in annotation_commands)
    assert len({command.shortcut for command in annotation_commands}) == 20
    assert not any(command.id.startswith("annot_") for command in window._commands)
    window.close()


def test_polygon_tool_creates_clicked_triangle_not_drag_rectangle(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "polygon.pdf", pages=1)
    window._load_file_sync(str(source))
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


@pytest.mark.parametrize("tool", ["line", "arrow"])
def test_line_tools_preserve_drag_direction_and_do_not_use_a_rectangle(
    tmp_path: Path, monkeypatch, tool: str
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / f"{tool}.pdf", pages=1)
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    window._activate_annotation_tool(tool)

    canvas = window.workspace.canvas
    requested: list[AnnotationOp] = []
    canvas.annotationRequested.connect(requested.append)
    overlay = canvas._page_views[0].overlay
    assert overlay._interaction_state.value == "line"
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(280, 220))
    QTest.mouseMove(overlay, QPoint(70, 60), delay=10)
    assert overlay._marquee is None
    assert overlay._preview is not None
    assert overlay._preview["kind"] == tool
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(70, 60))
    app.processEvents()

    assert len(requested) == 1
    op = requested[0]
    assert op.kind == tool
    assert op.points[0][0] > op.points[1][0]
    assert op.points[0][1] > op.points[1][1]
    page = window.engine.document.load_page(0)
    annotations = list(page.annots())
    assert len(annotations) == 1
    assert "Line" in str(annotations[0].type)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


def test_text_box_mouse_drag_has_visible_guide_and_visible_result(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "textbox-mouse.pdf", pages=1)
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    monkeypatch.setattr(
        viewer_module.QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *args, **kwargs: ("VISIBLE TEXT BOX", True)),
    )
    window._activate_annotation_tool("freetext_box")

    canvas = window.workspace.canvas
    assert canvas._annot_options["color"] == "#202124"
    assert canvas._annot_options["fill"] == "#fff4b8"
    assert canvas._annot_options["opacity"] >= 0.05
    overlay = canvas._page_views[0].overlay
    start = QPoint(100, 180)
    end = QPoint(360, 310)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(overlay, end, delay=10)
    app.processEvents()
    assert overlay._marquee is not None
    preview = overlay.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
    centre = preview.pixelColor((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    assert (centre.red(), centre.green(), centre.blue()) != (255, 255, 255)

    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    page = window.engine.document.load_page(0)
    annotations = list(page.annots())
    assert len(annotations) == 1
    assert "FreeText" in str(annotations[0].type)
    rendered = page.get_pixmap(colorspace=fitz.csRGB, alpha=False, annots=True)
    samples = rendered.samples
    assert any(
        samples[index] < 80
        and samples[index + 1] < 80
        and samples[index + 2] < 80
        for index in range(0, len(samples), rendered.n)
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


@pytest.mark.parametrize("zoom", [0.8, 1.6])
def test_typewriter_is_point_and_inline_text_interaction(
    tmp_path: Path, monkeypatch, zoom: float
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "typewriter-inline.pdf", pages=1)
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    window._activate_annotation_tool("freetext_typewriter")

    canvas = window.workspace.canvas
    canvas.set_zoom(zoom)
    _wait_renders(app, canvas)
    overlay = canvas._page_views[0].overlay
    assert overlay._interaction_state.value == "note"
    assert canvas._annot_options["fill"] == ""
    click = QPoint(140, 240)
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=click)
    app.processEvents()
    editor = overlay._inline_editor
    assert editor is not None and editor.isVisible()
    assert overlay._marquee is None
    assert editor.geometry().center().y() == pytest.approx(click.y(), abs=1.0)
    original_position = editor.pos()
    QTest.keyClick(
        editor,
        Qt.Key.Key_Right,
        Qt.KeyboardModifier.AltModifier,
    )
    QTest.keyClick(
        editor,
        Qt.Key.Key_Up,
        Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.x() == original_position.x() + 1
    assert editor.y() == original_position.y() - 5
    adjusted_anchor = QPointF(click.x() + 1, click.y() - 5)
    stored_anchor = editor.property("typewriterAnchor")
    assert stored_anchor == adjusted_anchor
    QTest.keyClicks(editor, "Point based typewriter")
    app.processEvents()
    editor_rect = editor.geometry()
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()

    page = window.engine.document.load_page(0)
    annotations = list(page.annots())
    assert len(annotations) == 1
    assert "FreeText" in str(annotations[0].type)
    assert annotations[0].info["content"] == "Point based typewriter"
    click_pdf = overlay.widget_to_pdf(adjusted_anchor)
    midpoint, line_height = freetext_visual_metrics(
        canvas._annot_options["font"],
        canvas._annot_options["font_size"],
    )
    assert annotations[0].rect.x0 == pytest.approx(click_pdf.x, abs=0.1)
    assert annotations[0].rect.y0 == pytest.approx(click_pdf.y - midpoint, abs=0.1)
    assert annotations[0].rect.height == pytest.approx(line_height, abs=0.1)
    assert annotations[0].rect.width == pytest.approx(
        editor_rect.width() / zoom,
        abs=1.0 / zoom + 0.1,
    )
    words = [word for word in page.get_text("words") if "Point" in str(word[4])]
    assert words
    assert words[0][0] == pytest.approx(annotations[0].rect.x0, abs=4.0)
    assert words[0][1] == pytest.approx(annotations[0].rect.y0, abs=6.0)
    word_midpoint = (float(words[0][1]) + float(words[0][3])) / 2.0
    assert word_midpoint == pytest.approx(click_pdf.y, abs=3.0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


def test_manage_content_editor_only_shows_for_text_annotations(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "conditional-content.pdf", pages=3)
    window._load_file_sync(str(source))
    window._handle_annotation(
        AnnotationOp(
            kind="rect", page=0, rects=(fitz.Rect(80, 120, 200, 220),)
        )
    )
    rect_item = window.context_panel._annot_list.item(0)
    window.context_panel._annot_list.setCurrentItem(rect_item)
    assert window.context_panel._property_text.isHidden()
    assert window.context_panel._apply_properties.text() == "Apply Style"

    window._handle_annotation(
        AnnotationOp(
            kind="freetext_box",
            page=0,
            rects=(fitz.Rect(220, 120, 430, 220),),
            text="editable",
            style=AnnotationStyle(stroke="#202124", fill="#fff4b8"),
        )
    )
    text_item = window.context_panel._annot_list.item(1)
    window.context_panel._annot_list.setCurrentItem(text_item)
    assert not window.context_panel._property_text.isHidden()
    assert window.context_panel._property_text.toPlainText() == "editable"
    assert window.context_panel._apply_properties.text() == "Apply Style & Content"

    text_entry = text_item.data(Qt.ItemDataRole.UserRole + 1)
    text_xref = int(text_entry["xref"])
    window._change_annotation_geometry(
        window._session,
        0,
        text_xref,
        {"rect": fitz.Rect(250, 240, 460, 340)},
    )
    app.processEvents()
    assert window.context_panel._annot_list.currentItem() is not None

    window.bottom_bar.nextClicked.emit()
    app.processEvents()
    assert window._page == 1
    assert window.workspace.canvas.current_page == 1
    assert window.workspace.canvas.selected_annotation() is None

    QTest.keyClick(
        window,
        Qt.Key.Key_Right,
        Qt.KeyboardModifier.ControlModifier,
    )
    app.processEvents()
    assert window._page == 2
    assert window.workspace.canvas.current_page == 2

    window.previous_page()
    window.previous_page()
    app.processEvents()
    assert window._page == 0
    assert window.workspace.canvas.selected_annotation() is None
    assert all(
        view.overlay._selected_xref is None
        for view in window.workspace.canvas._page_views.values()
    )

    # Internal list rebuilds stay silent, while a real list selection still
    # performs the intended cross-page navigation.
    other_item = next(
        window.context_panel._annot_list.item(index)
        for index in range(window.context_panel._annot_list.count())
        if int(
            window.context_panel._annot_list.item(index).data(
                Qt.ItemDataRole.UserRole
            )
        )
        != text_xref
    )
    window.context_panel._annot_list.setCurrentItem(other_item)
    app.processEvents()
    assert window._page == 0
    assert window.workspace.canvas.selected_annotation() == (
        0,
        int(other_item.data(Qt.ItemDataRole.UserRole)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


def test_annotation_defaults_switch_without_cross_contamination(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "defaults.pdf")
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    original_highlight = {
        "stroke": "red",
        "fill": "",
        "opacity": 0.45,
        "width": 1.5,
        "font": "Helv",
        "font_size": 11.0,
        "alignment": 0,
    }
    rectangle = {
        "stroke": "green",
        "fill": "cyan",
        "opacity": 0.8,
        "width": 3.5,
        "font": "Cour",
        "font_size": 18.0,
        "alignment": 2,
    }
    window.settings.set(
        "annotation_defaults",
        {"highlight": dict(original_highlight), "rect": dict(rectangle)},
    )

    window._activate_annotation_tool("highlight")
    window._activate_annotation_tool("rect")

    defaults = window.settings.get("annotation_defaults")
    assert defaults["highlight"] == original_highlight
    assert window.context_panel._annot_width.value() == pytest.approx(3.5)
    assert window.workspace.canvas._annot_options["width"] == pytest.approx(3.5)
    opacity_label = window.context_panel._style_form.labelForField(
        window.context_panel._annot_opacity
    )
    font_label = window.context_panel._style_form.labelForField(
        window.context_panel._annot_font
    )
    assert opacity_label is not None and not opacity_label.isHidden()
    assert font_label is not None and font_label.isHidden()
    window._activate_annotation_tool("stamp")
    assert window.context_panel._annot_opacity.isHidden()
    assert opacity_label.isHidden()
    window._activate_annotation_tool("freetext_box")
    font_combo = window.context_panel._annot_font
    assert font_combo.isEditable()
    assert font_combo.completer() is not None
    installed_families = QFontDatabase.families()
    if installed_families:
        assert font_combo.findText(
            installed_families[0], Qt.MatchFlag.MatchFixedString
        ) >= 0
    assert font_combo.findText("Helv", Qt.MatchFlag.MatchFixedString) >= 0
    canvas = window.workspace.canvas

    window._tool_requested("font_inspect")
    assert canvas.tool_mode == ToolMode.FONT_INSPECT
    assert window.context_panel._stack.currentWidget() is (
        window.context_panel._pages["font_inspect"]
    )

    canvas.fontInspectionRequested.emit(0, fitz.Point(80, 90))
    app.processEvents()
    inspection = window.context_panel._font_inspection
    assert inspection is not None
    assert inspection["display_font"] == "Helvetica"
    assert inspection["suggested_font"] == "Helv"
    assert inspection["size"] == pytest.approx(11.0)
    assert canvas._font_inspection is not None
    assert window.context_panel._font_apply_typewriter.isEnabled()

    window.context_panel._font_copy_name.click()
    assert QApplication.clipboard().text() == "Helvetica"

    canvas.fontInspectionRequested.emit(0, fitz.Point(500, 500))
    app.processEvents()
    assert window.context_panel._font_inspection is None
    assert canvas._font_inspection is None
    assert not window.context_panel._font_apply_typewriter.isEnabled()

    canvas.fontInspectionRequested.emit(0, fitz.Point(80, 90))
    app.processEvents()
    window.context_panel._font_apply_typewriter.click()
    app.processEvents()
    assert canvas.tool_mode == ToolMode.FREETEXT_TYPEWRITER
    assert canvas.annotation_options()["font"] == "Helv"
    assert canvas.annotation_options()["font_size"] == pytest.approx(11.0)
    defaults = window.settings.get("annotation_defaults")
    assert defaults["freetext_typewriter"]["font"] == "Helv"
    assert defaults["freetext_typewriter"]["stroke"] == "#000000"
    window.close()


def test_split_canvas_annotation_tool_style_and_signal_parity(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "split-annot.pdf", pages=2)
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    window.settings.set(
        "annotation_defaults",
        {
            "rect": {
                "stroke": "red",
                "fill": "green",
                "opacity": 0.5,
                "width": 2.5,
            }
        },
    )
    window._activate_annotation_tool("rect")

    window._toggle_split_view()
    split = window._session.split_canvas
    assert split is not None
    assert split.tool_mode == ToolMode.RECT
    assert split._annot_options == window.workspace.canvas._annot_options
    window._activate_annotation_tool("ellipse")
    assert window.workspace.canvas.tool_mode == ToolMode.ELLIPSE
    assert split.tool_mode == ToolMode.ELLIPSE
    window._activate_annotation_tool("rect")

    split.annotationRequested.emit(
        AnnotationOp(
            kind="rect",
            page=1,
            rects=(fitz.Rect(80, 120, 200, 240),),
            style=AnnotationStyle(
                stroke="red", fill="green", opacity=0.5, width=2.5
            ),
        )
    )
    app.processEvents()
    assert len(list(window.engine.document.load_page(1).annots())) == 1
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.close()


def test_annotation_undo_preserves_page_and_refreshes_list(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "undo-page.pdf", pages=3)
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)
    window.workspace.canvas.set_page(1)
    app.processEvents()
    assert window._page == 1

    window._handle_annotation(
        AnnotationOp(
            kind="rect",
            page=1,
            rects=(fitz.Rect(80, 120, 200, 240),),
        )
    )
    assert window.context_panel._annot_list.count() == 1

    window._undo()
    app.processEvents()

    assert window._page == 1
    assert window.workspace.canvas.current_page == 1
    assert window.context_panel._annot_list.count() == 0
    window.close()
