from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from core.viewer import PDFViewer
from styles.theme import apply_theme
from styles.tokens import D


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("enabled", [False, True])
def test_main_entry_feature_flag_and_shared_action(app, monkeypatch, enabled):
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION", "1" if enabled else "0")
    opened = []
    monkeypatch.setattr(PDFViewer, "_open_composition", lambda self: opened.append("designer"))
    apply_theme(app, "light")
    window = PDFViewer()
    try:
        window.show()
        QApplication.processEvents()
        button = window.command_bar._designer
        assert button.isHidden() is not enabled
        if enabled:
            assert window.command_bar.mode_switcher.buttons["pdf"].isChecked()
            assert button.accessibleName() == "Document Designer mode"
            for integrated in (False, True):
                window.command_bar.set_integrated_chrome(integrated)
                for width in (640, 960, 1280):
                    window.resize(width, 720)
                    QApplication.processEvents()
                    assert not button.isHidden() and button.isEnabled()
                    assert window.command_bar.width() == width
                    assert window.command_bar.height() == D.COMMAND_H
                    assert button.geometry().right() < window.command_bar.width()
                    assert window.command_bar._more.geometry().right() < window.command_bar.width()
                    if width >= 760:
                        assert button.text() == "Document Designer"
            window.command_bar.set_document_available(False)
            button.click()
            window.command_bar.set_document_available(True)
            button.click()
            assert opened == ["designer", "designer"]
        else:
            assert window.command_bar._designer_action is None
    finally:
        window.close()
        window.deleteLater()
        QApplication.processEvents()
