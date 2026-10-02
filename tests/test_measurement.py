from __future__ import annotations

import time

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.annotations import (
    AnnotationOp,
    apply_annotation,
    recalibrate_measurements,
    remove_annotation,
    update_annotation_geometry,
    update_saved_measurement,
)
from core.measurement import (
    calibrated_factor,
    copy_page_scale,
    distance_mm,
    format_distance,
    page_scale,
    saved_measurements,
    set_page_scale,
)
from core.pdf_engine import PdfEngine
from ui.page_overlay import PageOverlay


def test_metric_distance_and_pdf_user_unit() -> None:
    assert distance_mm((0, 0), (72, 0)) == pytest.approx(25.4)
    assert distance_mm((0, 0), (1, 0)) == pytest.approx(25.4 / 72)
    assert distance_mm((0, 0), (0.001, 0)) > 0
    assert distance_mm((0, 0), (72, 72)) == pytest.approx(35.921024)
    assert format_distance(25.4, "mm") == "25.40 mm"
    assert format_distance(25.4, "cm") == "2.54 cm"
    assert format_distance(2540, "mm") == "2,540.00 mm"
    assert calibrated_factor((0, 0), (72, 0), 2540) == pytest.approx(100)
    assert calibrated_factor((0, 0), (72, 0), 12.7) == pytest.approx(0.5)
    assert calibrated_factor((0, 0), (72, 0), 254000) == pytest.approx(10000)
    for invalid in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            calibrated_factor((0, 0), (72, 0), invalid)
    with pytest.raises(ValueError):
        calibrated_factor((0, 0), (0, 0), 100)

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


def test_page_scale_follows_page_and_managed_labels_recalculate() -> None:
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((0, 20), (72, 20)),
        text="25.40 mm",
    ))
    records = saved_measurements(doc[0])
    assert len(records) == 1
    assert page_scale(doc[0]).state == "paper"
    recalibrate_measurements(doc, 0, 100)
    assert page_scale(doc[0]).real_per_paper == 100
    assert page_scale(doc[1]).state == "paper"
    assert [annot.info["content"] for annot in doc[0].annots()] == [
        "2,540.00 mm", "2,540.00 mm",
    ]
    assert update_saved_measurement(
        doc, 0, records[0].identifier, ((0, 20), (144, 20)), "cm"
    )
    assert [annot.info["content"] for annot in doc[0].annots()] == [
        "508.00 cm", "508.00 cm",
    ]
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    assert saved_measurements(reopened[0])[0].unit == "cm"
    reopened.select([1, 0])
    assert page_scale(reopened[0]).state == "paper"
    assert page_scale(reopened[1]).real_per_paper == 100
    copied = fitz.open()
    copied.insert_pdf(reopened, from_page=1, to_page=1)
    assert page_scale(copied[0]).state == "paper"
    copy_page_scale(reopened[1], copied[0])
    assert page_scale(copied[0]).real_per_paper == 100
    assert len(saved_measurements(copied[0])) == 1
    copied.close()
    reopened.close()
    doc.close()


def test_corrupt_calibration_falls_back_without_changing_document() -> None:
    doc = fitz.open()
    page = doc.new_page()
    for factor in (0, -2, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            set_page_scale(page, factor)
    assert page_scale(page).state == "paper"
    doc.xref_set_key(page.xref, "PDFDocuEditScale", fitz.get_pdf_str("broken"))
    assert page_scale(page).state == "invalid"
    assert page_scale(page).real_per_paper == 1
    doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_saved_points_stay_stable_after_page_rotation(rotation) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.set_rotation(rotation)
    set_page_scale(page, 0.5)
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((20, 20), (92, 20)),
        text="12.70 mm",
    ))
    reopened = fitz.open(stream=doc.tobytes(), filetype="pdf")
    record = saved_measurements(reopened[0])[0]
    assert record.points[0] == pytest.approx((20, 20))
    assert record.points[1] == pytest.approx((92, 20))
    assert page_scale(reopened[0]).real_per_paper == 0.5
    reopened.close()
    doc.close()


def test_rotated_wide_page_keeps_label_near_measurement() -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    page.set_rotation(90)
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((210, 40), (280, 40)),
        text="24.69 mm",
    ))
    annotations = list(page.annots())
    assert annotations[1].rect.x0 > 200
    assert annotations[1].rect.x1 <= 300
    doc.close()


def test_generic_annotation_operations_keep_managed_pair_together() -> None:
    doc = fitz.open()
    doc.new_page()
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((0, 20), (72, 20)),
        text="25.40 mm",
    ))
    record = saved_measurements(doc[0])[0]
    new_xref = update_annotation_geometry(
        doc[0], record.line_xref, points=((0, 20), (144, 20))
    )
    assert new_xref == saved_measurements(doc[0])[0].line_xref
    assert [annot.info["content"] for annot in doc[0].annots()] == [
        "50.80 mm", "50.80 mm",
    ]
    assert remove_annotation(doc[0], new_xref)
    assert list(doc[0].annots()) == []
    doc.close()


def test_legacy_and_managed_measurements_coexist_without_rewriting_legacy() -> None:
    doc = fitz.open()
    page = doc.new_page()
    legacy = page.add_line_annot((10, 10), (82, 10))
    legacy.set_info(subject="Measurement", content="25.40 mm")
    legacy.update()
    old_xref = legacy.xref
    apply_annotation(doc, AnnotationOp(
        kind="measurement", page=0, points=((0, 30), (72, 30)),
        text="25.40 mm",
    ))
    recalibrate_measurements(doc, 0, 100)
    assert page.load_annot(old_xref).info["content"] == "25.40 mm"
    assert len(saved_measurements(page)) == 1
    assert len(list(page.annots())) == 3
    doc.close()


def test_readonly_overlay_can_inspect_but_not_create_measurements() -> None:
    app = QApplication.instance() or QApplication([])
    overlay = PageOverlay(0)
    overlay.resize(200, 200)
    overlay.set_geometry_info(fitz.Rect(0, 0, 200, 200), 1)
    overlay.set_measure_mode(True)
    overlay.set_annotations_editable(False)
    drawn = []
    overlay.measurementDrawn.connect(lambda *value: drawn.append(value))
    overlay.show()
    app.processEvents()
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=overlay.rect().center())
    assert not drawn
    assert overlay._measure_origin is None
    overlay.set_measurements([], "cm", scale=100, scale_state="calibrated")
    assert not overlay.grab().isNull()
    overlay.close()


def test_engine_page_operations_preserve_scale(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page()
        set_page_scale(document[0], 100)
        document.new_page()
        document.save(source)
    engine = PdfEngine()
    engine.open(source)
    engine.reorder_pages([1, 0])
    assert page_scale(engine.document[1]).real_per_paper == 100
    extracted = engine.extract_pages([1], tmp_path / "extracted.pdf")
    with fitz.open(extracted) as document:
        assert page_scale(document[0]).real_per_paper == 100
    engine.save()
    engine.close()
    with fitz.open(source) as document:
        assert page_scale(document[1]).real_per_paper == 100


def test_viewer_calibration_saved_drag_and_undo(tmp_path, monkeypatch) -> None:
    import core.viewer as viewer_module
    from core.settings import SettingsManager

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        viewer_module, "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    source = tmp_path / "interactive.pdf"
    with fitz.open() as document:
        document.new_page(width=300, height=300)
        document.save(source)
    window = viewer_module.PDFViewer()
    window.resize(1000, 700)
    window.show()
    try:
        app.processEvents()
        window._load_file_sync(str(source))
        canvas = window.workspace.canvas
        canvas.set_tool_mode("measure")
        deadline = time.monotonic() + 10
        while 0 not in canvas._page_views and time.monotonic() < deadline:
            QTest.qWait(10)
        assert 0 in canvas._page_views
        overlay = canvas._page_views[0].overlay
        start = overlay.pdf_point_to_widget((72, 72)).toPoint()
        end = overlay.pdf_point_to_widget((144, 72)).toPoint()
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=end)
        window._store_selected_measurement(window._session, canvas)
        record = saved_measurements(window.engine.document[0])[0]
        window._apply_page_scale(window._session, canvas, 0, 100)
        assert page_scale(window.engine.document[0]).real_per_paper == 100
        assert saved_measurements(window.engine.document[0])[0].identifier == record.identifier
        window._undo()
        assert page_scale(window.engine.document[0]).state == "paper"
        assert next(window.engine.document[0].annots()).info["content"] == "25.40 mm"
        window._redo()
        assert page_scale(window.engine.document[0]).real_per_paper == 100
        overlay = canvas._page_views[0].overlay
        assert overlay._saved_measurements
        end = overlay.pdf_point_to_widget((144, 72)).toPoint()
        target = overlay.pdf_point_to_widget((216, 72)).toPoint()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=end)
        QTest.mouseMove(overlay, target)
        window._escape_to_browse()
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=target)
        assert saved_measurements(window.engine.document[0])[0].points[1][0] == pytest.approx(144)
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=end)
        QTest.mouseMove(overlay, target)
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=target)
        moved = saved_measurements(window.engine.document[0])[0]
        assert moved.points[1][0] == pytest.approx(216, abs=0.1)
        assert next(window.engine.document[0].annots()).info["content"] == "5,080.00 mm"
        window._undo()
        assert saved_measurements(window.engine.document[0])[0].points[1][0] == pytest.approx(144)
        window._redo()
        assert saved_measurements(window.engine.document[0])[0].points[1][0] == pytest.approx(216, abs=0.1)
        window.save_file()
        with fitz.open(source) as saved:
            assert page_scale(saved[0]).real_per_paper == 100
            assert saved_measurements(saved[0])[0].identifier == record.identifier
        copied_path = tmp_path / "saved-as.pdf"
        window.engine.save_as(copied_path)
        with fitz.open(copied_path) as copied:
            assert page_scale(copied[0]).real_per_paper == 100
            assert saved_measurements(copied[0])[0].points[1][0] == pytest.approx(216, abs=0.1)
    finally:
        window.close()


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
