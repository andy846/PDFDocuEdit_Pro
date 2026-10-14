import pytest


@pytest.fixture(autouse=True)
def readable_offscreen_font(qt_application):
    from PyQt6.QtGui import QFont, QFontDatabase

    from composition.engine.assets import asset_root
    original=qt_application.font()
    identity=QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    if identity>=0:
        qt_application.setFont(QFont(QFontDatabase.applicationFontFamilies(identity)[0],9))
    yield
    qt_application.setFont(original)


@pytest.mark.parametrize("status,accepted,stale,words",[
    ("Pending",False,False,"Check"),
    ("Ready",True,False,"Production Review"),
    ("Needs review",False,False,"Accept data"),
    ("Checked",False,False,"Confirm production"),
    ("Ready",True,True,"Check again"),
    ("Blocked",False,False,"Issues"),
    ("Completed",False,False,"validated outputs"),
])
def test_acceptance_and_production_guidance_are_distinct(status,accepted,stale,words):
    from composition.review.presentation import next_step
    assert words in next_step(status,accepted=accepted,stale=stale)


def test_batch_acceptance_does_not_skip_production_review(qt_application,tmp_path):
    from tests.composition.test_workspace import wait_until
    from tests.test_mail_merge_workflow import pair, recipe
    from workflow.batch import BatchRun, prepare
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    w=MailMergeWorkflowWindow()
    try:
        job=pair(tmp_path)
        spec=recipe([job])
        w.apply_spec(spec.to_dict())
        w.batch=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
        w.refresh_jobs()
        w.jobs_table.selectRow(0)
        assert w.accept_button.text()=="Accept data & jobs"
        w.approve_selected()
        assert job.approved
        assert "Production Review" in w.feedback.text()
        assert not hasattr(w,"production_review")
        assert not (tmp_path/"output").exists()
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)


@pytest.mark.parametrize("theme",["dark","light"])
def test_branch_data_acceptance_actions_fit_narrow_window(qt_application,theme):
    from styles.theme import apply_theme
    from tests.composition.test_workspace import wait_until
    from workflow.branch_ui import BranchWorkflowWindow
    apply_theme(qt_application,theme)
    w=BranchWorkflowWindow()
    try:
        w.show()
        w.resize(960,640)
        qt_application.processEvents()
        assert w.width()<=960
        assert w.compact.isVisible()
        w.tabs.setCurrentWidget(w.review_page)
        qt_application.processEvents()
        from PyQt6.QtWidgets import QPushButton
        for button in w.review_page.findChildren(QPushButton):
            assert w.review_page.rect().contains(button.mapTo(w.review_page,button.rect().bottomRight()))
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)
        apply_theme(qt_application,"system")


@pytest.mark.parametrize("theme",["dark","light"])
def test_media_settings_panel_fits_narrow_workflow(qt_application,theme):
    import os
    from pathlib import Path

    from PyQt6.QtWidgets import QComboBox

    from styles.theme import apply_theme
    from tests.composition.test_workspace import wait_until
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    from workflow.model import WorkflowNode
    from workflow.registry import default_options
    apply_theme(qt_application,theme)
    w=MailMergeWorkflowWindow()
    try:
        spec=w.spec.upgraded(4).insert_after(w.spec.node("template").id,WorkflowNode("media_assignment",params=default_options("media_assignment")))
        w.apply_spec(spec.to_dict())
        w.select_node(w.spec.node("media_assignment").id)
        w.show()
        w.resize(960,640)
        w.panel_view.setCurrentIndex(w.panel_view.findData("details"))
        qt_application.processEvents()
        assert w.width()<=960
        source=w.inspector.findChild(QComboBox,"mediaSettingsSource")
        assert source.currentData()=="project"
        assert source.isVisible()
        assert w.inspector.rect().contains(source.mapTo(w.inspector,source.rect().bottomRight()))
        assert w.inspector_scroll.horizontalScrollBar().maximum()==0
        directory=os.environ.get("PDFDOC_WORKFLOW_QA_DIR")
        if directory:
            Path(directory).mkdir(parents=True,exist_ok=True)
            w.grab().save(str(Path(directory)/f"media-source-{theme}.png"))
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)
        apply_theme(qt_application,"system")
