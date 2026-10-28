"""Operator-visible workbench behavior, not just widget existence."""
from copy import deepcopy

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QSettings, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from tests.test_quick_extraction import fixture_pdf
from tests.test_quick_extraction_ui import wait_until

GROUP = "dialogs/extract-region-workbench-v2"


@pytest.fixture(autouse=True)
def layout_settings(qt_application):
    QSettings().remove(GROUP)
    yield
    QSettings().remove(GROUP)


def make_dialog(tmp_path, *, empty=False):
    from dialogs.quick_text_extractor import QuickTextExtractorDialog
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    dialog = QuickTextExtractorDialog(source, 0, str(tmp_path/"result.xlsx"),
                                     spec=None if empty else spec.to_dict())
    dialog.show()
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    return dialog


def close_dialog(dialog):
    dialog.reject()
    wait_until(lambda: not dialog.host.workers)


def draw(dialog, first=(5, 5), last=(50, 30)):
    view = dialog.view
    for kind, coord in ((QEvent.Type.MouseButtonPress, first), (QEvent.Type.MouseMove, last),
                        (QEvent.Type.MouseButtonRelease, last)):
        point = view.mapFromScene(QPointF(*coord))
        event = QMouseEvent(kind, QPointF(point), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress: view.mousePressEvent, QEvent.Type.MouseMove: view.mouseMoveEvent,
         QEvent.Type.MouseButtonRelease: view.mouseReleaseEvent}[kind](event)


def test_empty_job_requires_explicit_draw_and_escape_cancels(qt_application, tmp_path):
    from PyQt6.QtTest import QTest
    dialog = make_dialog(tmp_path, empty=True)
    try:
        assert dialog.regions == []
        assert not dialog.extract_button.isEnabled()
        assert not dialog.sample_button.isEnabled()
        dialog.add()
        assert dialog.regions == []
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible() and dialog.regions == []
        dialog.add()
        draw(dialog)
        assert len(dialog.regions) == 1 and dialog.extract_button.isEnabled()
        assert 43 < dialog.regions[0]["width_mm"] < 47
        assert not dialog.draw_mode
        original = deepcopy(dialog.regions)
        draw(dialog, (60, 100), (80, 120))  # Ordinary blank dragging is not redraw/new.
        assert dialog.regions == original
        dialog.delete()
        assert dialog.regions == [] and not dialog.extract_button.isEnabled()
        dialog.undo.undo()
        assert len(dialog.regions) == 1
    finally:
        close_dialog(dialog)


@pytest.mark.parametrize("size, minimum", [((1280, 800), 8), ((960, 640), 6)])
def test_result_viewport_has_real_rows_and_resize_keeps_split(size, minimum, qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        dialog.resize(*size)
        QApplication.processEvents()
        assert dialog.width() <= size[0] and dialog.height() <= size[1]
        fields = [f"Field_{n}" for n in range(12)]
        dialog.model.replace([{"page": n, "status": "Extracted", "issues": "", "values": {f: str(n) for f in fields}}
                              for n in range(1, 51)], fields)
        QApplication.processEvents()
        assert dialog.view.isVisible() and dialog.table.isVisible()
        assert dialog.table.viewport().height() // dialog.table.rowHeight(0) >= minimum
        dialog.wide.setSizes([180, 420])
        before = dialog.wide.sizes()
        dialog.resize(size[0]+30, size[1]+40)
        QApplication.processEvents()
        after = dialog.wide.sizes()
        assert abs(before[1]/sum(before)-after[1]/sum(after)) < .08
        for button in (dialog.extract_button, dialog.export_button, dialog.cancel_button, dialog.close_button):
            point = button.mapTo(dialog, QPoint())
            assert 0 <= point.y() and point.y()+button.height() <= dialog.height()
        dialog.focus_results()
        assert not dialog.editor_page.isVisible() and dialog.table.isVisible()
        dialog.focus_results()
        assert dialog.editor_page.isVisible()
    finally:
        close_dialog(dialog)


def test_geometry_and_panels_restore_but_no_document_data_is_saved(qt_application, tmp_path, monkeypatch):
    import ui.responsive as responsive
    monkeypatch.setattr(responsive, "available_area", lambda widget: QRect(0, 0, 1920, 1080))
    dialog = make_dialog(tmp_path)
    assert abs(dialog.width()-1766) < 30 and abs(dialog.height()-993) < 50
    dialog.resize(1340, 850)
    dialog.wide.setSizes([260, 400])
    expected = dialog.wide.sizes()
    close_dialog(dialog)
    again = make_dialog(tmp_path)
    try:
        assert abs(again.width()-1340) < 10
        assert abs(again.wide.sizes()[1]/sum(again.wide.sizes())-expected[1]/sum(expected)) < .08
        values = QSettings()
        values.beginGroup(GROUP)
        assert not any(word in key.lower() for key in values.allKeys()
                       for word in ("source", "region", "field", "text", "output"))
    finally:
        close_dialog(again)


def test_boxes_labels_overlap_selection_and_duplicate_offset(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        for _ in range(12):
            dialog.duplicate()
        assert len(dialog.regions) == 13
        assert dialog.regions[0]["x_mm"] != dialog.regions[1]["x_mm"]
        for index in range(13):
            dialog.list.setCurrentRow(index)
        dialog.other_boxes()
        frames = [i for i in dialog.view.scene().items() if i.data(0) == "quick_region"]
        labels = [i for i in dialog.view.scene().items() if i.data(0) == "quick_label"]
        assert len(frames) == 13 and len(labels) == 13
        assert "13" in dialog.list.item(12).text() and dialog.regions[12]["name"] in dialog.list.item(12).toolTip()
        dialog.show_all.setChecked(False)
        assert len([i for i in dialog.view.scene().items() if i.data(0) == "quick_region"]) == 1
        dialog.show_all.setChecked(True)
        identical = deepcopy(dialog.regions[0])
        identical["name"] = "Overlapping"
        dialog.apply_regions([dialog.regions[0], identical])
        dialog.list.setCurrentRow(1)
        # Drag inside the current overlapping field; it must not jump to index 0.
        draw(dialog, (30, 30), (31, 31))
        assert dialog.current == 1
        menu = dialog.view.overlap_menu(QPointF(40, 40))
        assert len(menu.actions()) == 2
        menu.actions()[0].trigger()
        assert dialog.current == 0
    finally:
        close_dialog(dialog)


def test_table_navigation_keeps_custom_results_current_and_export_button_works(qt_application, tmp_path, monkeypatch):
    dialog = make_dialog(tmp_path)
    try:
        dialog.page_mode.setCurrentText("Custom pages")
        dialog.page_range.setText("1,3")
        dialog.start_scan()
        wait_until(lambda: dialog.result is not None and not dialog.host.workers)
        identity = dialog.scan_signature
        dialog.navigate_result(dialog.model.index(1, 3))
        assert dialog.page.value() == 3 and dialog.scan_signature == identity
        assert dialog.export_button.isEnabled()
        target = tmp_path/"clicked.xlsx"
        monkeypatch.setattr("dialogs.quick_text_extractor.QFileDialog.getSaveFileName",
                            lambda *args: (str(target), "Excel workbook (*.xlsx)"))
        dialog.choose_export()  # Also catches helper argument errors as Python failures.
        wait_until(lambda: dialog.last_output is not None and not dialog.host.workers)
        assert target.exists()
        clicked = tmp_path/"button.xlsx"
        monkeypatch.setattr("dialogs.quick_text_extractor.QFileDialog.getSaveFileName",
                            lambda *args: (str(clicked), "Excel workbook (*.xlsx)"))
        dialog.export_button.click()
        wait_until(lambda: dialog.last_output == str(clicked) and not dialog.host.workers)
        assert clicked.exists()
    finally:
        close_dialog(dialog)


def test_duplicate_selected_field_is_one_undo_and_selection_does_not_rescan(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        dialog.duplicate()
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        dialog.list.setCurrentRow(0)
        count, before = dialog.undo.count(), deepcopy(dialog.regions)
        dialog.duplicate()
        assert dialog.undo.index() == count+1
        assert dialog.regions[-1]["width_mm"] == before[0]["width_mm"]
        dialog.undo.undo()
        assert dialog.regions == before
        dialog.undo.redo()
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        dialog.list.setCurrentRow(0)
        assert not dialog.host.workers and dialog.host.pending is None
    finally:
        close_dialog(dialog)


def test_maximized_restore_and_offscreen_geometry_are_bounded(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    dialog.showMaximized()
    QApplication.processEvents()
    assert dialog.isMaximized()
    close_dialog(dialog)
    again = make_dialog(tmp_path)
    try:
        assert again.isMaximized()
        again.showNormal()
        QApplication.processEvents()
        # Simulate a previously removed monitor, then reopen on the current one.
        again.move(20000, 20000)
    finally:
        close_dialog(again)
    bounded = make_dialog(tmp_path)
    try:
        assert bounded.frameGeometry().intersects(bounded.screen().availableGeometry())
    finally:
        close_dialog(bounded)


def test_live_screen_and_dpi_changes_clamp_without_rebuilding_layout(qt_application, tmp_path, monkeypatch):
    from PyQt6.QtCore import QObject, pyqtSignal

    import ui.responsive as responsive
    class Screen(QObject):
        availableGeometryChanged = pyqtSignal(QRect)
        logicalDotsPerInchChanged = pyqtSignal(float)
    area = [QRect(0, 0, 1920, 1080)]
    monkeypatch.setattr(responsive, "available_area", lambda widget: area[0])
    dialog = make_dialog(tmp_path)
    screen = Screen()
    try:
        dialog.watch_workbench_screen(screen)
        dialog.resize(1400, 900)
        dialog.wide.setSizes([350, 440])
        area[0] = QRect(0, 0, 1100, 800)
        screen.availableGeometryChanged.emit(area[0])
        QApplication.processEvents()
        assert dialog.width() <= 1100 and dialog.height() <= 800
        dialog.resize(1400, 900)
        screen.logicalDotsPerInchChanged.emit(192)
        QApplication.processEvents()
        assert dialog.width() <= 1100 and dialog.height() <= 800
        assert dialog.table.isVisible() and dialog.view.isVisible()
    finally:
        close_dialog(dialog)


def test_new_region_is_not_cancelled_by_an_older_preview(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        dialog.name.setText("Changed")
        dialog.save_controls()
        dialog.preview()
        dialog.add()
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        assert dialog.draw_mode
        draw(dialog, (10, 110), (45, 135))
        assert len(dialog.regions) == 2
    finally:
        close_dialog(dialog)


def test_page_raster_must_match_before_drawing(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        old_image = dialog.last_image
        dialog.page.setValue(4)  # Landscape, unlike the currently displayed portrait page.
        dialog.preview()
        dialog.add()
        assert not dialog.draw_mode
        before = deepcopy(dialog.regions)
        draw(dialog, (10, 110), (45, 135))
        assert dialog.regions == before
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        assert dialog.last_image != old_image
        assert dialog.view.sceneRect().width() > dialog.view.sceneRect().height()
        dialog.add()
        assert dialog.draw_mode
        draw(dialog, (10, 20), (45, 35))
        assert dialog.regions[-1]["page_width_mm"] > dialog.regions[-1]["page_height_mm"]
    finally:
        close_dialog(dialog)


def test_current_sample_navigates_but_cannot_export_and_stale_sample_cannot_navigate(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        dialog.start_scan(sample=True)
        wait_until(lambda: dialog.result is not None and not dialog.host.workers)
        assert not dialog.export_button.isEnabled()
        dialog.navigate_result(dialog.model.index(2, 3))
        assert dialog.page.value() == 3
        dialog.name.setText("Changed")
        dialog.save_controls()
        wait_until(lambda: not dialog.host.workers)
        dialog.navigate_result(dialog.model.index(0, 3))
        assert dialog.page.value() == 3
    finally:
        close_dialog(dialog)


def test_entire_resize_handle_accepts_drag(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        view = dialog.view
        corner = view.mapFromScene(view.region_item.rect().bottomRight())
        point = corner+QPoint(3, 3)  # Visible handle outside the region's rectangle.
        event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(point), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.mousePressEvent(event)
        assert view.move_start is not None and view.move_start[2]
        view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(point),
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier))
    finally:
        close_dialog(dialog)


def test_edge_labels_and_theme_changes_preserve_geometry(qt_application, tmp_path):
    from styles.theme import apply_theme, get_color
    dialog = make_dialog(tmp_path)
    try:
        corner = deepcopy(dialog.regions[0])
        corner.update(name="Very_Long_Region_Name_At_The_Page_Edge", x_mm=95, y_mm=130,
                      width_mm=10, height_mm=10)
        dialog.apply_regions([dialog.regions[0], corner])
        dialog.list.setCurrentRow(1)
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        original = deepcopy(dialog.regions)
        for theme in ("light", "dark"):
            apply_theme(qt_application, theme)
            QApplication.processEvents()
            assert dialog.view.region_item.pen().color().name() == get_color("primary")
            badge = dialog.view.active_label
            point = dialog.view.mapFromScene(badge.scenePos())
            right = dialog.view.mapFromScene(dialog.view.sceneRect().bottomRight()).x()
            assert point.x()+badge.rect().width() <= right+2
            assert corner["name"] in badge.toolTip()
            assert dialog.regions == original
    finally:
        apply_theme(qt_application, "system")
        close_dialog(dialog)
