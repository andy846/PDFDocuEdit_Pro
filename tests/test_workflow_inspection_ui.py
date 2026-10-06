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


def test_busy_canvas_browsing_keeps_items_and_blocks_edits(window):
    from types import SimpleNamespace

    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QSignalSpy, QTest
    from PyQt6.QtWidgets import QGraphicsItem
    canvas = window.canvas
    item = canvas.nodes[window.spec.node("group").id]
    before = window.spec.to_dict()
    window.active_worker = SimpleNamespace()
    window.inspections.active = True
    try:
        window.lock()
        assert canvas.isEnabled() and not canvas.editable
        assert not item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        assert item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        canvas.scene().clearSelection()
        item.setSelected(True)
        assert window.selected == item.node.id
        assert not window.inspector.isEnabled()
        assert not window.inspections.pane.check.isEnabled()
        connections = QSignalSpy(canvas.connectionRequested)
        positions = QSignalSpy(canvas.positionChanged)
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        canvas.zoom(1.15)
        window.update_progress(10, 100, "Workflow node: " + item.node.id + " | checking")
        assert not connections and not positions
        assert window.spec.to_dict() == before
        assert canvas.nodes[item.node.id] is item and not window.run.statuses
    finally:
        window.active_worker = None
        window.inspections.active = False
        window.lock()


def test_description_search_categories_and_compatible_next(window):
    from PyQt6.QtCore import Qt

    from workflow.chrome import populate_next
    w = window
    w.library_search.setText("padding")
    visible = [w.toolbox.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.toolbox.count())
               if not w.toolbox.item(i).isHidden()]
    assert "create_fields" in visible
    w.library_search.clear()
    w.library_category.setCurrentIndex(w.library_category.findData("Sources"))
    visible = [w.toolbox.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.toolbox.count())
               if not w.toolbox.item(i).isHidden()]
    assert set(visible) == {"input", "merge"}
    node = WorkflowNode("running_sequence", params=default_options("running_sequence"))
    w.apply_spec(w.spec.insert_after(w.spec.node("group").id, node).to_dict())
    w.select_node(node.id)
    populate_next(w)
    assert "Insert Sort Records" not in [action.text() for action in w.next_menu.actions()]
    explanations = w.next_menu.actions()[0].menu().actions()
    assert any("Sort Records" in action.text() and "before" in action.toolTip() for action in explanations)


def test_only_affected_inspection_results_are_invalidated(window):
    w=window
    first=w.spec.node("input").id
    last=w.spec.node("output").id
    for node_id in (first,last):
        w.inspections.results[("",node_id)]={"node_id":node_id,"job_id":"","status":"Checked",
                                              "ui_config":w.inspections.config_key(node_id,"")}
    w.select_node(last)
    assert w.params(w.spec.node("output"),{"directory":"changed-output-folder"})
    assert w.inspections.current(first)["status"]=="Checked"
    assert w.inspections.current(last)["status"]=="Out of date"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_single_panels_remember_visibility_and_fit_narrow_window(window, qt_application, theme):
    from styles.theme import apply_theme
    w = window
    apply_theme(qt_application, theme)
    w.resize(960, 640)
    qt_application.processEvents()
    assert w.width() == 960
    w.settings_toggle.click()
    assert not w.inspector_scroll.isVisible()
    w.resize(1300, 800)
    qt_application.processEvents()
    w.resize(960, 640)
    qt_application.processEvents()
    assert not w.inspector_scroll.isVisible()
    for mode, target in (("details", w.inspector_scroll), ("steps", w.library), ("canvas", w.canvas)):
        w.panel_view.setCurrentIndex(w.panel_view.findData(mode))
        qt_application.processEvents()
        assert target.isVisible() and target.width() > 850
        assert w.panel_view.parentWidget().geometry().bottom() < w.flow_page.height()
    w.settings_toggle.click()
    assert w.inspector_scroll.isVisible()
