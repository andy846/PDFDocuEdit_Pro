"""PDF cleanup shares production services without approving or publishing a job."""
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from tests.test_pdf_operations import source_file
from tests.test_workflow_core import configured
from workflow.engine import execute
from workflow.extraction import ExtractionSpec, Region
from workflow.inspection import inspect_step, inspection_rows
from workflow.model import WorkflowNode, WorkflowRun, WorkflowSpec
from workflow.registry import default_options
from workflow.serializer import load_workflow, save_workflow


def recipe(source):
    spec = configured(source, source.parent / "output").upgraded(6)
    spec.node("extract").params = ExtractionSpec([Region(name="Content", x_mm=5, y_mm=5, width_mm=90, height_mm=20)]).to_dict()
    spec.node("group").params = {"method": "fixed", "pages": 1}
    node = WorkflowNode("flatten_pdf", params=default_options("flatten_pdf"))
    return spec.insert_after(spec.node("input").id, node), node


def test_cleanup_format_gate_and_legacy_roundtrip(tmp_path):
    original = WorkflowSpec.default()
    assert WorkflowSpec.from_dict(original.to_dict()).to_dict() == original.to_dict()
    with pytest.raises(ValueError):
        original.insert_after(original.node("input").id,
                              WorkflowNode("flatten_pdf", params=default_options("flatten_pdf")))
    spec, node = recipe(source_file(tmp_path))
    assert WorkflowSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()
    saved = save_workflow(spec, tmp_path / "cleanup.pdflow")
    reopened = load_workflow(saved)
    assert reopened.workflow_version == 6 and reopened.node("flatten_pdf").params == node.params
    with pytest.raises(ValueError):
        spec.insert_after(spec.node("group").id, replace(node, id="wrong"))


def test_cleanup_cache_source_invalidation_and_independent_nodes(tmp_path):
    source = source_file(tmp_path)
    raw = source.read_bytes()
    spec, node = recipe(source)
    second = WorkflowNode("repair_pdf", params=default_options("repair_pdf"))
    spec = spec.insert_after(node.id, second)
    run = execute(spec, WorkflowRun(), tmp_path / "scratch")
    assert not run.error, run.error
    assert not run.accepted and set(run.pdf_operation_reports) == {node.id, second.id}
    with fitz.open(run.source) as output:
        assert not list(output[0].annots() or [])
    prior = run.source
    run = execute(spec, run, tmp_path / "scratch")
    assert not run.error and run.source == prior
    spec.nodes[spec.nodes.index(node)].params["options"]["pages"] = [0]
    run = execute(spec, run, tmp_path / "scratch")
    assert not run.error and run.source != prior
    with fitz.open(run.source) as output:
        assert len(list(output[1].annots() or [])) == 1
    assert source.read_bytes() == raw
    assert not run.accepted and not run.output


def test_check_cleanup_disconnected_tail_preserves_page_identity(tmp_path):
    source = source_file(tmp_path)
    spec, node = recipe(source)
    spec.edges = [edge for edge in spec.edges if edge[0] != node.id]
    result = inspect_step(spec, node.id, tmp_path / "checks")
    assert result["result"]["status"] == "Checked", result["result"]["error"]
    rows = inspection_rows(tmp_path / "checks", result["result"]["run_id"], node.id, spec)
    assert rows["total"] == 2 and [row["source_id"] for row in rows["rows"]] == [1, 2]
    assert result["result"]["input_count"] == result["result"]["output_count"] == 2
    assert not (tmp_path / "output").exists()
    assert all(path.is_relative_to(tmp_path / "checks") for path in tmp_path.rglob("*flattened.pdf"))


def test_changed_private_cleanup_copy_is_not_reused(tmp_path):
    spec, node = recipe(source_file(tmp_path))
    run = execute(spec, WorkflowRun(), tmp_path / "scratch")
    previous = Path(run.source)
    previous.write_bytes(previous.read_bytes() + b"\n%tampered\n")
    run = execute(spec, run, tmp_path / "scratch")
    assert not run.error and Path(run.source) != previous


def test_cleanup_and_data_steps_share_existing_pipeline(tmp_path):
    spec, node = recipe(source_file(tmp_path))
    extra = WorkflowNode("create_fields", params={"fields": [{"field": "Fixed", "operation": "constant", "value": "value"}]})
    spec = spec.insert_after(spec.node("extract").id, extra)
    run = execute(spec, WorkflowRun(), tmp_path / "scratch")
    assert not run.error, run.error
    assert run.statuses[node.id] == "Completed" and not run.accepted


def test_cleanup_settings_ui_and_undo_share_headless_options(qt_application, monkeypatch):
    from PyQt6.QtWidgets import QPushButton

    from core.pdf_operations.model import PdfOptions
    from dialogs.pdf_operations import PdfOperationDialog
    from workflow.workspace import WorkflowWindow
    window = WorkflowWindow()
    window.show()
    qt_application.processEvents()
    try:
        window.insert_step("flatten_pdf", after_id=window.spec.node("input").id)
        node = window.spec.node("flatten_pdf")
        assert node and window.spec.workflow_version == 6
        button = next(button for button in window.inspector.findChildren(QPushButton)
                      if button.text() == "Configure PDF processing…")
        def settings(dialog):
            assert dialog.settings_only
            dialog.selected_options = PdfOptions(pages=(0, 2), forms=True)
            dialog.directory.cleanup()
            return 1
        monkeypatch.setattr(PdfOperationDialog, "exec", settings)
        button.click()
        assert tuple(window.spec.node("flatten_pdf").params["options"]["pages"]) == (0, 2)
        window.undo.undo()
        assert window.spec.node("flatten_pdf").params["options"]["pages"] is None
    finally:
        window._close_approved = True
        window.close()
        qt_application.processEvents()
