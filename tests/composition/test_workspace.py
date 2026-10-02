from __future__ import annotations

import json
import time

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from composition.designer.workspace import CompositionWindow
from composition.engine.assets import asset_root
from composition.template.model import DataConfig
from composition.template.serializer import load_project

pytestmark = pytest.mark.skipif(
    not (asset_root() / "qpdf" / "qpdf.exe").exists(), reason="Prepared Windows composition runtime required."
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        QApplication.processEvents()
        QTest.qWait(10)
    assert predicate(), "Timed out waiting for composition worker"


def close_window(window):
    window.undo.setClean()
    window.close()
    wait_until(lambda: not window.workers)


def test_designer_undo_preview_production_and_save(app, tmp_path, monkeypatch):
    window = CompositionWindow()
    window.show()
    window.resize(960, 640)
    window.add_element("text", "Account: {{Account}}")
    assert len(window.template.elements) == 1
    window.undo.undo()
    assert not window.template.elements
    window.undo.redo()
    assert len(window.template.elements) == 1
    source = tmp_path / "customers.csv"
    source.write_text("Account\n0001\n0002\n", encoding="utf-8")
    window._start_import(DataConfig(path=str(source)))
    wait_until(lambda: window.import_worker is None)
    assert window.record_count == 2
    window.tabs.setCurrentIndex(2)
    wait_until(lambda: window.canvas.preview_item is not None)
    window.record.setValue(2)
    wait_until(lambda: window.canvas.preview_item is not None)
    save = tmp_path / "statement.pdcx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(save), ""))
    assert window.save_project()
    assert load_project(save).elements[0].value == "Account: {{Account}}"
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    window.start_production(str(tmp_path / "output"))
    wait_until(lambda: window.production_worker is None)
    timer.stop()
    assert ticks, "GUI event loop must continue during production"
    assert window.last_output, window.production_summary.toPlainText()
    with fitz.open(window.last_output) as doc:
        assert doc.page_count == 2
        assert "0001" in doc[0].get_text()
        assert "0002" in doc[1].get_text()
    log = json.loads((__import__("pathlib").Path(window.last_output).parent / "job.json").read_text(encoding="utf-8"))
    assert log["successful_records"] == 2
    close_window(window)


def test_preview_error_does_not_display_stale_success(app, tmp_path):
    window = CompositionWindow()
    original_policy = window.auto_repair.isChecked()
    window.auto_repair.setChecked(False)  # Explicitly exercise the retained strict mode.
    window.add_element("text", "Valid text")
    wait_until(lambda: window.canvas.preview_item is not None)
    selected = window.template.elements[0].id
    previous = window.canvas.preview_item
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][0]["elements"][0]["value"] = "\u9999\u6e2f"
    window._commit(before, after, "unsupported glyph", selected)
    assert window.canvas.preview_item is previous
    assert window.preview_state.text() == "Updating preview…"
    wait_until(lambda: "cannot render" in window.message.text())
    assert window.canvas.preview_item is None
    window.preferences.setValue("auto_glyph_repair", original_policy)
    close_window(window)
