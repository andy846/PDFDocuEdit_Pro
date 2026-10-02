"""Focused regression cases for layout and mailpiece review hardening."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.canvas import Canvas
from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.detection import DetectionConfig, detect_texts, page_text
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.template.model import MM_TO_PT, CompositionError, Element, Template
from composition.worker import dispatch
from tests.composition.test_mailpiece_detection import make_pdf, variable_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def bounded_ui(monkeypatch):
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)


class ControlledWorker(QObject):
    ended = pyqtSignal()
    progress = pyqtSignal(int, int, str)

    def __init__(self):
        super().__init__()
        self.stopped = 0

    def stop_preview(self):
        self.stopped += 1

    def cancel(self):
        self.stopped += 1


def test_pending_review_survives_reinspection_and_sequence_changes(app, tmp_path, monkeypatch):
    path = make_pdf(tmp_path, ["Page 1 of 2", "Page 2 of 2"])
    settings = EnvelopeSettings(pages_per_envelope=1)
    spec = EnvelopeSpec(inspect_source(path, settings, uniform=True), settings,
                        detection_review={"required": True, "accepted": False})
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        requests = []
        def worker(request, ready, *args, **kwargs):
            requests.append(request)
            ready(dispatch(request))
        monkeypatch.setattr(window, "worker", worker)
        monkeypatch.setattr(window, "detect_mailpieces", lambda: None)
        settings.start = 100
        window.inspect_source(path, settings, preserve=True)
        assert requests[0]["uniform"]
        assert window.spec.source.geometry_mode == "uniform"
        assert window.spec.needs_detection_review
        assert not window.actions["generate"].isEnabled()
        assert window.spec.settings.start == 100
        window.undo.undo()
        assert window.spec.needs_detection_review and window.spec.settings.start == 1
    finally:
        finish(window)


def test_preview_bounded_latest_only_unique_paths_and_stale_errors(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    requests = []
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        def worker(request, ready, failed=None, **kwargs):
            instance = ControlledWorker()
            requests.append((request, ready, failed, instance))
            return instance
        monkeypatch.setattr(window, "worker", worker)
        dialog = MailpieceDialog(window)
        dialog.show()
        for page in range(2, 10):
            dialog.show_source_page(page)
        assert len(requests) == 1
        dialog.detail.setPlainText("Current selection")
        old, _, fail, instance = requests[0]
        Path(old["target"]).touch()
        fail("Old failure")
        assert dialog.detail.toPlainText() == "Current selection"
        instance.ended.emit()
        app.processEvents()
        assert len(requests) == 2 and requests[-1][0]["page"] == 9
        assert not Path(old["target"]).exists()
        latest, ready, _, instance = requests[-1]
        assert latest["target"] != old["target"]
        ready(dispatch(latest))
        assert not dialog.preview.sceneRect().isEmpty()
        assert not Path(latest["target"]).exists()
        dialog.reject()
        instance.ended.emit()
        app.processEvents()
        count = len(requests)
        assert count == 2
        other = MailpieceDialog(window)
        assert len(requests) == count+1
        assert requests[-1][0]["target"] not in (old["target"], latest["target"])
        other.reject()
        requests[-1][3].ended.emit()
        app.processEvents()
    finally:
        finish(window)


def test_scan_local_progress_close_reopen_discards_late_results(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        calls = []
        def worker(request, ready, failed=None, **kwargs):
            if request["task"] != "mailpiece_scan":
                return None
            instance = ControlledWorker()
            calls.append((request, ready, failed, instance))
            return instance
        monkeypatch.setattr(window, "worker", worker)
        dialog = MailpieceDialog(window)
        dialog.show()
        dialog.scan()
        assert dialog.model.rowCount() == 0 and dialog.scan_progress.isVisible()
        request, ready, failed, instance = calls[-1]
        instance.progress.emit(2, 13, "Scanning source page 2")
        assert dialog.scan_progress.value() == 2
        assert "page 2" in dialog.scan_status.text()
        dialog.reject()
        dialog.show()
        ready(dispatch(request))
        failed("Obsolete error")
        assert dialog.report is None and "Obsolete" not in dialog.summary.text()
        instance.ended.emit()
        assert not dialog.scan_progress.isVisible() and not dialog.apply_button.isEnabled()
        dialog.reject()
    finally:
        finish(window)


def test_review_edits_keep_context_warnings_cycle_and_stale_rows_clear(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        monkeypatch.setattr(window, "worker", lambda *args, **kwargs: None)
        dialog = MailpieceDialog(window)
        dialog.show()
        dialog.report["findings"] = [{"page": 5, "message": "First warning"}, {"page": 6, "message": "Second warning"}]
        dialog.show_report()
        dialog.select_next_warning()
        assert dialog.table.currentIndex().row() == 2 and dialog.preview_page.value() == 5
        dialog.select_next_warning()
        assert dialog.preview_page.value() == 6
        original_groups = [list(group) for group in dialog.report["groups"]]
        dialog.merge()
        assert dialog.table.currentIndex().row() == 1
        dialog.undo_boundary.click()
        assert dialog.report["groups"] == original_groups and dialog.table.currentIndex().row() == 2
        dialog.redo_boundary.click()
        assert dialog.table.currentIndex().row() == 1 and not dialog.acknowledge.isChecked()
        monkeypatch.setattr("composition.designer.mailpiece_dialog.QInputDialog.getInt", lambda *a: (7, True))
        dialog.split()
        assert dialog.table.currentIndex().row() == 2 and dialog.report["groups"][2][0] == 7
        dialog.number_pattern.setText("{CURRENT}/{TOTAL}")
        assert dialog.model.rowCount() == 0 and dialog.report is None
        assert not dialog.merge_button.isEnabled() and not dialog.next_warning.isEnabled()
        dialog.reject()
    finally:
        finish(window)


def test_search_region_visual_sync_zoom_resize_and_load_mid_drag(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        monkeypatch.setattr(window, "worker", lambda *args, **kwargs: None)
        dialog = MailpieceDialog(window)
        dialog.show()
        source = asdict(window.spec.source)
        value = dispatch({"task": "mailpiece_preview", "source": source["path"], "page": 1,
                          "size": source["size"], "mtime_ns": source["mtime_ns"], "target": str(tmp_path/"preview.png")})
        view = dialog.preview
        view.load(value["image"], value["geometry"])
        dialog.whole.setChecked(False)
        assert view.region_item.isVisible()
        dialog.region[0].setValue(40)
        assert view.region_item.rect().x() == 40
        view.fit_mode = False
        view.scale(2, 2)
        zoom = view.transform().m11()
        dialog.resize(960, 640)
        app.processEvents()
        assert view.transform().m11() == zoom
        view.load(value["image"], value["geometry"])
        assert view.transform().m11() == zoom and view.region_item.rect().x() == 40
        view.fit_page()
        point = view.mapFromScene(QPointF(70, 100))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert view.anchor is not None
        view.load(value["image"], value["geometry"])
        assert view.anchor is None
        QTest.mouseMove(view.viewport(), point)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        with pytest.raises(ValueError, match="could not be loaded"):
            view.load(str(tmp_path/"missing.png"), value["geometry"])
        dialog.reject()
    finally:
        finish(window)


@pytest.mark.parametrize("angle", [37, 90, 180, 270])
def test_rotated_resize_keeps_opposite_corner_and_one_commit(app, angle):
    canvas = Canvas()
    try:
        canvas.resize(800, 800)
        canvas.show()
        element = Element(x_mm=60, y_mm=90, width_mm=40, height_mm=20, rotation_deg=angle)
        canvas.set_template(Template(elements=[element]), [element.id])
        canvas.set_zoom(2)
        app.processEvents()
        item = canvas.element_items[0]
        corner = item.mapToScene(QPointF(0, 0))
        start = canvas.mapFromScene(item.mapToScene(QPointF(39, 19)))
        end = canvas.mapFromScene(item.mapToScene(QPointF(49, 24)))
        commits = []
        canvas.editCommitted.connect(lambda before, after: commits.append(after))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end, 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert len(commits) == 1
        after = item.mapToScene(QPointF(0, 0))
        assert (after.x(), after.y()) == pytest.approx((corner.x(), corner.y()), abs=.03)
        assert element.width_mm == pytest.approx(50, abs=.3)
        assert element.height_mm == pytest.approx(25, abs=.3)
        Template.from_dict(commits[0])
    finally:
        canvas.close()


def test_rejected_batch_size_restores_controls_and_mixed_geometry(app):
    window = CompositionWindow()
    try:
        elements = [Element(x_mm=20, y_mm=60, width_mm=30), Element(x_mm=170, y_mm=90, width_mm=25)]
        window._apply_template(Template(elements=elements).to_dict())
        window.canvas.select_ids([e.id for e in elements])
        assert "mixed" in window.properties.geometry.title()
        before = window.template.to_dict()
        window.properties.numbers["width_mm"].setValue(100)
        window.properties.geometry_apply.click()
        assert window.template.to_dict() == before
        assert window.properties.numbers["width_mm"].value() == 30
        assert not window.properties.geometry_checks["width_mm"].isChecked()
        assert "page width" in window.message.text()
    finally:
        close_window(window)


def test_rounded_full_page_region_and_literal_pattern_boundaries(tmp_path):
    path = make_pdf(tmp_path, ["Page 1 of 1"])
    with fitz.open(path) as pdf:
        page = pdf[0]
        assert "Page 1" in page_text(page, [0, 0, round(page.rect.width/MM_TO_PT, 2), round(page.rect.height/MM_TO_PT, 2)])
        with pytest.raises(CompositionError, match="beyond"):
            page_text(page, [0, 0, page.rect.width/MM_TO_PT+1, page.rect.height/MM_TO_PT])
    config = DetectionConfig(rules=[{"kind": "document_id", "pattern": "ID: {ID} ;"}])
    report = detect_texts(["ID: A ; note ;", "ID: A ; revised ;", "ID: B ; note ;"], config)
    assert report["groups"] == [[1, 2], [3, 3]]
    report = detect_texts(["Page 1 of 1234567"], DetectionConfig())
    assert any(f["code"] == "missing_signal" for f in report["findings"])
    with pytest.raises(CompositionError, match="Unexpected"):
        DetectionConfig(rules=[{"kind": "first_text", "terms": ["start"], "pattern": "{ID}"}]).validate()


def test_cached_review_refreshes_after_project_undo_or_settings_change(app, tmp_path, monkeypatch):
    window = OverlayWindow()
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        monkeypatch.setattr(window, "worker", lambda *args, **kwargs: None)
        window.detect_mailpieces()
        first = window.detection_dialog
        first.reject()
        raw = window.spec.to_dict()
        raw["settings"]["prefix"] = "Batch-"
        assert window.commit(raw, "Sequence prefix")
        window.detect_mailpieces()
        second = window.detection_dialog
        assert first is not second and second.context_settings["prefix"] == "Batch-"
        second.reject()
        window.undo.undo()
        window.detect_mailpieces()
        assert window.detection_dialog is not second
        assert window.detection_dialog.context_settings["prefix"] == ""
        window.detection_dialog.reject()
    finally:
        finish(window)


def test_rejected_overlay_drag_restores_visible_canvas(app, tmp_path):
    window = OverlayWindow()
    try:
        window.apply_spec(variable_spec(tmp_path).to_dict())
        before = window.spec.to_dict()
        item = window.canvas.element_items[0]
        item.setSelected(True)
        prior = window.canvas.snapshot()
        item.element.width_mm = 1000
        item.setRect(0, 0, 1000, item.rect().height())
        window.canvas_edit(prior, window.canvas.snapshot())
        after = window.spec.to_dict()
        assert after == before and window.undo.count() == 0
        restored = next(i for i in window.canvas.element_items if i.element.id == item.element.id)
        assert restored.rect().width() == before["objects"][0]["element"]["width_mm"]
    finally:
        finish(window)


def test_overlay_geometry_checks_applicable_roles_without_rejecting_repairable_projects(app, tmp_path):
    from composition.overlay.model import OverlayObject
    path = tmp_path/"different-roles.pdf"
    with fitz.open() as pdf:
        pdf.new_page(width=595, height=842)
        pdf.new_page(width=300, height=842)
        pdf.save(path)
    settings = EnvelopeSettings(pages_per_envelope=2)
    spec = EnvelopeSpec(inspect_source(path, settings), settings,
                        [OverlayObject(Element(value="Sequence", x_mm=20, y_mm=40), scope="first")])
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        raw = window.spec.to_dict()
        raw["objects"][0]["element"]["width_mm"] = 100
        assert window.commit(raw, "Resize first-page text")
        before = window.spec.to_dict()
        raw = window.spec.to_dict()
        raw["objects"][0]["scope"] = "all_source"
        assert not window.commit(raw, "Change scope")
        assert window.spec.to_dict() == before and "outside" in window.statusBar().currentMessage()
        window.canvas.select_ids([window.spec.objects[0].element.id])
        window.scope.setCurrentIndex(window.scope.findData("all_source"))
        assert window.scope.currentData() == "first" and window.spec.to_dict() == before
        # A legacy bad layout still opens for repair rather than becoming unusable.
        window.apply_spec(raw)
        raw["objects"][0]["element"]["width_mm"] = 70
        assert window.commit(raw, "Repair width")
        assert window.spec.objects[0].element.width_mm == 70
    finally:
        finish(window)
