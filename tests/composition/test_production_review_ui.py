import copy
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from composition.designer.production_review import template_pane
from composition.designer.workspace import CompositionWindow
from composition.review.ui import ProductionReviewPane, ReviewController
from composition.template.model import Element, Template
from tests.composition.review_helpers import confirm_review
from tests.composition.test_designer_controls import cleanup, wait
from tests.composition.test_inserter_production import template_for


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtGui import QFont, QFontDatabase

    from composition.engine.assets import asset_root
    application = QApplication.instance() or QApplication([])
    original = application.font()
    # Offscreen Windows Qt does not enumerate native fonts; use the bundled
    # family for readable visual QA, without changing production UI settings.
    font = QFontDatabase.addApplicationFont(str(asset_root() / "fonts" / "NotoSans-Regular.ttf"))
    if font >= 0:
        application.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0], 9))
    yield application
    application.setFont(original)


@pytest.mark.parametrize("size", [(1280, 820), (960, 640), (480, 320)])
def test_responsive_read_only_review_has_visible_confirmation(app, size):
    pane = ProductionReviewPane()
    pane.resize(*size)
    pane.show()
    QApplication.processEvents()
    try:
        assert pane.confirm.isVisible()
        assert pane.confirm.geometry().bottom() <= pane.height()
        assert pane.confirm.geometry().right() <= pane.width()
        assert pane.compact.isVisible() == (pane.width() < 1080)
        assert not pane.confirm.isEnabled()
        assert pane.envelopes.editTriggers().value == 0
        assert pane.pages.editTriggers().value == 0
    finally:
        pane.close()
        pane.deleteLater()


def test_template_review_is_required_then_generates_and_returns_to_results(app, tmp_path, monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        window._apply_template(Template(elements=[Element(value="Approved")], record_mode="generated", generated_count=2).to_dict())
        window.start_production(tmp_path / "output")
        controller = window.production_review
        wait(lambda: len(controller.results) == 1 and not controller.check_worker)
        assert window.stack.currentWidget() is controller.pane
        assert not (tmp_path / "output").exists()
        assert controller.results[0]["summary"]["pages"] == 2
        confirm_review(window)
        wait(lambda: bool(window.last_output) and not window.production_worker)
        assert window.stack.currentIndex() == 2
        assert "Generated pages: 2" in window.production_summary.toPlainText()
        assert controller.results[0]["summary"]["job_id"] in window.production_summary.toPlainText()
        controller.refresh_confirm()
        assert not controller.pane.confirm.isEnabled()
    finally:
        cleanup(window)


def test_modified_settings_and_cancel_cannot_reenable_old_confirmation(app, tmp_path, monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        window._apply_template(Template(record_mode="generated", generated_count=2).to_dict())
        window.start_production(tmp_path / "output")
        controller = template_pane(window)
        wait(lambda: len(controller.results) == 1 and not controller.check_worker)
        controller.refresh_confirm()
        assert controller.pane.confirm.isEnabled()
        before = window.template.to_dict()
        after = copy.deepcopy(before)
        after["name"] = "Updated"
        window._commit(before, after, "Change reviewed template")
        controller.pane.acknowledge.setChecked(True)
        controller.select_job()
        assert not controller.pane.confirm.isEnabled()
        assert not (tmp_path / "output").exists()
    finally:
        cleanup(window)


def test_cancel_state_cannot_be_reenabled_by_selecting_result(app):
    owner = QWidget()
    pane = ProductionReviewPane(owner)
    owner.workers = []
    state = {}
    controller = ReviewController(owner, pane, lambda: state, lambda _: None)
    class Pending:
        def cancel(self):
            pass
    controller.original_state = controller.state()
    controller.contexts = [{}]
    controller.results = [{"complete": True, "status": "checked", "issues": []}]
    controller.session_valid = True
    controller.check_worker = Pending()
    controller.cancel()
    controller.check_worker = None
    controller.refresh_confirm()
    assert not pane.confirm.isEnabled()
    owner.deleteLater()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_physical_sheet_preview_themes_and_narrow_layout(app, tmp_path, monkeypatch, theme):
    from styles.theme import apply_theme
    apply_theme(app, theme)
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        window._apply_template(template_for(3, 2).to_dict())
        window.show()
        window.resize(960, 640)
        window.start_production(tmp_path / "output")
        controller = window.production_review
        pane = controller.pane
        wait(lambda: len(controller.results) == 1 and not controller.check_worker)
        wait(lambda: pane.envelopes.rowCount() == 2)
        pane.envelopes.selectRow(0)
        wait(lambda: not pane.front.original.isNull() and not pane.back.original.isNull())
        wait(lambda: not controller.view_workers)
        assert pane.compact.isVisible() and pane.confirm.isVisible()
        assert pane.confirm.geometry().bottom() < pane.height()
        assert "0000" in pane.payload.text()
        assert pane.pages.rowCount() == 4
        pane.acknowledge.setChecked(True)
        assert pane.confirm.isEnabled()
        window.tabs.setCurrentIndex(1)
        window.tabs.setCurrentIndex(4)
        assert window.stack.currentWidget() is pane
        assert not pane.front.original.isNull()
        directory = os.environ.get("PDFDOC_REVIEW_QA_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            window.grab().save(str(Path(directory) / f"production-review-{theme}.png"))
    finally:
        cleanup(window)
        apply_theme(app, "system")


def blocked_review_controller(app, tmp_path, monkeypatch):
    from dataclasses import asdict

    from composition.production.model import ProductionJob
    from composition.review.service import create_review, review_rows
    from composition.template.model import CompositionError, PageSpec
    from tests.composition.test_postscript import ps_media

    def missing_runtime():
        raise CompositionError("PostScript output requires Ghostscript. Select its executable in Settings.")

    monkeypatch.setattr("composition.media.postscript.ghostscript_executable", missing_runtime)
    template = Template(pages=[PageSpec(), PageSpec()], record_mode="generated",
                        generated_count=211, media=ps_media())
    directory = tmp_path / "review"
    context = {"kind":"template", "job":asdict(ProductionJob(
        template.to_dict(), "", str(tmp_path / "output"))), "label":"Review fixture"}
    result = create_review(directory, context)
    assert result["status"] == "blocked" and result["summary"]["records"] == 211
    assert result["summary"]["pages"] == 422
    assert not (tmp_path / "output").exists()
    owner = QWidget()
    owner.directory, owner.workers = directory, []
    pane = ProductionReviewPane(owner)
    QVBoxLayout(owner).addWidget(pane)
    controller = ReviewController(owner, pane, lambda: context, lambda _: None)
    controller.contexts, controller.results = [context], [result]
    controller.original_state, controller.session_valid = controller.state(), True
    pane.jobs.addItem("Review fixture")

    def request(task, callback, **values):
        assert task == "rows"
        callback(review_rows(directory, values["snapshot_id"], offset=values.get("offset", 0)))

    monkeypatch.setattr(controller, "_request", request)
    return owner, pane, controller, result


@pytest.mark.parametrize("width", [1280, 960])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("font_size", [9, 18])
def test_blocked_review_explains_error_and_opens_issues(app, tmp_path, monkeypatch, width, theme, font_size):
    from PyQt6.QtGui import QFont

    from styles.theme import apply_theme

    original = app.font()
    apply_theme(app, theme)
    font = QFont(original)
    font.setPointSize(font_size)
    app.setFont(font)
    owner, pane, controller, result = blocked_review_controller(app, tmp_path, monkeypatch)
    try:
        owner.resize(width, 640)
        owner.show()
        app.processEvents()
        controller.select_job()
        app.processEvents()
        assert hasattr(pane, "blocker_reason"), "Blocked needs a prominent explanation"
        assert pane.blocker_reason.isVisible()
        assert "Ghostscript" in pane.blocker_reason.text()
        assert pane.details.currentWidget() is pane.issue_page
        if width < 1080:
            assert pane.compact.currentWidget() is pane.details
        assert pane.issues.currentRow() == 0
        assert pane.envelopes.rowCount() == 0
        assert "211" in pane.position.text() and "0 checked" in pane.position.text()
        assert not pane.confirm.isEnabled() and not pane.acknowledge.isVisible()
        assert not result["complete"]
        assert "Planned barcodes: Not fully checked" in pane.overview.text()
        assert pane.confirm.isVisible() and pane.edit.isVisible()
        for control in (pane.confirm, pane.edit, pane.blocker_reason):
            assert pane.rect().contains(control.mapTo(pane, control.rect().bottomRight()))
        directory = os.environ.get("PDFDOC_REVIEW_QA_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            owner.grab().save(str(Path(directory) / f"blocked-{width}-{theme}-{font_size}.png"))
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()
        apply_theme(app, "system")
        app.setFont(original)


def test_switching_to_checked_job_clears_old_blocker(app, tmp_path, monkeypatch):
    owner, pane, controller, result = blocked_review_controller(app, tmp_path, monkeypatch)
    try:
        owner.show()
        app.processEvents()
        controller.select_job()
        assert hasattr(pane, "blocker_reason"), "Blocked needs a prominent explanation"
        controller.results = [{**result, "status":"checked", "complete":True, "issues":[]}]
        controller.select_job()
        assert not pane.blocker_reason.isVisible()
        assert pane.confirm.isEnabled()
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()


def test_checked_warning_still_requires_acknowledgement(app, tmp_path, monkeypatch):
    owner, pane, controller, result = blocked_review_controller(app, tmp_path, monkeypatch)
    try:
        owner.show()
        warning = {**result["issues"][0], "severity": "warning", "reason": "Printer validation pending"}
        controller.results = [{**result, "status": "checked", "complete": True, "issues": [warning]}]
        controller.select_job()
        assert not pane.blocker_reason.isVisible()
        assert pane.acknowledge.isVisible() and not pane.confirm.isEnabled()
        pane.acknowledge.setChecked(True)
        assert pane.confirm.isEnabled()
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()


def test_blocked_issues_remain_visible_when_window_becomes_narrow(app, tmp_path, monkeypatch):
    owner, pane, controller, _ = blocked_review_controller(app, tmp_path, monkeypatch)
    try:
        owner.resize(1280, 640)
        owner.show()
        app.processEvents()
        controller.select_job()
        assert pane.details.currentWidget() is pane.issue_page
        for width in (960, 1280, 960):
            owner.resize(width, 640)
            app.processEvents()
            assert pane.edit.isVisible(), (width, pane._narrow, pane.details.isHidden(), pane.compact.currentIndex())
            assert pane.details.currentWidget() is pane.issue_page
            if pane._narrow:
                assert pane.compact.currentWidget() is pane.details
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("action", ["settings", "media"])
def test_template_review_settings_return_to_design(app, monkeypatch, action):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    opened = []
    monkeypatch.setattr(window, "edit_print_media", lambda: opened.append(
        (window.tabs.currentIndex(), window.stack.currentWidget())))
    try:
        controller = template_pane(window)
        window.tabs.setCurrentIndex(4)
        before = window.template.to_dict()
        controller.pane.editRequested.emit({"action": action})
        assert window.tabs.currentIndex() == 1 and window.stack.currentWidget() is window.design_page
        if action == "media":
            assert opened == [(1, window.design_page)]
        assert window.template.to_dict() == before
    finally:
        cleanup(window)
