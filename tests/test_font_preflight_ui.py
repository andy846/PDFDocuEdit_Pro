"""Focused Editor UI checks, using the shared QApplication lifecycle."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QFont

from core.font_preflight.inventory import analyze
from dialogs.font_preflight import FontPreflightDialog


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


def base_pdf(tmp_path):
    from core.pdf_backend import fitz

    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((20, 30), "Original")
        doc.save(path)
    return path


def test_selection_page_navigation_and_protected_controls(qt_application, tmp_path):
    path = base_pdf(tmp_path)
    dialog = FontPreflightDialog(path, scan_only=True)
    report = analyze(path).to_dict()
    dialog.analysis_ready({"inventory": report})
    assert report["protected"]
    assert not dialog.repair_button.isEnabled()
    pages = []
    dialog.pageRequested.connect(pages.append)
    dialog.table.selectRow(0)
    dialog.jump_page()
    assert pages == [0]
    assert "Base-14" in dialog.details.toPlainText()
    dialog.reject()


def test_invalidates_drafts_and_cancel_waits_for_ended(qt_application, tmp_path, monkeypatch):
    from dialogs import font_preflight

    monkeypatch.setattr(font_preflight, "Worker", FakeWorker)
    dialog = FontPreflightDialog(base_pdf(tmp_path))
    dialog.analyze()
    worker = dialog.worker
    dialog.reject()
    assert dialog.close_pending and worker.cancelled
    assert dialog.worker is worker
    worker.ended.emit()
    assert dialog.worker is None
    assert not dialog.analyze_button.isEnabled() or not dialog.isVisible()


def test_source_change_cancels_and_no_wrong_page_jump_for_batch(qt_application, tmp_path, monkeypatch):
    from dialogs import font_preflight

    monkeypatch.setattr(font_preflight, "Worker", FakeWorker)
    state = {"valid": True}
    dialog = FontPreflightDialog(base_pdf(tmp_path), source_current=lambda: state["valid"])
    dialog.analyze()
    state["valid"] = False
    dialog.check_current()
    assert dialog.worker.cancelled
    dialog.worker.ended.emit()
    dialog.analysis_ready({"inventory": analyze(dialog.source).to_dict()})
    dialog.editor_source = False
    pages = []
    dialog.pageRequested.connect(pages.append)
    dialog.table.selectRow(0)
    dialog.jump_page()
    assert not pages
    dialog.reject()


def test_narrow_window_and_large_font_footer_reachable(qt_application, tmp_path):
    dialog = FontPreflightDialog(base_pdf(tmp_path))
    font = QFont(dialog.font())
    font.setPointSize(18)
    dialog.setFont(font)
    dialog.resize(900, 600)
    dialog.show()
    qt_application.processEvents()
    assert dialog._responsive_footer is not None
    assert dialog.repair_button.parentWidget() is dialog._responsive_footer
    assert dialog.cancel_button.parentWidget() is dialog._responsive_footer
    dialog.reject()


def test_worker_rejects_decrypted_editor_snapshot_repair(tmp_path):
    import pytest

    from core.font_preflight.worker import dispatch

    with pytest.raises(ValueError, match="scan-only"):
        dispatch({"task": "font_repair", "scan_only": True}, {})


def test_batch_drilldown_returns_to_results_and_settings_invalidate(qt_application, tmp_path):
    path = base_pdf(tmp_path)
    dialog = FontPreflightDialog(path)
    dialog.sources = [str(path), str(path)]
    report = analyze(path).to_dict()
    batch = {"files": [{"file_index": 1, "status": "ANALYZED", "inventory": report},
                       {"file_index": 2, "status": "ANALYZED", "inventory": report}]}
    dialog.analysis_ready(batch)
    dialog.table.selectRow(1)
    dialog.inspect_selected_batch()
    assert dialog.inventory["page_count"] == 1
    dialog.return_batch()
    assert dialog.table.rowCount() == 2
    dialog.policy.setCurrentIndex(1)
    assert dialog.batch_results is None and dialog.inventory is None
    dialog.reject()
