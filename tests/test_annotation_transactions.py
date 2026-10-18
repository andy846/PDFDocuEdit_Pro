from __future__ import annotations

import json

import fitz
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QThreadPool
from PyQt6.QtWidgets import QDialog, QMessageBox

import core.annotation_io as annotation_io
import core.viewer as viewer_module
from core.annotations import AnnotationOp, list_document_annotations
from core.settings import SettingsManager


@pytest.fixture(scope="module")
def annotation_app(qt_application):
    # Keep one application for this module and drain its workers before teardown.
    app = qt_application
    yield app
    QThreadPool.globalInstance().waitForDone()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def viewer(tmp_path, monkeypatch, annotation_app):
    app = annotation_app
    monkeypatch.setattr(viewer_module, "SettingsManager",
                        lambda: SettingsManager(tmp_path / "settings.json"))
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 96), "Sensitive secret text")
        page.add_text_annot((200, 200), "Original note")
        page.add_rect_annot(fitz.Rect(100, 120, 180, 170))
        doc.new_page().insert_text((72, 96), "Second secret")
        doc.save(source)
    window = viewer_module.PDFViewer()
    monkeypatch.setattr(window, "_error", lambda *args: None)
    window._load_file_sync(str(source))
    window._session.set_split(True)
    yield window
    window.engine._is_modified = False
    window.close_document()
    window.close()
    # Close retires PDF readers asynchronously. A test must drain those readers
    # before explicitly destroying their widgets or starting the next case.
    QThreadPool.globalInstance().waitForDone()
    app.processEvents()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def state(window):
    return (
        tuple(page.get_text() for page in window.engine.document),
        tuple((entry["page"], entry["kind"], entry["text"], tuple(entry["rect"]))
              for entry in list_document_annotations(window.engine.document)),
    )


@pytest.mark.parametrize("operation", ["geometry", "properties", "remove"])
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("image_kind", ["image", "signature"])
def test_added_image_edit_transaction(viewer, tmp_path, monkeypatch, operation, fail, image_kind):
    window = viewer
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), False)
    pixmap.clear_with(180)
    path = tmp_path / "picture.png"
    pixmap.save(path)
    source = window.engine.original_path.read_bytes()
    window._handle_annotation(AnnotationOp(kind=image_kind, page=0,
                                          rects=(fitz.Rect(50, 200, 150, 250),), image_path=str(path)))
    entries = list_document_annotations(window.engine.document)
    entry = next(entry for entry in entries if entry["kind"] == ("Image" if image_kind == "image" else "Signature Image"))
    assert window._session.canvas.tool_mode.value == "browse"
    # Qt needs && to display a literal &, rather than an invisible mnemonic.
    assert window.context_panel._apply_properties.text() == "Apply Position && Size"
    assert not window.context_panel._image_geometry.isHidden()
    assert not window._tasks  # automatic properties must not scan the entire PDF
    before = state(window)
    pixels_before = window.engine.document[0].get_pixmap().samples
    function = "remove_annotation" if operation == "remove" else "update_annotation_geometry"
    if fail:
        original = getattr(viewer_module, function)
        def failed(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected after image edit")
        monkeypatch.setattr(viewer_module, function, failed)
    if operation == "remove":
        window._handle_remove_annotation(0, entry["xref"])
    elif operation == "properties":
        window._edit_annotation(0, entry["xref"], {"rect": fitz.Rect(70, 210, 270, 310), "keep_aspect": False})
    else:
        window._change_annotation_geometry(window._session, 0, entry["xref"], {"rect": fitz.Rect(70, 210, 270, 310)})
    if fail:
        assert state(window) == before
        assert window.engine.document[0].get_pixmap().samples == pixels_before
        assert window._undo_stack.undo_count == 1
    else:
        after = state(window)
        pixels_after = window.engine.document[0].get_pixmap().samples
        assert after != before
        assert pixels_after != pixels_before
        assert window._undo_stack.undo_count == 2
        assert window._undo()
        assert state(window) == before
        assert window.engine.document[0].get_pixmap().samples == pixels_before
        assert window._redo()
        assert state(window) == after
        assert window.engine.document[0].get_pixmap().samples == pixels_after
    assert window.engine.original_path.read_bytes() == source


@pytest.mark.parametrize("operation", ["add", "remove", "geometry", "text", "properties"])
@pytest.mark.parametrize("fail", [False, True])
def test_annotation_actions_commit_once_or_roll_back(viewer, monkeypatch, operation, fail):
    window = viewer
    session = window._session
    entries = list_document_annotations(window.engine.document)
    note = next(entry["xref"] for entry in entries if entry["kind"] == "Text")
    rect = next(entry["xref"] for entry in entries if entry["kind"] == "Square")
    before = state(window)
    stack = session.undo_stack
    stack.push_redo(str(window.engine.temp_path), "Existing redo")
    functions = {"add": "apply_annotation", "remove": "remove_annotation",
                 "geometry": "update_annotation_geometry", "text": "update_annotation_text",
                 "properties": "update_annotation"}
    function = functions[operation]
    with monkeypatch.context() as patch:
        if fail:
            original = getattr(viewer_module, function)
            def fail_after_change(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("injected after annotation mutation")
            patch.setattr(viewer_module, function, fail_after_change)
        if operation == "add":
            window._handle_annotation(AnnotationOp(kind="note", page=1, points=((200, 200),), text="New"))
        elif operation == "remove":
            window._handle_remove_annotation(0, note)
        elif operation == "geometry":
            window._change_annotation_geometry(session, 0, rect, {"rect": fitz.Rect(150, 160, 230, 210)})
        elif operation == "text":
            window._inline_edit_annotation(session, 0, note, "Changed")
        else:
            window._edit_annotation(0, note, {"text": "Properties changed", "opacity": 0.5})
    if fail:
        assert state(window) == before
        assert stack.undo_count == 0
        assert stack.redo_descriptions() == ["Existing redo"]
        assert not window.engine.is_modified
        assert session.canvas._doc is window.engine.document
        assert session.split_canvas._doc is window.engine.document
    else:
        after = state(window)
        assert after != before
        assert stack.undo_count == 1
        assert stack.redo_count == 0
        assert window._undo()
        assert state(window) == before
        assert window._redo()
        assert state(window) == after


@pytest.mark.parametrize("mode", ["success", "failure", "unsupported_only"])
def test_annotation_import_batch_transaction(viewer, tmp_path, monkeypatch, mode):
    window = viewer
    before = state(window)
    records = [{"page": 0, "pdf_kind": "FileAttachment"}]
    if mode != "unsupported_only":
        records += [{"page": page, "pdf_kind": "Text", "rect": [200, 250, 220, 270], "text": "Imported"}
                    for page in range(2)]
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps({"schema": annotation_io.SCHEMA, "version": 1, "annotations": records}))
    monkeypatch.setattr(viewer_module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    stack = window._undo_stack
    stack.push_redo(str(window.engine.temp_path), "Existing redo")
    if mode == "failure":
        apply = annotation_io.apply_annotation
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            apply(*args, **kwargs)
            if calls == 2:
                raise RuntimeError("failed after second import")
        monkeypatch.setattr(annotation_io, "apply_annotation", fail_second)
    window._import_annotations()
    if mode == "success":
        assert len(list_document_annotations(window.engine.document)) == 4
        assert stack.undo_count == 1
        assert window._undo()
        assert state(window) == before
    else:
        assert state(window) == before
        assert not stack.can_undo
        assert stack.redo_descriptions() == ["Existing redo"]
        assert not window.engine.is_modified


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize("fail", [False, True])
def test_multi_page_watermark_transaction(viewer, tmp_path, monkeypatch, mode, fail):
    from PIL import Image
    window = viewer
    image = tmp_path / "watermark.png"
    Image.new("RGB", (20, 20), "red").save(image)
    class Dialog:
        details = {"pages": "all", "mode": mode, "text": "WATERMARK", "image": str(image),
                   "fontsize": 20, "opacity": 0.5, "rotation": 0}
        def __init__(self, *args):
            pass
        def exec(self):
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(viewer_module, "WatermarkDialog", Dialog)
    before = state(window)
    if fail:
        function = "add_watermark_text" if mode == "text" else "add_watermark_image"
        original = getattr(viewer_module, function)
        def fail_midway(doc, pages, *args, **kwargs):
            original(doc, [pages[0]], *args, **kwargs)
            raise RuntimeError("failed after first page")
        monkeypatch.setattr(viewer_module, function, fail_midway)
    window._show_watermark_dialog()
    if fail:
        assert not window._undo_stack.can_undo
        assert state(window) == before
        assert not window.engine.is_modified
        assert all(not page.get_images() for page in window.engine.document)
    else:
        assert window._undo_stack.undo_count == 1
        if mode == "text":
            assert all("WATERMARK" in page.get_text() for page in window.engine.document)
        else:
            assert all(page.get_images() for page in window.engine.document)
        assert window._undo()
        assert state(window) == before
        assert all(not page.get_images() for page in window.engine.document)


@pytest.mark.parametrize("fail", [False, True])
def test_multi_page_redaction_transaction(viewer, monkeypatch, fail):
    window = viewer
    for page in window.engine.document:
        page.add_redact_annot(fitz.Rect(60, 70, 260, 110))
    window.engine.mark_modified()
    before = state(window)
    monkeypatch.setattr(viewer_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    if fail:
        original = viewer_module.apply_redaction_marks
        def fail_midway(doc, **kwargs):
            original(doc, pages=[0], **kwargs)
            raise RuntimeError("failed after first redacted page")
        monkeypatch.setattr(viewer_module, "apply_redaction_marks", fail_midway)
    window._apply_redactions()
    if fail:
        assert not window._undo_stack.can_undo
        assert state(window) == before
    else:
        assert window._undo_stack.undo_count == 1
        assert all("secret" not in page.get_text() for page in window.engine.document)
        assert window.engine._requires_sanitized_save
        assert window._undo()
        assert state(window) == before
        assert window._redo()
        assert window.engine._requires_sanitized_save
        output = window.engine.save(window.engine.original_path.with_name("redacted.pdf"))
        with fitz.open(output) as saved:
            for xref in range(1, saved.xref_length()):
                if saved.xref_is_stream(xref):
                    data = (saved.xref_stream(xref) or b"").lower()
                    assert b"secret" not in data
                    assert b"secret".hex().encode() not in data


def add_spot_redaction(window):
    doc = window.engine.document
    page = doc[0]
    pixmap = fitz.Pixmap(fitz.csGRAY, 20, 20, bytes([255] * 400), False)
    image = page.insert_image(fitz.Rect(40, 200, 140, 300), pixmap=pixmap)
    doc.xref_set_key(image, "ColorSpace", "[/Separation /Black /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 0 0 1] /N 1 >>]")
    page.add_redact_annot(fitz.Rect(60, 220, 80, 240))
    before = page.get_pixmap().samples
    original = doc.xref_object(image), doc.xref_stream(image)
    window.engine.mark_modified()
    return before, original, image


def test_spot_image_redaction_reports_conversion_and_undo_redo(viewer, monkeypatch):
    window = viewer
    before, original, image = add_spot_redaction(window)
    messages = []
    monkeypatch.setattr(window.info_bar, "show_message", lambda message, *args: messages.append(message))
    confirmations = []

    def confirm(*args, **kwargs):
        confirmations.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(viewer_module.QMessageBox, "question", confirm)
    window._apply_redactions()
    assert "spot-colour" in confirmations[-1]
    assert "process colour" in confirmations[-1]
    assert window._undo_stack.undo_count == 1
    assert window.engine._requires_sanitized_save
    assert "spot-colour" in messages[-1]
    assert "process colour" in messages[-1]
    after = window.engine.document[0].get_pixmap().samples
    assert after != before
    assert not list(window.engine.document[0].annots(types=[fitz.PDF_ANNOT_REDACT]))
    assert window._undo()
    restored = window.engine.document
    assert restored[0].get_pixmap().samples == before
    assert (restored.xref_object(image), restored.xref_stream(image)) == original
    assert window._redo()
    assert window.engine.document[0].get_pixmap().samples == after
    assert window.engine._requires_sanitized_save



def test_spot_image_redaction_cancel_preserves_image_and_mark(viewer, monkeypatch):
    window = viewer
    before, original, image = add_spot_redaction(window)
    monkeypatch.setattr(viewer_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._apply_redactions()
    assert window.engine.document[0].get_pixmap().samples == before
    assert (window.engine.document.xref_object(image), window.engine.document.xref_stream(image)) == original
    assert list(window.engine.document[0].annots(types=[fitz.PDF_ANNOT_REDACT]))
    assert not window._undo_stack.can_undo
    assert not window.engine._requires_sanitized_save


@pytest.mark.parametrize("rotation", [90, 270])
@pytest.mark.parametrize("zoom", [0.5, 2.0])
def test_rotated_eraser_mouse_drag_apply_undo_redo_and_save(viewer, monkeypatch, tmp_path, rotation, zoom):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from ui.page_overlay import pdf_rect_to_widget

    window = viewer
    app = QCoreApplication.instance()
    source_path = window.engine.original_path
    source_bytes = source_path.read_bytes()
    window.show()
    app.processEvents()
    window.workspace.canvas.wait_for_renders()
    with window.engine.mutation_transaction("Fixture text"):
        window.engine.document[0].insert_text((60, 740), "ERASE_TARGET")
        window.engine.mark_modified()
    window._rotate_current(rotation)
    assert window.engine.document[0].rotation == rotation
    canvas = window._session.canvas
    canvas.set_zoom(zoom)
    app.processEvents()
    canvas.wait_for_renders()
    app.processEvents()
    window._activate_annotation_tool("redact")
    page = window.engine.document[0]
    source = fitz.Rect(50, 700, 200, 780)
    selection = pdf_rect_to_widget(source, page.rect, 1 / zoom, page.rotation_matrix)
    overlay = canvas._page_views[0].overlay
    assert overlay._interaction_state.value == "select"
    before = state(window)
    undo_count = window._undo_stack.undo_count
    # Exercise real mouse events -> overlay -> canvas -> viewer transaction.
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=selection.topLeft().toPoint())
    QTest.mouseMove(overlay, selection.bottomRight().toPoint())
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=selection.bottomRight().toPoint())
    page = window.engine.document[0]
    redactions = list(page.annots(types=[fitz.PDF_ANNOT_REDACT]))
    assert len(redactions) == 1
    expected = fitz.Rect(
        overlay.widget_to_pdf(selection.topLeft().toPoint()),
        overlay.widget_to_pdf(selection.bottomRight().toPoint()),
    ).normalize()
    assert tuple(redactions[0].rect) == pytest.approx(tuple(expected), abs=0.01)
    # Mouse positions are integer logical pixels; allow their rounding only.
    assert tuple(redactions[0].rect) == pytest.approx(tuple(source), abs=0.5 / zoom + 0.01)
    marked = state(window)
    assert window._undo_stack.undo_count == undo_count + 1
    assert window._undo()
    assert state(window) == before
    assert window._redo()
    assert state(window) == marked

    monkeypatch.setattr(viewer_module.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._apply_redactions()
    assert "ERASE_TARGET" not in window.engine.document[0].get_text()
    assert "Sensitive secret text" in window.engine.document[0].get_text()
    assert window._undo()
    assert state(window) == marked
    assert window._redo()
    output = window.engine.save(tmp_path / "rotated-redacted.pdf")
    with fitz.open(output) as saved:
        assert saved[0].rotation == rotation
        assert tuple(saved[0].mediabox) == (0, 0, 595, 842)
        assert "ERASE_TARGET" not in saved[0].get_text()
        assert "Sensitive secret text" in saved[0].get_text()
    assert source_bytes == source_path.read_bytes()
