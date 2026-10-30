"""Viewport, navigation and message regressions with application fonts/styles."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest

from composition.designer.workspace import CompositionWindow
from composition.engine.assets import asset_root
from composition.template.model import SequenceSpec
from styles.components import global_style
from styles.theme import apply_theme, set_application_stylesheet
from tests.composition.test_designer_controls import cleanup


@pytest.fixture
def styled_app(qt_application):
    app = qt_application
    palette, font, style = app.palette(), app.font(), app.styleSheet()
    ids = [QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/name))
           for name in ("NotoSans-Regular.ttf", "NotoSansCJKhk-Regular.otf")]
    app.setFont(QFont("Noto Sans", 9))
    set_application_stylesheet(app, global_style())
    yield app
    set_application_stylesheet(app, style)
    app.setPalette(palette)
    app.setFont(font)
    for font_id in ids:
        QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("size", [(960, 640), (760, 580)])
def test_canvas_and_preview_controls_fit_small_windows(styled_app, theme, size):
    apply_theme(styled_app, theme)
    window = CompositionWindow()
    try:
        window.resize(*size)
        window.show()
        window.preview_timer.stop()
        window.add_element("text", "{{Seq}}")
        assert window.apply_sequences([SequenceSpec("Seq")], "generated", 50000)
        template = window.template.to_dict()
        styled_app.processEvents()
        assert window.width() == size[0], "Controls forced the window wider"
        # Keep the existing toolbar/control budget. The readable status row is
        # reserved separately; the old total budget relied on a collapsed footer.
        status = window.statusBar()
        assert status.height() >= status.fontMetrics().height() + 6
        assert window.canvas.viewport().height() >= size[1]-170-status.height()
        assert window.project_toolbar.height() <= 42
        assert not window.record_navigation.isVisible()
        for mode in (2, 0, 3, 1, 2):
            window.tabs.setCurrentIndex(mode)
            window.preview_timer.stop()
            styled_app.processEvents()
            if mode == 2:
                assert window.record_navigation.isVisible()
                window.next.click()
                assert window.record.value() >= 2
                window.last.click()
                assert window.record.value() == 50000
                window.first.click()
                assert window.record.value() == 1
                for widget in (window.record, window.record_label, window.first, window.last,
                               window.page_menu, window.preview_retry, window.generate_button):
                    assert widget.isVisible()
                    assert widget.mapTo(window, widget.rect().topRight()).x() < window.width()
                    assert widget.mapTo(window, widget.rect().topLeft()).x() >= 0
            else:
                assert not window.record_navigation.isVisible()
        assert window.template.to_dict() == template
        assert window.generate_button.isEnabled()
    finally:
        cleanup(window)


def test_long_message_stays_one_line_and_preserves_full_details(styled_app, monkeypatch):
    window = CompositionWindow()
    try:
        window.resize(960, 640)
        window.show()
        window.preview_timer.stop()
        styled_app.processEvents()
        height = window.statusBar().height()
        value = 'Record 18042: <unrenderable> font.\n' + 'Affected pages: 12, 27, 89. ' * 100
        window.message.setText(value)
        styled_app.processEvents()
        assert window.statusBar().height() == height
        assert window.message.text() == value
        assert '&lt;unrenderable&gt;' in window.message.toolTip()
        window.canvas.pointerMoved.emit(20, 30)
        assert not window.statusBar().currentMessage(), "Coordinates concealed the error message"
        opened = []
        monkeypatch.setattr(window.message, "details", lambda: opened.append(window.message.text()))
        window.message.setFocus()
        QTest.keyClick(window.message, Qt.Key.Key_Return)
        assert opened == [value]
        window.message.setText("")
        window.canvas.pointerMoved.emit(20, 30)
        assert "X 20.00 mm" in window.statusBar().currentMessage()
        window.statusBar().clearMessage()
        window.production_worker = object()
        window._busy()
        styled_app.processEvents()
        assert window.progress.isVisible() and window.cancel_button.isVisible()
        assert window.statusBar().height() <= height+12
        window.production_worker = None
        window._busy()
        assert not window.progress.isVisible() and not window.cancel_button.isVisible()
    finally:
        window.production_worker = None
        cleanup(window)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_design_has_visible_paper_tray_button_using_existing_media_action(styled_app, monkeypatch, theme):
    from composition.designer.media_dialog import MediaDialog

    apply_theme(styled_app, theme)
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    opened = []
    def configure(dialog):
        opened.append(dialog)
        dialog.enabled.setChecked(False)
        dialog.duplex.setChecked(True)
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(MediaDialog, "exec", configure)
    window = CompositionWindow()
    try:
        window.resize(960, 640)
        window.show()
        window.preview_timer.stop()
        styled_app.processEvents()
        assert hasattr(window, "paper_tray_button"), "Paper / Tray must be visible in Design"
        button = window.paper_tray_button
        assert button.isVisible() and "Paper / Tray" in button.text()
        assert button.defaultAction() is window.actions["media"]
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
        before = window.template.to_dict()
        button.click()
        assert len(opened) == 1 and window.template.media["duplex"]
        window.undo.undo()
        assert window.template.to_dict() == before
        window.tabs.setCurrentIndex(3)
        assert not button.isVisible()
        window.tabs.setCurrentIndex(1)
        assert button.isVisible()
        window.production_worker = object()
        window._update_actions()
        assert not button.isEnabled()
        button.click()
        assert len(opened) == 1
    finally:
        window.production_worker = None
        cleanup(window)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_design_owns_conditional_inserter_setup_and_production_is_summary(styled_app, monkeypatch, theme):
    from PyQt6.QtWidgets import QComboBox

    from composition.engine.barcode_profiles import BarcodeProfile
    from composition.template.model import Element, Template
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda _: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda _: None)
    window = CompositionWindow()
    try:
        apply_theme(styled_app, theme)
        set_application_stylesheet(styled_app, global_style())
        window.resize(960, 640)
        window.show()
        styled_app.processEvents()
        assert hasattr(window, "design_inserter_button")
        assert not window.design_inserter_button.isVisible()
        model = Template(record_mode="generated", generated_count=3)
        model.elements.append(Element(type="qr", value="123", width_mm=40, height_mm=40))
        window._apply_template(model.to_dict())
        assert not window.design_inserter_button.isVisible()
        model.elements[0] = Element(type="i25", width_mm=100, height_mm=14, barcode_profile=BarcodeProfile.inserter().to_dict())
        window._apply_template(model.to_dict())
        assert window.design_inserter_button.isVisible()
        assert "Apply barcode to required fronts" in window.design_inserter_button.menu().actions()[0].text()
        before = window.template.to_dict()
        window.tabs.setCurrentIndex(3)
        assert not window.design_inserter_button.isVisible()
        assert not window.production_page.findChildren(QComboBox)
        assert "Printing: Simplex" in window.production_plan.text()
        window.production_media_button.click()
        assert window.tabs.currentIndex() == 1 and window.design_inserter_button.isVisible()
        assert window.template.to_dict() == before
        from composition.designer.production_review import template_pane
        template_pane(window)  # Keep the fifth Review tab in the layout check.
        styled_app.processEvents()
        assert window.width() == 960
        for control in (window.paper_tray_button, window.design_printing, window.design_inserter_button):
            assert control.isVisible()
            assert window.rect().contains(control.mapTo(window, control.rect().bottomRight()))
        import os
        from pathlib import Path
        directory = os.environ.get("PDFDOC_DESIGN_QA_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            window.canvas.select_ids([window.template.elements[0].id])
            styled_app.processEvents()
            window.grab().save(str(Path(directory) / f"design-settings-{theme}.png"))
    finally:
        cleanup(window)
