from __future__ import annotations

import os
from pathlib import Path

import fitz
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from core.settings import SettingsManager
from styles.tokens import D


def make_pdf(path: Path) -> Path:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 96), "PyQt6 smoke test")
        document.save(path)
    return path


def test_main_window_constructs_and_loads_document(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-test"])
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(settings_path))

    window = viewer_module.PDFViewer()
    assert not window.engine.is_loaded()
    assert not window.side_panel._buttons["insert"].isEnabled()
    assert window.side_panel._buttons["merge"].isEnabled()
    assert not window.bottom_bar._zoom_in.isEnabled()
    assert window.side_panel.width() in {52, 272, 100}
    assert not window.side_panel._buttons["insert"].icon().isNull()
    window.side_panel._search.setText("encrypt")
    app.processEvents()
    assert not window.side_panel._buttons["encrypt"].isHidden()
    assert window.side_panel._buttons["merge"].isHidden()
    window.side_panel._search.clear()

    source = make_pdf(tmp_path / "smoke.pdf")
    window.load_file(str(source))
    app.processEvents()
    assert window.engine.page_count == 1
    assert "smoke.pdf" in window.windowTitle()
    assert window.command_bar._title.text() == "PDFDocuEdit Pro"
    assert "smoke.pdf" in window.command_bar._title.toolTip()
    assert window.workspace.canvas.current_page == 0
    assert not window.task_bar.isVisible()
    assert window.side_panel._buttons["insert"].isEnabled()
    assert not window.side_panel._buttons["decrypt"].isEnabled()
    assert not window.bottom_bar._prev.isEnabled()
    assert not window.bottom_bar._next.isEnabled()
    assert window.bottom_bar._zoom_in.isEnabled()

    window._apply_theme("dark")
    window.side_panel.set_collapsed(True, animate=False)
    app.processEvents()
    assert window.side_panel.is_collapsed()
    assert window.side_panel.width() == 52
    assert window.splitter.sizes()[0] <= 56
    assert window.side_panel._buttons["insert"].text() == ""
    window.close_document()
    assert not window.side_panel._buttons["insert"].isEnabled()
    assert not window.bottom_bar._zoom_in.isEnabled()
    window.close()


def test_windows_integrated_title_bar_keeps_complete_menu(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-chrome-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "chrome-settings.json"),
    )
    window = viewer_module.PDFViewer()
    window.resize(1280, 760)
    window.show()
    app.processEvents()

    integrated = os.name == "nt"
    assert window._integrated_chrome is integrated
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) is integrated
    assert bool(window.command_bar.property("integratedTitleBar")) is integrated
    assert window.command_bar._window_divider.isHidden() is not integrated
    assert window.command_bar._window_controls.isHidden() is not integrated
    if integrated:
        assert window.menuBar().isHidden()
        compact_menu = window.command_bar._main_menu_button.menu()
        assert compact_menu is not None
        assert len(compact_menu.actions()) == len(window.menuBar().actions())
        assert window.command_bar._window_close.property("closeButton") is True
        assert window._resize_handles is not None
        assert len(window._resize_handles.handles) == 8
        assert window._resize_handles.handles["top"].height() == 6
        window._toggle_maximize_restore()
        app.processEvents()
        assert window.isMaximized()
        assert window.command_bar._window_maximize.toolTip() == "Restore"
        assert all(handle.isHidden() for handle in window._resize_handles.handles.values())
        window._toggle_maximize_restore()
        app.processEvents()
        assert not window.isMaximized()
    window.close()


def test_sidebar_sections_collapse_and_expand_without_animation() -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-sidebar-test"])
    panel = viewer_module.SidePanel(False, False)
    app.processEvents()
    section = panel._sections[0]
    section.header.setChecked(False)
    section._header_clicked(False)
    app.processEvents()
    assert section.body.isHidden()
    section.header.setChecked(True)
    section._header_clicked(True)
    app.processEvents()
    assert not section.body.isHidden()
    assert section.body.maximumHeight() > 0
    panel.close()


def test_motion_states_and_reduced_motion_behaviour(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-motion-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "motion-settings.json"),
    )
    window = viewer_module.PDFViewer()
    window._set_motion_enabled(False)

    button = window.side_panel._buttons["merge"]
    original_size = button.iconSize()
    app.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert button.property("hovered") is True
    assert button.iconSize() == original_size
    app.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert button.property("hovered") is False

    source = make_pdf(tmp_path / "motion.pdf")
    window.load_file(str(source))
    assert window.context_panel.show_tool("rotate", "Rotate Pages")
    assert window.context_panel.panelWidth == D.CONTEXT_W
    window._hide_context()
    assert window.context_panel.panelWidth == 0
    assert window.context_panel.isHidden()

    window.info_bar.show_message("Motion test", timeout=0)
    assert not window.info_bar.isHidden()
    assert window.info_bar.maximumHeight() >= 42
    window.info_bar.hide_bar()
    assert window.info_bar.isHidden()
    window.close()


def test_print_renderer_creates_complete_pdf_job(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-print-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "print-settings.json"),
    )
    source = tmp_path / "print-source.pdf"
    with fitz.open() as document:
        for label in ("First print page", "Second print page"):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), label)
        document.save(source)
    output = tmp_path / "printed.pdf"
    details = {
        "printer": "",
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "pages": [0, 1],
        "paper": "A4",
        "orientation": 1,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output))
    printer.setResolution(150)
    window = viewer_module.PDFViewer()
    with fitz.open(source) as document:
        window._configure_print_layout(printer, document.load_page(0), details)
        window._paint_documents(printer, [(document, [0, 1], source.name)], details)
    app.processEvents()
    with fitz.open(output) as printed:
        assert printed.page_count == 2
        assert all(page.get_images() for page in printed)
    window.close()
