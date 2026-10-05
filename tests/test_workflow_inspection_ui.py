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
