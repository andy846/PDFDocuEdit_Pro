"""Portable profiles, review safety and the shared Workflow/Designer handoff."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QScrollArea

from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.model import EnvelopeSpec
from composition.overlay.serializer import load_project, save_project
from composition.pdf_source.detection import DetectionConfig
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.profiles import load_profile, save_profile
from composition.pdf_source.smart_detection import (
    analyze_pdf,
    identity_fields,
    page_number,
    scan_pdf,
    spatial_lines,
    text_in,
)
from composition.pdf_source.source import inspect_source
from composition.template.model import CompositionError
from core.pdf_backend import fitz
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_smart_mailpieces import fixture_pdf
from tests.composition.test_workspace import wait_until
from tests.production_approval import execute
from workflow.extraction import ExtractionSpec, ExtractionStore, Region
from workflow.model import WorkflowRun, WorkflowSpec
from workflow.serializer import load_workflow, save_workflow
from workflow.workspace import WorkflowWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def analyzed(path, cache):
    value = analyze_pdf(path, cache)
    return scan_pdf(path, DetectionConfig(**value["suggestions"][0]["config"]), cache_path=cache)


def test_profile_roundtrip_reuses_rule_with_new_customer_values(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    value = analyzed(path, tmp_path/"cache.sqlite")
    profile = save_profile(tmp_path/"customer.pdmp", DetectionConfig(**value["detection"]["config"]))
    content = Path(profile).read_text(encoding="utf-8")
    assert str(path) not in content and "customer" not in content and "001" not in content
    other = fixture_pdf(tmp_path/"other.pdf", offset=100)
    result = scan_pdf(other, DetectionConfig(**load_profile(profile)))
    assert result["detection"]["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert not result["detection"]["findings"]
    bad = json.loads(content)
    bad["source"] = str(path)
    Path(profile).write_text(json.dumps(bad))
    with pytest.raises(CompositionError):
        load_profile(profile)


def test_region_does_not_match_marker_outside_region_on_same_line():
    lines = spatial_lines([(10, 10, 50, 20, "Body", 0, 0), (400, 10, 450, 20, "Dear", 1, 0)])
    assert "Dear" not in text_in(lines, [0, 0, 40, 20])


def test_labels_do_not_capture_recipient_prefix_or_dates_as_page_counters():
    lines = [{"text": "Mr Chan Employer Account No.: 00001 Member Account No.: 00002", "box": [0, 0, 500, 20]}]
    assert [(label, value) for label, value, _ in identity_fields(lines)] == [
        ("Employer Account No", "00001"), ("Member Account No", "00002")]
    assert page_number([{"text": "01/10/2026", "box": [0, 0, 500, 20]}], {"auto": True}) is None


def test_reviewed_detection_workflow_preserves_upstream_and_actual_audit(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    spec = WorkflowSpec.default()
    spec.node("input").params = {"paths": [str(path)]}
    spec.node("extract").params = ExtractionSpec([Region(x_mm=0, y_mm=30, width_mm=160, required=False)]).to_dict()
    run = execute(spec, WorkflowRun(), tmp_path/"run", until="extract")
    assert not run.error, run.error
    marker = Path(run.database).stat().st_mtime_ns
    result = analyzed(run.source, tmp_path/"cache.sqlite")
    report = result["detection"]
    report["accepted"] = True
    spec.node("group").params = {"method": "reviewed_detection", "detection_review": report}
    # A regroup uses the extracted database, including operator corrections.
    with ExtractionStore(run.database) as store:
        store.db.execute("INSERT INTO meta VALUES ('reuse_marker','keep')")
        store.db.commit()
    run = execute(spec, run, tmp_path/"run")
    assert not run.error and run.groups == [[1, 2], [3, 5], [6, 6]] and not run.accepted
    with ExtractionStore(run.database) as store:
        assert store.metadata()["reuse_marker"] == "keep"
        assert json.loads(store.metadata()["mailpiece_review"])["config"]["version"] == 2
        store.accept()
    assert Path(run.database).stat().st_mtime_ns >= marker
    saved = save_workflow(spec, tmp_path/"rules.pdflow")
    assert load_workflow(saved).node("group").params["detection_review"] == report
    overlay = spec.node("overlay")
    spec.nodes.remove(overlay)
    spec.edges = [edge for edge in spec.edges if overlay.id not in edge]
    spec.edges.append([spec.node("review").id, spec.node("output").id])
    spec.node("output").params = {"directory": str(tmp_path/"output")}
    run.accepted = True
    run = execute(spec, run, tmp_path/"run", until="review")
    run = execute(spec, run, tmp_path/"run", until="output")
    assert not run.error and run.output["status"] == "completed"
    report_folder = Path(run.output["report_dir"])
    audit = json.loads((report_folder/"job.json").read_text(encoding="utf-8"))
    assert audit["detection_review"]["config"]["version"] == 2
    with (report_folder/"detection.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[-1]["End basis"] == "pdf_end_inferred"
    assert "document_id" in rows[0]["Boundary evidence"]
    wrong = copy.deepcopy(report)
    wrong["source_sha256"] = "0"*64
    spec.node("group").params["detection_review"] = wrong
    run = execute(spec, run, tmp_path/"run")
    assert "source changed" in run.error.lower() and not run.accepted


@pytest.fixture
def overlay(app, tmp_path, monkeypatch):
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    monkeypatch.setattr(MailpieceDialog, "library_root", lambda self: str(tmp_path / "library"), raising=False)
    window = OverlayWindow()
    path = fixture_pdf(tmp_path/"source.pdf")
    settings = EnvelopeSettings(pages_per_envelope=1)
    window.apply_spec(EnvelopeSpec(inspect_source(path, settings, uniform=True), settings).to_dict())
    window.show()
    yield window
    for dialog in window.findChildren(MailpieceDialog):
        dialog.reject()
    finish(window)


def test_analyze_teach_profile_paired_preview_and_accept_undo(overlay, app, tmp_path, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.analyze_button.click()
    wait_until(lambda:dialog.smart_config is not None and not overlay.active_worker)
    assert "mm" in dialog.suggestion_reason.text()
    dialog.scan_button.click()
    wait_until(lambda:dialog.report is not None and not dialog.scan_worker)
    assert dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    wait_until(lambda:not dialog.preview.loading and not dialog.secondary_preview.preview.loading and not overlay.workers)
    assert dialog.secondary_preview.preview.scene().items()
    dialog.begin_teaching()
    for control, value in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(value)
    dialog.remember_marker()
    dialog.try_teaching.click()
    wait_until(lambda:dialog.report is not None and not dialog.scan_worker)
    assert dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    profile = tmp_path/"format.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs:(str(profile), ""))
    dialog.save_profile()
    wait_until(lambda:profile.exists() and not overlay.workers)
    assert dialog.report is not None
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs:(str(profile), ""))
    dialog.open_profile()
    wait_until(lambda:not dialog.scan_worker)
    assert dialog.smart_config["profile_name"] == "format" and dialog.report is None
    dialog.smart_scan()
    wait_until(lambda:dialog.report is not None and not dialog.scan_worker)
    dialog.resize(960, 640)
    app.processEvents()
    assert all(s.horizontalScrollBar().maximum() == 0 for s in dialog.findChildren(QScrollArea)), [
        (s.width(), s.horizontalScrollBar().maximum(), s.widget().minimumSizeHint().width()) for s in dialog.findChildren(QScrollArea)]
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs:(2, True))
    dialog.split()
    assert dialog.report["groups"][:2] == [[1, 1], [2, 2]]
    dialog.restore_boundary_edit(False)
    assert dialog.report["groups"][0] == [1, 2]
    dialog.acknowledge.setChecked(True)
    dialog.apply()
    wait_until(lambda:not overlay.active_worker and overlay.undo.count() == 1)
    assert overlay.spec.settings.groups == [[1, 2], [3, 5], [6, 6]]
    target = save_project(overlay.spec, tmp_path/"accepted.pdcx")
    assert load_project(target).detection_review["config"]["version"] == 2
    overlay.undo.undo()
    assert not overlay.spec.settings.groups


def test_source_changed_after_scan_cannot_be_accepted(overlay, tmp_path):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.scan()
    wait_until(lambda:dialog.report is not None and not dialog.scan_worker and not overlay.workers)
    dialog.acknowledge.setChecked(True)
    path = Path(overlay.spec.source.path)
    with fitz.open(path) as doc:
        doc[0].insert_text((30, 400), "Changed after scanning")
        doc.saveIncr()
    dialog.apply()
    wait_until(lambda:not overlay.active_worker)
    assert overlay.undo.count() == 0 and not overlay.spec.settings.groups
    assert "changed" in dialog.summary.text().lower() and dialog.report is None


def test_cancel_analysis_keeps_project_and_unlocks_review(overlay):
    before = overlay.spec.to_dict()
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.scan()
    assert dialog.scan_worker is not None
    dialog.cancel_button.click()
    wait_until(lambda:not dialog.scan_worker and not overlay.workers)
    assert overlay.spec.to_dict() == before and dialog.report is None
    assert dialog.analyze_button.isEnabled() and not dialog.apply_button.isEnabled()
    dialog.reject()


def test_filtered_exception_edits_target_original_envelope(overlay, monkeypatch):
    result = analyzed(overlay.spec.source.path, overlay.directory/"fixture.sqlite")
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.smart_config = result["detection"]["config"]
    result["detection"]["findings"] = [{"page": 4, "code": "fixture", "message": "Review this letter"}]
    dialog.scanned(result)
    assert dialog.model.rows == [1] and dialog.selected_row() == 1
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs:(4, True))
    dialog.split()
    assert dialog.report["groups"] == [[1, 2], [3, 3], [4, 5], [6, 6]]
    dialog.restore_boundary_edit(False)
    assert dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    dialog.reject()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_teaching_and_review_narrow_layout_in_both_themes(overlay, app, theme, monkeypatch):
    from styles.components import global_style
    from styles.theme import apply_theme, get_theme
    previous = get_theme()
    previous_style = app.styleSheet()
    monkeypatch.setattr(overlay, "worker", lambda *args, **kwargs:None)
    dialog = MailpieceDialog(overlay)
    try:
        apply_theme(app, theme)
        app.setStyleSheet(global_style())
        dialog.show()
        dialog.begin_teaching()
        dialog.resize(960, 640)
        app.processEvents()
        assert dialog.width() == 960 and dialog.height() == 640
        assert dialog.apply_button.mapTo(dialog, dialog.apply_button.rect().bottomRight()).x() < 960
        assert dialog.apply_button.mapTo(dialog, dialog.apply_button.rect().bottomRight()).y() < 640
        assert all(s.horizontalScrollBar().maximum() == 0 for s in dialog.findChildren(QScrollArea))
        dialog.finish_teaching.click()
        assert not dialog.teaching and not dialog.first_sample.isVisible()
    finally:
        dialog.reject()
        apply_theme(app, previous)
        app.setStyleSheet(previous_style)


def test_workflow_auto_detect_shared_dialog_handoff(app, tmp_path):
    window = WorkflowWindow()
    window.show()
    try:
        path = fixture_pdf(tmp_path/"source.pdf")
        raw = window.spec.to_dict()
        next(n for n in raw["nodes"] if n["kind"] == "input")["params"] = {"paths": [str(path)]}
        next(n for n in raw["nodes"] if n["kind"] == "extract")["params"] = ExtractionSpec([
            Region(x_mm=0, y_mm=30, width_mm=160, required=False)]).to_dict()
        window.apply_spec(raw)
        window.select_node(window.spec.node("group").id)
        window.auto_detect_mailpieces()
        wait_until(lambda:getattr(window, "detection_dialog", None) is not None and not window.active_worker, timeout=30)
        dialog = window.detection_dialog
        dialog.scan()
        wait_until(lambda:dialog.report is not None and not dialog.scan_worker, timeout=30)
        database = window.run.database
        dialog.acknowledge.setChecked(True)
        dialog.apply()
        wait_until(lambda:not window.workers and window.run.groups == [[1, 2], [3, 5], [6, 6]], timeout=30)
        assert window.run.database == database and not window.run.error
        assert window.spec.node("group").params["detection_review"]["accepted"] is True
        assert not window.run.accepted  # Data/extraction still needs its separate review.
        window.auto_detect_mailpieces()
        wait_until(lambda:window.detection_dialog is not dialog and not window.active_worker)
        assert window.detection_dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
        window.detection_dialog.reject()
    finally:
        window._close_approved = True
        window.close()
        wait_until(lambda:not window.workers)



def test_default_detection_window_uses_available_screen(overlay, monkeypatch):
    from types import SimpleNamespace

    from PyQt6.QtCore import QRect

    monkeypatch.setattr(MailpieceDialog, "screen", lambda self: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1440, 1000)))
    monkeypatch.setattr(overlay, "worker", lambda *a, **k: None)
    dialog = MailpieceDialog(overlay)
    try:
        assert 1250 <= dialog.width() <= 1440
        assert 800 <= dialog.height() <= 1000
    finally:
        dialog.reject()


def test_profile_actions_remain_visible_when_teaching_is_scrolled(overlay, app, monkeypatch):
    monkeypatch.setattr(overlay, "worker", lambda *a, **k: None)
    dialog = MailpieceDialog(overlay)
    dialog.show()
    try:
        dialog.begin_teaching()
        dialog.resize(960, 640)
        app.processEvents()
        dialog.controls_scroll.verticalScrollBar().setValue(dialog.controls_scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert dialog.save_profile_button.isVisible()
        assert not dialog.controls_scroll.isAncestorOf(dialog.save_profile_button)
        assert dialog.save_profile_button.mapTo(dialog, dialog.save_profile_button.rect().bottomRight()).x() < 960
        assert dialog.save_profile_button.mapTo(dialog, dialog.save_profile_button.rect().bottomRight()).y() < 640
    finally:
        dialog.reject()


def test_save_profile_compiles_drawn_lesson_without_try_step(overlay, app, tmp_path, monkeypatch):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest

    original = overlay.spec.to_dict()
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.begin_teaching()
    wait_until(lambda: not dialog.preview.loading and not overlay.workers)
    target = tmp_path / "direct-save.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    start = dialog.preview.mapFromScene(QPointF(8, 19))
    end = dialog.preview.mapFromScene(QPointF(78, 27))
    QTest.mousePress(dialog.preview.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(dialog.preview.viewport(), end)
    QTest.mouseRelease(dialog.preview.viewport(), Qt.MouseButton.LeftButton, pos=end)
    dialog.save_profile()
    assert dialog.scan_worker is not None
    wait_until(lambda: target.exists() and not overlay.workers)
    assert load_profile(target)["rules"][0]["terms"] == ["Dear"]
    assert overlay.spec.to_dict() == original and overlay.undo.count() == 0
    assert not dialog.acknowledge.isChecked()
    dialog.reject()


def test_save_revalidates_edited_lesson_instead_of_exporting_old_rule(overlay, tmp_path, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.begin_teaching()
    for control, value in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(value)
    dialog.remember_marker()
    dialog.teach_scan()
    wait_until(lambda: dialog.report is not None and not overlay.workers)
    dialog.static_marker.setText("UNMATCHED STATIC HEADING")
    target = tmp_path / "stale.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_profile()
    assert dialog.scan_worker is not None
    wait_until(lambda: not overlay.workers)
    assert not target.exists()
    assert "not saved" in dialog.summary.text().lower()
    assert not dialog.apply_button.isEnabled()
    dialog.reject()


def test_cancel_teach_and_save_never_opens_save_picker(overlay, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.begin_teaching()
    for control, value in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(value)
    dialog.remember_marker()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("Cancelled lesson opened save picker"))
    dialog.save_profile()
    assert dialog.scan_worker is not None
    dialog.cancel_button.click()
    wait_until(lambda: not overlay.workers)
    assert not dialog.pending_profile_save
    dialog.reject()



def test_save_pending_lesson_after_returning_to_boundary_review(overlay, tmp_path, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.begin_teaching()
    for control, value in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(value)
    dialog.remember_marker()
    dialog.end_teaching()
    target = tmp_path / "review-save.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_profile()
    assert dialog.scan_worker is not None
    wait_until(lambda: target.exists() and not overlay.workers)
    assert load_profile(target)["rules"][0]["terms"] == ["Dear"]
    dialog.reject()


def test_image_or_blank_feature_never_saves_an_empty_profile(overlay, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.begin_teaching()
    for control, value in zip(dialog.region, [120, 100, 20, 10], strict=True):
        control.setValue(value)
    dialog.remember_marker()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("No PDF text must not offer Save"))
    dialog.save_profile()
    assert dialog.scan_worker is not None
    wait_until(lambda: not overlay.workers)
    assert "not saved" in dialog.summary.text().lower()
    assert "QR/image" in dialog.summary.text()
    assert not dialog.apply_button.isEnabled()
    dialog.reject()



def test_save_current_method_never_exports_previous_smart_rule(overlay, tmp_path, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.smart_config = analyzed(overlay.spec.source.path, overlay.directory / "save-method.sqlite")["detection"]["config"]
    dialog.method.setCurrentIndex(dialog.method.findData("page_number"))
    target = tmp_path / "current-method.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_profile()
    wait_until(lambda: not overlay.workers)
    assert target.exists(), dialog.summary.text()
    saved = load_profile(target)
    assert saved["version"] == 1
    assert saved["rules"] == [{"kind": "page_number", "pattern": dialog.number_pattern.text()}]
    dialog.reject()


def test_region_profile_save_reopen_rescan_preserves_rules_not_review(overlay, tmp_path, monkeypatch):
    original = overlay.spec.to_dict()
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.method.setCurrentIndex(dialog.method.findData("region_present"))
    dialog.whole.setChecked(False)
    for control, value in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(value)
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not overlay.workers)
    assert dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    dialog.report["groups"] = [[1, 5], [6, 6]]  # Operator corrections belong to this PDF only.
    dialog.acknowledge.setChecked(True)
    report_before = copy.deepcopy(dialog.report)
    target = tmp_path / "region.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_profile_button.click()
    wait_until(lambda: not overlay.workers)
    assert target.exists(), dialog.summary.text()
    saved = load_profile(target)
    assert saved["rules"] == [{"kind": "region_present"}]
    assert saved["region_mm"] == [8, 19, 70, 8]
    assert dialog.report == report_before and dialog.acknowledge.isChecked()
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert set(raw) == {"profile_version", "config"}
    assert "source_sha256" not in raw["config"] and "groups" not in raw["config"]
    assert str(overlay.spec.source.path) not in target.read_text(encoding="utf-8")
    dialog.reject()
    reopened = MailpieceDialog(overlay)
    reopened.show()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    reopened.open_profile_button.click()
    wait_until(lambda: not overlay.workers)
    assert reopened.method.currentData() == "region_present", reopened.summary.text()
    assert reopened.report is None and not reopened.acknowledge.isChecked()
    assert not reopened.apply_button.isEnabled()
    assert not reopened.suggestion_reason.isVisible()
    reopened.scan()
    wait_until(lambda: reopened.report is not None and not overlay.workers)
    assert reopened.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert overlay.spec.to_dict() == original and overlay.undo.count() == 0
    reopened.reject()


def test_invalid_region_profile_does_not_open_save_picker(overlay, monkeypatch):
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.method.setCurrentIndex(dialog.method.findData("region_present"))
    dialog.whole.setChecked(True)
    wait_until(lambda: not overlay.workers)  # Initial page previews are separate from profile saving.
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("Invalid rule opened Save"))
    dialog.save_profile()
    assert "selected search region" in dialog.summary.text()
    assert not overlay.workers
    dialog.reject()



def test_manual_save_appears_in_library_and_use_restores_current_method(overlay, tmp_path, monkeypatch):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog
    from composition.pdf_source.profile_library import ProfileLibrary

    original = overlay.spec.to_dict()
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.method.setCurrentIndex(dialog.method.findData("region_present"))
    dialog.whole.setChecked(False)
    for control, number in zip(dialog.region, [8, 19, 70, 8], strict=True):
        control.setValue(number)
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not overlay.workers)
    library = ProfileLibrary(dialog.library_root())
    assert library.list()["entries"] == []  # Scanning never creates library entries.
    target = tmp_path / "saved.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_profile()
    wait_until(lambda: not overlay.workers)
    assert target.exists()
    entries = library.list()["entries"]
    assert len(entries) == 1
    dialog.method.setCurrentIndex(dialog.method.findData("page_number"))
    def select_saved(manager):
        manager.show()
        wait_until(lambda: not manager.busy and len(manager.records) == 1)
        manager.entries.setCurrentRow(0)
        wait_until(lambda: not manager.busy and manager.value is not None)
        assert manager.use_button.isEnabled()
        assert str(tmp_path / "library") in manager.location.text()
        manager.use_profile()
        return manager.result()
    monkeypatch.setattr(ProfileLibraryDialog, "exec", select_saved)
    dialog.open_library()
    assert dialog.method.currentData() == "region_present"
    assert [c.value() for c in dialog.region] == [8, 19, 70, 8]
    assert dialog.report is None and not dialog.acknowledge.isChecked()
    assert not dialog.apply_button.isEnabled()
    dialog.scan()
    wait_until(lambda: dialog.report is not None and not overlay.workers)
    assert dialog.report["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert overlay.spec.to_dict() == original
    dialog.reject()


def test_external_save_reports_library_failure_without_losing_file(overlay, tmp_path, monkeypatch):
    library_root = tmp_path / "not-a-directory"
    library_root.write_text("occupied")
    monkeypatch.setattr(MailpieceDialog, "library_root", lambda self: str(library_root))
    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.method.setCurrentIndex(dialog.method.findData("page_number"))
    target = tmp_path / "preserved.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    wait_until(lambda: not overlay.workers)
    dialog.save_profile()
    wait_until(lambda: not overlay.workers)
    assert target.exists()
    assert "Library" in dialog.summary.text() and "not" in dialog.summary.text().lower()
    assert load_profile(target)["version"] == 1
    dialog.reject()



def test_save_opened_collection_also_registers_it_in_library(overlay, tmp_path, monkeypatch):
    from composition.pdf_source.profile_library import ProfileLibrary, new_profile, new_rule

    dialog = MailpieceDialog(overlay)
    dialog.show()
    value = new_profile("External collection")
    value["rule_sets"] = [new_rule("Letters", analyzed(overlay.spec.source.path, tmp_path / "collection.sqlite")["detection"]["config"], template_id="LETTER")]
    dialog.set_collection_profile(value)
    target = tmp_path / "collection.pdmpx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    wait_until(lambda: not overlay.workers)
    dialog.save_profile()
    wait_until(lambda: not overlay.workers)
    library = ProfileLibrary(dialog.library_root())
    assert target.exists()
    assert len(library.list()["entries"]) == 1
    assert library.read(value["profile_id"]) == value
    assert dialog.single_library_profile is None
    dialog.reject()



def test_save_locks_library_until_registration_finishes(overlay, tmp_path, monkeypatch):
    from composition.designer.mailpiece_profile_library import ProfileLibraryDialog

    dialog = MailpieceDialog(overlay)
    dialog.show()
    dialog.method.setCurrentIndex(dialog.method.findData("page_number"))
    wait_until(lambda: not overlay.workers)
    target = tmp_path / "one-save.pdmp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(ProfileLibraryDialog, "exec", lambda self: pytest.fail("Library opened before Save completed"))
    dialog.save_profile()
    assert overlay.active_worker is not None
    dialog.open_library()
    assert "Wait" in dialog.summary.text()
    wait_until(lambda: not overlay.workers)
    assert target.exists()
    assert overlay.active_worker is None
    dialog.reject()
