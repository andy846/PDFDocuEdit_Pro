"""Staged AcroForm editor. The preview owns a private document."""
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.diagnostics import log_failure
from core.forms import apply_values, enumerate_fields, validate_values
from dialogs.base import ToolDialog
from ui.pdf_canvas import PdfCanvas


class FormDialog(ToolDialog):
    def __init__(self, snapshot: bytes, parent=None):
        super().__init__("Fill PDF form", "acroform", parent)
        self.snapshot = snapshot
        self.preview = fitz.open(stream=snapshot, filetype="pdf")
        try:
            self.fields = enumerate_fields(self.preview)
        except Exception:
            self.preview.close()
            raise
        self.staged = {}
        self.preview_values = {item.name: item.value for item in self.fields}
        self.signatures = {}
        self.acknowledge_scripts = False
        self._current = None
        self._editor = None
        self.resize(1150, 780)
        self._root.addWidget(QLabel("Fill existing fields • Preview first • Apply creates one Undo step"))
        splitter = QSplitter()
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Field", "Type", "Pages", "Value", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, item in enumerate(self.fields):
            self.table.insertRow(row)
            status = ", ".join(s for s, enabled in (("Read only", item.readonly), ("Required", item.required),
                ("Calculated", bool(item.calculation)), ("Digitally signed", item.signed)) if enabled)
            for col, value in enumerate((item.name, item.label,
                    ", ".join(str(w.page + 1) for w in item.widgets), str(item.value or ""), status)):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        self.editor_box = QVBoxLayout()
        layout.addLayout(self.editor_box)
        buttons = QHBoxLayout()
        preview_button = QPushButton("Update preview")
        preview_button.clicked.connect(self.update_preview)
        reset = QPushButton("Discard staged values")
        reset.clicked.connect(self.reset_values)
        buttons.addWidget(preview_button)
        buttons.addWidget(reset)
        layout.addLayout(buttons)
        splitter.addWidget(panel)
        self.canvas = PdfCanvas()
        self.canvas.set_annotations_editable(False)
        self.canvas.load_doc(self.preview)
        # Reuse the canvas's existing unrotated PDF hit-test coordinates.
        self.canvas.set_tool_mode("font_inspect")
        self.canvas.fontInspectionRequested.connect(self.select_at)
        splitter.addWidget(self.canvas)
        splitter.setSizes([480, 640])
        self._root.addWidget(splitter, 1)
        self.add_validation()
        self.notice = QLabel("Signature appearances are pictures only; they do not digitally sign or validate this PDF.")
        self.notice.setWordWrap(True)
        self._root.addWidget(self.notice)
        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        footer.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        footer.rejected.connect(self.reject)
        self._root.addWidget(footer)
        from ui.shortcut_bindings import bind_dialog_commands
        bind_dialog_commands(self, {"form.preview": preview_button, "form.reset": reset,
                                   "form.apply": footer.button(QDialogButtonBox.StandardButton.Apply)})
        self.table.currentCellChanged.connect(self.select_field)
        if self.fields:
            self.table.selectRow(0)
        else:
            self.show_error("This PDF has no existing AcroForm fields.")
            footer.button(QDialogButtonBox.StandardButton.Apply).setEnabled(False)

    def select_at(self, page, point):
        for row, item in enumerate(self.fields):
            if any(w.page == page and fitz.Rect(w.rect).contains(point) for w in item.widgets):
                self.table.selectRow(row)
                return

    def save_editor(self):
        if self._current is None or self._editor is None:
            return
        item = self.fields[self._current]
        if item.readonly or item.calculation:
            return
        editor = self._editor
        if isinstance(editor, QPlainTextEdit):
            value = editor.toPlainText()
        elif isinstance(editor, QCheckBox):
            value = next((s for s in item.widgets[0].states if s != "Off"), "Off") if editor.isChecked() else "Off"
        elif isinstance(editor, QComboBox):
            value = editor.currentText() if editor.isEditable() else editor.currentData()
        elif isinstance(editor, QListWidget):
            value = [i.data(Qt.ItemDataRole.UserRole) for i in editor.selectedItems()]
        else:
            return
        if value != item.value:
            self.staged[item.name] = value
        else:
            self.staged.pop(item.name, None)
        self.table.item(self._current, 3).setText(str(value or ""))

    def select_field(self, row, *_):
        self.save_editor()
        self._current = row if row >= 0 else None
        self._editor = None
        while self.editor_box.count():
            child = self.editor_box.takeAt(0).widget()
            if child:
                child.deleteLater()
        if row < 0:
            return
        item = self.fields[row]
        value = self.preview_values.get(item.name, item.value) if item.calculation else self.staged.get(item.name, item.value)
        self.editor_box.addWidget(QLabel(item.name))
        if item.kind == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            editor = QPushButton("Choose signature appearance image…")
            editor.setEnabled(not item.signed and not item.readonly)
            editor.clicked.connect(self.choose_signature)
        elif item.kind == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            editor = QCheckBox("Checked")
            editor.setChecked(value not in (None, "", "Off", False))
        elif item.kind in (fitz.PDF_WIDGET_TYPE_RADIOBUTTON, fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            choices = item.choices
            if item.kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                choices = tuple(dict.fromkeys(s for w in item.widgets for s in w.states))
            if item.kind == fitz.PDF_WIDGET_TYPE_LISTBOX and item.flags & (1 << 21):
                editor = QListWidget()
                editor.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
                for choice in choices:
                    export, label = choice if isinstance(choice, (tuple, list)) else (choice, choice)
                    entry = QListWidgetItem(label, editor)
                    entry.setData(Qt.ItemDataRole.UserRole, export)
                    entry.setSelected(export in (value if isinstance(value, list) else [value]))
            else:
                editor = QComboBox()
                for choice in choices:
                    export, label = choice if isinstance(choice, (tuple, list)) else (choice, choice)
                    editor.addItem(label, export)
                editor.setCurrentIndex(editor.findData(value))
                editor.setEditable(item.kind == fitz.PDF_WIDGET_TYPE_COMBOBOX and bool(item.flags & (1 << 18)))
                if editor.isEditable():
                    editor.setCurrentText(str(value or ""))
        else:
            editor = QPlainTextEdit(str(value or ""))
            editor.setMaximumHeight(110)
        editor.setEnabled(not item.readonly and not item.calculation and not item.signed
                          and item.kind != fitz.PDF_WIDGET_TYPE_BUTTON)
        self._editor = editor
        self.editor_box.addWidget(editor)
        if item.kind == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            draw = QPushButton("Draw signature appearance…")
            draw.setEnabled(not item.signed and not item.readonly)
            draw.clicked.connect(self.draw_signature)
            self.editor_box.addWidget(draw)
        ref = item.widgets[0]
        self.canvas.set_page(ref.page)
        self.canvas.show_search_hits(ref.page, [fitz.Rect(w.rect) for w in item.widgets if w.page == ref.page])

    def draw_signature(self):
        from dialogs.signature_appearance import SignatureAppearanceDialog
        dialog = SignatureAppearanceDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.signatures[self.fields[self._current].name] = dialog.image_bytes()
            self.update_preview()

    def choose_signature(self):
        path, _ = QFileDialog.getOpenFileName(self, "Signature appearance", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            try:
                data = Path(path).read_bytes()
                fitz.Pixmap(data)  # Validate before staging a private copy.
                self.signatures[self.fields[self._current].name] = data
                self.update_preview()
            except Exception:
                log_failure("Could not load signature appearance")
                self.show_error("Could not load this signature image.")

    def update_preview(self):
        self.save_editor()
        candidate = None
        try:
            values, warnings = validate_values(self.fields, self.staged)
            candidate = fitz.open(stream=self.snapshot, filetype="pdf")
            apply_values(candidate, self.staged, self.signatures, acknowledge_scripts=True)
            self.canvas.clear()
            self.preview.close()
            self.preview, candidate = candidate, None
            self.canvas.load_doc(self.preview)
            if self._current is not None:
                ref = self.fields[self._current].widgets[0]
                self.canvas.set_page(ref.page)
                self.canvas.show_search_hits(ref.page, [fitz.Rect(ref.rect)])
            self.preview_values = values
            for row, item in enumerate(self.fields):
                self.table.item(row, 3).setText(str(values[item.name] or ""))
            if self._current is not None and self.fields[self._current].calculation and isinstance(self._editor, QPlainTextEdit):
                self._editor.setPlainText(str(values[self.fields[self._current].name] or ""))
            self._validation.hide()
            if warnings:
                self.show_error("\n".join(warnings))
            return True
        except Exception as exc:
            log_failure("Form preview failed")
            self.show_error(str(exc))
            return False
        finally:
            if candidate is not None:
                candidate.close()

    def reset_values(self):
        self._editor = None
        self.staged.clear()
        self.signatures.clear()
        # Restoring the original snapshot must also work for an incomplete form
        # whose required fields or calculations are not yet valid.
        self.canvas.clear()
        self.preview.close()
        self.preview = fitz.open(stream=self.snapshot, filetype="pdf")
        self.preview_values = {item.name: item.value for item in self.fields}
        self.canvas.load_doc(self.preview)
        self._validation.hide()
        for row, item in enumerate(self.fields):
            self.table.item(row, 3).setText(str(item.value or ""))
        if self._current is not None:
            self.select_field(self._current)

    def accept(self):
        if not self.update_preview():
            return
        _, warnings = validate_values(self.fields, self.staged)
        if warnings:
            if QMessageBox.question(self, "Scripts not executed", "\n".join(warnings) +
                    "\n\nApply supported values anyway?", QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.acknowledge_scripts = True
        super().accept()

    def release(self):
        self.canvas.clear()
        if not self.preview.is_closed:
            self.preview.close()
