from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox

import core.viewer as viewer_module
from core.settings import SettingsManager
from dialogs.readme_dialog import README_CONTENT, ReadmeDialog
from ui.side_panel import SidePanel


def make_pdf(path: Path, pages: int = 3, prefix: str = "Doc") -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), f"{prefix} content page {index + 1}")
        document.save(path)
    return path


def _window(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication(["pdfdocuedit-legacy-test"])
    monkeypatch.setattr(
        viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json")
    )
    window = viewer_module.PDFViewer()
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    return window, app


def _wait(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def test_readme_dialog_constructs(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    dialog = ReadmeDialog(window)
    assert "PDFDocuEdit Pro" in README_CONTENT
    assert dialog.text_edit.toPlainText() == README_CONTENT
    assert dialog.text_edit.isReadOnly() is not False
    dialog.close()
    window.close()


def test_thumbnail_context_delete_current(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "ctx.pdf", pages=3)
    window.load_file(str(source))
    assert _wait(app, lambda: not window.workspace.canvas._pending)
    session = window._session

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    window._handle_thumbnail_action(session, "delete_current")
    app.processEvents()
    assert session.engine.page_count == 2
    assert "content page 2" in session.engine.document.load_page(0).get_text()

    window._undo()
    app.processEvents()
    assert session.engine.page_count == 3
    window.close()


def test_rotate_current_quick_action(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "rot.pdf")
    window.load_file(str(source))
    assert _wait(app, lambda: not window.workspace.canvas._pending)

    window._rotate_current(90)
    app.processEvents()
    assert window.engine.document.load_page(0).rotation == 90
    assert window.engine.is_modified

    window._undo()
    app.processEvents()
    assert window.engine.document.load_page(0).rotation == 0
    window.close()


def test_save_all_files(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "all-a.pdf")
    second = make_pdf(tmp_path / "all-b.pdf")
    window.load_file(str(first))
    window.open_in_new_tab(str(second))
    assert _wait(app, lambda: not window.workspace.canvas._pending)

    for session in window._sessions:
        session.engine.rotate_pages([0], 90)
        session.engine.mark_modified()
    assert all(session.engine.is_modified for session in window._sessions)

    window.save_all_files()
    app.processEvents()
    assert all(not session.engine.is_modified for session in window._sessions)
    with fitz.open(first) as doc:
        assert doc.load_page(0).rotation == 90
    window.close()


def test_sidebar_icons_follow_old_assets(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    expected = {
        "compress": "compress.png",
        "postscript": "postscript.png",
        "barcode": "qrcode.png",
        "barcode_batch": "batch_qrcode.png",
        "sort": "visual_organize.png",
    }
    found: dict[str, str] = {}
    for _section_key, _title, items in SidePanel.SECTIONS:
        for item in items:
            found[item.key] = item.asset_name or ""
    assert "version_control" not in found
    for key, asset in expected.items():
        assert found.get(key) == asset, (key, found.get(key))

    # The referenced assets must exist on disk.
    from core.resources import resource_path

    for asset in expected.values():
        assert resource_path("App_icon", asset).exists(), asset

    # Both barcode tools are registered in the command table.
    ids = [command.id for command in window._commands]
    assert "barcode" in ids and "barcode_batch" in ids
    assert "readme" in ids and "save_all" in ids
    window.close()


def test_decrypt_ui_flow_produces_readable_output(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    encrypted = tmp_path / "locked.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 96), "Top secret content")
        doc.save(
            encrypted,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret123",
            owner_pw="owner",
        )

    monkeypatch.setattr(
        viewer_module, "ask_password", lambda *args, **kwargs: ("secret123", True)
    )
    window.load_file(str(encrypted))
    assert _wait(app, lambda: not window.workspace.canvas._pending)
    assert window.engine.is_loaded() and window.engine.is_encrypted()
    assert window.side_panel._buttons["decrypt"].isEnabled()

    output = tmp_path / "unlocked.pdf"

    class FakeDecryptDialog:
        output_path = str(output)

        def __init__(self, *args, **kwargs):
            pass

        def exec(self) -> int:
            return 1

    monkeypatch.setattr(viewer_module, "DecryptDialog", FakeDecryptDialog)
    window._decrypt_pdf()
    # Decryption now runs as a background task; wait for the output file.
    assert _wait(app, lambda: output.exists())
    with fitz.open(output) as document:
        assert not document.needs_pass
        assert "Top secret" in document.load_page(0).get_text()
    window.close()


def test_editing_encrypted_doc_preserves_password_on_save(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    encrypted = tmp_path / "locked.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 96), "Keep me secret")
        doc.save(
            encrypted,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret123",
            owner_pw="owner",
        )

    monkeypatch.setattr(
        viewer_module, "ask_password", lambda *args, **kwargs: ("secret123", True)
    )
    window.load_file(str(encrypted))
    assert _wait(app, lambda: not window.workspace.canvas._pending)
    assert "Keep me secret" in window.engine.document.load_page(0).get_text()
    assert window.engine.is_encrypted()  # original was encrypted

    window._rotate_current(90)
    window.save_file()

    with fitz.open(encrypted) as document:
        assert document.needs_pass  # password still required
        assert document.authenticate("secret123")
        assert document.load_page(0).rotation == 90
        assert "Keep me secret" in document.load_page(0).get_text()
    window.close()
