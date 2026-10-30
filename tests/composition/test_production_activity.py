"""Production status stays visible even when status-bar tips obscure normal labels."""

from types import SimpleNamespace

import pytest

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from styles.components import global_style
from styles.theme import apply_theme, set_application_stylesheet
from tests.composition.test_compact_layout import styled_app  # noqa: F401
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(autouse=True)
def quiet_workers(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)


@pytest.mark.parametrize("overlay", [False, True])
@pytest.mark.parametrize("size", [(960, 640), (760, 580)])
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.usefixtures("styled_app")
def test_live_phase_is_visible_and_unknown_progress_is_indeterminate(qt_application, overlay, size, theme):
    apply_theme(qt_application, theme)
    set_application_stylesheet(qt_application, global_style())
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        assert hasattr(window, "production_activity"), "Production lacks a visible live activity panel"
        window.resize(*size)
        window.show()
        if overlay:
            window.tabs.setCurrentIndex(1)
            window.active_worker = SimpleNamespace(task="overlay_generate")
            update = window.show_progress
        else:
            window.tabs.setCurrentIndex(3)
            window.production_worker = SimpleNamespace(task="generate")
            update = window._progress
        window.production_activity.set_running(True)
        update(0, 0, "PostScript conversion · waiting for page progress")
        window.statusBar().showMessage("Menu status tip")
        qt_application.processEvents()
        panel = window.production_activity
        assert panel.isVisible() and panel.label.isVisible()
        assert "PostScript" in panel.label.text()
        assert panel.bar.minimum() == panel.bar.maximum() == 0
        assert not panel.bar.isTextVisible()
        assert panel.mapTo(window, panel.rect().topLeft()).y() >= 0
        assert panel.mapTo(window, panel.rect().bottomRight()).y() < window.height()
        update(12, 2388, "PostScript conversion · processing page 13")
        assert panel.bar.value() == 12 and panel.bar.maximum() == 2388
        assert "13" in panel.label.text()
        assert "Job elapsed" in panel.detail.text()
        if not overlay:
            scroll = window.production_console.scroll
            top = panel.mapTo(window, panel.rect().topLeft())
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            qt_application.processEvents()
            assert panel.mapTo(window, panel.rect().topLeft()) == top
    finally:
        window.production_worker = None
        if overlay:
            window.active_worker = None
        (finish if overlay else close_window)(window)


def test_activity_elapsed_silence_cancel_and_finish(qt_application, monkeypatch):
    import importlib.util

    assert importlib.util.find_spec("composition.designer.production_activity"), "Live production activity is missing"
    from composition.designer import production_activity as module

    clock = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    cancelled = []
    panel = module.ProductionActivity(lambda: cancelled.append(True))
    try:
        panel.set_running(True)
        panel.update_progress(0, 0, "Preparing PostScript")
        clock[0] += 65
        panel.refresh()
        assert "01:05" in panel.detail.text()
        assert "No progress update" in panel.detail.text()
        panel.cancel_button.click()
        assert cancelled == [True] and not panel.cancel_button.isEnabled()
        panel.update_progress(1, 5, "Late queued event")
        assert "Cancelling" in panel.label.text()
        panel.set_running(False)
        assert not panel.timer.isActive() and panel.isHidden()
        panel.set_running(True)
        assert panel.cancel_button.isEnabled() and panel.bar.maximum() == 0
    finally:
        panel.close()
