from __future__ import annotations

import json

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.media.planner import preview_plan
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


def test_apply_smaller_plan_and_undo_clamp_indices(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    monkeypatch.setattr(window, "schedule_preview", lambda *args: None)
    try:
        large = sample_spec(tmp_path, pages=60, duplex=True)
        assert window.apply_spec(large.to_dict())
        window.envelope.setValue(20)
        window.print_page.setValue(4)
        small = sample_spec(tmp_path, pages=6)
        assert window.commit(small.to_dict(), "Smaller source")
        assert (window.envelope.value(), window.print_page.value()) == (2, 3)
        window.undo.undo()
        window.envelope.setValue(20)
        window.print_page.setValue(4)
        window.undo.redo()
        assert (window.envelope.value(), window.print_page.value()) == (2, 3)
        assert not window.draft_error
    finally:
        finish(window)


def test_invalid_plan_preserves_spec_and_can_recover(app, tmp_path, monkeypatch):
    import composition.designer.overlay_workspace as module
    from composition.template.model import CompositionError

    window = OverlayWindow()
    monkeypatch.setattr(window, "schedule_preview", lambda *args: None)
    try:
        value = sample_spec(tmp_path).to_dict()
        assert window.apply_spec(value)
        previous = window.spec
        real_plan = module.preview_plan

        def invalid(spec):
            raise CompositionError("Invalid envelope plan")

        monkeypatch.setattr(module, "preview_plan", invalid)
        assert not window.apply_spec(value)
        assert window.spec is previous and window.draft_error
        window.refresh_canvas()
        assert "Preview unavailable" in window.preview_status.text()
        assert not window.timer.isActive()
        monkeypatch.setattr(module, "preview_plan", real_plan)
        assert window.apply_spec(value)
        assert not window.draft_error
    finally:
        finish(window)


def test_variable_envelope_pages_clamp_before_lookup(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    monkeypatch.setattr(window, "schedule_preview", lambda *args: None)
    try:
        value = sample_spec(tmp_path, pages=60).to_dict()
        assert window.apply_spec(value)
        window.envelope.setValue(20)
        window.print_page.setValue(3)
        value["settings"]["groups"] = [[1, 59], [60, 60]]
        value["source"]["geometry_mode"] = "uniform"
        value["source"]["geometries"] = value["source"]["geometries"][:1]
        value["detection_review"] = {
            "accepted": True, "source_sha256": value["source"]["sha256"],
            "groups": value["settings"]["groups"], "excluded_pages": [],
            "config": {"rules": [{"kind": "page_number", "pattern": "Page {CURRENT} of {TOTAL}"}]},
            "pages": 60, "findings": [], "evidence": [], "edits": [],
        }
        assert window.apply_spec(value)
        assert (window.envelope.value(), window.print_page.value()) == (2, 1)
        window.envelope.setValue(1)
        window.print_page.setValue(59)
        window.envelope.setValue(2)
        assert window.print_page.value() == 1
        assert not window.draft_error
        window.envelope.blockSignals(True)
        window.sync_preview_indices(preview_plan(window.spec))
        assert window.envelope.signalsBlocked()
        window.envelope.blockSignals(False)
    finally:
        finish(window)


def test_source_preview_bulk_typography_save_and_production(app, tmp_path):
    window = OverlayWindow()
    try:
        window.show()
        source = make_source(tmp_path/"input.pdf", 60)
        window.inspect_source(source)
        wait_until(lambda: window.spec is not None and not window.active_worker)
        assert len(window.spec.objects) == 1
        window.add_object("code128", y=35)
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
        from tests.composition.review_helpers import confirm_review
        confirm_review(window)
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
        wait_until(lambda: len(window.production_review.results) == 1 and not window.active_worker)
        review = window.production_review.results[0]
        assert review["status"] == "blocked"
        assert not window.production_review.pane.confirm.isEnabled()
        assert not (tmp_path/"failed").exists()
        assert not window.pdf_button.isEnabled()
        window.required_scope.setCurrentIndex(window.required_scope.findData("first"))
        window.generate_pdf(output_dir=tmp_path/"valid")
        from tests.composition.review_helpers import confirm_review
        confirm_review(window)
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
