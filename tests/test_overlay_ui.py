from __future__ import annotations

import time
from pathlib import Path
from shutil import copyfile

import fitz
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from core.overlay import OverlayFileResult
from dialogs.overlay_tool import OverlayDialog, OverlayResultsDialog


def make_pdf(path: Path, pages: int = 1) -> Path:
    with fitz.open() as document:
        for page_number in range(pages):
            page = document.new_page(width=180, height=240)
            page.insert_text((20, 30), f"Page {page_number + 1}")
        document.save(path)
    return path


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(20)
    assert predicate()


def test_overlay_dialog_preflight_preview_and_options(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["overlay-dialog-test"])
    template = make_pdf(tmp_path / "template.pdf")
    target = make_pdf(tmp_path / "target.pdf", 2)
    dialog = OverlayDialog(target)
    dialog.show()
    dialog.template.setText(str(template))
    dialog.output.setText(str(tmp_path))
    wait_for(lambda: dialog.apply_button.isEnabled())
    assert dialog.model.rowCount() == 1
    assert dialog.model.jobs[0].pages == 2
    wait_for(lambda: dialog._images is not None)
    dialog.preview_zoom.setCurrentIndex(2)
    assert dialog.before_label.pixmap() is not None
    assert dialog.before_scroll.horizontalScrollBar().maximum() > 0
    dialog.mapping.setCurrentIndex(1)
    dialog.layer.setCurrentIndex(1)
    dialog.offset_x.setValue(5.0)
    dialog._validate()
    assert dialog.details is not None
    assert dialog.details["options"].mapping == "cycle"
    assert dialog.details["options"].layer == "background"
    assert dialog.details["options"].offset_x_mm == 5.0
    assert dialog.details["targets"] == [str(target)]
    dialog.close()
    app.processEvents()


def test_overlay_dialog_blocks_output_collisions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["overlay-collision-test"])
    template = make_pdf(tmp_path / "template.pdf")
    target = make_pdf(tmp_path / "target.pdf")
    make_pdf(tmp_path / "target_overlay.pdf")
    dialog = OverlayDialog(target)
    dialog.template.setText(str(template))
    dialog.output.setText(str(tmp_path))
    wait_for(lambda: dialog._preflight is not None)
    assert not dialog.apply_button.isEnabled()
    assert "already exists" in dialog.model.jobs[0].problem
    dialog.close()
    app.processEvents()


def test_overlay_results_csv_contains_each_file_status(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["overlay-results-test"])
    output = tmp_path / "results.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(output), "CSV (*.csv)"))
    results = [
        OverlayFileResult(tmp_path / "a.pdf", tmp_path / "a_overlay.pdf", "completed"),
        OverlayFileResult(tmp_path / "b.pdf", tmp_path / "b_overlay.pdf", "failed", "Unreadable"),
    ]
    dialog = OverlayResultsDialog(results, tmp_path)
    dialog._export_csv()
    content = output.read_text(encoding="utf-8-sig")
    assert "a.pdf" in content and "completed" in content
    assert "b.pdf" in content and "Unreadable" in content
    dialog.close()
    app.processEvents()


def test_folder_preflight_lists_500_files_without_loading_table_cells(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["overlay-large-folder-test"])
    template = make_pdf(tmp_path / "template.pdf")
    targets = tmp_path / "targets"
    targets.mkdir()
    sample = make_pdf(tmp_path / "sample.pdf")
    for index in range(500):
        copyfile(sample, targets / f"target-{index:03d}.pdf")
    output = tmp_path / "output"
    output.mkdir()
    dialog = OverlayDialog(None)
    dialog.target_mode.setCurrentIndex(2)
    dialog.target.setText(str(targets))
    dialog.output.setText(str(output))
    dialog.template.setText(str(template))
    wait_for(lambda: dialog.apply_button.isEnabled(), timeout=15.0)
    assert dialog.model.rowCount() == 500
    assert "Targets: 500" in dialog.summary.text()
    dialog.close()
    app.processEvents()
