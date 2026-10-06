"""Choose whether edited PDF pages are reusable templates or finished mailpieces."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from composition.template.model import MAX_TEMPLATE_PAGES
from core.page_plan import parse_page_selection


class DesignerHandoffDialog(QDialog):
    def __init__(self, parent, *, label, page_count, current_page, pages=None):
        super().__init__(parent)
        self.setWindowTitle("Send to Document Designer")
        self.setMinimumWidth(360)
        self.page_count, self.current_page = page_count, current_page
        self._pages = None
        self.source = QLabel(f"Source: {label}")
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem("Mail Merge Project", "mail_merge_template")
        self.kind.addItem("PDF Overlay Project", "overlay")
        self.kind.setAccessibleName("Designer project type")
        self.selection = QComboBox()
        self.selection.addItems(["Entire PDF", "Current page", "Page range"])
        self.selection.setAccessibleName("Source page selection")
        self.range = QLineEdit()
        self.range.setPlaceholderText("Example: 1-3, 5")
        self.range.setAccessibleName("Source page range")
        if pages is not None:
            self.selection.setCurrentIndex(2)
            self.range.setText(", ".join(str(page+1) for page in sorted(set(pages))))
        self.explanation, self.summary = QLabel(), QLabel()
        for widget in (self.explanation, self.summary):
            widget.setWordWrap(True)
            widget.setTextFormat(Qt.TextFormat.PlainText)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create / Open Project")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.source)
        form = QFormLayout()
        form.addRow("Project", self.kind)
        form.addRow("Pages", self.selection)
        form.addRow("Range", self.range)
        layout.addLayout(form)
        layout.addWidget(self.explanation)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.selection.currentIndexChanged.connect(self.refresh)
        self.range.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        mail_merge = self.kind.currentData() == "mail_merge_template"
        self.explanation.setText(
            "Repeat all selected template pages for each customer. Add merge fields, running sequences and barcodes in Template Designer."
            if mail_merge else "Keep existing PDF pages and add envelope sequences or inserter barcodes.")
        self.range.setEnabled(self.selection.currentIndex() == 2)
        valid = True
        try:
            mode = self.selection.currentIndex()
            self._pages = None if mode == 0 else [self.current_page] if mode == 1 else parse_page_selection(self.range.text(), self.page_count)
            count = self.page_count if self._pages is None else len(self._pages)
            if not count:
                raise ValueError("Choose at least one source page.")
            if mail_merge and count > MAX_TEMPLATE_PAGES:
                raise ValueError(f"Mail Merge supports up to {MAX_TEMPLATE_PAGES} template pages. Select a smaller range.")
            selected = "Entire PDF" if self._pages is None else ", ".join(str(p+1) for p in self._pages[:16]) + (" …" if count > 16 else "")
            self.summary.setText(f"{self.kind.currentText()} · {count:,} source page(s)\n{selected}\n" +
                                 (f"Each customer produces {count:,} template page(s)." if mail_merge else "Envelope grouping is reviewed in Designer."))
        except ValueError as error:
            self.summary.setText(str(error))
            valid = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def accept(self):
        self.refresh()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            super().accept()

    def request(self):
        return self.kind.currentData(), self._pages
