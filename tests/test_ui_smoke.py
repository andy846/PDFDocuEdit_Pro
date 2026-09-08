from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest
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

    window.apply_theme("dark")
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
    draw = window._draw_print_page

    def guarded_draw(*args):
        assert window._printing
        assert all(not action.isEnabled() for action in window._registered_shortcut_actions)
        return draw(*args)

    with monkeypatch.context() as patch:
        patch.setattr(window, "_draw_print_page", guarded_draw)
        with fitz.open(source) as document:
            window._configure_print_layout(printer, document.load_page(0), details)
            window._paint_documents(printer, [(document, [0, 1], source.name)], details)
    app.processEvents()
    with fitz.open(output) as printed:
        assert printed.page_count == 2
        assert all(page.get_images() for page in printed)
    from threading import Event

    cancelled = Event()
    cancelled_output = tmp_path / "cancelled.pdf"
    printer.setOutputFileName(str(cancelled_output))
    with fitz.open(source) as document:
        window._paint_documents(
            printer, [(document, [0, 1], source.name)], details,
            progress=lambda *_: cancelled.set(), should_cancel=cancelled.is_set,
        )
    with fitz.open(cancelled_output) as printed:
        assert printed.page_count == 1
    assert window.isEnabled() and not window._printing
    window.close()


def test_print_guard_restores_state_on_failure_and_cancel(tmp_path, monkeypatch):
    import pytest
    from PyQt6.QtGui import QCloseEvent

    app = QApplication.instance() or QApplication(["print-guard-test"])
    monkeypatch.setattr(viewer_module, "SettingsManager",
                        lambda: SettingsManager(tmp_path / "settings.json"))
    window = viewer_module.PDFViewer()
    enabled = window._action("enabled", None, lambda: None)
    disabled = window._action("disabled", None, lambda: None)
    disabled.setEnabled(False)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            with window._print_operation():
                assert not enabled.isEnabled()
                event = QCloseEvent()
                window.closeEvent(event)
                assert not event.isAccepted()
                assert window.open_in_new_tab("missing.pdf") is None
                raise RuntimeError("injected")
        assert window.isEnabled()
        assert enabled.isEnabled()
        assert not disabled.isEnabled()
        assert not window._printing
        with window._print_operation():
            pass  # cooperative cancellation returns through the same finally
        assert window.isEnabled() and not window._printing
    finally:
        window.close()
        app.processEvents()


def test_background_print_cancel_restores_ui_and_keeps_dialog_alive(tmp_path, monkeypatch):
    import time
    from threading import Event

    from PyQt6.QtTest import QTest

    import ui.print_controller as controller_module
    from dialogs.batch_print_dialog import BatchPrintDialog

    app = QApplication.instance() or QApplication(["background-print-ui"])
    monkeypatch.setattr(viewer_module, "SettingsManager",
                        lambda: SettingsManager(tmp_path / "print-settings.json"))
    window = viewer_module.PDFViewer()
    dialog = BatchPrintDialog(window)
    source = tmp_path / "cancel-source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(source)
    entered, release = Event(), Event()
    original = controller_module.prepare_print_job

    def slow_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(controller_module, "prepare_print_job", slow_prepare)
    states = [action.isEnabled() for action in window._registered_shortcut_actions]
    window._run_batch_print(dialog, {"paths": [str(source)]})
    try:
        deadline = time.monotonic() + 5
        while not entered.is_set() and time.monotonic() < deadline:
            QTest.qWait(5)
        assert entered.is_set()
        assert window._printing
        assert not window.workspace.isEnabled()
        assert not window.command_bar.isEnabled()
        assert window.task_bar._cancel.isEnabled()
        assert window.open_in_new_tab(str(source)) is None
        dialog.cancel_button.click()
        assert window._print_controller._cancel.is_set()
        dialog.close()  # hiding/cancelling must not destroy progress signal targets
        release.set()
        while window._printing and time.monotonic() < deadline:
            QTest.qWait(5)
        assert not window._printing
        assert not dialog._printing
        assert window.workspace.isEnabled() and window.command_bar.isEnabled()
        assert [action.isEnabled() for action in window._registered_shortcut_actions] == states
        assert window.task_bar.isHidden()
    finally:
        release.set()
        window._cancel_tasks()
        deadline = time.monotonic() + 5
        while window._printing and time.monotonic() < deadline:
            QTest.qWait(5)
        dialog.close()
        window.close()
        app.processEvents()


def test_page_transaction_undo_redo_and_rollback_rebind(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication(["transaction-test"])
    monkeypatch.setattr(viewer_module, "SettingsManager",
                        lambda: SettingsManager(tmp_path / "transaction-settings.json"))
    window = viewer_module.PDFViewer()
    window.load_file(str(make_pdf(tmp_path / "transaction.pdf")))
    session = window._session
    session.set_split(True)
    try:
        window._rotate_current(90)
        assert session.undo_stack.undo_descriptions() == ["Rotate Page"]
        assert session.engine.document[0].rotation == 90
        window._undo()
        assert session.engine.document[0].rotation == 0
        assert not session.engine.is_modified
        window._redo()
        assert session.engine.document[0].rotation == 90
        assert session.engine.is_modified
        # The replacement engine must retain the owning session's recorder.
        window._rotate_current(90)
        assert session.undo_stack.undo_count == 2
        window._undo()
        assert session.undo_stack.redo_count == 1
        before = session.engine.document
        rotate = fitz.Page.set_rotation
        def fail(page, amount):
            rotate(page, amount)
            raise RuntimeError("injected after mutation")
        with monkeypatch.context() as patch:
            patch.setattr(fitz.Page, "set_rotation", fail)
            window._rotate_current(90)
        assert session.engine.document is not before
        assert session.engine.document[0].rotation == 90
        assert session.undo_stack.undo_count == 1
        assert session.undo_stack.redo_count == 1
        assert session.canvas._doc is session.engine.document
        assert session.split_canvas._doc is session.engine.document
        app.processEvents()
        window._redo()
        assert session.engine.document[0].rotation == 180
    finally:
        # Avoid a save prompt for this intentionally unsaved test document.
        session.engine._is_modified = False
        window.close_document()
        window.close()


@pytest.mark.parametrize("direction", ["undo", "redo"])
@pytest.mark.parametrize("failure", ["write", "missing", "corrupt", "open", "display"])
def test_history_failure_keeps_live_document_and_all_history(tmp_path, monkeypatch, direction, failure):
    app = QApplication.instance() or QApplication(["history-failure-test"])
    monkeypatch.setattr(viewer_module, "SettingsManager",
                        lambda: SettingsManager(tmp_path / "history-settings.json"))
    window = viewer_module.PDFViewer()
    errors = []
    monkeypatch.setattr(window, "_error", lambda *args: errors.append(args))
    window.load_file(str(make_pdf(tmp_path / "history.pdf")))
    session = window._session
    session.set_split(True)
    try:
        window._rotate_current(90)
        window._rotate_current(90)
        assert window._undo()
        stack = session.undo_stack
        previous = session.engine
        before = (stack.undo_descriptions(), stack.redo_descriptions(),
                  previous.is_modified, previous.revision, previous.original_path)
        target = (stack._undo if direction == "undo" else stack._redo)[-1].path
        data = target.read_bytes()
        with monkeypatch.context() as patch:
            if failure == "write":
                write = Path.write_bytes
                def fail_write(path, content):
                    if path.name.startswith(".history-"):
                        raise OSError("disk full")
                    return write(path, content)
                patch.setattr(Path, "write_bytes", fail_write)
            elif failure == "missing":
                target.unlink()
            elif failure == "corrupt":
                target.write_bytes(b"broken PDF")
            elif failure == "open":
                def fail_open(*args, **kwargs):
                    raise OSError("cannot open snapshot")
                patch.setattr(viewer_module.PdfEngine, "open", fail_open)
            else:
                complete = window._complete_pdf_open
                def fail_display(*args, **kwargs):
                    complete(*args, **kwargs)
                    raise RuntimeError("display failed after engine replacement")
                patch.setattr(window, "_complete_pdf_open", fail_display)
            getattr(window, f"_{direction}_to")(3)
        assert len(errors) == 1  # multi-step history stops at the first failure
        assert session.engine is previous
        assert previous.document[0].rotation == 90
        assert before == (stack.undo_descriptions(), stack.redo_descriptions(),
                          previous.is_modified, previous.revision, previous.original_path)
        assert session.canvas._doc is previous.document
        assert session.split_canvas._doc is previous.document
        if failure != "missing":
            assert target.exists()
        target.write_bytes(data)
        assert getattr(window, f"_{direction}")()
        assert session.engine.document[0].rotation == (0 if direction == "undo" else 180)
        app.processEvents()
    finally:
        session.engine._is_modified = False
        window.close_document()
        window.close()
