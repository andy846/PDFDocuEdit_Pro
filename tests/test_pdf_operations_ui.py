import time
from pathlib import Path

import fitz

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
