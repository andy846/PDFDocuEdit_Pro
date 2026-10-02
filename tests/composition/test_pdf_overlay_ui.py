from __future__ import annotations

import json

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.overlay.serializer import load_project, save_project
from tests.composition.test_pdf_overlay_models import make_source, sample_spec
from tests.composition.test_workspace import close_window, wait_until


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def finish(window):
    window.undo.setClean()
    window.draft_error = ""
    window.close()
    wait_until(lambda: not window.workers)


def test_source_preview_bulk_typography_save_and_production(app, tmp_path):
    window = OverlayWindow()
    try:
        window.show()
        source = make_source(tmp_path/"input.pdf", 60)
        window.inspect_source(source)
        wait_until(lambda: window.spec is not None and not window.active_worker)
        assert len(window.spec.objects) == 2
        assert window.spec.objects[1].control
        window.envelope.setValue(20)
        window.print_page.setValue(3)
        wait_until(lambda: window.canvas.preview_item is not None)
        assert "000020" in window.position.text() and "Source 60" in window.position.text()
        window.add_object("text", "SourcePage", y=60)
        texts = [obj.element.id for obj in window.spec.objects if obj.element.type == "text"]
        window.canvas.select_ids(texts)
        window.property_edit({"font": {"size_pt": 15}})
        assert all(obj.element.font.size_pt == 15 for obj in window.spec.objects if obj.element.id in texts)
        window.undo.undo()
        assert all(obj.element.font.size_pt == 10 for obj in window.spec.objects if obj.element.id in texts)
        window.undo.redo()
        target = tmp_path/"overlay.pdcx"
        window.save_project(path=target)
        wait_until(lambda: not window.active_worker)
        assert load_project(target).source.path == str(source)
        assert window.undo.isClean()
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        window.generate_pdf(output_dir=tmp_path/"output")
        wait_until(lambda: window.last_result is not None and not window.active_worker)
        timer.stop()
        assert ticks
        result = window.last_result
        assert result["status"] == "completed", result["error"]
        assert result["successful_envelopes"] == 20 and result["decoded_barcodes"] == 60
        with fitz.open(result["output_pdf"]) as doc:
            assert "Original Source Page 60" in doc[59].get_text()
            assert "000020" in doc[59].get_text()
        for width, height in [(1280, 820), (960, 640)]:
            window.resize(width, height)
            QApplication.processEvents()
            assert window.canvas.width() > 400
            assert window.position.geometry().right() < window.centralWidget().width()
    finally:
        finish(window)


def test_object_scope_payload_and_coverage_failure(app, tmp_path):
    spec = sample_spec(tmp_path)
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        barcode = spec.objects[1].element.id
        window.canvas.select_ids([barcode])
        window.scope.setCurrentIndex(window.scope.findData("first"))
        assert window.spec.objects[1].scope == "first"
        window.generate_pdf(output_dir=tmp_path/"failed")
        wait_until(lambda: window.last_result is not None and not window.active_worker)
        assert window.last_result["status"] == "failed"
        assert window.last_result["error_source_page"] == 2
        assert not window.pdf_button.isEnabled()
        window.required_scope.setCurrentIndex(window.required_scope.findData("first"))
        window.generate_pdf(output_dir=tmp_path/"valid")
        wait_until(lambda: window.last_result is not None and not window.active_worker)
        assert window.last_result["status"] == "completed", window.last_result["error"]
        assert window.last_result["decoded_barcodes"] == 2
    finally:
        finish(window)


def test_open_overlay_preserves_unsaved_standard_template(app, tmp_path, monkeypatch):
    path = save_project(sample_spec(tmp_path), tmp_path/"job.pdcx")
    editor = CompositionWindow()
    try:
        editor.add_element("text", "Existing unsaved template")
        before = editor.template.to_dict()
        monkeypatch.setattr(editor, "_discard_check", lambda: pytest.fail("Overlay must not discard standard template"))
        editor.open_project(path=str(path))
        assert editor.template.to_dict() == before and not editor.undo.isClean()
        assert len(editor.overlay_windows) == 1
        assert json.loads(path.read_text())["project_kind"] == "pdf_overlay"
        finish(editor.overlay_windows[0])
    finally:
        monkeypatch.undo()
        close_window(editor)


def test_close_before_deferred_font_loading_starts_no_worker(app):
    from PyQt6.QtTest import QTest
    window = OverlayWindow()
    window.close()
    QTest.qWait(100)
    assert window.close_pending and not window.workers
    assert not window.directory.exists()
