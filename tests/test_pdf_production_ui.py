"""Targeted production tab behavior, lifecycle and original-service integration."""
import time
from pathlib import Path

import fitz
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QMessageBox

from ui.pdf_production_workspace import PdfProductionWorkspace


class FakeWorker(QObject):
    resultReady = pyqtSignal(dict)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    ended = pyqtSignal()

    def __init__(self, directory, request, parent, **kwargs):
        super().__init__(parent)
        self.request = request
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def source(tmp_path, name="customer.pdf"):
    path = tmp_path / name
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 30), "Searchable original")
        page.add_highlight_annot(fitz.Rect(25, 20, 140, 36))
        doc.save(path)
    return path


def wait(app, predicate):
    deadline = time.monotonic() + 25
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate()


def test_embedded_controls_and_drafts_are_retained(qt_application, tmp_path):
    page = PdfProductionWorkspace()
    try:
        page.set_sources(paths=[source(tmp_path)], page_count=1, editor=True)
        assert all(not isinstance(panel, QDialog) for panel in page.panels.values())
        assert not page.busy_state and not page.controller.overview
        page.select_section("flatten")
        panel = page.panels["flatten"]
        panel.pages.setCurrentIndex(2)
        panel.range.setText("bad draft")
        panel.forms.setChecked(True)
        page.select_section("repair")
        page.panels["repair"].mode.setCurrentIndex(1)
        page.panels["repair"].javascript.setChecked(True)
        page.select_section("flatten")
        assert panel.range.text() == "bad draft" and panel.forms.isChecked()
        assert not page.generate_button.isEnabled()
        assert page.panels["repair"].javascript.isChecked()
        assert not page.panels["fonts"].safe_embed.isChecked()
    finally:
        page.request_close()


def test_real_overview_and_flatten_publish_only_on_generate(qt_application, tmp_path):
    path = source(tmp_path)
    original = path.read_bytes()
    page = PdfProductionWorkspace()
    try:
        page.set_sources(paths=[path], page_count=1, editor=True)
        page.output_folder.setText(str(tmp_path / "output"))
        page.analyze()
        wait(qt_application, lambda: not page.busy_state)
        assert page.controller.overview["files"][0]["pdf"]["annotations"] == 1
        assert page.overview_table.rowCount() == 1
        assert not (tmp_path / "output").exists()
        assert not page.generate_button.isVisible()
        page.select_section("flatten")
        assert not page.generate_button.isEnabled()  # Overview does not approve a different operation.
        page.analyze()
        wait(qt_application, lambda: not page.busy_state)
        assert page.generate_button.isEnabled()
        page.generate()
        wait(qt_application, lambda: not page.busy_state)
        assert page.KEYS[page.stack.currentIndex()] == "results"
        output = page.selected_output()["output_pdf"]
        with fitz.open(output) as doc:
            assert "Searchable original" in doc[0].get_text()
            assert not list(doc[0].annots() or [])
        assert path.read_bytes() == original
        assert page.open_output.isEnabled() and page.open_reports.isEnabled()
    finally:
        page.request_close()


def test_shared_source_refresh_invalidates_approvals_and_preserves_draft(qt_application, tmp_path):
    path = source(tmp_path)
    page = PdfProductionWorkspace()
    try:
        state = {"current": True}
        page.set_sources(paths=[path], current=lambda: state["current"], editor=True, page_count=1)
        panel = page.panels["flatten"]
        panel.range.setText("invalid but retained")
        panel.forms.setChecked(True)
        fonts = page.panels["fonts"]
        fonts.reference.setText("old-reference.pdf")
        fonts.authorized.setChecked(True)
        fonts.selections = {"8": {"path": "old.ttf"}}
        state["current"] = False
        page.controller.check_source()
        assert page.controller.stale
        page.select_section("flatten")
        assert not page.analyze_button.isEnabled() and not page.generate_button.isEnabled()
        state["current"] = True
        page.controller.refresh_factory = lambda: dict(paths=[path], editor=True, page_count=1)
        page.refresh_source()
        assert not page.controller.stale
        assert panel.range.text() == "invalid but retained" and panel.forms.isChecked()
        assert not fonts.reference.text() and not fonts.selections and not fonts.authorized.isChecked()
    finally:
        page.request_close()


def test_source_change_cancels_and_discards_late_result(qt_application, tmp_path, monkeypatch):
    import dialogs.pdf_operations as operations
    monkeypatch.setattr(operations, "Worker", FakeWorker)
    page = PdfProductionWorkspace()
    state = {"current": True}
    page.set_sources(paths=[source(tmp_path)], current=lambda: state["current"], page_count=1)
    page.select_section("flatten")
    page.analyze()
    panel = page.panels["flatten"]
    worker = panel.worker
    page.select_section("fonts")
    assert panel.worker is worker and not worker.cancelled
    assert not page.choose_button.isEnabled()
    state["current"] = False
    page.controller.check_source()
    assert worker.cancelled
    worker.resultReady.emit({"plan": {}})
    assert panel.plan is None
    worker.ended.emit()
    assert not page.busy_state
    assert page.controller.history[-1]["outdated"]
    page.request_close()


def test_close_retains_worker_and_temp_until_safe_end(qt_application, tmp_path, monkeypatch):
    import dialogs.pdf_operations as operations
    monkeypatch.setattr(operations, "Worker", FakeWorker)
    page = PdfProductionWorkspace()
    page.set_sources(paths=[source(tmp_path)], page_count=1)
    page.select_section("flatten")
    page.analyze()
    worker = page.panels["flatten"].worker
    directory = Path(page.controller.directory.name)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    page.request_close()
    assert not page.stopped and not worker.cancelled
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.request_close()
    assert page.stopped and worker.cancelled and directory.exists()
    worker.ended.emit()
    assert not directory.exists()


def test_narrow_large_font_footer_and_navigation(qt_application, tmp_path):
    from PyQt6.QtGui import QFont
    page = PdfProductionWorkspace()
    try:
        page.set_sources(paths=[source(tmp_path)], page_count=1)
        font = QFont(page.font())
        font.setPointSize(18)
        page.setFont(font)
        page.resize(700, 550)
        page.show()
        qt_application.processEvents()
        assert page.navigation.isVisible() and not page.tabs.isVisible()
        page.navigation.setCurrentIndex(2)
        qt_application.processEvents()
        assert page.stack.currentIndex() == 2
        assert page.generate_button.isVisible()
        assert page.footer.geometry().bottom() <= page.rect().bottom()
        assert page.generate_button.mapTo(page, page.generate_button.rect().bottomRight()).x() < page.width()
        assert all(panel.footer.isHidden() for panel in page.panels.values())
    finally:
        page.request_close()


def test_viewer_routes_single_entry_legacy_commands_and_snapshots(qt_application, tmp_path, monkeypatch):
    import core.viewer as viewer_module
    from core.settings import SettingsManager
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    window = viewer_module.PDFViewer()
    try:
        window._load_file_sync(str(source(tmp_path)))
        session = window._session
        session.engine.document[0].insert_text((30, 65), "Unsaved edit")
        window._open_pdf_production()
        page = window.workspace.current_tool()
        assert isinstance(page, PdfProductionWorkspace)
        with fitz.open(page.controller.sources[0]) as snapshot:
            assert "Unsaved edit" in snapshot[0].get_text()
        assert page.property("workspaceKind") == "pdf_production"
        assert not window.command_bar._save.isEnabled()
        assert not window.command_bar._undo.isEnabled()
        assert not window.side_panel.isHidden()
        window._open_font_preflight()
        assert window.workspace.current_tool() is page and page.stack.currentIndex() == 1
        assert len(window._pdf_production_pages) == 1
        window.workspace.set_current_session(session)
        window._open_pdf_operation("flatten")
        assert window.workspace.current_tool() is page and page.stack.currentIndex() == 2
        page.request_close()
        assert not window._pdf_production_pages
    finally:
        window.close()
        window.deleteLater()
