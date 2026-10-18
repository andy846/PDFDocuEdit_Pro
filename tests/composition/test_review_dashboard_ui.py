"""The dashboard is a view of review state, never a confirmation control."""

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QWidget

from composition.review.presentation import ReviewDashboardModel
from composition.review.ui import ProductionReviewPane, ReviewController
from tests.composition.test_review_dashboard import checked, production


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1280, 820), (960, 640), (480, 320)])
def test_dashboard_metrics_and_footer_are_accessible(qt_application, theme, size):
    from styles.components import global_style
    from styles.theme import apply_theme

    previous_style = qt_application.styleSheet()
    apply_theme(qt_application, theme)
    qt_application.setStyleSheet(global_style())
    pane = ProductionReviewPane()
    pane.resize(*size)
    pane.show()
    qt_application.processEvents()
    try:
        assert hasattr(pane, "dashboard")
        pane.dashboard.display(ReviewDashboardModel.from_review(checked(), confirmation_available=True))
        pane.details.setCurrentIndex(0)
        if pane._narrow:
            pane.compact.setCurrentWidget(pane.details)
        qt_application.processEvents()
        assert pane.dashboard.values["mailpieces"].text() == "2"
        assert pane.dashboard.values["actual_pages"].text() == "Not generated"
        assert pane.confirm.isVisible() and not pane.confirm.isEnabled()
        for button in (pane.confirm, pane.recheck, pane.cancel):
            point = button.mapTo(pane, button.rect().bottomRight())
            assert point.x() < pane.width() and point.y() < pane.height()
        assert pane.envelopes.editTriggers().value == 0
        assert pane.pages.editTriggers().value == 0
    finally:
        pane.close()
        pane.deleteLater()
        apply_theme(qt_application, "system")
        qt_application.setStyleSheet(previous_style)


def controller_for():
    owner = QWidget()
    owner.workers = []
    pane = ProductionReviewPane(owner)
    controller = ReviewController(owner, pane, lambda: {"source": "current"}, lambda _: None)
    result = checked()
    controller.results = [result]
    controller.contexts = [result["context"]]
    controller.original_state = controller.state()
    controller.session_valid = True
    return owner, pane, controller


def test_dashboard_navigation_does_not_acknowledge_or_confirm(qt_application):
    owner, pane, controller = controller_for()
    try:
        controller.results[0]["issues"] = [
            {"severity": "warning", "reason": "Printer proof", "action": "media"}
        ]
        controller.refresh_confirm()
        assert not pane.confirm.isEnabled() and not pane.acknowledge.isChecked()
        pane.dashboard.warning_button.click()
        assert pane.details.currentWidget() is pane.issue_page
        assert not pane.acknowledge.isChecked() and not pane.confirm.isEnabled()
        pane.acknowledge.setChecked(True)
        assert pane.confirm.isEnabled()
        assert pane.dashboard.model.status == "ready_to_confirm"
        controller.current = lambda: {"source": "changed"}
        controller.invalidate()
        assert not pane.confirm.isEnabled() and pane.dashboard.model.status == "stale"
    finally:
        owner.deleteLater()


def test_dashboard_confirmed_is_not_generated_and_late_result_is_ignored(qt_application):
    from PyQt6.QtCore import QObject, pyqtSignal

    class ProductionWorker(QObject):
        resultReady = pyqtSignal(dict)
        failed = pyqtSignal(str)
        ended = pyqtSignal()

    owner, pane, controller = controller_for()
    worker = ProductionWorker()
    try:
        controller.consumed = True
        controller.session_valid = False
        controller.refresh_confirm()
        assert pane.dashboard.model.status == "confirmed"
        receipt = {"snapshot_id": "snap-1", "context": controller.results[0]["context"]}
        controller.watch_generation(worker, [receipt])
        assert pane.dashboard.model.status == "generating"
        result = production(controller.results[0])["result"]
        worker.resultReady.emit(result)
        assert pane.dashboard.model.status == "generating"  # process has not ended
        worker.ended.emit()
        assert pane.dashboard.model.status == "generated"
        controller.epoch += 1
        controller.generation_serial += 1
        controller.results = [{**checked(), "snapshot_id": "snap-2", "fingerprint": "source-2"}]
        controller.refresh_confirm()
        worker.resultReady.emit(result)
        worker.ended.emit()
        assert pane.dashboard.model.status != "generated"
    finally:
        owner.deleteLater()
        worker.deleteLater()


def test_generate_palette_entry_still_opens_review_without_publishing(qt_application, tmp_path, monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from composition.template.model import Template
    from core.commands import Command
    from core.viewer import PDFViewer
    from tests.composition.test_designer_controls import cleanup, wait

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        window._apply_template(Template(record_mode="generated", generated_count=2).to_dict())
        command = Command(
            "designer.generate",
            "Generate PDF",
            "",
            "Designer",
            lambda: window.start_production(tmp_path / "output"),
            enabled=lambda: True,
        )
        owner = SimpleNamespace(
            _commands_for_mode=lambda: [command], info_bar=SimpleNamespace(show_message=lambda *_: None)
        )
        PDFViewer._run_command(owner, command.id)
        controller = window.production_review
        wait(lambda: len(controller.results) == 1 and not controller.check_worker)
        assert not (tmp_path / "output").exists()
        assert controller.pane.dashboard.values["planned_pages"].text() == "2"
        assert controller.pane.dashboard.model.status == "ready_to_confirm"
        assert not controller.consumed
    finally:
        cleanup(window)


def test_real_template_generation_updates_the_same_checked_dashboard(qt_application, tmp_path, monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from tests.composition.review_helpers import confirm_review
    from tests.composition.test_designer_controls import cleanup, wait
    from tests.composition.test_inserter_production import template_for

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        window._apply_template(template_for(3, 2).to_dict())
        window.start_production(tmp_path / "output")
        controller = window.production_review
        wait(lambda: len(controller.results) == 1 and not controller.check_worker)
        snapshot = controller.results[0]["snapshot_id"]
        model = controller.pane.dashboard.model
        assert model.planned_barcode.state == "Passed"
        assert model.final_barcode.state == "Not Checked"
        assert controller.pane.dashboard.values["planned_pages"].text() == "8"
        confirm_review(window)
        wait(lambda: bool(window.last_output) and not window.production_worker)
        model = controller.pane.dashboard.model
        assert model.snapshot_id == snapshot and model.status == "generated"
        assert model.final_barcode.state == "Passed"
        assert model.final_barcode.verified == 4
        assert controller.pane.dashboard.values["actual_pages"].text() == "8"
        assert not controller.pane.confirm.isEnabled()
    finally:
        cleanup(window)


def test_workflow_progress_and_job_switch_preserve_bound_completion(qt_application, monkeypatch):
    import copy

    from PyQt6.QtCore import QObject, pyqtSignal

    class ProductionWorker(QObject):
        resultReady = pyqtSignal(dict)
        failed = pyqtSignal(str)
        ended = pyqtSignal()

    owner, pane, controller = controller_for()
    state = {
        "spec": {"name": "Recipe"},
        "batch": {
            "status": "Ready",
            "jobs": [
                {
                    "id": "job-1",
                    "status": "Ready",
                    "approved": True,
                    "prepared_template": {"name": "Original"},
                },
                {"id": "job-2", "status": "Ready", "approved": True, "prepared_template": {"name": "Other"}},
            ],
        },
    }
    controller.current = lambda: state
    controller.original_state = controller.state()
    # Start via the real entry point while leaving IO to the tested worker path.
    monkeypatch.setattr(controller, "_check_next", lambda: None)
    context = checked()["context"]
    controller.start([context, copy.deepcopy(context)], lambda _: None)
    first, second = checked(), checked(count=7)
    second.update(snapshot_id="snap-2", fingerprint="source-2")
    second["summary"]["job_id"] = "job-2"
    second["context"]["job"]["job_id"] = "job-2"
    controller.results = [first, second]
    controller.consumed = True
    controller.session_valid = False
    monkeypatch.setattr(controller, "_request", lambda *args, **kwargs: None)
    receipts = [{"snapshot_id": r["snapshot_id"], "context": r["context"]} for r in controller.results]
    worker = ProductionWorker()
    try:
        controller.watch_generation(worker, receipts)
        state["batch"]["status"] = "Running"
        state["batch"]["jobs"][0].update(status="Running", stage="Compose")
        pane.jobs.setCurrentIndex(1)
        assert pane.dashboard.model.status == "generating"
        assert pane.dashboard.values["mailpieces"].text() == "7"
        a, b = production(first)["result"], production(second)["result"]
        b["job_id"] = "job-2"
        worker.resultReady.emit({"batch": {"jobs": [{"result": a}, {"result": b}]}})
        worker.ended.emit()
        assert pane.dashboard.model.status == "generated"
        pane.jobs.setCurrentIndex(0)
        assert pane.dashboard.model.status == "generated"
        state["batch"]["jobs"][0]["prepared_template"]["name"] = "Changed"
        controller.invalidate()
        assert pane.dashboard.model.status == "stale"
        assert not pane.confirm.isEnabled()
        state["batch"]["jobs"][0]["prepared_template"]["name"] = "Original"
        controller.invalidate()
        assert pane.dashboard.model.status == "stale"  # a new review is still required
    finally:
        owner.deleteLater()
        worker.deleteLater()
