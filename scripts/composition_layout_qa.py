"""Small native/frozen viewport acceptance with the real application style."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication


def verify_layout(window, output, *, outer=None):
    from scripts.composition_smoke import check
    from styles.components import global_style
    from styles.theme import apply_theme

    app = QApplication.instance()
    palette, style = app.palette(), app.styleSheet()
    outer = outer or window
    original_size = outer.size()
    result = []
    for theme in ("dark", "light"):
        apply_theme(app, theme)
        app.setStyleSheet(global_style())
        window.tabs.setCurrentIndex(1)
        outer.resize(960, 640)
        window._adjust_inspector()
        app.processEvents()
        check(window.canvas.viewport().height() >= (350 if window.embedded else 450), "Designer canvas lost vertical space")
        check(window.project_toolbar.height() <= 42, "Toolbar is too tall")
        metrics = {"theme":theme, "size":[window.width(),window.height()],
                   "canvas_height":window.canvas.viewport().height(),
                   "toolbar_height":window.project_toolbar.height(),
                   "status_height":window.statusBar().height()}
        message = 'Layout check: ' + 'Full production details. ' * 100 + '\nSecond line'
        window.message.setText(message)
        app.processEvents()
        check(window.statusBar().height() == metrics["status_height"], "Long message enlarged the footer")
        check(window.message.text() == message, "Status message details were lost")
        window.message.setText("")
        window.grab().save(str(output/f"compact-{theme}-960.png"))
        window.tabs.setCurrentIndex(2)
        outer.resize(760,580)
        app.processEvents()
        check(outer.width() == 760 and window.width() <= 760, "Preview controls enlarged the window")
        for widget in (window.record, window.first, window.last, window.preview_retry,
                       window.page_menu, window.generate_button):
            check(widget.isVisible(), "Important Designer control became hidden")
            check(widget.mapTo(window,widget.rect().topRight()).x() < 760,
                  "Important Designer control was clipped")
        window.grab().save(str(output/f"compact-{theme}-preview-760.png"))
        result.append(metrics)
    app.setStyleSheet(style)
    app.setPalette(palette)
    window.tabs.setCurrentIndex(1)
    outer.resize(original_size)
    return result
