"""Legacy TOOLS port tests: menus, sidebar layout, quick toolbar, rotate box,
zoom slider, file info tooltip, status messages and shortcuts."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit

import core.viewer as viewer_module
from core.settings import SettingsManager
from ui.bottom_bar import BottomBar
from ui.side_panel import SidePanel


def make_pdf(path: Path, pages: int = 2) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 96), f"Searchable page {index + 1}")
        document.save(path)
    return path


_app_instance: QApplication | None = None


def _app() -> QApplication:
    """Single QApplication kept alive for the whole module (PyQt6 destroys it
    when the last Python reference is dropped)."""
    global _app_instance
    if _app_instance is None:
        _app_instance = QApplication.instance() or QApplication(["pdfdocuedit-tools-test"])
    return _app_instance


def _window(tmp_path: Path, monkeypatch):
    _app()
    monkeypatch.setattr(
        viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json")
    )
    return viewer_module.PDFViewer()


def _messages(window) -> list[str]:
    collected: list[str] = []
    window.info_bar.show_message = lambda msg, kind="", duration=0: collected.append(msg)
    return collected


def _allow_discard(monkeypatch) -> None:
    """Answer every unsaved-changes prompt with Discard (offscreen has no user)."""
    monkeypatch.setattr(
        viewer_module.QMessageBox,
        "question",
        lambda *args, **kwargs: viewer_module.QMessageBox.StandardButton.Discard,
    )


# --- P1: menus (G3/G9) ---------------------------------------------------

def test_file_menu_has_legacy_encrypt_decrypt_and_postscript(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    menus = {action.text(): action for action in window.menuBar().actions()}
    file_menu = menus.get("&File")
    assert file_menu is not None and file_menu.menu() is not None
    texts = [action.text() for action in file_menu.menu().actions() if not action.isSeparator()]
    for label in ("Open PostScript…", "Encrypt PDF…", "Decrypt PDF…", "Print…"):
        assert label in texts
    assert texts.index("Encrypt PDF…") < texts.index("Print…")
    assert texts.index("Decrypt PDF…") < texts.index("Print…")
    assert texts.index("Open PostScript…") < texts.index("Save")
    window.close()


def test_encrypt_decrypt_actions_follow_document_state(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    window._set_document_available(False)
    assert not window.encrypt_action.isEnabled()
    assert not window.decrypt_action.isEnabled()

    source = make_pdf(tmp_path / "plain.pdf")
    window.load_file(str(source))
    assert window.encrypt_action.isEnabled()
    assert not window.decrypt_action.isEnabled()  # not encrypted
    window.close()


def test_open_postscript_uses_ps_filter_and_loads(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    loaded: list[str] = []
    monkeypatch.setattr(viewer_module.QFileDialog, "getOpenFileName", lambda *a, **k: ("/tmp/x.ps", "PostScript (*.ps *.eps)"))
    monkeypatch.setattr(window, "load_file", lambda path: loaded.append(path))
    window._open_postscript()
    assert loaded == ["/tmp/x.ps"]
    window.close()


def test_print_pdf_confirms_system_dialog_and_names_job(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog

    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "printme.pdf")
    window.load_file(str(source))
    details = {
        "printer": "",
        "pages": [0, 1],
        "copies": 2,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "A4",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "confirm_system_dialog": True,
    }

    class FakeOptions:
        def exec(self):
            return QDialog.DialogCode.Accepted

    fake = FakeOptions()
    fake.details = details
    monkeypatch.setattr(viewer_module, "PrintOptionsDialog", lambda *a, **k: fake)
    captured: dict[str, object] = {}

    class FakeNativeDialog:
        def __init__(self, printer, parent):
            captured["printer"] = printer

        def setWindowTitle(self, title):
            captured["title"] = title

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(viewer_module, "QPrintDialog", FakeNativeDialog)
    painted: list = []
    monkeypatch.setattr(
        window, "_paint_documents", lambda printer, docs, details, **kwargs: painted.append(docs)
    )
    window.print_pdf()
    assert captured["title"] == "System Print"
    assert captured["printer"].docName() == "printme.pdf"
    assert painted and painted[0][0][2] == "printme.pdf"
    window.close()


def test_print_pdf_prints_directly_without_system_dialog(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog

    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "direct.pdf")
    window.load_file(str(source))
    details = {
        "printer": "",
        "pages": [0],
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "A4",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "confirm_system_dialog": False,
    }

    class FakeOptions:
        def exec(self):
            return QDialog.DialogCode.Accepted

    fake = FakeOptions()
    fake.details = details
    monkeypatch.setattr(viewer_module, "PrintOptionsDialog", lambda *a, **k: fake)

    class ExplodingNativeDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("the system dialog must not open for direct printing")

    monkeypatch.setattr(viewer_module, "QPrintDialog", ExplodingNativeDialog)
    painted: list = []
    monkeypatch.setattr(
        window, "_paint_documents", lambda printer, docs, details, **kwargs: painted.append(docs)
    )
    window.print_pdf()
    assert painted and painted[0][0][2] == "direct.pdf"
    window.close()


def test_paint_documents_writes_pages_and_supports_cancel(tmp_path, monkeypatch):
    from PyQt6.QtPrintSupport import QPrinter

    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "a.pdf", pages=3)
    details = {
        "printer": "",
        "pages": [],
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "A4",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    output = tmp_path / "paint.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output))
    log: list[str] = []
    progress: list[tuple[int, int, int]] = []
    with fitz.open(source) as document:
        window._paint_documents(
            printer,
            [(document, [0, 1, 2], "a.pdf")],
            details,
            log=log.append,
            progress=lambda i, p, n: progress.append((i, p, n)),
        )
    assert log[0].startswith("Printing a.pdf")
    assert progress == [(0, 0, 3), (0, 1, 3), (0, 2, 3)]
    with fitz.open(output) as result:
        assert result.page_count == 3

    # Cancelling after the first page stops the job mid-document.
    output2 = tmp_path / "paint2.pdf"
    printer2 = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer2.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer2.setOutputFileName(str(output2))
    drawn: list[int] = []

    def cancelled():
        return len(drawn) >= 1

    with fitz.open(source) as document:
        window._paint_documents(
            printer2,
            [(document, [0, 1, 2], "a.pdf")],
            details,
            progress=lambda i, p, n: drawn.append(p),
            should_cancel=cancelled,
        )
    with fitz.open(output2) as result:
        assert result.page_count == 1

    # Automatic orientation follows the job's first page. Qt applies one
    # layout per job, which is why the batch prints one job per file.
    mixed = tmp_path / "mixed.pdf"
    with fitz.open() as document:
        document.new_page(width=842, height=595)  # landscape A4
        document.save(mixed)
    output3 = tmp_path / "paint3.pdf"
    printer3 = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer3.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer3.setOutputFileName(str(output3))
    details3 = dict(details)
    details3["paper"] = "PDF page size"
    with fitz.open(mixed) as landscape_doc:
        window._configure_print_layout(printer3, landscape_doc.load_page(0), details3)
        window._paint_documents(
            printer3,
            [(landscape_doc, [0], "mixed.pdf")],
            details3,
        )
    with fitz.open(output3) as result:
        assert result.page_count == 1
        assert result[0].rect.width > result[0].rect.height
    window.close()


def test_batch_print_skips_unreadable_files(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog

    window = _window(tmp_path, monkeypatch)
    good1 = make_pdf(tmp_path / "good1.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    good2 = make_pdf(tmp_path / "good2.pdf")

    class FakeDialog:
        def __init__(self):
            self.logs: list[str] = []
            self.status: dict[str, str] = {}
            self.cancelled = False

        def set_printing(self, value):
            pass

        def log_message(self, message):
            self.logs.append(message)

        def mark_file_error(self, path):
            self.status[path] = "Error"

        def set_file_status(self, path, text):
            self.status[path] = text

        def mark_file_printed(self, path):
            self.status[path] = "Done"

        def mark_printing_as_error(self):
            pass

        def cancel_requested(self):
            return self.cancelled

    fake = FakeDialog()

    class FakeNativeDialog:
        def __init__(self, printer, parent):
            pass

        def setWindowTitle(self, title):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(viewer_module, "QPrintDialog", FakeNativeDialog)
    painted: list = []

    def fake_paint(printer, documents, details, log=None, progress=None, should_cancel=None):
        painted.append((printer.docName(), documents))
        for index, (_document, pages, name) in enumerate(documents):
            log(f"Printing {name} ({len(pages)} page(s))…")
            for page in pages:
                progress(index, page, len(pages))

    monkeypatch.setattr(window, "_paint_documents", fake_paint)
    details = {
        "paths": [str(good1), str(bad), str(good2)],
        "printer": "",
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "A4",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    window._run_batch_print(fake, details)
    # One print job per file, named after the file (legacy parity).
    assert [doc_name for doc_name, _docs in painted] == ["good1.pdf", "good2.pdf"]
    assert [entry[2] for entry in painted[0][1]] == ["good1.pdf"]
    assert [entry[2] for entry in painted[1][1]] == ["good2.pdf"]
    assert any("Skipped bad.pdf" in line for line in fake.logs)
    assert fake.status[str(bad)] == "Error"
    assert fake.status[str(good1)] == "Done"
    assert fake.status[str(good2)] == "Done"
    assert any("Sent 2 PDF file(s)" in line for line in fake.logs)
    window.close()


def test_batch_print_cancel_marks_partial_file(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog

    window = _window(tmp_path, monkeypatch)
    good1 = make_pdf(tmp_path / "one.pdf")
    good2 = make_pdf(tmp_path / "two.pdf")

    class FakeDialog:
        def __init__(self):
            self.logs: list[str] = []
            self.status: dict[str, str] = {}
            self.cancelled = False

        def set_printing(self, value):
            pass

        def log_message(self, message):
            self.logs.append(message)

        def mark_file_error(self, path):
            self.status[path] = "Error"

        def set_file_status(self, path, text):
            self.status[path] = text

        def mark_file_printed(self, path):
            self.status[path] = "Done"

        def mark_printing_as_error(self):
            pass

        def cancel_requested(self):
            return self.cancelled

    fake = FakeDialog()

    class FakeNativeDialog:
        def __init__(self, printer, parent):
            pass

        def setWindowTitle(self, title):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(viewer_module, "QPrintDialog", FakeNativeDialog)

    def fake_paint(printer, documents, details, log=None, progress=None, should_cancel=None):
        # The user cancels while the first page is being drawn.
        for index, (_document, pages, name) in enumerate(documents):
            log(f"Printing {name} ({len(pages)} page(s))…")
            for page in pages:
                progress(index, page, len(pages))
                fake.cancelled = True
                if should_cancel and should_cancel():
                    return

    monkeypatch.setattr(window, "_paint_documents", fake_paint)
    details = {
        "paths": [str(good1), str(good2)],
        "printer": "",
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "A4",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    window._run_batch_print(fake, details)
    assert any("Batch print cancelled." in line for line in fake.logs)
    assert fake.status.get(str(good1)) == "Cancelled"
    assert str(good2) not in fake.status  # never started
    window.close()


def test_mixed_orientation_pages_print_upright(tmp_path, monkeypatch):
    from PyQt6.QtPrintSupport import QPrinter

    window = _window(tmp_path, monkeypatch)
    mixed = tmp_path / "mixed.pdf"
    with fitz.open() as doc:
        landscape = doc.new_page(width=842, height=595)
        landscape.insert_text((72, 96), "Landscape page")
        portrait = doc.new_page(width=595, height=842)
        portrait.insert_text((72, 96), "Portrait page")
        doc.save(mixed)
    details = {
        "printer": "",
        "pages": [],
        "copies": 1,
        "collate": True,
        "colour": 0,
        "duplex": 0,
        "paper": "PDF page size",
        "orientation": 0,
        "scale_mode": 0,
        "scale": 100,
        "center": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    output = tmp_path / "print_mixed.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output))
    with fitz.open(mixed) as doc:
        window._configure_print_layout(printer, doc.load_page(0), details)
        window._paint_documents(
            printer,
            [(doc, [0, 1], "mixed.pdf")],
            details,
        )
    with fitz.open(output) as result:
        assert result.page_count == 2
        # The job keeps the first page's landscape layout...
        assert result[0].rect.width > result[0].rect.height
        # ...and the portrait page's content is rotated upright: the text
        # (originally top-left) ends up on the right-hand side.
        page = result[1]
        images = page.get_images(full=True)
        assert images, "the second page must contain its rendered image"
        from PIL import Image
        import io

        data = result.extract_image(images[0][0])["image"]
        with Image.open(io.BytesIO(data)).convert("L") as img:
            pixels = img.load()
            dark = [(x, y) for y in range(0, img.height, 2) for x in range(0, img.width, 2) if pixels[x, y] < 128]
        assert dark, "the rendered page must have visible content"
        centroid_x = sum(x for x, _y in dark) / len(dark)
        assert centroid_x > img.width / 2, (
            f"content centroid {centroid_x} should sit on the right half after rotation"
        )
    window.close()


def test_save_as_uses_remembered_save_folder(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "src.pdf")
    window.load_file(str(source))
    saved = tmp_path / "saved"
    saved.mkdir()
    window.settings.set_last_save_directory(saved)
    chosen = saved / "renamed.pdf"
    captured: list[str] = []
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: captured.append(args[2]) or (str(chosen), "PDF (*.pdf)"),
    )
    window.save_as_file()
    assert Path(captured[0]) == saved / "src.pdf"
    assert chosen.exists()
    assert window.settings.get_last_save_directory() == str(saved.resolve())
    window.close()


def test_save_as_falls_back_to_document_folder(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "src.pdf")
    window.load_file(str(source))
    captured: list[str] = []
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: captured.append(args[2]) or ("", ""),
    )
    window.save_as_file()
    assert Path(captured[0]) == tmp_path / "src.pdf"
    window.close()

def test_open_dialog_multi_select_opens_each_file_in_own_tab(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    selected = [str(first), str(second)]
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getOpenFileNames",
        lambda *a, **k: (selected, "Supported documents (*.pdf *.ps *.eps)"),
    )
    window._open_dialog()
    assert window.workspace.session_count() == 2
    assert window.workspace.session_at(0).display_path == first.resolve()
    assert window.workspace.session_at(1).display_path == second.resolve()
    assert window._session.engine.is_loaded()
    window.close()


def test_open_files_reuses_empty_tab_then_opens_new_tabs(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "a.pdf")
    second = make_pdf(tmp_path / "b.pdf")
    third = make_pdf(tmp_path / "c.pdf")
    # A failed open must not leave a placeholder tab behind.
    errors: list[str] = []
    monkeypatch.setattr(window, "_error", lambda title, message: errors.append(message))
    window.load_file(str(tmp_path / "missing.pdf"))
    assert window.workspace.session_count() == 0
    assert errors
    # Every file then opens in its own fresh tab.
    window.open_files([str(first), str(second)])
    assert window.workspace.session_count() == 2
    assert window._session.display_path == second.resolve()
    # Once a document is loaded, further opens always use new tabs.
    window.open_files([str(third)])
    assert window.workspace.session_count() == 3
    window.close()


def test_dropped_file_opens_new_tab_when_document_is_open(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    window.load_file(str(first))
    assert window.workspace.session_count() == 1
    window._file_dropped(str(second))
    assert window.workspace.session_count() == 2
    assert window.workspace.session_at(0).display_path == first.resolve()
    assert window._session.display_path == second.resolve()
    window.close()


def test_cancelled_background_tab_close_keeps_active_session(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    window.load_file(str(first))
    window.open_in_new_tab(str(second))  # second tab becomes the active one
    background = window.workspace.session_at(0)
    assert window._session is not background
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: False)
    window.close_document(background)
    # Cancel keeps the background tab open and the active session in sync
    # with the visible tab.
    assert window.workspace.session_count() == 2
    assert window._session is window.workspace.current_session()
    assert window._session is not background
    window.close()


def test_save_all_prompts_save_as_for_never_saved_documents(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "unsaved.pdf")
    window.load_file(str(source))
    session = window._session
    session.engine.detach_save_target()  # simulate a never-saved document
    session.engine.rotate_pages([0], 90)  # mark it modified
    assert session.engine.is_modified

    chosen = tmp_path / "named.pdf"
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "PDF (*.pdf)"),
    )
    window.save_all_files()
    assert chosen.exists()
    assert session.display_path == chosen
    window.close()


def test_save_all_skipping_save_as_reports_warning(tmp_path, monkeypatch):
    _allow_discard(monkeypatch)  # the document stays modified at close time
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "unsaved.pdf")
    window.load_file(str(source))
    session = window._session
    session.engine.detach_save_target()
    session.engine.rotate_pages([0], 90)
    messages: list[tuple] = []
    monkeypatch.setattr(
        window.info_bar, "show_message", lambda msg, kind="info", timeout=0: messages.append((msg, kind))
    )
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    window.save_all_files()
    assert any("not saved" in msg for msg, kind in messages)
    window.close()


# --- P1: sidebar legacy layout (G2a/G2b) ---------------------------------

def test_thumbnail_panel_renders_only_visible_window(tmp_path):
    import time

    from PyQt6.QtWidgets import QApplication

    from ui.thumbnail_panel import MAX_PENDING_RENDERS, ThumbnailPanel

    _app()
    source = make_pdf(tmp_path / "big.pdf", pages=80)
    panel = ThumbnailPanel(animations_enabled=False)
    panel.resize(220, 420)
    panel.show()
    panel.load_document(str(source), 80)
    app = QApplication.instance()
    first, last = panel._visible_range()
    # Only the scroll window plus overscan schedules renders, never all pages.
    assert 0 <= first <= last < 80
    assert last - first < 40
    for _ in range(80):
        app.processEvents()
        if panel._cache:
            break
        time.sleep(0.05)
    assert panel._cache
    assert len(panel._pending) <= MAX_PENDING_RENDERS
    assert len(panel._cache) <= MAX_PENDING_RENDERS * 3 + 4
    panel.clear()
    assert panel._cache == {}
    panel.hide()
    panel.deleteLater()
    app.processEvents()


def test_sidebar_sections_use_legacy_names(tmp_path, monkeypatch):
    _app()
    panel = SidePanel(animations_enabled=False)
    titles = [section.header.text() for section in panel._sections]
    assert titles == ["Page Operations", "Annotate", "Conversion", "Utilities", "Security"]
    panel.deleteLater()


def test_sidebar_pages_order_and_new_order_tool(tmp_path, monkeypatch):
    _app()
    panel = SidePanel(animations_enabled=False)
    pages_items = [item.key for item in panel.SECTIONS[0][2]]
    assert pages_items == [
        "search", "insert", "delete", "extract", "order",
        "sort", "split", "rotate", "info",
    ]
    assert "order" in panel._buttons
    received: list[str] = []
    panel.toolRequested.connect(received.append)
    panel._buttons["order"].click()
    assert received == ["order"]
    panel.deleteLater()


def test_viewer_order_tool_opens_order_context(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "order.pdf")
    window.load_file(str(source))
    shown: list[str] = []
    monkeypatch.setattr(window, "_show_context", lambda key: shown.append(key))
    window._tool_requested("order")
    assert shown == ["sort"]
    window.close()


# --- P1: bottom bar rotate box (G4) --------------------------------------

def test_bottom_bar_rotate_box_submenu(tmp_path, monkeypatch):
    _app()
    bar = BottomBar()
    submenus = [action for action in bar._rotate.menu().actions() if action.menu()]
    assert len(submenus) == 1
    box = submenus[0]
    assert box.text() == "Rotate Page(s) from Page Box"
    assert [action.text() for action in box.menu().actions()] == [
        "90° Clockwise", "180°", "90° Counter-Clockwise",
    ]
    received: list[int] = []
    bar.rotateBoxRequested.connect(received.append)
    box.menu().actions()[1].trigger()
    assert received == [180]
    bar.deleteLater()


def test_rotate_box_pages_rotates_pages_from_page_box(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "rot.pdf", pages=3)
    window.load_file(str(source))
    messages = _messages(window)
    window.bottom_bar._page.setText("1-2")
    window.bottom_bar.rotateBoxRequested.emit(180)
    engine = window.engine
    assert engine.document.load_page(0).rotation == 180
    assert engine.document.load_page(1).rotation == 180
    assert engine.document.load_page(2).rotation == 0
    assert any("🔄 Rotated 2 page(s)" in message for message in messages)
    _allow_discard(monkeypatch)
    window.close()


def test_rotate_box_pages_empty_and_invalid_input(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "rot2.pdf")
    window.load_file(str(source))
    messages = _messages(window)

    window.bottom_bar._page.setText("")
    window._rotate_box_pages(90)
    assert any("page box first" in message for message in messages)

    window.bottom_bar._page.setText("abc")
    window._rotate_box_pages(90)
    assert any("Rotate failed" in message for message in messages)
    window.close()


# --- P2: zoom slider (G5) ------------------------------------------------

def test_zoom_slider_syncs_both_ways(tmp_path, monkeypatch):
    _app()
    bar = BottomBar()
    assert bar._slider.value() == 100

    bar.set_zoom_percent(200)
    assert bar._slider.value() == 200

    received: list[int] = []
    bar.zoomSliderChanged.connect(received.append)
    bar._slider.setValue(300)
    assert received == [300]
    assert bar._zoom.text() == "300%"

    zoom_set: list[float] = []
    bar.zoomSet.connect(zoom_set.append)
    bar._zoom.setText("1000%")
    bar._commit_zoom()
    assert zoom_set == [4.0]
    assert bar._slider.value() == 400
    bar.deleteLater()


def test_viewer_zoom_slider_sets_canvas(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "zoom.pdf")
    window.load_file(str(source))
    ratios: list[float] = []
    monkeypatch.setattr(window.workspace.canvas, "set_zoom", lambda ratio: ratios.append(ratio))
    window._zoom_slider_set(150)
    assert ratios == [1.5]
    window.close()


# --- P2: file info tooltip (G6) ------------------------------------------

def test_file_info_tooltip_contains_path_and_pages(tmp_path, monkeypatch):
    _app()
    bar = BottomBar()
    bar.set_document_info("doc.pdf", 7, "/tmp/doc.pdf")
    assert bar._file.toolTip() == "/tmp/doc.pdf | 7 page(s)"
    bar.set_document_info("doc.pdf", 7)
    assert bar._file.toolTip() == "doc.pdf"
    bar.deleteLater()


# --- P3: status messages (G7) --------------------------------------------

def test_legacy_status_messages_on_load_and_save(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "msg.pdf")
    messages = _messages(window)
    window.load_file(str(source))
    assert any("✅ Loaded: msg.pdf" in message for message in messages)

    window.save_file()
    assert any("💾 Saved: msg.pdf" in message for message in messages)
    window.close()


# --- P3: shortcuts (G10) --------------------------------------------------

def test_legacy_shortcuts_installed_with_window_context(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    assert window._shortcut_rotate_left.key().toString() == "Ctrl+L"
    assert window._shortcut_rotate_right.key().toString() == "Ctrl+R"
    assert window._shortcut_extract.key().toString() == "Ctrl+E"
    assert window._shortcut_delete.key().toString() == "Del"
    for shortcut in (
        window._shortcut_rotate_left,
        window._shortcut_rotate_right,
        window._shortcut_extract,
        window._shortcut_delete,
    ):
        assert shortcut.context() == Qt.ShortcutContext.WindowShortcut
    window.close()


def test_delete_shortcut_ignores_text_inputs(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    calls: list[bool] = []
    monkeypatch.setattr(window, "_delete_pages_dialog", lambda: calls.append(True))
    window._delete_pages_shortcut()
    assert calls == [True]

    line = QLineEdit()
    monkeypatch.setattr(viewer_module.QApplication, "focusWidget", lambda: line)
    window._delete_pages_shortcut()
    assert calls == [True]  # unchanged while typing
    window.close()


# --- robustness: no qFatal on unexpected I/O errors -----------------------

def test_settings_save_failure_degrades_gracefully(tmp_path, monkeypatch):
    from core.settings import SettingsManager

    settings = SettingsManager(tmp_path / "settings.json")

    def deny_replace(*args, **kwargs):
        raise PermissionError("preferences directory is read-only")

    monkeypatch.setattr("os.replace", deny_replace)
    settings.set("theme", "dark")  # must not raise
    settings.set("theme", "light")  # second failure stays silent
    assert settings.get("theme") == "light"


def test_load_file_guard_swallows_unexpected_errors(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    errors: list[str] = []
    monkeypatch.setattr(window, "_error", lambda title, message: errors.append(message))
    monkeypatch.setattr(
        window, "_load_path", lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    window.load_file("/tmp/missing.pdf")
    assert errors == ["boom"]
    window.close()


def test_organize_pages_applies_and_refreshes_canvas(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QDialog

    class FakeOrganizer:
        order = [2, 1, 0]
        rotations = {2: 90}

        def exec(self):
            return QDialog.DialogCode.Accepted

    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "org-apply.pdf", pages=3)
    window.load_file(str(source))
    monkeypatch.setattr(
        viewer_module, "VisualOrganizerDialog", lambda document, parent: FakeOrganizer()
    )
    refreshed: list[bool] = []
    monkeypatch.setattr(window.workspace.canvas, "refresh", lambda: refreshed.append(True))

    window._organize_pages()

    assert refreshed == [True]
    engine = window.engine
    assert engine.document.load_page(0).rotation == 90  # original page 3, rotated
    assert "Searchable page 3" in engine.document.load_page(0).get_text()
    assert "Searchable page 2" in engine.document.load_page(1).get_text()
    assert "Searchable page 1" in engine.document.load_page(2).get_text()
    assert window.bottom_bar._total.text() == "/ 3"
    _allow_discard(monkeypatch)
    window.close()


def test_search_panel_scope_integration(tmp_path, monkeypatch):
    """The former advanced-search dialog features live in the search panel."""
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "scope.pdf", pages=3)
    window.load_file(str(source))
    panel = window.workspace.nav_panel.search
    assert panel._page_count == 3

    received: list[tuple[str, object]] = []
    panel.searchRequested.connect(lambda query, pages: received.append((query, pages)))
    panel._query.blockSignals(True)
    panel._query.setText("searchable")
    panel._query.blockSignals(False)

    panel._all_pages.setChecked(True)
    panel._emit_search()
    assert received[-1] == ("searchable", None)

    panel._current_only.setChecked(True)
    panel.set_current_page(1)
    assert panel._current_only.text() == "Current page (2)"
    panel._emit_search()
    assert received[-1] == ("searchable", [1])

    panel._custom.setChecked(True)
    panel._custom_pages.setText("2-3")
    panel._emit_search()
    assert received[-1] == ("searchable", [1, 2])

    panel._custom_pages.setText("bad")
    panel._emit_search()
    assert "Invalid page range" in panel._status.text()
    window.close()


def test_run_search_scopes_results_to_selected_pages(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "scope-run.pdf", pages=3)
    window.load_file(str(source))
    panel = window.workspace.nav_panel.search
    window._run_search("searchable", None, [1])
    assert panel._list.count() == 1
    assert "Page 2" in panel._list.item(0).text()
    assert "1 match(es)" in panel._list.item(0).text()
    window.close()


def test_encrypt_then_open_with_password_in_viewer(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "enc-viewer.pdf", pages=2)
    window.load_file(str(source))
    encrypted = tmp_path / "enc_viewer_enc.pdf"
    window.engine.encrypt("secret123", str(encrypted))

    prompts = iter([("secret123", True)])
    monkeypatch.setattr(
        viewer_module, "ask_password", lambda *args, **kwargs: next(prompts)
    )
    window.load_file(str(encrypted))
    assert window.engine.page_count == 2
    assert "Searchable page 1" in window.engine.document.load_page(0).get_text()
    assert window.engine.is_encrypted()
    assert window.engine.password == "secret123"
    window.close()


def test_viewer_password_retry_after_wrong_password(tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "enc-retry.pdf")
    window.load_file(str(source))
    encrypted = tmp_path / "enc_retry_enc.pdf"
    window.engine.encrypt("secret123", str(encrypted))

    prompts = iter([("wrong", True), ("secret123", True)])
    monkeypatch.setattr(
        viewer_module, "ask_password", lambda *args, **kwargs: next(prompts)
    )
    messages: list[str] = []
    monkeypatch.setattr(
        window.info_bar, "show_message", lambda msg, kind="", duration=0: messages.append(msg)
    )
    window.load_file(str(encrypted))
    assert window.engine.page_count == 2
    assert window.engine.password == "secret123"
    assert any("password is not valid" in message for message in messages)
    window.close()


# --- password fields reject input methods (IME) ----------------------------

def test_password_fields_disable_input_method(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QLineEdit

    from dialogs.base import ask_password, password_line_edit
    from dialogs.security_dialogs import EncryptDialog

    edit = password_line_edit("optional")
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert not edit.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
    assert edit.inputMethodHints() & Qt.InputMethodHint.ImhLatinOnly

    source = make_pdf(tmp_path / "enc-ime.pdf")
    dialog = EncryptDialog(source)
    for field in (dialog.user_password, dialog.confirm_password, dialog.owner_password):
        assert field.echoMode() == QLineEdit.EchoMode.Password
        assert not field.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        assert field.inputMethodHints() & Qt.InputMethodHint.ImhLatinOnly
    dialog.close()

    def fake_exec(self):
        self.findChild(QLineEdit).setText("secret123")
        from PyQt6.QtWidgets import QDialog

        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "PyQt6.QtWidgets.QInputDialog.exec", fake_exec
    )
    text, accepted = ask_password(None, "Encrypted PDF", "Password")
    assert (text, accepted) == ("secret123", True)


# --- retina icons must fill the whole pixmap -------------------------------

def test_retina_icons_render_full_pixmap(tmp_path, monkeypatch):
    from ui import icons as icons_module

    _app()
    icons_module._pixmap.cache_clear()
    icons_module.clear_icon_cache()
    monkeypatch.setattr(icons_module, "_screen_dpr", lambda: 2.0)
    pixmap = icons_module._pixmap("search", 16, "#000000")
    assert pixmap.devicePixelRatio() == 2.0
    assert pixmap.width() == 32 and pixmap.height() == 32
    image = pixmap.toImage()
    probes = (
        (14, 6),   # circle ring, top
        (6, 15),   # circle ring, left
        (24, 15),  # circle ring, right
        (24, 24),  # magnifier handle (bottom-right)
    )
    for x, y in probes:
        assert image.pixelColor(x, y).alpha() > 0, f"no ink near ({x}, {y})"
    monkeypatch.undo()
    icons_module._pixmap.cache_clear()
    icons_module.clear_icon_cache()


# --- bundled Ghostscript detection -----------------------------------------

def test_bundled_ghostscript_detection(tmp_path, monkeypatch):

    import sys

    from core import capabilities as capabilities_module

    # On non-Windows dev trees the Windows binaries must NOT be picked up;
    # on Windows the repository ships them and detection must find them.
    if sys.platform == "win32":
        dev_tree = capabilities_module._bundled_ghostscript()
        assert dev_tree and Path(dev_tree).is_file()
    else:
        assert capabilities_module._bundled_ghostscript() is None

    fake_root = tmp_path / "ghostscript" / "bin"
    fake_root.mkdir(parents=True)
    (fake_root / "gswin64c.exe").write_text("fake", encoding="utf-8")

    monkeypatch.setattr(capabilities_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(capabilities_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(capabilities_module.sys, "_MEIPASS", str(tmp_path), raising=False)
    found = capabilities_module._bundled_ghostscript()
    assert found == str(fake_root / "gswin64c.exe")
    monkeypatch.undo()


# --- fast-scroll rendering: visible pages render first ---------------------

def test_canvas_renders_visible_pages_first(tmp_path, monkeypatch):
    import time

    window = _window(tmp_path, monkeypatch)
    window.resize(1100, 760)
    window.show()
    source = make_pdf(tmp_path / "fast-scroll.pdf", pages=12)
    window.load_file(str(source))
    canvas = window.workspace.canvas
    app = _app()

    def drain() -> None:
        deadline = time.monotonic() + 10
        while canvas._pending and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

    window._set_layout_mode("continuous")
    drain()
    # Warm the cache near the top so a later jump lands on uncached pages.
    canvas.verticalScrollBar().setValue(canvas._rows[2][0])
    canvas._apply_scroll_sync()
    drain()

    starts: list[tuple[object, int]] = []
    monkeypatch.setattr(
        canvas._pool, "start", lambda task, priority=0: starts.append((task, priority))
    )
    canvas.verticalScrollBar().setValue(canvas._rows[10][0])
    canvas._apply_scroll_sync()
    priorities = [priority for _task, priority in starts]
    assert 6 in priorities, f"visible pages must render at high priority: {priorities}"
    assert 0 in priorities, f"prefetch buffer must render at low priority: {priorities}"

    # A saturated pool never starves the focused pages: buffer prefetch is
    # throttled, focused pages still start.
    canvas._pending = {1000 + index for index in range(50)}
    canvas._teardown_views()
    starts.clear()
    canvas._sync_views()
    priorities = [priority for _task, priority in starts]
    assert priorities and all(priority == 6 for priority in priorities)
    _allow_discard(monkeypatch)
    window.close()


# --- rounded translucent popup menus ---------------------------------------

def test_menus_are_rounded_and_translucent(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMenu

    from styles.components import global_style
    from styles.theme import _RoundMenuStyle

    _app()
    style = _RoundMenuStyle()
    menu = QMenu()
    style.polish(menu)
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert menu.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    css = global_style()
    assert "QMenu" in css and "border-radius: 12px" in css
    assert "QComboBox QAbstractItemView" in css and "border-radius: 10px" in css
    menu.deleteLater()
