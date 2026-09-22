"""Legacy Deep Search: backend multi-keyword support and dialog layout/features."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from core.tools import deep_search
from ui.deep_search_dialog import OPEN_CURRENT, OPEN_NEW_TAB, OPEN_SYSTEM, DeepSearchDialog


def make_pdf(path: Path, text: str) -> Path:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 96), text)
        document.save(path)
    return path


def _dialog(tmp_path: Path):
    app = QApplication.instance() or QApplication(["pdfdocuedit-deepsearch-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    return DeepSearchDialog(str(tmp_path)), app


# --- backend ---------------------------------------------------------------

def test_deep_search_multiple_keywords(tmp_path: Path) -> None:
    make_pdf(tmp_path / "one.pdf", "An apple a day keeps the doctor away")
    make_pdf(tmp_path / "two.pdf", "Cherry on top of the cake")

    results = deep_search(tmp_path, "apple, cherry")
    filenames = {str(result["filename"]) for result in results}
    assert filenames == {"one.pdf", "two.pdf"}

    results = deep_search(tmp_path, "apple")
    assert [str(result["filename"]) for result in results] == ["one.pdf"]
    assert "apple" in str(results[0]["snippets"][0]).casefold()

    results = deep_search(tmp_path, "pear")
    assert results == []


def test_deep_search_rejects_empty_keywords(tmp_path: Path) -> None:
    from core.tools import ToolError

    try:
        deep_search(tmp_path, "  , , ")
    except ToolError:
        return
    raise AssertionError("Expected ToolError for empty keyword list")


# --- dialog layout parity ---------------------------------------------------

def test_deep_search_dialog_legacy_layout(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    assert dialog.isModal() is False

    tab_titles = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
    assert tab_titles == ["Search Result", "Preview", "Error Message"]

    headers = [
        dialog.table.horizontalHeaderItem(column).text()
        for column in range(dialog.table.columnCount())
    ]
    assert headers == ["File Name", "Page number", "Match Count", "Contextual Summary"]

    error_headers = [
        dialog.error_table.horizontalHeaderItem(column).text()
        for column in range(dialog.error_table.columnCount())
    ]
    assert error_headers == ["File name", "Error message"]

    combo_options = [
        dialog.open_option.itemText(index) for index in range(dialog.open_option.count())
    ]
    assert combo_options == [
        "Open in new window",
        "Open in current window",
        "Open with system default application",
    ]
    assert dialog.subfolders.isChecked() is True
    assert dialog.barcodes.isChecked() is False
    for button in (
        dialog.clear_button,
        dialog.export_button,
        dialog.open_selected_button,
    ):
        assert button is not None
    assert not hasattr(dialog, "resize_button")
    assert dialog.table.objectName() == "deepSearchResultsTable"
    assert dialog.error_table.objectName() == "deepSearchErrorTable"
    dialog.close()


def test_deep_search_results_and_preview(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog.query.setText("apple")
    dialog._show_results(
        [
            {
                "path": str(tmp_path / "one.pdf"),
                "filename": "one.pdf",
                "pages": [1, 3],
                "snippets": ["An apple a day", "Another apple"],
            },
            {
                "path": str(tmp_path / "bad.pdf"),
                "filename": "bad.pdf",
                "pages": [],
                "snippets": [],
                "error": "boom",
            },
        ]
    )
    assert dialog.table.rowCount() == 1
    assert dialog.error_table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "one.pdf"
    assert dialog.table.item(0, 1).text() == "1, 3"
    assert dialog.table.item(0, 2).text() == "2"
    assert dialog.export_button.isEnabled() is True

    dialog.table.setCurrentCell(0, 0)
    dialog._update_preview()
    content = dialog.preview.toHtml()
    # The highlight now follows the theme (warning_soft), so assert the
    # styled span rather than a hardcoded colour.
    assert "background-color:" in content and "font-weight" in content
    assert "one.pdf" in content
    dialog.close()


def test_deep_search_open_selected_emits_method(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog._results = [
        {
            "path": str(tmp_path / "one.pdf"),
            "filename": "one.pdf",
            "pages": [1],
            "snippets": ["apple"],
        }
    ]
    dialog._show_results(dialog._results)
    dialog.table.setCurrentCell(0, 0)

    emitted: list[tuple[str, str]] = []
    dialog.openRequested.connect(lambda path, method: emitted.append((path, method)))

    dialog.open_option.setCurrentIndex(
        dialog.open_option.findData(OPEN_NEW_TAB)
    )
    dialog._open_selected()
    assert emitted == [(str(tmp_path / "one.pdf"), OPEN_NEW_TAB)]

    dialog.open_option.setCurrentIndex(
        dialog.open_option.findData(OPEN_SYSTEM)
    )
    dialog._open_selected()
    assert emitted[1] == (str(tmp_path / "one.pdf"), OPEN_SYSTEM)

    dialog.open_option.setCurrentIndex(
        dialog.open_option.findData(OPEN_CURRENT)
    )
    dialog._open_selected()
    assert emitted[2] == (str(tmp_path / "one.pdf"), OPEN_CURRENT)
    dialog.close()


def test_deep_search_enter_triggers_search(tmp_path: Path, monkeypatch) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog.query.clear()
    # returnPressed is wired to _search at construction; an empty query makes
    # it show the validation status instead of starting a background task.
    dialog.query.returnPressed.emit()
    assert dialog.status.text() == "Enter text to search for."
    dialog.close()


def test_deep_search_exports_html_and_text(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog.query.setText("apple")
    dialog._results = [
        {
            "path": str(tmp_path / "one.pdf"),
            "filename": "one.pdf",
            "pages": [1],
            "snippets": ["An apple a day"],
        }
    ]
    html_path = tmp_path / "results.html"
    text_path = tmp_path / "results.txt"
    dialog._export_html(str(html_path))
    dialog._export_text(str(text_path))
    assert "one.pdf" in html_path.read_text(encoding="utf-8")
    assert "one.pdf" in text_path.read_text(encoding="utf-8")
    assert "apple" in text_path.read_text(encoding="utf-8")
    dialog.close()


# --- regressions: correct file always opens --------------------------------

def _fill(dialog, results) -> None:
    dialog._show_results(results)
    dialog.table.setCurrentCell(0, 0)


def test_deep_search_interleaved_errors_keep_row_mapping(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    emitted: list[str] = []
    dialog.openRequested.connect(lambda path, method: emitted.append(path))
    dialog._show_results(
        [
            {
                "path": str(tmp_path / "a.pdf"),
                "filename": "a.pdf",
                "pages": [1],
                "snippets": ["x"],
            },
            {
                "path": str(tmp_path / "bad.pdf"),
                "filename": "bad.pdf",
                "pages": [],
                "snippets": [],
                "error": "boom",
            },
            {
                "path": str(tmp_path / "b.pdf"),
                "filename": "b.pdf",
                "pages": [2],
                "snippets": ["y"],
            },
        ]
    )
    assert dialog.table.rowCount() == 2
    assert dialog.error_table.rowCount() == 1

    dialog.table.setCurrentCell(1, 0)  # second visible row must be b.pdf
    dialog._open_selected(1)
    assert emitted == [str(tmp_path / "b.pdf")]
    dialog.close()


def test_deep_search_sorted_rows_open_correct_file(tmp_path: Path) -> None:
    from PyQt6.QtCore import Qt

    dialog, _app = _dialog(tmp_path)
    emitted: list[str] = []
    dialog.openRequested.connect(lambda path, method: emitted.append(path))
    dialog._show_results(
        [
            {
                "path": str(tmp_path / "a.pdf"),
                "filename": "a.pdf",
                "pages": [1],
                "snippets": ["x"],
            },
            {
                "path": str(tmp_path / "b.pdf"),
                "filename": "b.pdf",
                "pages": [1],
                "snippets": ["y"],
            },
        ]
    )
    dialog.table.sortItems(0, Qt.SortOrder.DescendingOrder)
    dialog.table.setCurrentCell(0, 0)
    dialog._open_selected(0)
    assert emitted == [str(tmp_path / "b.pdf")]
    dialog.close()


def test_deep_search_ignores_second_search_while_running(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog._task = object()  # pretend a search is running
    dialog.query.setText("apple")
    dialog.folder.setText(str(tmp_path))
    task_before = dialog._task
    dialog._search()
    assert dialog._task is task_before
    dialog.close()


def test_deep_search_empty_folder_status(tmp_path: Path) -> None:
    dialog, _app = _dialog(tmp_path)
    dialog._task = None
    dialog._total_files = 0
    dialog._results = []
    dialog._errors = []
    dialog._search_finished()
    assert "No PDF files" in dialog.status.text()
    dialog.close()


def test_header_click_keeps_preview_and_open_mapping(tmp_path: Path) -> None:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    dialog, app = _dialog(tmp_path)
    dialog.query.setText("apple")
    dialog._show_results([
        {"path": str(tmp_path / name), "filename": name, "pages": [page],
         "snippets": [f"apple in {name}"]}
        for name, page in [("b.pdf", 2), ("a.pdf", 1)]
    ])
    dialog.show()
    app.processEvents()
    emitted = []
    dialog.openRequested.connect(lambda path, method: emitted.append(path))
    try:
        header = dialog.table.horizontalHeader()
        for expected in [("a.pdf", "b.pdf"), ("b.pdf", "a.pdf")]:
            QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(30, header.height() // 2))
            for row, name in enumerate(expected):
                rect = dialog.table.visualItemRect(dialog.table.item(row, 0))
                QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                assert name in dialog.preview.toPlainText()
                assert f"apple in {name}" in dialog.preview.toPlainText()
                assert dialog.open_selected_button.isEnabled()
                dialog.open_selected_button.click()
                assert emitted[-1] == str(tmp_path / name)
                count = len(emitted)
                QTest.mouseDClick(dialog.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                assert len(emitted) == count + 1
                assert emitted[-1] == str(tmp_path / name)
    finally:
        dialog.close()


def test_open_button_uses_selected_row_not_clicked_boolean(tmp_path: Path) -> None:
    dialog, app = _dialog(tmp_path)
    dialog._show_results([
        {"path": str(tmp_path / name), "filename": name, "pages": [1], "snippets": [name]}
        for name in ("one.pdf", "two.pdf")
    ])
    emitted = []
    dialog.openRequested.connect(lambda path, method: emitted.append(path))
    try:
        dialog.table.setCurrentCell(1, 0)
        dialog.open_selected_button.click()
        assert emitted == [str(tmp_path / "two.pdf")]
        assert "two.pdf" in dialog.preview.toPlainText()
    finally:
        dialog.close()


def test_preview_populates_on_results_and_clears_with_results(tmp_path: Path) -> None:
    dialog, app = _dialog(tmp_path)
    try:
        dialog._show_results([
            {"path": str(tmp_path / "first.pdf"), "filename": "first.pdf",
             "pages": [7], "snippets": ["Matching page content"]}
        ])
        assert "Matching page content" in dialog.preview.toPlainText()
        assert "Page 7" in dialog.preview.toPlainText()
        assert dialog.open_selected_button.isEnabled()
        dialog._clear_results()
        assert dialog.preview.toPlainText() == ""
        assert not dialog.open_selected_button.isEnabled()
    finally:
        dialog.close()


def test_sortable_table_preserves_custom_roles_and_numeric_order(tmp_path: Path) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QTableWidgetItem

    from dialogs.base import SortableTableWidget

    app = QApplication.instance() or QApplication([])
    table = SortableTableWidget(2, 1)
    try:
        for row, text in enumerate(("10", "2")):
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole + 19, f"identity-{text}")
            item.setForeground(QColor("red"))
            item.setToolTip(f"tooltip-{text}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, item)
        table._on_header_clicked(0)
        assert [table.item(row, 0).text() for row in range(2)] == ["2", "10"]
        for row in range(2):
            item = table.item(row, 0)
            assert item.data(Qt.ItemDataRole.UserRole + 19) == f"identity-{item.text()}"
            assert item.foreground().color() == QColor("red")
            assert item.toolTip() == f"tooltip-{item.text()}"
            assert not item.flags() & Qt.ItemFlag.ItemIsEditable
        table._on_header_clicked(0)
        assert table.item(0, 0).text() == "10"
    finally:
        table.close()
        table.deleteLater()
        app.processEvents()
