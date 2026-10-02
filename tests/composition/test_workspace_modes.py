from __future__ import annotations

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.overlay.serializer import save_project as save_overlay
from composition.template.model import DataConfig, Element, Template
from composition.template.serializer import save_project
from core.settings import SettingsManager
from core.viewer import PDFViewer
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_workspace import wait_until
from ui.workspace_modes import WorkspaceMode


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION", "1")
    monkeypatch.setattr("core.viewer.SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    root = PDFViewer()
    root.resize(960, 640)
    root.show()
    app.processEvents()
    yield root
    controller = root._mode_controller
    if controller.host:
        monkeypatch.setattr(controller.host, "confirm_all", lambda: True)
        for project in controller.host.projects:
            project.undo.setClean()
            project.content_invalid = False
            project.draft_error = ""
    monkeypatch.setattr(root, "_confirm_discard_changes", lambda: True)
    root.close()
    wait_until(lambda: not root.isVisible())
    root.deleteLater()
    app.processEvents()


def designer(window):
    controller = window._mode_controller
    controller.request_mode("designer")
    QApplication.processEvents()
    return controller, controller.host.current_project


def test_lazy_modes_keep_pdf_and_designer_state(window, tmp_path):
    controller = window._mode_controller
    assert controller.host is None
    assert controller.modes.mode == WorkspaceMode.PDF
    pdf = tmp_path / "document.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(pdf)
    window._open_in_new_tab_sync(str(pdf))
    session = window._session
    controller, project = designer(window)
    project.add_element("text", "Name: {{Name}}")
    project.canvas.zoom_by(1.3)
    selected = project.canvas.selected_ids()
    transform = project.canvas.transform()
    undo = project.undo.index()
    for _ in range(5):
        controller.request_mode("pdf")
        assert window.workspace.current_session() is session
        controller.request_mode("designer")
    assert project.canvas.selected_ids() == selected
    assert project.canvas.transform() == transform
    assert project.undo.index() == undo
    assert len(project.template.elements) == 1
    assert not project.isWindow()
    assert project.menuBar().isHidden()


def test_template_overlay_tabs_deduplicate_paths(window, tmp_path, monkeypatch):
    controller, first = designer(window)
    template_path = tmp_path / "template.pdcx"
    save_project(Template(elements=[Element(value="Saved")]), template_path)
    template = controller.host.open_project(template_path)
    template.add_element("text", "Unsaved")
    overlay_path = tmp_path / "overlay.pdcx"
    save_overlay(sample_spec(tmp_path), overlay_path)
    overlay = controller.host.open_project(overlay_path)
    assert len(controller.host.projects) == 3
    assert not overlay.isWindow()
    assert controller.host.open_project(str(template_path).upper()) is template
    assert len(controller.host.projects) == 3
    assert len(template.template.elements) == 2
    notices = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: notices.append(args))
    assert not controller.host.allow_save_path(first, template_path)
    assert notices
    assert controller.host.tabs.currentWidget() is template


def test_shortcuts_only_active_mode_and_project(window, app, monkeypatch):
    controller, first = designer(window)
    first.add_element("text", "One")
    second = controller.host.new_template()
    second.add_element("text", "Two")
    assert window.save_action.shortcut().isEmpty()
    assert first.actions["undo"].shortcut().isEmpty()
    assert second.actions["undo"].shortcut() == QKeySequence("Ctrl+Z")
    second.canvas.setFocus()
    app.processEvents()
    QTest.keyClick(second.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not second.template.elements
    assert len(first.template.elements) == 1
    paths = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (paths.append("designer") or "", ""))
    second.canvas.setFocus()
    QTest.keyClick(second.canvas, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert paths == ["designer"]
    controller.host.tabs.setCurrentWidget(first)
    assert second.actions["undo"].shortcut().isEmpty()
    assert first.actions["undo"].shortcut() == QKeySequence("Ctrl+Z")
    controller.request_mode("pdf")
    assert window.save_action.shortcut() == QKeySequence("Ctrl+S")
    assert first.actions["undo"].shortcut().isEmpty()
    controller.request_mode("designer")
    window._apply_command_shortcuts()
    assert window.save_action.shortcut().isEmpty()
    controller.request_mode("pdf")
    assert window.save_action.shortcut() == QKeySequence("Ctrl+S")


def test_text_undo_does_not_undo_object(window, app):
    controller, project = designer(window)
    project.add_element("text", "Original")
    control = project.properties.content
    control.setFocus()
    QTest.keyClicks(control, " added")
    before = project.undo.index()
    QTest.keyClick(control, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert project.template.elements
    assert project.undo.index() >= before - 1
    assert "added" not in control.toPlainText()


def test_commands_and_menus_follow_active_project(window):
    controller, template = designer(window)
    keys = {command.id for command in window._commands_for_mode()}
    assert "designer.save" in keys and "designer.host.open" in keys
    assert "save" not in keys
    overlay = controller.host.new_overlay()
    assert controller.host.current_project is overlay
    assert "designer.grouping" in {c.id for c in window._commands_for_mode()}
    assert "designer.background" not in {c.id for c in window._commands_for_mode()}
    assert window.command_bar._more.menu() is window.command_bar._main_menu_button.menu()
    controller.request_mode("pdf")
    assert "save" in {c.id for c in window._commands_for_mode()}
    assert window.command_bar._more.menu() is window.command_bar._pdf_more_menu


def test_quick_switch_last_choice_and_animation_preference(window, app):
    controller, project = designer(window)
    for mode in ("pdf", "designer", "pdf", "designer", "pdf"):
        controller.request_mode(mode)
    QTest.qWait(250)
    assert controller.modes.mode == WorkspaceMode.PDF
    assert controller.modes.overlay is None
    window._set_motion_enabled(False)
    controller.request_mode("designer")
    assert controller.modes.overlay is None
    assert window.command_bar.mode_switcher.buttons[WorkspaceMode.DESIGNER].isChecked()
    assert len(controller.host.projects) == 1


def test_background_job_survives_mode_switch(window, tmp_path):
    controller, project = designer(window)
    source = tmp_path / "records.csv"
    source.write_text("Name\nOne\nTwo\n", encoding="utf8")
    project.add_element("text", "Name: {{Name}}")
    project._start_import(DataConfig(path=str(source)))
    controller.request_mode("pdf")
    wait_until(lambda: project.import_worker is None)
    assert project.record_count == 2
    controller.request_mode("designer")
    project.start_production(str(tmp_path / "output"))
    worker = project.production_worker
    assert worker is not None
    controller.request_mode("pdf")
    assert project.production_worker is worker
    assert window.command_bar.mode_switcher.busy[WorkspaceMode.DESIGNER]
    wait_until(lambda: project.production_worker is None)
    controller.request_mode("designer")
    assert project.last_output, project.production_summary.toPlainText()
    with fitz.open(project.last_output) as doc:
        assert doc.page_count == 2
        assert "One" in doc[0].get_text()
        assert "Two" in doc[1].get_text()
    assert not window.command_bar.mode_switcher.busy[WorkspaceMode.DESIGNER]


def test_pdf_open_and_output_routing_keep_designer(window, tmp_path, monkeypatch):
    controller, project = designer(window)
    project.add_element("text", "Keep me")
    monkeypatch.setattr(window, "_schedule_queued_open", lambda: None)
    window.queue_open_files(["external.pdf"])
    assert controller.modes.mode == WorkspaceMode.PDF
    controller.request_mode("designer")
    controller.host.open_pdf("output.pdf")
    assert controller.modes.mode == WorkspaceMode.PDF
    assert len(project.template.elements) == 1
    window._queued_open_paths.clear()


def test_close_tab_cancel_invalid_draft_and_empty_designer(window, monkeypatch):
    controller, project = designer(window)
    project.add_element("text", "Keep")
    project.properties.content.setPlainText("{{")
    assert project.content_invalid
    text = project.properties.content.toPlainText()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert not controller.host.close_project(project)
    assert project.properties.content.toPlainText() == text
    assert project.content_invalid
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    controller.host.close_project(project)
    wait_until(lambda: not controller.host.projects)
    assert controller.modes.mode == WorkspaceMode.DESIGNER
    assert controller.host.stack.currentWidget() is controller.host.start
    assert controller.designer_actions["open"].shortcut() == QKeySequence("Ctrl+O")
    controller.request_mode("pdf")
    controller.request_mode("designer")
    assert not controller.host.projects


def test_exit_cancel_does_not_discard_other_drafts(window, monkeypatch):
    controller, first = designer(window)
    first.add_element("text", "First")
    first.properties.content.setPlainText("{{")
    second = controller.host.new_template()
    second.add_element("text", "Second")
    answers = iter([QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(answers))
    assert not window.close()
    assert window.isVisible() and window.isEnabled()
    assert not controller.exit_approved
    assert not first.close_pending and not second.close_pending
    assert first.content_invalid and first.properties.content.toPlainText() == "{{"
    assert len(controller.host.projects) == 2


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_narrow_window_theme_and_main_controls(window, app, theme):
    controller, project = designer(window)
    window._apply_theme(theme)
    for mode in ("designer", "pdf"):
        controller.request_mode(mode)
        window.resize(960, 640)
        app.processEvents()
        switcher = window.command_bar.mode_switcher
        assert switcher.isVisible()
        assert switcher.geometry().right() < window.command_bar.width()
        assert window.command_bar._more.geometry().right() < window.command_bar.width()
        if mode == "designer":
            assert project.canvas.width() > 350
            assert window.command_bar._open.isHidden()
        else:
            assert not window.command_bar._open.isHidden()


def test_ctrl_save_writes_active_tab_and_reopen(window, tmp_path, monkeypatch):
    controller, first = designer(window)
    first.add_element("text", "First unsaved")
    second = controller.host.new_template()
    second.add_element("text", "Second saved")
    path = tmp_path / "saved.pdcx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    second.canvas.setFocus()
    QApplication.processEvents()
    QTest.keyClick(second.canvas, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert path.exists()
    assert second.project_path == path
    assert second.undo.isClean() and not first.undo.isClean()
    controller.host.close_project(second)
    wait_until(lambda: second not in controller.host.projects)
    reopened = controller.host.open_project(path)
    assert reopened.template.elements[0].value == "Second saved"
    assert first.template.elements[0].value == "First unsaved"


def test_overlay_new_shortcut_creates_tab_without_ambiguity(window):
    controller, project = designer(window)
    overlay = controller.host.new_overlay()
    overlay.canvas.setFocus()
    QApplication.processEvents()
    QTest.keyClick(overlay.canvas, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert len(controller.host.projects) == 3
    assert isinstance(controller.host.current_project, OverlayWindow)
    assert controller.host.current_project is not overlay


def test_overlay_save_on_close_and_reopen(window, tmp_path, monkeypatch):
    controller, project = designer(window)
    overlay = controller.host.new_overlay()
    spec = sample_spec(tmp_path)
    overlay.apply_spec(spec.to_dict())
    overlay.add_object("text", "EnvelopeSeq")
    path = tmp_path / "overlay_saved.pdcx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)
    controller.host.close_project(overlay)
    wait_until(lambda: overlay not in controller.host.projects)
    assert path.exists()
    loaded = controller.host.open_project(path)
    assert len(loaded.spec.objects) == 3
    assert loaded.undo.isClean()


def test_exit_cancel_keeps_pdf_form_draft_and_active_job(window, tmp_path, monkeypatch):
    from types import SimpleNamespace

    pdf = tmp_path / "form.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(pdf)
    session = window._open_in_new_tab_sync(str(pdf))
    controller, project = designer(window)
    project.add_element("text", "Unsaved")
    draft = SimpleNamespace(changed=True)
    session.form_draft = draft
    session.form_mode_active = True
    worker = SimpleNamespace(cancel=lambda: pytest.fail("Cancel exit must keep the job running"))
    project.production_worker = worker

    class DraftPrompt:
        ButtonRole = QMessageBox.ButtonRole
        StandardButton = QMessageBox.StandardButton

        def __init__(self, parent):
            self.discard = None

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            pass

        def addButton(self, text, *args):
            value = object()
            if text == "Discard draft":
                self.discard = value
            return value

        def exec(self):
            pass

        def clickedButton(self):
            return self.discard

    monkeypatch.setattr("core.viewer.QMessageBox", DraftPrompt)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    try:
        assert not window.close()
        assert session.form_draft is draft
        assert session.form_mode_active
        assert project.production_worker is worker
        assert not project.close_pending
    finally:
        project.production_worker = None
        session.form_draft = None


def test_close_tab_waits_for_worker_cleanup(window, tmp_path, monkeypatch):
    controller, project = designer(window)
    project.add_element("text", "{{Name}}")
    source = tmp_path / "import.csv"
    source.write_text("Name\n" + "Value\n" * 100, encoding="utf8")
    project._start_import(DataConfig(path=str(source)))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    controller.host.close_project(project)
    assert project.close_pending
    wait_until(lambda: project not in controller.host.projects)
    assert controller.modes.mode == WorkspaceMode.DESIGNER


def test_approved_exit_waits_for_pdf_task_checkpoint(window):
    from threading import Event

    from PyQt6.QtCore import QTimer

    started, release = Event(), Event()
    def operation(is_cancelled):
        started.set()
        release.wait(2)
        return "Cancelled" if is_cancelled() else "Finished"
    window._run_task("Controlled PDF task", operation, cancel_argument="is_cancelled")
    wait_until(started.is_set)
    QTimer.singleShot(100, release.set)
    assert not window.close()
    assert window._closing and not window.isEnabled()
    wait_until(lambda: not window.isVisible())
    assert not window._tasks


def test_overlay_toolbar_icons_follow_shared_theme(window):
    controller, project = designer(window)
    window._apply_theme("light")
    overlay = controller.host.new_overlay()
    before = overlay.actions["save"].icon().cacheKey()
    window._apply_theme("dark")
    assert overlay.actions["save"].icon().cacheKey() != before
    assert controller.host.current_project is overlay
