"""Shared native dialog shell with persistent geometry and inline validation."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.diagnostics import log_failure
from ui.responsive import ResponsiveDialog, reveal_widget


def password_line_edit(placeholder: str = "") -> QLineEdit:
    """Password field that disables input-method (IME) input.

    Passwords must be typed as plain ASCII key strokes: IME composition
    (e.g. Chinese or full-width characters) would make the entered password
    differ from the one used when encrypting the file.
    """
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
    edit.setInputMethodHints(
        Qt.InputMethodHint.ImhLatinOnly
        | Qt.InputMethodHint.ImhSensitiveData
        | Qt.InputMethodHint.ImhNoPredictiveText
    )
    if placeholder:
        edit.setPlaceholderText(placeholder)
    return edit


_WINDOWS_INVALID_FILENAME = re.compile(r'[\\/:*?"<>|]')


def windows_safe_filename_component(value: str) -> bool:
    """True when the text contains no characters Windows forbids in file names."""
    return not _WINDOWS_INVALID_FILENAME.search(value)


def _settings_owner(widget) -> object | None:
    """Walk the widget parent chain for the first object with settings."""
    current = widget
    while current is not None:
        settings = getattr(current, "settings", None)
        if settings is not None:
            return settings
        current = current.parent()
    return None


def start_in_save_directory(widget, filename: str, fallback=None) -> str:
    """Initial path for a save dialog: the remembered Save-As folder (or the
    fallback) plus the suggested file name.

    The Save-As folder is tracked separately from the open dialog's last
    directory, so opening from one folder and saving into another both
    stay sticky.
    """
    settings = _settings_owner(widget)
    if settings is None:
        if fallback is not None:
            return str(Path(fallback) / filename)
        return filename
    return str(Path(settings.get_last_save_directory(fallback)) / filename)


def last_save_directory(widget, fallback=None) -> str:
    """The remembered Save-As folder (or the fallback, or home)."""
    settings = _settings_owner(widget)
    if settings is not None:
        return settings.get_last_save_directory(fallback)
    if fallback is not None:
        return str(Path(fallback))
    return str(Path.home())


def remember_save_directory(widget, path) -> None:
    """Persist the folder of a chosen save path for the next save dialog."""
    settings = _settings_owner(widget)
    if settings is not None:
        settings.set_last_save_directory(Path(path).parent)


def ask_password(parent, title: str, label: str) -> tuple[str, bool]:
    """Modal password prompt whose input field rejects input methods."""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    edit = dialog.findChild(QLineEdit)
    if edit is not None:
        edit.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        edit.setInputMethodHints(
            Qt.InputMethodHint.ImhLatinOnly
            | Qt.InputMethodHint.ImhSensitiveData
            | Qt.InputMethodHint.ImhNoPredictiveText
        )
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.textValue(), accepted


class PathLineEdit(QLineEdit):
    """Read-only path field that middle-elides long paths.

    The filename tail stays visible, the full path is shown in the tooltip,
    and ``path()`` always returns the complete unelided value.
    """

    def __init__(self, value: str = "", parent=None):
        super().__init__(parent)
        self._full_path = value
        self.setReadOnly(True)
        self.setToolTip(value)
        self.setCursorPosition(0)
        self._refresh()

    def setText(self, value: str) -> None:
        self._full_path = value
        self.setToolTip(value)
        self._refresh()

    def path(self) -> str:
        return self._full_path

    def _refresh(self) -> None:
        width = max(40, self.width() - 12)
        display = self.fontMetrics().elidedText(
            self._full_path, Qt.TextElideMode.ElideMiddle, width
        )
        super().setText(display)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()


class ToolDialog(ResponsiveDialog):
    def __init__(self, title: str, geometry_key: str, parent=None):
        super().__init__(parent)
        self._geometry_key = geometry_key
        self._first_show = True
        settings = getattr(parent, "settings", None)
        self._animations_enabled = bool(
            settings.get("animations_enabled", True) if settings is not None else True
        )
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(520, 420)
        self._root = QVBoxLayout(self)
        self._validation = QLabel()
        self._validation.setObjectName("validationError")
        self._validation.setWordWrap(True)
        self._validation.hide()
        saved = QSettings().value(f"dialogs/{geometry_key}/geometry")
        if saved:
            self.restoreGeometry(saved)
        else:
            self.resize(680, 620)

    # --- whole-dialog file drops -----------------------------------------
    def drop_extensions(self) -> set[str] | None:
        """Extensions accepted by drag-and-drop, or None to disable.

        Subclasses return e.g. {".pdf"}; dropped files are routed to
        add_dropped_paths() regardless of where they land on the dialog.
        """
        return None

    def add_dropped_paths(self, paths: list[str]) -> None:
        """Handle files dropped onto the dialog (override in subclasses)."""

    def dragEnterEvent(self, event) -> None:
        extensions = self.drop_extensions()
        if extensions is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        extensions = self.drop_extensions()
        if extensions is None:
            super().dropEvent(event)
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        accepted = [
            path for path in paths if Path(path).suffix.casefold() in extensions
        ]
        if accepted:
            self.add_dropped_paths(accepted)
            event.acceptProposedAction()

    def show_error(self, message: str) -> None:
        self._validation.setText(message)
        self._validation.show()
        QTimer.singleShot(0, lambda: reveal_widget(self._validation))

    def add_validation(self) -> None:
        self._root.addWidget(self._validation)

    def done(self, result: int) -> None:
        QSettings().setValue(f"dialogs/{self._geometry_key}/geometry", self.saveGeometry())
        super().done(result)

    def closeEvent(self, event) -> None:
        QSettings().setValue(f"dialogs/{self._geometry_key}/geometry", self.saveGeometry())
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._first_show:
            return
        self._first_show = False
        self._fit_to_content()
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
            )
        if not self._animations_enabled:
            return
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _fit_to_content(self) -> None:
        self._fit_screen()


class NumericSortItem(QTableWidgetItem):
    """Sorts numbers numerically instead of lexicographically."""

    @staticmethod
    def _key(text: str) -> tuple:
        match = re.match(r"\s*([\d.,]+)\s*([KMGT]?B)?", text)
        if match and match.group(1):
            try:
                value = float(match.group(1).replace(",", ""))
                multiplier = {
                    "KB": 1024,
                    "MB": 1024**2,
                    "GB": 1024**3,
                    "TB": 1024**4,
                }.get(match.group(2), 1)
                return (0, value * multiplier)
            except ValueError:
                log_failure('base._key: fallback after failure', 10)
                pass
        return (1, text.casefold())

    def __lt__(self, other) -> bool:
        return self._key(self.text()) < self._key(other.text())


class SortableTableWidget(QTableWidget):
    """QTableWidget with sortable headers, context menu copy, and Ctrl+C."""

    def __init__(self, rows: int = 0, columns: int = 0, parent=None):
        super().__init__(rows, columns, parent)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSortingEnabled(False)
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._sort_column = -1
        self.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _on_header_clicked(self, logical_index: int) -> None:
        if logical_index == self._sort_column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = logical_index
            self._sort_order = Qt.SortOrder.AscendingOrder
        # Swap the clicked column's items for numeric-aware ones so "10" sorts
        # after "9" and "12.34 MB" sorts after "900 KB".
        for row in range(self.rowCount()):
            item = self.item(row, logical_index)
            if item is not None and not isinstance(item, NumericSortItem):
                # Copy every Qt/custom role, flags and styling. Consumers keep
                # result identity in roles beyond UserRole (e.g. Deep Search).
                replacement = NumericSortItem(item)
                self.setItem(row, logical_index, replacement)
        self.sortItems(logical_index, self._sort_order)

    def _show_context_menu(self, position) -> None:
        menu = QMenu(self)
        copy_cell = QAction("Copy cell", self)
        copy_cell.setShortcut(QKeySequence.StandardKey.Copy)
        copy_cell.triggered.connect(self._copy_selection)
        menu.addAction(copy_cell)
        copy_row = QAction("Copy row", self)
        copy_row.triggered.connect(self._copy_row)
        menu.addAction(copy_row)
        menu.addSeparator()
        select_all = QAction("Select all", self)
        select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all.triggered.connect(self.selectAll)
        menu.addAction(select_all)
        menu.exec(self.viewport().mapToGlobal(position))

    def _copy_selection(self) -> None:
        items = self.selectedItems()
        if not items:
            self._copy_row()
            return
        rows: dict[int, dict[int, str]] = {}
        for item in items:
            rows.setdefault(item.row(), {})[item.column()] = item.text()
        lines = []
        for row_index in sorted(rows):
            cols = rows[row_index]
            lines.append("\t".join(cols.get(c, "") for c in sorted(cols)))
        QApplication.clipboard().setText("\n".join(lines))

    def _copy_row(self) -> None:
        rows = sorted({item.row() for item in self.selectedItems()})
        if not rows:
            return
        lines = []
        for row_index in rows:
            cells = []
            for column in range(self.columnCount()):
                item = self.item(row_index, column)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy_selection()
            return
        super().keyPressEvent(event)
