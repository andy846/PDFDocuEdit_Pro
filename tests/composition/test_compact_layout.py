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
from styles.theme import apply_theme
from tests.composition.test_designer_controls import cleanup


@pytest.fixture
def styled_app(qt_application):
    app = qt_application
    palette, font, style = app.palette(), app.font(), app.styleSheet()
    ids = [QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/name))
           for name in ("NotoSans-Regular.ttf", "NotoSansCJKhk-Regular.otf")]
    app.setFont(QFont("Noto Sans", 9))
    app.setStyleSheet(global_style())
    yield app
    app.setStyleSheet(style)
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
