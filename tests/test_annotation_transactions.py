from __future__ import annotations

import json

import fitz
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QThreadPool
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

import core.annotation_io as annotation_io
import core.viewer as viewer_module
from core.annotations import AnnotationOp, list_document_annotations
from core.settings import SettingsManager


@pytest.fixture(scope="module")
def annotation_app():
    # Keep one application for this module and drain its workers before teardown.
    app = QApplication.instance() or QApplication(["annotation-transaction-test"])
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
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def state(window):
    return (
        tuple(page.get_text() for page in window.engine.document),
        tuple((entry["page"], entry["kind"], entry["text"], tuple(entry["rect"]))
              for entry in list_document_annotations(window.engine.document)),
    )


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
        def fail_midway(doc):
            original(doc, pages=[0])
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
