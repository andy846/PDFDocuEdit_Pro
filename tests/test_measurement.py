from __future__ import annotations

import time

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.annotations import AnnotationOp, apply_annotation
from core.measurement import distance_mm, format_distance
from ui.page_overlay import PageOverlay


def test_metric_distance_and_pdf_user_unit() -> None:
    assert distance_mm((0, 0), (72, 0)) == pytest.approx(25.4)
    assert distance_mm((0, 0), (72, 72)) == pytest.approx(35.921024)
    assert format_distance(25.4, "mm") == "25.40 mm"
    assert format_distance(25.4, "cm") == "2.54 cm"

    doc = fitz.open()
    page = doc.new_page(width=72, height=72)
    doc.xref_set_key(page.xref, "UserUnit", "2")
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    # PyMuPDF presents page coordinates after applying UserUnit.
    assert reopened[0].rect.width == 144
    assert distance_mm((0, 0), (reopened[0].rect.width, 0)) == pytest.approx(50.8)
    reopened.close()
    doc.close()


def test_overlay_two_click_measurement_and_rotation() -> None:
    app = QApplication.instance() or QApplication([])
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.set_rotation(90)
    overlay = PageOverlay(0)
    overlay.resize(200, 400)
    overlay.set_geometry_info(page.rect, 0.5, page.rotation_matrix, page.derotation_matrix)
    overlay.set_measure_mode(True)
    drawn = []
    overlay.measurementDrawn.connect(lambda _page, points: drawn.append(points))
    overlay.show()
    app.processEvents()

    start = overlay.pdf_point_to_widget((20, 10)).toPoint()
    end = overlay.pdf_point_to_widget((92, 10)).toPoint()
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(overlay, end)
    assert overlay._measure_origin is not None
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=end)
    assert len(drawn) == 1
    assert drawn[0][0] == pytest.approx((20, 10))
    assert drawn[0][1] == pytest.approx((92, 10))
    assert distance_mm(*drawn[0]) == pytest.approx(25.4)
    overlay.set_measurements(drawn, "cm", 0)
    assert not overlay.grab().isNull()
    overlay.close()
    doc.close()


def test_saved_measurement_has_visible_label_after_reopen() -> None:
    doc = fitz.open()
    doc.new_page()
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((72, 72), (144, 72)),
        text="25.40 mm",
    ))
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    page = reopened[0]
    annotations = list(page.annots())
    assert [entry.type[1] for entry in annotations] == ["Line", "FreeText"]
    assert [entry.info["content"] for entry in annotations] == ["25.40 mm"] * 2
    reopened.close()
    doc.close()


def test_canvas_measurement_can_be_saved_through_viewer(tmp_path, monkeypatch) -> None:
    import core.viewer as viewer_module
    from core.settings import SettingsManager
    from ui.pdf_canvas import ToolMode

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        viewer_module, "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    source = tmp_path / "measured.pdf"
    with fitz.open() as document:
        document.new_page(width=300, height=300)
        document.new_page(width=300, height=300)
        document.save(source)
    window = viewer_module.PDFViewer()
    window.resize(1000, 700)
    window.show()
    def wait_for_page(canvas, page_number):
        deadline = time.monotonic() + 10
        while page_number not in canvas._page_views and time.monotonic() < deadline:
            QTest.qWait(10)
        assert page_number in canvas._page_views

    try:
        app.processEvents()
        window._load_file_sync(str(source))
        app.processEvents()
        canvas = window.workspace.canvas
        window.command_bar._canvas_buttons["measure"].click()
        assert canvas.tool_mode == ToolMode.MEASURE
        wait_for_page(canvas, 0)
        overlay = canvas._page_views[0].overlay
        start = overlay.pdf_point_to_widget((72, 72)).toPoint()
        end = overlay.pdf_point_to_widget((144, 72)).toPoint()
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=end)
        assert canvas.selected_measurement() is not None
        canvas.set_zoom(2.0)
        wait_for_page(canvas, 0)
        assert len(canvas._page_views[0].overlay._measurements) == 1
        canvas.set_page(1)
        wait_for_page(canvas, 1)
        canvas.set_page(0)
        wait_for_page(canvas, 0)
        assert len(canvas._page_views[0].overlay._measurements) == 1
        canvas.set_measure_unit("cm")
        assert canvas._page_views[0].overlay._measure_unit == "cm"
        window._store_selected_measurement(window._session, canvas)
        assert canvas.selected_measurement() is None
        assert len(list(window.engine.document[0].annots())) == 2
        window.save_file()
        with fitz.open(source) as saved:
            page = saved[0]
            assert [annotation.info["content"] for annotation in page.annots()] == [
                "2.54 cm", "2.54 cm"
            ]
    finally:
        window.close()
