"""External tool diagnostics and application preferences."""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib import metadata

from PyQt6.QtCore import Qt
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
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.capabilities import CapabilityId, refresh_capabilities
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
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
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
                    value
                    for value in (capability.reason, capability.guidance)
                    if value
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
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(440)
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
    def _offset_spin(value: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(-100.0, 100.0)
        control.setDecimals(1)
        control.setSuffix(" mm")
        control.setValue(value)
        return control

    def _path_row(self, form: QFormLayout, label: str, value: str, title: str) -> QLineEdit:
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
        super().accept()
