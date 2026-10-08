import time
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QFileDialog

from core.pdf_operations.model import PdfOperationPlan, PdfOptions
from dialogs.pdf_operations import PdfOperationDialog
from ui.variable_name import VariableNameEdit


def wait(qt_application, predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.01)
    assert predicate(), "Background PDF worker did not finish"


def source(tmp_path):
    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 30), "Customer")
        page.add_text_annot((50, 50), "Note")
        doc.save(path)
    return path


def test_actual_worker_analysis_generation_and_scrollable_footer(qt_application, tmp_path):
    path = source(tmp_path)
    dialog = PdfOperationDialog(path, "flatten", page_count=1)
    dialog.resize(800, 550)
    dialog.show()
    qt_application.processEvents()
    assert dialog._responsive_footer is not None
    assert not dialog.generate_button.isEnabled()
    dialog.analyze()
    wait(qt_application, lambda: dialog.worker is None)
    assert dialog.plan and dialog.generate_button.isEnabled()
    dialog.output_folder.setText(str(tmp_path / "output"))
    dialog.generate()
    wait(qt_application, lambda: dialog.worker is None)
    assert Path(dialog.last_result["output_pdf"]).is_file()
    assert dialog.open_button.isEnabled() and dialog.reports_button.isEnabled()
    dialog.reject()


def test_changes_invalidate_analysis_and_wrong_password_is_not_written(qt_application, tmp_path):
    path = source(tmp_path)
    dialog = PdfOperationDialog(path, "flatten", page_count=1, password="private-test-password")
    dialog.analyze()
    worker = dialog.worker
    assert "private-test-password" not in worker.request_file.read_text()
    wait(qt_application, lambda: dialog.worker is None)
    assert dialog.plan
    dialog.forms.setChecked(True)
    assert dialog.plan is None and not dialog.generate_button.isEnabled()
    dialog.reject()


def test_source_revision_changes_block_generation(qt_application, tmp_path):
    path = source(tmp_path)
    dialog = PdfOperationDialog(path, "flatten", source_current=lambda: False)
    dialog.analyze()
    assert dialog.worker is None and "changed" in dialog.summary.toPlainText()
    dialog.reject()


def test_naming_editor_reports_invalid_token_and_matches_prepared_value(qt_application):
    editor = VariableNameEdit("{{input.stem}}_{{workflow.sequence|pad:6}}.pdf")
    assert editor.resolved() == "example_000001.pdf"
    editor.edit.setText("{{record.Missing}}.pdf")
    assert "Missing field" in editor.preview.text()


def test_naming_preview_explains_sanitisation_and_clears_stale_error(qt_application):
    from core.variables import VariableContext
    editor = VariableNameEdit("{{record.Name}}.pdf")
    editor.set_context(VariableContext.for_job(record={"Name": "陳/大文"}), prepared=True)
    assert editor.resolved() == "陳_大文.pdf"
    assert "Filename sanitised" in editor.preview.text()
    assert "陳/大文" in editor.preview.toolTip()
    editor.edit.setText("{{record.Missing}}.pdf")
    assert editor.edit.property("invalid") is True
    assert "Missing field" in editor.preview.toolTip()
    editor.edit.setText("valid.pdf")
    assert editor.edit.property("invalid") is False
    assert editor.preview.toolTip() == "valid.pdf"


def test_settings_only_retains_invalid_draft_and_returns_selected_pages(qt_application, tmp_path):
    from core.pdf_operations.model import PdfOptions
    options = PdfOptions(pages=(0, 2), forms=True)
    dialog = PdfOperationDialog(source(tmp_path), "flatten", settings_only=True, initial_options=options)
    dialog.show()
    qt_application.processEvents()
    assert not dialog.analyse_button.isVisible() and dialog.generate_button.isEnabled()
    dialog.range.setText("invalid")
    dialog.generate()
    assert dialog.selected_options is None and dialog.range.text() == "invalid"
    dialog.range.setText("1,3")
    dialog.generate()
    assert dialog.selected_options.pages == (0, 2) and dialog.selected_options.forms


def test_pdf_production_tools_in_sidebar_search_and_collapsed_mode(qt_application):
    from ui.side_panel import SidePanel
    panel = SidePanel(animations_enabled=False)
    try:
        panel.set_document_available(False)
        assert not panel._buttons["flatten"].isEnabled()
        assert panel._buttons["pdf_repair"].isEnabled()
        panel.set_document_available(True)
        received = []
        panel.toolRequested.connect(received.append)
        for key, search in (("flatten", "Flatten"), ("pdf_repair", "Production Normalise")):
            button = panel._buttons[key]
            assert not button.icon().isNull()
            panel._search.setText(search)
            qt_application.processEvents()
            assert not button.isHidden()
            assert panel._buttons["merge"].isHidden()
            panel._search.clear()
            panel.set_collapsed(True, animate=False)
            assert button.text() == "" and "new" in button.toolTip().lower()
            button.click()
            assert received[-1] == key
            panel.set_collapsed(False, animate=False)
            assert button.text()
    finally:
        panel.close()
        panel.deleteLater()


def test_sidebar_tools_route_to_existing_dialogs_and_commands(qt_application, tmp_path, monkeypatch):
    import core.viewer as viewer_module
    from core.settings import SettingsManager
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    window = viewer_module.PDFViewer()
    try:
        # Use a loaded document so the normal availability guard participates.
        window._load_file_sync(str(source(tmp_path)))
        qt_application.processEvents()
        calls = []
        monkeypatch.setattr(window, "_open_pdf_operation", calls.append)
        window.side_panel._buttons["flatten"].click()
        window.side_panel._buttons["pdf_repair"].click()
        assert calls == ["flatten", "repair"]
        for key in ("flatten", "pdf_repair"):
            assert sum(c.id == key for c in window._commands) == 1
            assert window._command_action_map[key].isEnabled()
    finally:
        window.close()
        window.deleteLater()


def test_batch_exposes_required_approvals_and_password_invalidates_analysis(qt_application, tmp_path):
    dialog = PdfOperationDialog(source(tmp_path), "repair")
    options = PdfOptions(operation="repair", annotations=False)
    plan = PdfOperationPlan(dialog.source, "test-hash", options, 1, signed=True,
                            diagnostics={"recovery": {"status": "Warning", "original_unrenderable": True}})
    row = {"source": dialog.source, "plan": plan.to_dict(), "error": ""}
    try:
        dialog.analysis_ready({"analyses": [row]})
        dialog.worker_ended()
        assert not dialog.signature.isHidden() and not dialog.recovery_ack.isHidden()
        assert dialog.generate_button.isEnabled()
        dialog.signature.setChecked(True)
        dialog.recovery_ack.setChecked(True)
        assert dialog.analyses and dialog.generate_button.isEnabled()
        acknowledged = dialog.analyses[0]["plan"]
        assert acknowledged["options"]["acknowledge_signatures"]
        assert acknowledged["options"]["acknowledge_recovery"]
        assert acknowledged["source_sha256"] == "test-hash"
        dialog.password_edit.setText("new-password")
        assert not dialog.analyses and not dialog.generate_button.isEnabled()
    finally:
        dialog.reject()


def test_single_plan_approval_retains_inventory_but_transform_changes_invalidate(qt_application, tmp_path):
    dialog = PdfOperationDialog(source(tmp_path), "flatten", page_count=1)
    try:
        options = PdfOptions(rasterise=True)
        dialog.raster.setChecked(True)
        dialog.plan = PdfOperationPlan(dialog.source, "stable-source", options, 1, annotations=2)
        dialog.raster_ack.setChecked(True)
        assert dialog.plan.source_sha256 == "stable-source"
        assert dialog.plan.annotations == 2 and dialog.plan.options.acknowledge_raster
        assert dialog.options() == dialog.plan.options
        dialog.forms.setChecked(True)
        assert dialog.plan is None and not dialog.generate_button.isEnabled()
    finally:
        dialog.reject()


def test_batch_page_range_is_checked_per_source_and_current_page_resets(qt_application, tmp_path, monkeypatch):
    path = source(tmp_path)
    other = tmp_path / "other.pdf"
    other.write_bytes(path.read_bytes())
    dialog = PdfOperationDialog(path, "flatten", page_count=8, current_page=7)
    try:
        dialog.pages.setCurrentIndex(1)
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(path), str(other)], ""))
        dialog.choose_batch()
        assert dialog.pages.currentIndex() == 0
        assert not dialog.pages.model().item(1).isEnabled()
        dialog.pages.setCurrentIndex(2)
        dialog.range.setText("1,3")
        assert dialog.options().pages == (0, 2)
    finally:
        dialog.reject()


def test_maximum_mode_ignores_stale_range_and_batch_failure_remains_reviewable(qt_application, tmp_path):
    dialog = PdfOperationDialog(source(tmp_path), "repair")
    try:
        dialog.pages.setCurrentIndex(2)
        dialog.range.setText("invalid range")
        dialog.mode.setCurrentIndex(dialog.mode.findData("maximum"))
        assert dialog.options().pages is None
        assert not dialog.pages.isEnabled() and not dialog.range.isEnabled()
        dialog.analyses = [{"source": dialog.source, "plan": None, "error": "unreadable PDF"}]
        dialog.generate()
        assert "No source passed analysis" in dialog.summary.toPlainText()
        assert dialog.worker is None
        dialog.generated({"status": "needs_review", "report_dir": str(tmp_path), "files": [
            {"source": dialog.source, "status": "completed", "output_pdf": "one.pdf"},
            {"source": "broken.pdf", "status": "failed", "error": "unreadable PDF"}]})
        text = dialog.summary.toPlainText()
        assert "Completed: 1" in text and "Failed: 1" in text and "broken.pdf: failed" in text
    finally:
        dialog.reject()
