"""Targeted node identity, retained drafts and safe inspection behavior."""
import pytest
from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from tests.composition.test_workspace import wait_until
from workflow.model import WorkflowNode
from workflow.registry import default_options
from workflow.workspace import WorkflowWindow


@pytest.fixture
def window(qt_application):
    window = WorkflowWindow()
    window.show()
    yield window
    window._close_approved = True
    window.close()
    wait_until(lambda: not window.workers)


def test_invalid_node_draft_survives_navigation_and_blocks_save(window, tmp_path):
    node = window.spec.node("group")
    window.select_node(node.id)
    form = QWidget()
    layout = QVBoxLayout(form)
    number = QLineEdit("1")
    layout.addWidget(number)
    window.inspector_scroll.takeWidget().deleteLater()
    window.inspector = form
    window.inspector_scroll.setWidget(form)
    window.watch_settings(node, lambda: {**node.params, "pages": int(number.text())}, [number])
    number.setText("invalid number")
    window.select_node(window.spec.node("output").id)
    assert node.id in window.node_drafts
    assert not window.save_project(path=str(tmp_path / "must-not-save.pdflow"))
    assert not (tmp_path / "must-not-save.pdflow").exists()
    window.select_node(node.id)
    assert window.inspector is form and number.text() == "invalid number"
    number.setText("8")
    assert window.flush_settings()
    assert window.spec.node("group").params["pages"] == 8
    assert not window.node_drafts and not window.draft_error


def test_repeated_step_progress_targets_its_own_identity(window):
    spec = window.spec
    first = WorkflowNode("clean_fields", params=default_options("clean_fields"))
    second = WorkflowNode("clean_fields", params=default_options("clean_fields"))
    spec = spec.insert_after(spec.node("extract").id, first).insert_after(first.id, second)
    window.apply_spec(spec.to_dict())
    item = window.canvas.nodes[second.id]
    window.update_progress(1, 10, "Workflow node: " + second.id + " | clean fields")
    assert window.run.statuses[second.id] == "Running"
    assert first.id not in window.run.statuses
    assert window.canvas.nodes[second.id] is item
    assert second.id not in window.feedback.text()


def test_inspection_four_tabs_pages_and_separate_production_state(qt_application, tmp_path):
    from tests.test_mail_merge_workflow import pair, recipe
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    w = MailMergeWorkflowWindow()
    w.show()
    try:
        job = pair(tmp_path, records=125)
        w.batch.jobs = [job]
        w.apply_spec(recipe([job]).upgraded().to_dict())
        target = w.spec.node("mapping").id
        w.select_node(target)
        pane = w.inspections.pane
        assert [pane.tabs.tabText(i) for i in range(4)] == ["Settings", "Input", "Output", "Issues"]
        pane.jobs.setCurrentIndex(pane.jobs.findData(job.id))
        w.run_selected()
        wait_until(lambda: not w.active_worker, timeout=40)
        result = w.inspections.current(target)
        assert result["status"] == "Checked", w.feedback.text()
        assert result["output_count"] == 125
        assert not w.run.statuses and not job.approved
        pane.tabs.setCurrentIndex(2)
        wait_until(lambda: not w.workers)
        assert pane.pages["output"]["table"].rowCount() == 50
        pane.read("output", delta=50)
        wait_until(lambda: not w.workers)
        assert pane.pages["output"]["rows"][0]["ordinal"] == 51
        pane.pages["output"]["search"].setText("Person 124")
        pane.read("output", reset=True)
        wait_until(lambda: not w.workers)
        assert pane.pages["output"]["table"].rowCount() == 1
        assert pane.pages["output"]["rows"][0]["source_id"] == 126
        job.data_options["header_row"] = 2
        w.changed_jobs()
        assert result["status"] == "Out of date"
    finally:
        w._close_approved = True
        w.close()
        wait_until(lambda: not w.workers)


def test_inline_numeric_draft_and_undo(window):
    from workflow.node_settings import StepDialog
    node = WorkflowNode("running_sequence", params=default_options("running_sequence"))
    window.apply_spec(window.spec.insert_after(window.spec.node("group").id, node).to_dict())
    window.select_node(node.id)
    editor = window.inspector.findChild(StepDialog)
    editor.controls["start"].setText("bad")
    window.select_node(window.spec.node("output").id)
    assert not window.flush_settings()
    window.select_node(node.id)
    assert window.inspector.findChild(StepDialog) is editor
    editor.controls["start"].setText("42")
    assert window.flush_settings()
    assert next(n for n in window.spec.nodes if n.id == node.id).params["start"] == 42
    window.undo.undo()
    assert next(n for n in window.spec.nodes if n.id == node.id).params["start"] == 1
