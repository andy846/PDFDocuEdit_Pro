"""Compact Production layout preserves existing controls and production intent."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QBoxLayout

from composition.designer.workspace import CompositionWindow
from composition.engine.barcode_profiles import BarcodeProfile
from composition.media.model import default_media
from composition.template.model import Element, PageSpec, Template
from styles.components import global_style
from styles.theme import apply_theme, set_application_stylesheet
from tests.composition.test_workspace import close_window


@pytest.fixture
def window(qt_application, monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    app = qt_application
    palette, style = app.palette(), app.styleSheet()
    value = CompositionWindow()
    pages = [PageSpec() for _ in range(6)]
    for page in pages[::2]:
        page.elements = [Element(type="i25", width_mm=100, height_mm=14,
                                  barcode_profile=BarcodeProfile.inserter().to_dict())]
    model = Template(pages=pages, record_mode="generated", generated_count=398)
    model.media = default_media()
    model.media.update(duplex=True, mode="template", assignments={
        page.id: "LH_" + "ABC"[i // 2] for i, page in enumerate(pages)})
    value._apply_template(model.to_dict())
    value.tabs.setCurrentIndex(3)
    yield value
    close_window(value)
    app.setPalette(palette)
    set_application_stylesheet(app, style)


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [1280, 960, 760])
def test_compact_cards_and_fixed_actions(window, qt_application, theme, width):
    apply_theme(qt_application, theme)
    set_application_stylesheet(qt_application, global_style())
    before = window.template.to_dict()
    window.resize(width, 640)
    window.show()
    qt_application.processEvents()
    console = window.production_console
    assert console.metrics["records"].text() == "398"
    assert console.metrics["pages"].text() == "2,388"
    assert console.metrics["sheets"].text() == "1,194"
    assert console.stocks.rowCount() == 3
    assert all(console.stocks.item(i, 1).text() == "398" for i in range(3))
    assert "Duplex" in console.printing.text()
    assert console.columns.direction() == (QBoxLayout.Direction.LeftToRight if width >= 960
                                            else QBoxLayout.Direction.TopToBottom)
    assert not console.log_toggle.isChecked()
    assert not window.production_summary.isVisible()
    assert not console.scroll.isAncestorOf(window.review_production_button)
    assert not console.scroll.isAncestorOf(window.open_output_button)
    assert console.scroll.horizontalScrollBar().maximum() == 0
    for control in (window.review_production_button, window.open_output_button, window.report_button):
        assert control.isVisible()
        assert window.rect().contains(control.mapTo(window, control.rect().bottomRight()))
    assert window.template.to_dict() == before


def test_log_keeps_report_and_expands_on_failure(window, qt_application):
    window.show()
    qt_application.processEvents()
    console = window.production_console
    window.production_summary.setPlainText("A complete report remains available.")
    QTest.mouseClick(console.log_toggle, Qt.MouseButton.LeftButton)
    assert window.production_summary.isVisible()
    QTest.mouseClick(console.log_toggle, Qt.MouseButton.LeftButton)
    assert not window.production_summary.isVisible()
    console.failed("PostScript validation failed")
    assert console.log_toggle.isChecked() and window.production_summary.isVisible()
    assert "PostScript validation failed" in window.production_summary.toPlainText()
    assert "A complete report" in window.production_summary.toPlainText()
    assert not window.open_output_button.isEnabled()


def test_invalid_plan_is_visible_and_cannot_display_old_counts(window, qt_application):
    value = window.template.to_dict()
    value["media"]["assignments"].pop(value["pages"][-1]["id"])
    window._apply_template(value)
    window.show()
    qt_application.processEvents()
    console = window.production_console
    assert console.metrics["sheets"].text() == "Not available"
    assert "no assigned Stock" in console.plan_error.text()
    assert console.stocks.rowCount() == 0
    assert window.production_media_button.isEnabled()


def test_review_entry_and_output_controls_retain_original_connections(qt_application, monkeypatch):
    calls = []
    monkeypatch.setattr(CompositionWindow, "generate_pdf", lambda self: calls.append("review"))
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    window = CompositionWindow()
    try:
        assert not window.review_production_button.isEnabled()
        window._apply_template(Template(record_mode="generated", generated_count=1).to_dict())
        window.tabs.setCurrentIndex(3)
        window.show()
        qt_application.processEvents()
        assert window.review_production_button.isEnabled()
        window.review_production_button.click()
        assert calls == ["review"]
        window.production_media_button.click()
        assert window.tabs.currentIndex() == 1
    finally:
        close_window(window)


def test_narrow_keyboard_focus_reveals_settings_without_hiding_footer(window, qt_application):
    window.resize(760, 580)
    window.show()
    qt_application.processEvents()
    console = window.production_console
    window.output_name_edit.edit.setFocus()
    qt_application.processEvents()
    for control in (window.output_name_edit.edit, window.output_limits, window.auto_repair,
                    window.production_media_button):
        assert qt_application.focusWidget() is control
        origin = control.mapTo(console.scroll.viewport(), control.rect().topLeft())
        end = control.mapTo(console.scroll.viewport(), control.rect().bottomRight())
        assert console.scroll.viewport().rect().contains(origin)
        assert console.scroll.viewport().rect().contains(end)
        QTest.keyClick(control, Qt.Key.Key_Tab)
        qt_application.processEvents()
    assert qt_application.focusWidget() is window.review_production_button
    assert window.review_production_button.isVisible()


def test_long_filename_does_not_widen_console(window, qt_application):
    window.resize(960, 640)
    window.show()
    window.output_name_edit.edit.setText("production_" + "long_name_" * 30 + ".pdf")
    qt_application.processEvents()
    assert window.width() == 960
    assert window.production_console.scroll.horizontalScrollBar().maximum() == 0
    assert window.review_production_button.isVisible()


def test_long_worker_failure_keeps_fixed_actions_reachable(window, qt_application):
    window.resize(760, 580)
    window.show()
    qt_application.processEvents()
    console = window.production_console
    console.started()
    message = "Worker failed\n" + "Detailed worker diagnostics with a long resource path.\n" * 30
    console.failed(message)
    qt_application.processEvents()
    assert window.height() == 580
    assert console.failure.height() < console.fontMetrics().lineSpacing() * 4
    assert window.rect().contains(window.review_production_button.mapTo(window, window.review_production_button.rect().bottomRight()))
    assert "running" not in console.log_toggle.text().lower()
    assert "failed" in console.log_toggle.text().lower()
    assert message in window.production_summary.toPlainText()
    assert console.failure.toolTip() == message


def test_stock_rows_fit_after_theme_change(window, qt_application):
    window.resize(960, 640)
    apply_theme(qt_application, "dark")
    set_application_stylesheet(qt_application, global_style())
    window.show()
    qt_application.processEvents()
    qt_application.processEvents()
    table = window.production_console.stocks
    assert table.rowCount() == 3
    assert table.viewport().rect().contains(table.visualItemRect(table.item(2, 0)).bottomRight())


def test_unloaded_data_does_not_present_missing_totals_as_zero(qt_application, monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    window = CompositionWindow()
    try:
        assert all(value.text() == "Not available" for value in window.production_console.metrics.values())
        assert "Import data" in window.production_console.source_note.text()
        assert not window.review_production_button.isEnabled()
    finally:
        close_window(window)
