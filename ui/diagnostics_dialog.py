"""External tool diagnostics and application preferences."""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib import metadata

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.capabilities import CapabilityId, refresh_capabilities
from core.commands import Command
from core.platform_service import PlatformService
from core.resources import config_dir, log_dir
from dialogs.base import SortableTableWidget, ToolDialog


class DiagnosticsDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("External Tools & Diagnostics", "diagnostics", parent)
        self.resize(760, 480)
        system = QLabel(
            f"Python {sys.version.split()[0]} · {platform.system()} {platform.release()} · {platform.machine()}"
        )
        system.setObjectName("secondary")
        self._root.addWidget(system)
        table = SortableTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            ["Feature", "Status", "Backend", "Version", "Path", "Details"]
        )
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for capability in refresh_capabilities().values():
            row = table.rowCount()
            table.insertRow(row)
            values = (
                capability.name,
                "Available" if capability.available else "Unavailable",
                capability.backend or "—",
                self._version(capability),
                capability.path or "—",
                "\n".join(
                    value for value in (capability.reason, capability.guidance) if value
                )
                or "Ready",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, column, item)
        self._root.addWidget(table, 1)
        paths = QLabel(f"Settings: {config_dir()}\nLogs: {log_dir()}")
        paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        paths.setWordWrap(True)
        paths.setObjectName("secondary")
        self._root.addWidget(paths)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    @staticmethod
    def _version(capability) -> str:
        packages = {
            CapabilityId.PDF_TO_WORD: "pdf2docx",
            CapabilityId.SPREADSHEET: "openpyxl",
            CapabilityId.BARCODE: "pyzbar",
        }
        package = packages.get(capability.id)
        if package:
            try:
                return metadata.version(package)
            except metadata.PackageNotFoundError:
                return "—"
        if capability.path:
            try:
                result = PlatformService.run([capability.path, "--version"], timeout=5)
                value = (result.stdout or result.stderr).strip().splitlines()
                return value[0][:80] if value else "Detected"
            except (OSError, subprocess.SubprocessError):
                return "Detected"
        return "Installed" if capability.available else "—"


class PreferencesDialog(QDialog):
    def __init__(
        self,
        settings,
        parent=None,
        commands: list[Command] | tuple[Command, ...] | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Preferences")
        self._commands = sorted(
            list(commands or ()),
            key=lambda command: (command.section.casefold(), command.label.casefold()),
        )
        self._shortcut_defaults = {
            command.id: self._canonical_shortcut(
                command.default_shortcut or command.shortcut
            )
            for command in self._commands
        }
        self._shortcut_values = {
            command.id: self._canonical_shortcut(command.shortcut)
            for command in self._commands
        }
        self.setMinimumWidth(720 if self._commands else 440)
        self.setMinimumHeight(680 if self._commands else 0)
        self.resize(960 if self._commands else 560, 800 if self._commands else 650)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem("Follow system", "system")
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.get_theme())))
        self.theme.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        form.addRow("Theme", self.theme)
        self.animations = QCheckBox("Use short panel and content animations")
        self.animations.setChecked(bool(settings.get("animations_enabled", True)))
        form.addRow("Motion", self.animations)
        self.ghostscript = self._path_row(
            form,
            "Ghostscript",
            str(settings.get("ghostscript_path") or ""),
            "Select Ghostscript executable",
        )
        self.libreoffice = self._path_row(
            form,
            "LibreOffice",
            str(settings.get("libreoffice_path") or ""),
            "Select LibreOffice executable",
        )
        layout.addLayout(form)

        offsets_group = QGroupBox("Print offsets (mm)")
        offsets_form = QFormLayout(offsets_group)
        left_mm, right_mm, top_mm, bottom_mm = settings.get_print_offsets()
        self.offset_left = self._offset_spin(left_mm)
        self.offset_right = self._offset_spin(right_mm)
        self.offset_top = self._offset_spin(top_mm)
        self.offset_bottom = self._offset_spin(bottom_mm)
        offsets_form.addRow("Shift from left", self.offset_left)
        offsets_form.addRow("Shift from right", self.offset_right)
        offsets_form.addRow("Shift from top", self.offset_top)
        offsets_form.addRow("Shift from bottom", self.offset_bottom)
        offsets_note = QLabel(
            "Default shift applied to every print job. Positive right/bottom "
            "values move the printed content left/up (some printers need "
            "this to centre the page). Each print dialog starts from these "
            "values and can still be adjusted per job."
        )
        offsets_note.setObjectName("secondary")
        offsets_note.setWordWrap(True)
        offsets_form.addRow(offsets_note)
        layout.addWidget(offsets_group)

        self.shortcuts_group = QGroupBox("Keyboard shortcuts")
        shortcuts_layout = QVBoxLayout(self.shortcuts_group)
        self.shortcut_filter = QLineEdit()
        self.shortcut_filter.setPlaceholderText(
            "Filter commands, sections or shortcuts"
        )
        self.shortcut_filter.setClearButtonEnabled(True)
        self.shortcut_filter.textChanged.connect(self._filter_shortcuts)
        shortcuts_layout.addWidget(self.shortcut_filter)

        self.shortcut_table = QTableWidget(0, 4)
        self.shortcut_table.setHorizontalHeaderLabels(
            ["Command", "Section", "Shortcut", "Default"]
        )
        self.shortcut_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.shortcut_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.shortcut_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.shortcut_table.verticalHeader().setVisible(False)
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3):
            self.shortcut_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.shortcut_table.itemSelectionChanged.connect(
            self._shortcut_selection_changed
        )
        shortcuts_layout.addWidget(self.shortcut_table, 1)

        editor_row = QHBoxLayout()
        editor_row.addWidget(QLabel("New shortcut"))
        self.shortcut_editor = QKeySequenceEdit()
        self.shortcut_editor.setClearButtonEnabled(True)
        editor_row.addWidget(self.shortcut_editor, 1)
        assign = QPushButton("Assign")
        assign.clicked.connect(self._assign_shortcut)
        editor_row.addWidget(assign)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_shortcut)
        editor_row.addWidget(clear)
        restore = QPushButton("Restore default")
        restore.clicked.connect(self._restore_shortcut)
        editor_row.addWidget(restore)
        shortcuts_layout.addLayout(editor_row)

        reset_row = QHBoxLayout()
        self.shortcut_status = QLabel(
            "Select a command, press the new key combination, then choose Assign."
        )
        self.shortcut_status.setObjectName("secondary")
        self.shortcut_status.setWordWrap(True)
        reset_row.addWidget(self.shortcut_status, 1)
        reset_all = QPushButton("Reset all")
        reset_all.clicked.connect(self._reset_all_shortcuts)
        reset_row.addWidget(reset_all)
        shortcuts_layout.addLayout(reset_row)
        self.shortcuts_group.setVisible(bool(self._commands))
        layout.addWidget(self.shortcuts_group, 1)
        self._populate_shortcuts()

        note = QLabel("Changes take effect immediately after this dialog closes.")
        note.setObjectName("secondary")
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _canonical_shortcut(value: str | QKeySequence) -> str:
        sequence = value if isinstance(value, QKeySequence) else QKeySequence(value)
        return sequence.toString(QKeySequence.SequenceFormat.PortableText)

    @staticmethod
    def _display_shortcut(value: str) -> str:
        if not value:
            return "Unassigned"
        return QKeySequence(value).toString(QKeySequence.SequenceFormat.NativeText)

    def _populate_shortcuts(self) -> None:
        if not hasattr(self, "shortcut_table"):
            return
        self.shortcut_table.setRowCount(0)
        for command in self._commands:
            row = self.shortcut_table.rowCount()
            self.shortcut_table.insertRow(row)
            command_item = QTableWidgetItem(command.label)
            command_item.setData(Qt.ItemDataRole.UserRole, command.id)
            self.shortcut_table.setItem(row, 0, command_item)
            self.shortcut_table.setItem(row, 1, QTableWidgetItem(command.section))
            self.shortcut_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    self._display_shortcut(self._shortcut_values[command.id])
                ),
            )
            self.shortcut_table.setItem(
                row,
                3,
                QTableWidgetItem(
                    self._display_shortcut(self._shortcut_defaults[command.id])
                ),
            )
        self._filter_shortcuts(self.shortcut_filter.text())
        if self.shortcut_table.rowCount():
            self.shortcut_table.selectRow(0)

    def _selected_shortcut_id(self) -> str | None:
        row = self.shortcut_table.currentRow()
        item = self.shortcut_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _shortcut_selection_changed(self) -> None:
        command_id = self._selected_shortcut_id()
        if command_id is None:
            self.shortcut_editor.clear()
            return
        self.shortcut_editor.setKeySequence(
            QKeySequence(self._shortcut_values.get(command_id, ""))
        )
        self.shortcut_status.setText(
            "Press a key combination and choose Assign, or restore the default."
        )

    def _filter_shortcuts(self, query: str) -> None:
        needle = query.strip().casefold()
        for row in range(self.shortcut_table.rowCount()):
            values = [
                self.shortcut_table.item(row, column).text().casefold()
                for column in range(self.shortcut_table.columnCount())
                if self.shortcut_table.item(row, column) is not None
            ]
            self.shortcut_table.setRowHidden(
                row, bool(needle and not any(needle in value for value in values))
            )

    def _set_shortcut_value(self, command_id: str, value: str) -> None:
        self._shortcut_values[command_id] = value
        for row in range(self.shortcut_table.rowCount()):
            item = self.shortcut_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == command_id:
                self.shortcut_table.item(row, 2).setText(self._display_shortcut(value))
                break
        self.shortcut_editor.setKeySequence(QKeySequence(value))

    def _assign_shortcut(self) -> bool:
        command_id = self._selected_shortcut_id()
        if command_id is None:
            self.shortcut_status.setText("Select a command first.")
            return False
        candidate = self._canonical_shortcut(self.shortcut_editor.keySequence())
        if candidate:
            conflict_id = next(
                (
                    other_id
                    for other_id, value in self._shortcut_values.items()
                    if other_id != command_id and value == candidate
                ),
                None,
            )
            if conflict_id is not None:
                conflict = next(
                    command for command in self._commands if command.id == conflict_id
                )
                self.shortcut_status.setText(
                    f"{self._display_shortcut(candidate)} is already assigned to "
                    f"{conflict.label}. Clear or change that shortcut first."
                )
                return False
        self._set_shortcut_value(command_id, candidate)
        self.shortcut_status.setText(
            f"Assigned {self._display_shortcut(candidate)}."
            if candidate
            else "Shortcut cleared."
        )
        return True

    def _clear_shortcut(self) -> None:
        command_id = self._selected_shortcut_id()
        if command_id is not None:
            self._set_shortcut_value(command_id, "")
            self.shortcut_status.setText("Shortcut cleared.")

    def _restore_shortcut(self) -> None:
        command_id = self._selected_shortcut_id()
        if command_id is not None:
            self._set_shortcut_value(
                command_id, self._shortcut_defaults.get(command_id, "")
            )
            self.shortcut_status.setText("Default shortcut restored.")

    def _reset_all_shortcuts(self) -> None:
        self._shortcut_values = self._shortcut_defaults.copy()
        self._populate_shortcuts()
        self.shortcut_status.setText("All shortcuts restored to their defaults.")

    def shortcut_overrides(self) -> dict[str, str]:
        return {
            command_id: value
            for command_id, value in self._shortcut_values.items()
            if value != self._shortcut_defaults.get(command_id, "")
        }

    @staticmethod
    def _offset_spin(value: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(-100.0, 100.0)
        control.setDecimals(1)
        control.setSuffix(" mm")
        control.setValue(value)
        return control

    def _path_row(
        self, form: QFormLayout, label: str, value: str, title: str
    ) -> QLineEdit:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        edit.setPlaceholderText("Auto-detect")
        edit.setAccessibleName(f"{label} executable path")
        edit.setMinimumWidth(260)
        edit.setToolTip(value)
        edit.textChanged.connect(edit.setToolTip)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_executable(edit, title))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(label, container)
        return edit

    def _browse_executable(self, edit: QLineEdit, title: str) -> None:
        value, _ = QFileDialog.getOpenFileName(self, title, edit.text())
        if value:
            edit.setText(value)

    def accept(self) -> None:
        self.settings.update(
            {
                "theme": str(self.theme.currentData()),
                "animations_enabled": self.animations.isChecked(),
                "ghostscript_path": self.ghostscript.text().strip() or None,
                "libreoffice_path": self.libreoffice.text().strip() or None,
            }
        )
        self.settings.set_print_offsets(
            self.offset_left.value(),
            self.offset_right.value(),
            self.offset_top.value(),
            self.offset_bottom.value(),
        )
        if self._commands:
            self.settings.set_shortcut_overrides(self.shortcut_overrides())
        super().accept()
