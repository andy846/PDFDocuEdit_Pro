"""Portable profiles, review safety and the shared Workflow/Designer handoff."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import fitz
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
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_smart_mailpieces import fixture_pdf
from tests.composition.test_workspace import wait_until
from workflow.engine import execute
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
